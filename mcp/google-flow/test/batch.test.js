import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'fs';
import os from 'os';
import path from 'path';

// Stubs only: no browser, no Flow. Port 1 makes any accidental attach fail.
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'batch-'));
process.env.FLOW_DATA_DIR = path.join(tmp, 'data');
process.env.FLOW_CDP_PORT = '1';
const { default: config } = await import('../src/utils/config.js');
const { startEngine } = await import('../src/engine/server.js');
const { rpc } = await import('../src/shim/client.js');
const { closeLog } = await import('../src/utils/logger.js');
const { parseCsv } = await import('../src/engine/batch.js');
const { createRun } = await import('../src/engine/run-folder.js');
const { enqueue, transition } = await import('../src/engine/job-store.js');
const { FlowError } = await import('../src/utils/errors.js');
const { matchTiles } = await import('../src/flow/reconcile.js');

const noPacer = { waitTurn: async () => {}, recordUse: () => {}, capReached: () => false };
const engines = [];
let dirs = 0;
let touched = 0;
const noPage = { ensure: async () => { touched++; return { browser: null, page: null }; }, peek: () => null };
const tab = { once() {}, off() {} };
const stubPage = { ensure: async () => ({ browser: null, page: tab }), peek: () => null };
const outputRoot = path.join(tmp, 'out');

function freshData() {
  config.dataDir = path.join(tmp, `d${++dirs}`);
  fs.mkdirSync(config.dataDir, { recursive: true });
  process.env.FLOW_DATA_DIR = config.dataDir;
}

async function engineWith(options = {}) {
  const engine = await startEngine({ adapter: async (job, ctx) => { ctx.submit(0); return { outputs: [] }; }, session: noPage, pacer: noPacer, ...options });
  engines.push(engine);
  return engine;
}

const until = async (check, ms = 10000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const value = await check();
    if (value) return value;
    await new Promise((r) => setTimeout(r, 20));
  }
  throw new Error('condition not met in time');
};

const images = (prompts) => prompts.map((prompt) => ({ prompt }));
const start = async (engine, args) => {
  const res = await rpc(engine, 'flow_batch_start', { auto_confirm: true, output_root: outputRoot, ...args });
  assert.ok(res.ok, res.message);
  return res.result;
};
const counts = async (engine, run_id) => (await rpc(engine, 'flow_job_status', { run_id })).result.counts;
const jobsOf = async (engine, run_id) => (await rpc(engine, 'flow_job_status', { run_id, detail: 'full' })).result.jobs;
const settled = (engine, run_id, wanted) => until(async () => {
  const c = await counts(engine, run_id);
  return Object.entries(wanted).every(([state, n]) => c[state] === n);
});
const refuse = (code) => new FlowError(code, 'stubbed');

after(async () => {
  await Promise.all(engines.map((engine) => engine.stop()));
  await closeLog();
  fs.rmSync(tmp, { recursive: true, force: true });
});

test('CSV: quotes, numbers, ingredients and blank rows', () => {
  const jobs = parseCsv('Prompt,count,kind,ingredients,silent\r\n"a, ""quoted""\nboat",2,,character:Ann; scene:Dock; x.png,\r\n,,,,\r\nb,,video,,TRUE\r\n');
  assert.deepEqual(jobs, [
    { prompt: 'a, "quoted"\nboat', count: 2, ingredients: [{ character: 'Ann' }, { scene: 'Dock' }, 'x.png'] },
    { prompt: 'b', kind: 'video', silent: true },
  ]);
  assert.throws(() => parseCsv('model\nx\n'), /prompt column/);
  assert.throws(() => parseCsv('prompt\n"open\n'), /unterminated/);
  assert.throws(() => parseCsv('prompt\na,b\n'), /row 2/);
});

test('jobs come from a JSON or CSV file, with defaults under each row', async () => {
  freshData();
  const engine = await engineWith();
  const json = path.join(tmp, 'b.json');
  const csv = path.join(tmp, 'b.csv');
  fs.writeFileSync(json, JSON.stringify({ jobs: [{ prompt: 'one' }, { prompt: 'two', count: 2 }] }));
  fs.writeFileSync(csv, 'prompt,count\nthree,2\nfour,\n');
  const dry = (file) => rpc(engine, 'flow_batch_start', { file, defaults: { model: 'bananaPro' } });
  for (const file of [json, csv]) {
    const { result } = await dry(file);
    assert.equal(result.jobs, 2);
    assert.deepEqual(result.estimate.imageQuota, { bananaPro: 3 });
  }
  assert.equal((await dry(path.join(tmp, 'missing.csv'))).error_code, 'INVALID_PARAMS');
  assert.equal((await rpc(engine, 'flow_batch_start', { file: json, jobs: [] })).error_code, 'INVALID_PARAMS');
});

test('a 200-job mixed batch estimates before any browser use', async () => {
  freshData();
  const engine = await engineWith();
  touched = 0;
  const jobs = Array.from({ length: 200 }, (_, i) => (i % 2 ? { prompt: `v${i}`, kind: 'video' } : { prompt: `i${i}` }));
  const { result } = await rpc(engine, 'flow_batch_start', { jobs });
  assert.equal(result.status, 'ready_for_confirmation');
  assert.equal(result.queued, 0);
  assert.ok(result.estimate.credits > 0);
  assert.equal(result.estimate.imageQuota.banana21, 100);
  assert.equal(touched, 0);
});

test('budget overrun and a bad row reject at start, queuing nothing', async () => {
  freshData();
  const engine = await engineWith();
  const video = { prompt: 'v', kind: 'video' };
  const over = await rpc(engine, 'flow_batch_start', { jobs: [video, video], max_credits: 1, auto_confirm: true, output_root: outputRoot });
  assert.equal(over.error_code, 'BUDGET_EXCEEDED');
  const bad = await rpc(engine, 'flow_batch_start', { jobs: [{ prompt: 'ok' }, { prompt: '' }], auto_confirm: true, output_root: outputRoot });
  assert.equal(bad.error_code, 'INVALID_PARAMS');
  assert.match(bad.message, /^Job 2:/);
  assert.deepEqual((await rpc(engine, 'flow_list_runs', {})).result.runs, []);
});

test('a repeated idempotency key returns the first run', async () => {
  freshData();
  const engine = await engineWith();
  const one = await start(engine, { jobs: images(['a', 'b']), idempotency_key: 'k' });
  const two = await start(engine, { jobs: images(['a', 'b']), idempotency_key: 'k' });
  assert.equal(two.run_id, one.run_id);
  assert.equal(two.repeated, true);
});

test('one refused job doesn\'t stop the rest', async () => {
  freshData();
  const ran = [];
  const engine = await engineWith({
    adapter: async ({ spec }, ctx) => {
      ran.push(spec.prompt);
      ctx.submit(0);
      if (spec.prompt === 'b') throw refuse('RESULT_MISMATCH');
      return { outputs: [] };
    },
  });
  const { run_id } = await start(engine, { jobs: images(['a', 'b', 'c']) });
  await settled(engine, run_id, { done: 2, failed: 1 });
  assert.deepEqual(ran, ['a', 'b', 'c']);
});

test('stop_on holds the rest of the run as paused, and resume runs them', async () => {
  for (const stop_on of ['failure', ['RESULT_MISMATCH']]) {
    freshData();
    const ran = [];
    const engine = await engineWith({
      adapter: async ({ spec }, ctx) => {
        ran.push(spec.prompt);
        ctx.submit(0);
        if (spec.prompt === 'a') throw refuse('RESULT_MISMATCH');
        return { outputs: [] };
      },
    });
    const { run_id } = await start(engine, { jobs: images(['a', 'b', 'c']), stop_on });
    await settled(engine, run_id, { failed: 1, paused: 2 });
    assert.deepEqual(ran, ['a']);
    assert.ok((await rpc(engine, 'flow_job_control', { action: 'resume', run_id })).ok);
    await settled(engine, run_id, { failed: 1, done: 2 });
    assert.deepEqual(ran, ['a', 'b', 'c']);
  }
});

test('stop_on with another code does not stop, and a bad value is refused', async () => {
  freshData();
  const engine = await engineWith({ adapter: async (job, ctx) => { ctx.submit(0); throw refuse('RESULT_MISMATCH'); } });
  const { run_id } = await start(engine, { jobs: images(['a', 'b']), stop_on: ['DOWNLOAD_FAILED'] });
  await settled(engine, run_id, { failed: 2 });
  assert.equal((await rpc(engine, 'flow_batch_start', { jobs: images(['a']), stop_on: 'sometimes' })).error_code, 'INVALID_PARAMS');
});

test('quota stops the rest as resumable, and resume runs only unfinished', async () => {
  freshData();
  const ran = [];
  let quota = true;
  const engine = await engineWith({
    adapter: async ({ spec }, ctx) => {
      ran.push(spec.prompt);
      if (spec.prompt === 'b' && quota) {
        quota = false;
        throw refuse('DAILY_MODEL_LIMIT');
      }
      ctx.submit(0);
      return { outputs: [] };
    },
  });
  const { run_id } = await start(engine, { jobs: images(['a', 'b', 'c']) });
  await settled(engine, run_id, { done: 1, paused: 1, queued: 1 });
  assert.equal(engine.worker.status().paused, 'DAILY_MODEL_LIMIT');
  assert.deepEqual(ran, ['a', 'b']);
  assert.ok((await rpc(engine, 'flow_job_control', { action: 'resume', run_id })).ok);
  await settled(engine, run_id, { done: 3 });
  assert.deepEqual(ran, ['a', 'b', 'b', 'c']);
});

test('retry_failed runs only failed and checks the spend budget', async () => {
  freshData();
  const ran = [];
  let failing = true;
  const engine = await engineWith({
    adapter: async ({ spec }, ctx) => {
      ran.push(spec.prompt);
      ctx.submit(0);
      if (spec.prompt === 'bad' && failing) throw refuse('RESULT_MISMATCH');
      return { outputs: [] };
    },
  });
  const video = { prompt: 'bad', kind: 'video' };
  const { run_id } = await start(engine, { jobs: [{ prompt: 'good' }, video], max_credits: 1000 });
  await settled(engine, run_id, { done: 1, failed: 1 });
  const refused = await rpc(engine, 'flow_job_control', { action: 'retry_failed', run_id, max_credits: 0 });
  assert.equal(refused.error_code, 'BUDGET_EXCEEDED');
  assert.equal((await counts(engine, run_id)).failed, 1);
  failing = false;
  assert.ok((await rpc(engine, 'flow_job_control', { action: 'retry_failed', run_id, max_credits: 1000 })).ok);
  await settled(engine, run_id, { done: 2 });
  assert.deepEqual(ran, ['good', 'bad', 'bad']);
});

test('cancel lets the current job finish its download', async () => {
  freshData();
  let finish;
  const downloading = new Promise((resolve) => {
    finish = resolve;
  });
  let reached;
  const atDownload = new Promise((resolve) => { reached = resolve; });
  const engine = await engineWith({
    adapter: async (job, ctx) => {
      ctx.submit(0);
      transition(job, 'generating');
      transition(job, 'downloading', { media: ['m'] });
      reached();
      await downloading;
      return { outputs: [] };
    },
  });
  const { run_id } = await start(engine, { jobs: images(['a', 'b']) });
  await atDownload;
  assert.ok((await rpc(engine, 'flow_job_control', { action: 'cancel', run_id })).ok);
  finish();
  await settled(engine, run_id, { done: 1, cancelled: 1 });
});

// --- past the credit line after a restart ---

const before = { ids: ['old1', 'old2'], firstIndex: 0, slots: ['old1', 'old2'] };

function lostJob(data = { before, projectUrl: 'https://flow.example/project/p' }) {
  const run = createRun({ name: 'r', outputRoot });
  const job = enqueue(run, { kind: 'image', prompt: 'paid', count: 1, model: 'banana21', size: '1K' });
  transition(job, 'preparing');
  transition(job, 'submitted', data);
  return job;
}

test('reconcile found: the job downloads with no second generation', async () => {
  freshData();
  const job = lostJob();
  const saved = [];
  const engine = await engineWith({
    session: stubPage,
    reconcile: async () => ({ found: true, assets: ['new1'] }),
    adapter: async (j) => {
      assert.equal(j.state, 'downloading', 'the adapter must only download');
      saved.push(...j.data.media);
      return { outputs: [] };
    },
  });
  await until(async () => (await rpc(engine, 'flow_job_status', { job_id: job.id })).result.state === 'done');
  assert.deepEqual(saved, ['new1']);
});

test('reconcile not found or broken: failed with credits at risk, never run again', async () => {
  for (const reconcile of [async () => ({ found: false, assets: [] }), async () => { throw new Error('page broke'); }]) {
    freshData();
    const job = lostJob();
    let ran = 0;
    const engine = await engineWith({ session: stubPage, reconcile, adapter: async () => { ran++; } });
    const view = await until(async () => {
      const { result } = await rpc(engine, 'flow_job_status', { job_id: job.id });
      return result.state === 'failed' && result;
    });
    assert.equal(view.error.credits_at_risk, true);
    assert.equal(ran, 0);
  }
});

test('with Chrome gone the job is looked for again on resume, not written off', async () => {
  freshData();
  const job = lostJob();
  let up = false;
  const session = {
    peek: () => null,
    ensure: async () => {
      if (!up) throw new FlowError('BROWSER_NOT_CONNECTED', 'no Chrome');
      return { browser: null, page: tab };
    },
  };
  const engine = await engineWith({ session, reconcile: async () => ({ found: true, assets: ['new1'] }), adapter: async () => ({ outputs: [] }) });
  await until(() => engine.worker.status().paused === 'BROWSER_NOT_CONNECTED');
  assert.equal((await rpc(engine, 'flow_job_status', { job_id: job.id })).result.state, 'submitted');
  up = true;
  await rpc(engine, 'flow_job_control', { action: 'resume' });
  await until(async () => (await rpc(engine, 'flow_job_status', { job_id: job.id })).result.state === 'done');
});

test('a job lost in verifying re-checks without reconcile', async () => {
  freshData();
  const job = lostJob();
  transition(job, 'downloading', { media: ['m'] });
  transition(job, 'verifying', { outputs: [{ mediaId: 'm', file: 'x' }] });
  let looked = 0;
  let saved;
  const engine = await engineWith({
    session: stubPage,
    reconcile: async () => { looked++; return { found: false }; },
    adapter: async (j) => { saved = j.data.saved; transition(j, 'verifying'); return { outputs: j.data.saved }; },
  });
  await until(async () => (await rpc(engine, 'flow_job_status', { job_id: job.id })).result.state === 'done');
  assert.equal(looked, 0);
  assert.deepEqual(saved.map(({ mediaId }) => mediaId), ['m']);
});

// --- matching the grid, from what the real page shows ---

const done = (mediaId, label = 'Auto title') => ({ mediaId, label, text: '' });
const query = { prompt: 'a red  boat', before, count: 1 };

test('matchTiles: a new tile above the shifted baseline is the result', () => {
  assert.deepEqual(matchTiles([done('new'), done('old1'), done('old2')], query).assets, ['new']);
});

test('matchTiles: an unshifted grid has no result, even if a baseline id changed', () => {
  // A video's stand-in id can differ after a reload; its place in the grid still gives it away.
  assert.deepEqual(matchTiles([done('old1b'), done('old2')], { ...query, before: { ...before, slots: ['old1', 'old2'] } }).assets, []);
});

test('matchTiles: a later result above ours is not taken for it', () => {
  assert.deepEqual(matchTiles([done('later'), done('ours'), done('old1')], query).assets, ['ours']);
});

test('matchTiles: reports a tile still running', () => {
  const { running, assets } = matchTiles([{ mediaId: null, label: 'a red boat', text: 'image 40% a red boat' }, done('old1')], query);
  assert.equal(running.length, 1);
  assert.deepEqual(assets, []);
});

test('matchTiles: baseline out of the window matches by prompt only', () => {
  const tiles = [done('x'), done('y', 'a red boat')];
  assert.deepEqual(matchTiles(tiles, query).assets, ['y']);
  assert.deepEqual(matchTiles([done('x'), done('z')], query).assets, []);
});

test('matchTiles: an empty baseline makes every tile new', () => {
  const empty = { ids: [], firstIndex: -1, slots: [] };
  assert.deepEqual(matchTiles([done('a'), done('b')], { ...query, before: empty, count: 2 }).assets, ['a', 'b']);
});
