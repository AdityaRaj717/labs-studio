import { test, before, after, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { chromium } from 'playwright';

// config.js reads FLOW_DATA_DIR at load, so point it at a temp dir before importing the engine.
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'guards-'));
process.env.FLOW_DATA_DIR = tmp;
const { default: config } = await import('../src/utils/config.js');
const { withTab } = await import('../src/engine/tab-lock.js');
const { pacer } = await import('../src/engine/pacer.js');
const ledger = await import('../src/engine/ledger.js');
const { checkBudget } = await import('../src/engine/budget.js');
const { detectBlock } = await import('../src/flow/blocks.js');
const { startFakeFlow } = await import('./fake-flow/server.js');
const { ErrorCodes, ERROR_CLASSES, createError, toErrorPayload } = await import('../src/utils/errors.js');

const pacerFile = path.join(tmp, 'pacer.json');
const ledgerFile = path.join(tmp, 'ledger.json');
const reset = () => {
  fs.rmSync(pacerFile, { force: true });
  fs.rmSync(ledgerFile, { force: true });
  Object.assign(config, { minGapMs: 0, maxGapMs: 0, dailyCap: 0 });
};
const hasCode = (code) => (err) => err.code === code;
const job = (id, spec = { kind: 'video', model: 'veoLite', count: 1 }) => ({ id, spec });
const ms = (fn) => async () => { const t = Date.now(); await fn(); return Date.now() - t; };

after(() => fs.rmSync(tmp, { recursive: true, force: true }));
afterEach(reset);

// --- tab lock

test('a screenshot during a job waits for the tab lock', async () => {
  const order = [];
  let finishJob;
  const running = withTab('job', async () => {
    order.push('job start');
    await new Promise((resolve) => { finishJob = resolve; });
    order.push('job end');
  });
  const shot = withTab('screenshot', () => { order.push('screenshot'); return 'png'; });
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.deepEqual(order, ['job start']);
  finishJob();
  await running;
  assert.equal(await shot, 'png');
  assert.deepEqual(order, ['job start', 'job end', 'screenshot']);
});

test('withTab releases after async and sync failures', async () => {
  await assert.rejects(withTab('a', async () => { throw new Error('async boom'); }), /async boom/);
  await assert.rejects(withTab('b', () => { throw new Error('sync boom'); }), /sync boom/);
  assert.equal(await withTab('c', () => 'still works'), 'still works');
});

// --- pacer

test('pacing is enforced across two client calls', async () => {
  Object.assign(config, { minGapMs: 250, maxGapMs: 250 });
  await pacer.waitTurn();
  pacer.recordUse();
  const waited = await ms(() => pacer.waitTurn())();
  assert.ok(waited >= 200, `waited only ${waited}ms`);
});

test('two clients waiting at once get separate turns', async () => {
  Object.assign(config, { minGapMs: 1000, maxGapMs: 1000 });
  const times = [];
  const turn = () => pacer.waitTurn().then(() => times.push(Date.now()));
  await Promise.all([turn(), turn()]);
  assert.ok(times[1] - times[0] >= 500, `turns ${times[1] - times[0]}ms apart`);
});

test('an aborted wait rejects', async () => {
  Object.assign(config, { minGapMs: 5000, maxGapMs: 5000 });
  await pacer.waitTurn();
  const controller = new AbortController();
  const waiting = pacer.waitTurn(controller.signal);
  controller.abort();
  await assert.rejects(waiting, { name: 'AbortError' });
});

test('cap persists across restart', async () => {
  config.dailyCap = 1;
  assert.equal(pacer.capReached(), false);
  pacer.recordUse();
  const { pacer: restarted } = await import('../src/engine/pacer.js?restart=cap');
  assert.equal(restarted.capReached(), true);
  await assert.rejects(restarted.waitTurn(), hasCode(ErrorCodes.DAILY_CAP_REACHED));
});

test('a gap survives restart, but a stale far-future one is clamped', async () => {
  Object.assign(config, { minGapMs: 300, maxGapMs: 300 });
  pacer.recordUse();
  const { pacer: restarted } = await import('../src/engine/pacer.js?restart=gap');
  assert.ok((await ms(() => restarted.waitTurn())()) >= 200);

  const saved = JSON.parse(fs.readFileSync(pacerFile, 'utf8'));
  fs.writeFileSync(pacerFile, JSON.stringify({ ...saved, nextAt: Date.now() + 3600_000 }));
  const { pacer: again } = await import('../src/engine/pacer.js?restart=clamp');
  assert.ok((await ms(() => again.waitTurn())()) < 1000);
});

test('the daily count resets on a new local day', () => {
  config.dailyCap = 1;
  pacer.recordUse();
  const saved = JSON.parse(fs.readFileSync(pacerFile, 'utf8'));
  fs.writeFileSync(pacerFile, JSON.stringify({ ...saved, day: '2000-01-01' }));
  assert.equal(pacer.capReached(), false);
});

test('a corrupt pacer file stops pacing instead of resetting the cap', () => {
  config.dailyCap = 1;
  fs.writeFileSync(pacerFile, '{"day":');
  assert.throws(() => pacer.capReached(), /pacer\.json/);
});

// --- ledger

test('recordSpend adds to the month and counts a job once', () => {
  ledger.recordSpend(job('a'), 10);
  ledger.recordSpend(job('b'), 5);
  ledger.recordSpend(job('a'), 10);
  assert.equal(ledger.monthTotal(), 15);
});

test('two paid attempts on one job both count, a repeated attempt does not', () => {
  const images = { kind: 'image', model: 'bananaPro', count: 2 };
  ledger.recordSpend(job('a'), 10);
  ledger.recordSpend({ ...job('a'), attempt: 1 }, 10);
  ledger.recordSpend({ ...job('a'), attempt: 2 }, 10);
  ledger.recordSpend({ ...job('a'), attempt: 2 }, 10);
  assert.equal(ledger.monthTotal(), 20);
  ledger.recordSpend(job('i', images), 0);
  ledger.recordSpend({ ...job('i', images), attempt: 2 }, 0);
  ledger.recordSpend({ ...job('i', images), attempt: 2 }, 0);
  assert.equal(ledger.todayQuota('bananaPro').used, 4);
});

test('monthTotal ignores other months and survives a torn temp file', () => {
  ledger.recordSpend(job('a'), 10);
  const saved = JSON.parse(fs.readFileSync(ledgerFile, 'utf8'));
  saved.spends.old = { credits: 99, model: 'veoLite', images: 0, day: '2000-01-01' };
  fs.writeFileSync(ledgerFile, JSON.stringify(saved));
  fs.writeFileSync(`${ledgerFile}.tmp`, '{"torn');
  assert.equal(ledger.monthTotal(), 10);
});

test('a corrupt ledger is an error, not zero spend', () => {
  fs.writeFileSync(ledgerFile, '{"spends":');
  assert.throws(() => ledger.monthTotal(), /ledger\.json/);
  assert.throws(() => checkBudget({ credits: 1 }, 30, ledger), /ledger\.json/);
});

test('recordSpend rejects bad input', () => {
  for (const credits of [-1, NaN, '5', undefined]) {
    assert.throws(() => ledger.recordSpend(job('a'), credits), hasCode(ErrorCodes.INVALID_PARAMS));
  }
  assert.throws(() => ledger.recordSpend({}, 1), hasCode(ErrorCodes.INVALID_PARAMS));
});

test('todayQuota shares a limit across a model group', () => {
  ledger.recordSpend(job('i1', { kind: 'image', model: 'banana21', count: 3 }), 0);
  ledger.recordSpend(job('i2', { kind: 'image', model: 'banana2Lite', count: 2 }), 0);
  ledger.recordSpend(job('i3', { kind: 'image', model: 'bananaPro', count: 1 }), 0);
  assert.deepEqual(ledger.todayQuota('banana21'), { model: 'banana21', used: 5, limit: 1000, remaining: 995 });
  assert.deepEqual(ledger.todayQuota('bananaPro'), { model: 'bananaPro', used: 1, limit: 100, remaining: 99 });
  assert.deepEqual(ledger.todayQuota('veoLite'), { model: 'veoLite', used: 0, limit: null, remaining: null });
});

test('checkBudget works with the real ledger', () => {
  ledger.recordSpend(job('a'), 990);
  checkBudget({ credits: 10 }, 30, ledger);
  assert.throws(() => checkBudget({ credits: 11 }, 30, ledger), hasCode(ErrorCodes.BUDGET_EXCEEDED));
});

test('checkBudget without a ledger is a clear error', () => {
  assert.throws(() => checkBudget({ credits: 1 }, 30), /ledger/);
});

// --- blocks

let browser;
let page;
let flow;
const detectIn = async (html) => {
  await page.setContent(html);
  return detectBlock(page);
};

before(async () => {
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  flow = await startFakeFlow();
  page = await browser.newPage();
  await page.goto(`${flow.url}/project/p1`);
});
after(async () => {
  await browser?.close();
  await flow?.close();
});

test('detectBlock maps sign-in URL, CAPTCHA text, quota text, unusual activity text', async () => {
  const signIn = await detectBlock({ url: () => 'https://accounts.google.com/v3/signin/identifier?hint=secret' });
  assert.equal(signIn.code, ErrorCodes.NOT_LOGGED_IN);
  assert.doesNotMatch(signIn.text, /secret/);

  const captcha = await detectIn('<p>Please verify you are not a robot to continue</p>');
  assert.equal(captcha.code, ErrorCodes.MANUAL_VERIFICATION_REQUIRED);
  assert.match(captcha.text, /not a robot/i);

  const quota = await detectIn('<div role="alert">You have reached your daily limit</div>');
  assert.equal(quota.code, ErrorCodes.GOOGLE_LIMIT_REACHED);

  const unusual = await detectIn('<p>Our systems have detected unusual traffic from your network</p>');
  assert.equal(unusual.code, ErrorCodes.WAF_BLOCK);
});

test('detectBlock reads a toast with a Dismiss button', async () => {
  const found = await detectIn('<div><span>Not enough credits</span><button>Dismiss</button></div>');
  assert.equal(found.code, ErrorCodes.GOOGLE_LIMIT_REACHED);
});

test('detectBlock ignores limit words in prompts and the reCAPTCHA badge', async () => {
  assert.equal(await detectIn('<p>A poster saying: you have reached your daily limit</p><small>protected by reCAPTCHA</small>'), null);
});

test('detectBlock is null on a normal fake Flow page', async () => {
  await page.goto(`${flow.url}/project/p1`);
  assert.equal(await detectBlock(page), null);
});

// --- errors

test('every ErrorCodes value has a class and a next_action', () => {
  for (const code of Object.values(ErrorCodes)) {
    const payload = toErrorPayload(createError(code, 'x'));
    assert.equal(payload.error_code, code);
    assert.ok(ERROR_CLASSES[code]?.class, `${code} has no class`);
    assert.ok(payload.next_action, `${code} has no next_action`);
  }
});

test('spec 6.5 codes are all present with their class', () => {
  const spec = {
    owner: ['NOT_LOGGED_IN', 'WRONG_GOOGLE_ACCOUNT', 'MANUAL_VERIFICATION_REQUIRED', 'WAF_BLOCK'],
    stop_run: ['GOOGLE_LIMIT_REACHED', 'DAILY_MODEL_LIMIT', 'DAILY_CAP_REACHED', 'BUDGET_EXCEEDED', 'UNKNOWN_UI_CHANGE', 'AUDIO_NO_CREDIT'],
    job: ['GENERATION_REFUSED', 'SAFETY_BLOCKED', 'AGENT_NEEDS_CLARIFICATION', 'RESULT_MISMATCH'],
    retry: ['UPLOAD_STALLED', 'DOWNLOAD_FAILED', 'NAVIGATION_TIMEOUT', 'BROWSER_NOT_CONNECTED', 'AUDIO_RATE_LIMITED', 'AUDIO_UNAVAILABLE'],
    retry_with_spend: ['FLOW_GENERATION_FAILED'],
    caller: ['INVALID_PARAMS', 'MODEL_NOT_AVAILABLE', 'RATIO_NOT_AVAILABLE', 'COMBINATION_NOT_SUPPORTED', 'PROJECT_NOT_FOUND', 'MISSING_API_KEY', 'FFMPEG_NOT_FOUND', 'JOB_NOT_FOUND'],
  };
  for (const [cls, codes] of Object.entries(spec)) {
    for (const code of codes) {
      assert.equal(ErrorCodes[code], code);
      assert.equal(ERROR_CLASSES[code].class, cls, code);
      assert.equal(toErrorPayload(createError(code, 'x')).retryable, cls === 'retry', code);
    }
  }
});

test('toErrorPayload has the spec shape and lifts contract fields out of details', () => {
  const err = createError(ErrorCodes.RESULT_MISMATCH, 'wrong ratio', {
    next_action: 'Check the tile.', credits_at_risk: true, screenshot: 'a.png', expected: '16:9',
  });
  assert.deepEqual(toErrorPayload(err), {
    ok: false,
    error_code: 'RESULT_MISMATCH',
    message: 'wrong ratio',
    retryable: false,
    credits_at_risk: true,
    next_action: 'Check the tile.',
    details: { expected: '16:9' },
    screenshot: 'a.png',
  });
});

test('toErrorPayload handles a foreign error as internal', () => {
  const payload = toErrorPayload(Object.assign(new Error('disk gone'), { code: 'ENOSPC' }));
  assert.equal(payload.error_code, ErrorCodes.INTERNAL_ERROR);
  assert.equal(payload.message, 'disk gone');
  assert.equal(payload.details.code, 'ENOSPC');
  assert.equal(payload.retryable, false);
  assert.equal(payload.credits_at_risk, false);
  assert.equal(payload.screenshot, null);
});

test('FlowError.toJSON stays for existing callers', () => {
  assert.deepEqual(createError(ErrorCodes.INVALID_PARAMS, 'm').toJSON(), { error: 'INVALID_PARAMS', message: 'm', details: {} });
});

// --- S2-1: a failed tile is not a page block

const TILE = '<flow-grid-tile-container role="group"><p>We noticed some unusual activity. You have not been charged for this generation.</p></flow-grid-tile-container>';

test('old failed tile does not block a new job', async () => {
  assert.equal(await detectIn(`<main>${TILE}<p>A prompt about a van</p></main>`), null);
});

test('whole page interstitial still blocks', async () => {
  const found = await detectIn('<p>We noticed some unusual activity from your network. Try again later.</p>');
  assert.equal(found.code, ErrorCodes.WAF_BLOCK);
});

test('new failed tile stops with not-charged', async () => {
  const { failureOf } = await import('../src/flow/image.js');
  const err = failureOf({ status: 'failed', text: 'We noticed some unusual activity. You have not been charged for this generation.' });
  const payload = toErrorPayload(err);
  assert.equal(payload.error_code, ErrorCodes.FLOW_ACTIVITY_FLAG);
  assert.equal(payload.credits_at_risk, false);
  assert.equal(ERROR_CLASSES.FLOW_ACTIVITY_FLAG.class, 'owner');
});

test('resume refuses while the block shows', async () => {
  const { createRpc } = await import('../src/engine/rpc.js');
  let resumed = false;
  const worker = { status: () => ({ paused: ErrorCodes.WAF_BLOCK, active: null }), assertSettled() {}, resume() { resumed = true; } };
  await page.setContent('<p>We noticed some unusual activity from your network.</p>');
  const rpc = createRpc({ worker, session: { peek: () => page }, hub: { on() {}, emit() {} } });
  const out = await rpc('flow_job_control', { action: 'resume' });
  assert.equal(out.error_code, ErrorCodes.WAF_BLOCK);
  assert.equal(resumed, false);
});

test('creditsFor sums a run\'s jobs, paid retries included', () => {
  reset();
  ledger.recordSpend(job('r1'), 10);
  ledger.recordSpend({ ...job('r1'), attempt: 2 }, 10);
  ledger.recordSpend(job('r2'), 5);
  ledger.recordSpend(job('other'), 99);
  assert.equal(ledger.creditsFor(['r1', 'r2']), 25);
  assert.equal(ledger.creditsFor([]), 0);
});
