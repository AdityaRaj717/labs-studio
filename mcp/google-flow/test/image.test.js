import { test, before, after, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { chromium } from 'playwright';

// config.js reads FLOW_DATA_DIR at load. Port 1 makes any accidental attach fail instead of reaching 9333.
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'image-'));
process.env.FLOW_DATA_DIR = path.join(tmp, 'data');
process.env.FLOW_CDP_PORT = '1';
const { default: config } = await import('../src/utils/config.js');
const { startEngine } = await import('../src/engine/server.js');
const { flowAdapter } = await import('../src/engine/worker.js');
const { rpc } = await import('../src/shim/client.js');
const { allRuns, jobEvents } = await import('../src/engine/job-store.js');
const ledger = await import('../src/engine/ledger.js');
const { withRetry, jitter } = await import('../src/engine/pacer.js');
const { verifyImage } = await import('../src/flow/verify.js');
const { addIngredient } = await import('../src/flow/ingredients.js');
const { locate } = await import('../src/flow/contract.js');
const { startFakeFlow, fakeJpeg } = await import('./fake-flow/server.js');
const { closeLog } = await import('../src/utils/logger.js');
const { createError, ErrorCodes } = await import('../src/utils/errors.js');

const noPacer = { waitTurn: async () => {}, recordUse: () => {}, capReached: () => false };
let browser;
let open = [];
let dirs = 0;

before(async () => { browser = await chromium.launch({ channel: 'chrome', headless: true }); });
after(async () => {
  await browser.close();
  await closeLog?.();
  fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
});
afterEach(async () => {
  for (const fn of open.reverse()) await fn();
  open = [];
});

const until = async (check, ms = 20000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const value = await check();
    if (value) return value;
    await new Promise((r) => setTimeout(r, 20));
  }
  throw new Error('condition not met in time');
};

async function flowPage(scenario = 'default') {
  const flow = await startFakeFlow({ scenario });
  const page = await browser.newPage();
  await page.goto(`${flow.url}/project/one`);
  open.push(async () => { await page.close().catch(() => {}); await flow.close(); });
  return { flow, page };
}

async function setup(scenario) {
  config.dataDir = path.join(tmp, `d${++dirs}`);
  fs.mkdirSync(config.dataDir, { recursive: true });
  process.env.FLOW_DATA_DIR = config.dataDir;
  Object.assign(config, { retryBaseMs: 5, noTileTimeoutMs: 60000, shortResultGraceMs: 300, generationTimeoutMs: 20000 });
  const { flow, page } = await flowPage(scenario);
  const engine = await startEngine({ adapter: flowAdapter, session: { ensure: async () => ({ browser, page }), peek: () => page }, pacer: noPacer, settleMs: 2000 });
  open.push(() => engine.stop());
  const startClicks = async () => (await (await fetch(`${flow.url}/__state`)).json()).startClicks;
  const clicks = async () => (await (await fetch(`${flow.url}/__state`)).json()).clicks;
  const generate = async (over = {}) => (await rpc(engine, 'flow_generate_image', {
    prompt: 'a boat', ratio: '16:9', auto_confirm: true, output_root: path.join(tmp, `out${dirs}`), ...over,
  })).result.job_id;
  const status = async (id) => (await rpc(engine, 'flow_job_status', { job_id: id })).result;
  const settled = (id, state) => until(async () => {
    const view = await status(id);
    return view.state === state && view;
  });
  return { flow, page, engine, startClicks, clicks, generate, status, settled };
}

const jobOf = (id) => allRuns().flatMap((run) => run.jobs).find((job) => job.id === id);

test('happy path saves x2 files named by assetName with manifest fields', { timeout: 60000 }, async () => {
  const { generate, settled, status, startClicks } = await setup();
  const id = await generate({ count: 2 });
  const sources = new Set();
  await until(async () => {
    const { state, progress } = await status(id);
    if (state === 'generating') sources.add(progress.source);
    return state === 'done';
  });
  const view = await settled(id, 'done');
  assert.equal(await startClicks(), 1);
  assert.ok(sources.has('flow'), 'progress came from Flow');
  assert.equal(view.outputs.length, 2);
  assert.deepEqual(view.outputs.map((o) => path.basename(o.file)), ['1_a-boat_v1.jpg', '1_a-boat_v2.jpg']);
  for (const out of view.outputs) {
    assert.equal(fs.existsSync(out.file), true);
    assert.equal(out.prompt, 'a boat');
    assert.equal(out.request, 'a boat');
    assert.equal(out.model, 'banana21');
    assert.match(out.observed, /Nano Banana 2\.1/);
    assert.equal(out.ratio, '16:9');
    assert.equal(out.quotedCredits, 0);
    assert.match(out.sha256, /^[0-9a-f]{64}$/);
    assert.deepEqual([out.width, out.height], [1376, 768]);
    assert.ok(!['old-1', 'old-2'].includes(out.mediaId), 'an old tile is not a result');
    assert.ok(out.flowProjectUrl.includes('/project/one'));
  }
  const manifest = JSON.parse(fs.readFileSync(path.join(jobOf(id).run.dir, 'manifest.json'), 'utf8'));
  assert.equal(manifest.jobs[0].data.outputs.length, 2);
  assert.equal(manifest.jobs[0].data.quotedCredits, 0);
  assert.equal(ledger.todayQuota('banana21').used, 2);
  assert.equal(ledger.lastBalance().credits, 1025);
});

test('a model with an emoji prefix is picked and read back', { timeout: 60000 }, async () => {
  const { generate, settled, page } = await setup();
  const id = await generate({ model: 'bananaPro' });
  await settled(id, 'done');
  assert.match(await locate(page, 'project.settingsTrigger').innerText(), /Nano Banana Pro x1/);
});

test('the chat is closed and the Agent toggle turned off before generating', { timeout: 60000 }, async () => {
  const { generate, settled, page, clicks } = await setup('agentOn');
  await settled(await generate(), 'done');
  assert.equal((await clicks()).Close, 1);
  assert.equal(await locate(page, 'project.agent').getAttribute('aria-pressed'), 'false');
});

test('an Agent toggle that stays on spends nothing', { timeout: 60000 }, async () => {
  const { generate, settled, startClicks } = await setup('stuckAgent');
  const view = await settled(await generate(), 'paused');
  assert.equal(view.error.error_code, 'UNKNOWN_UI_CHANGE');
  assert.equal(await startClicks(), 0);
});

test('error bubble fails fast within 5s, not at timeout', { timeout: 60000 }, async () => {
  const { generate, settled, startClicks } = await setup('failTile');
  let t0;
  const stamp = (event) => { if (event.state === 'submitted') t0 = Date.now(); };
  jobEvents.on('event', stamp);
  open.push(() => jobEvents.off('event', stamp));
  const view = await settled(await generate({ max_generation_retries: 0 }), 'failed');
  assert.ok(Date.now() - t0 < 5000, `${Date.now() - t0}ms after Start`);
  assert.equal(view.error.error_code, 'FLOW_GENERATION_FAILED');
  assert.match(view.error.message, /Something went wrong/);
  assert.equal(view.error.credits_at_risk, true);
  assert.equal(await startClicks(), 1);
});

test('a failed image retries once by default and counts each paid attempt', { timeout: 60000 }, async () => {
  const { generate, settled, startClicks } = await setup('failOnce');
  const id = await generate();
  const view = await settled(id, 'done');
  assert.equal(view.attempt, 2);
  assert.equal(await startClicks(), 2);
  const saved = JSON.parse(fs.readFileSync(path.join(config.dataDir, 'ledger.json'), 'utf8'));
  assert.deepEqual(Object.keys(saved.spends).sort(), [`${id}#1`, `${id}#2`]);
});

test('a job with no new tile fails without hanging, and a saved Character is no result', { timeout: 60000 }, async () => {
  const { generate, settled } = await setup('noTile');
  config.noTileTimeoutMs = 800;
  const view = await settled(await generate(), 'failed');
  assert.equal(view.error.error_code, 'GENERATION_TIMEOUT');
  assert.match(view.error.message, /no new tile/i);
});

test('one image when x2 requested is RESULT_MISMATCH and keeps the file', { timeout: 60000 }, async () => {
  const { generate, settled } = await setup('oneImage');
  const view = await settled(await generate({ count: 2 }), 'failed');
  assert.equal(view.error.error_code, 'RESULT_MISMATCH');
  assert.equal(view.outputs.length, 1);
  assert.equal(fs.existsSync(view.outputs[0].file), true);
});

test('wrong dimensions for 16:9 is RESULT_MISMATCH', { timeout: 60000 }, async () => {
  const { generate, settled } = await setup('wrongDims');
  const view = await settled(await generate(), 'failed');
  assert.equal(view.error.error_code, 'RESULT_MISMATCH');
  assert.match(view.error.message, /ratio/);
  assert.equal(fs.existsSync(view.outputs[0].file), true);
});

test('quota text pauses the run', { timeout: 60000 }, async () => {
  const { generate, settled, status, engine } = await setup('quotaToast');
  const one = await generate();
  const two = await generate({ prompt: 'two' });
  const view = await settled(one, 'paused');
  assert.equal(view.error.error_code, 'GOOGLE_LIMIT_REACHED');
  assert.equal(engine.worker.status().paused, 'GOOGLE_LIMIT_REACHED');
  assert.equal((await status(two)).state, 'queued');
});

test('CAPTCHA page sets needs_user and brings the window forward', { timeout: 60000 }, async () => {
  const { generate, settled, page } = await setup('captcha');
  let raised = 0;
  const real = page.bringToFront.bind(page);
  page.bringToFront = () => { raised++; return real(); };
  const view = await settled(await generate(), 'needs_user');
  assert.equal(view.error.error_code, 'MANUAL_VERIFICATION_REQUIRED');
  assert.equal(raised, 1);
});

test("unwritable output keeps the job downloadable and doesn't regenerate", { timeout: 60000 }, async () => {
  const { generate, settled, startClicks, engine } = await setup('slowGen');
  let images;
  const block = (event) => {
    if (event.state !== 'submitted') return;
    images = path.join(jobOf(event.jobId).run.dir, 'images');
    fs.rmSync(images, { recursive: true });
    fs.writeFileSync(images, 'a file where the folder should be');
  };
  jobEvents.on('event', block);
  open.push(() => jobEvents.off('event', block));
  const id = await generate({ count: 2 });
  const view = await settled(id, 'failed');
  assert.equal(view.error.error_code, 'DOWNLOAD_FAILED');
  assert.equal(view.error.retryable, true);
  assert.equal(await startClicks(), 1);

  fs.rmSync(images);
  fs.mkdirSync(images);
  assert.ok((await rpc(engine, 'flow_job_control', { action: 'retry_failed', job_id: id })).ok);
  const done = await settled(id, 'done');
  assert.equal(await startClicks(), 1, 'the generation is not repeated');
  assert.equal(done.attempt, 1);
  assert.equal(done.outputs.length, 2);
  assert.equal(done.error, undefined);
  done.outputs.forEach((o) => assert.equal(fs.existsSync(o.file), true));
});

test('settings readback mismatch throws before submit', { timeout: 60000 }, async () => {
  const { generate, settled, startClicks } = await setup('stickyRatio');
  const id = await generate();
  const view = await settled(id, 'paused');
  assert.equal(view.error.error_code, 'UNKNOWN_UI_CHANGE');
  assert.match(view.error.message, /16:9/);
  assert.equal(view.error.credits_at_risk, false);
  assert.equal(jobOf(id).submittedAt, undefined);
  assert.equal(await startClicks(), 0);
});

test('a live quote above max_credits spends nothing', { timeout: 60000 }, async () => {
  const { generate, settled, startClicks } = await setup('dearQuote');
  const view = await settled(await generate({ max_credits: 30 }), 'paused');
  assert.equal(view.error.error_code, 'BUDGET_EXCEEDED');
  assert.equal(await startClicks(), 0);
});

test('auto_confirm false stops before Start and spends nothing', { timeout: 60000 }, async () => {
  const { engine, startClicks } = await setup();
  const { result } = await rpc(engine, 'flow_generate_image', { prompt: 'a boat' });
  assert.equal(result.status, 'ready_for_confirmation');
  assert.equal(await startClicks(), 0);
});

test('submitted is journaled before Start is clicked', { timeout: 60000 }, async () => {
  const { generate, settled, page, startClicks } = await setup();
  let atClick = null;
  page.on('request', (req) => {
    if (!req.url().endsWith('/__click') || req.postData() !== 'Start generation') return;
    const events = fs.readFileSync(path.join(allRuns().at(-1).dir, 'events.jsonl'), 'utf8');
    atClick = events.includes('"to":"submitted"');
  });
  await settled(await generate(), 'done');
  assert.equal(await startClicks(), 1);
  assert.equal(atClick, true);
});

test('the navigation guard holds around the real Start click', { timeout: 60000 }, async () => {
  const { flow, page, generate, settled, status, startClicks, engine } = await setup('slowGen');
  const one = await generate();
  const two = await generate({ prompt: 'two' });
  await settled(one, 'generating');
  assert.equal(await startClicks(), 1);
  await page.goto(`${flow.url}/`);
  const view = await settled(one, 'failed');
  assert.equal(view.error.error_code, 'FLOW_PAGE_NOT_FOUND');
  assert.equal((await status(two)).state, 'queued');
  assert.ok(engine.worker.status().paused);
});

test('files and Characters attach, with Add to prompt optional, and the chip count gates Start', { timeout: 60000 }, async () => {
  const file = path.join(tmp, 'ref.png');
  fs.writeFileSync(file, 'x');
  const { generate, settled, clicks } = await setup('attachNow');
  await settled(await generate({ ingredients: [file, { character: 'y0 narrator' }] }), 'done');
  assert.equal((await clicks())['Add to prompt'], undefined);

  const { page } = await flowPage();
  await addIngredient(page, file);
  assert.equal(await locate(page, 'project.chip.ingredient').count(), 1, 'Add to prompt path');
  await assert.rejects(addIngredient(page, { character: 'y0 narrator', project: 'Nope' }), { code: 'PROJECT_NOT_FOUND' });
});

test('a stalled upload is tried 3 times, then UPLOAD_STALLED with no spend', { timeout: 60000 }, async () => {
  const file = path.join(tmp, 'stall.png');
  fs.writeFileSync(file, 'x');
  const { generate, settled, startClicks } = await setup('uploadStalls');
  config.uploadTimeoutMs = 300;
  const view = await settled(await generate({ ingredients: [file] }), 'failed');
  delete config.uploadTimeoutMs;
  assert.equal(view.error.error_code, 'UPLOAD_STALLED');
  assert.equal(await startClicks(), 0);
});

test('jitter stays within 25 percent', () => {
  for (let i = 0; i < 200; i++) {
    const value = jitter(1000);
    assert.ok(value >= 750 && value <= 1250, String(value));
  }
});

test('withRetry backs off, stops at 3 tries and never retries a spend or a caller error', async () => {
  let calls = 0;
  const stalled = () => { calls++; throw createError(ErrorCodes.UPLOAD_STALLED, 'x'); };
  const t0 = Date.now();
  await assert.rejects(withRetry(stalled, { baseMs: 40 }), { code: 'UPLOAD_STALLED' });
  assert.equal(calls, 3);
  assert.ok(Date.now() - t0 >= (40 + 80) * 0.75 - 5, 'waited with exponential backoff');
  for (const code of [ErrorCodes.FLOW_GENERATION_FAILED, ErrorCodes.INVALID_PARAMS]) {
    calls = 0;
    await assert.rejects(withRetry(() => { calls++; throw createError(code, 'x'); }, { baseMs: 1 }), { code });
    assert.equal(calls, 1, code);
  }
  assert.equal(await withRetry(async () => 7), 7);
});

test('verifyImage applies the 3% ratio tolerance and checks the shown model', () => {
  const file = path.join(tmp, 'v.jpg');
  fs.writeFileSync(file, fakeJpeg(1376, 768)); // 1.79:1 is what Flow calls 16:9
  assert.deepEqual(verifyImage(file, { ratio: '16:9' }).mismatches, []);
  assert.equal(verifyImage(file, { ratio: '16:9' }).ok, true);
  assert.match(verifyImage(file, { ratio: '1:1' }).mismatches[0], /ratio/);
  assert.match(verifyImage(file, { ratio: '16:9', model: 'bananaPro', info: 'Created 🍌 Nano Banana 2.1 16:9' }).mismatches[0], /model/);
  assert.equal(verifyImage(file, { ratio: '16:9', model: 'banana21', info: 'Created 🍌 Nano Banana 2.1 16:9' }).ok, true);
  fs.writeFileSync(file, 'not an image');
  assert.equal(verifyImage(file, { ratio: '16:9' }).ok, false);
});

test('the old queue and tools are gone', () => {
  for (const file of ['queue/job-queue.js', 'tools/generate-image.js', 'tools/download-latest.js', 'utils/file-manager.js']) {
    assert.equal(fs.existsSync(new URL(`../src/${file}`, import.meta.url)), false, file);
  }
});
