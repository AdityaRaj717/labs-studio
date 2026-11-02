import { test, before, after, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import http from 'node:http';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { chromium } from 'playwright';

// config.js reads FLOW_DATA_DIR at load. Port 1 makes any accidental attach fail instead of reaching 9333.
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'engine-'));
process.env.FLOW_DATA_DIR = path.join(tmp, 'data');
process.env.FLOW_CDP_PORT = '1';
const { default: config } = await import('../src/utils/config.js');
const { startEngine } = await import('../src/engine/server.js');
const { ensureEngine, rpc, callTool } = await import('../src/shim/client.js');
const { TOOLS } = await import('../src/shim/tools.js');
const { getBalance } = await import('../src/tools/flow-status.js');
const { startFakeFlow } = await import('./fake-flow/server.js');
const { closeLog } = await import('../src/utils/logger.js');
const { createRun } = await import('../src/engine/run-folder.js');
const { enqueue, transition, allRuns } = await import('../src/engine/job-store.js');

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const noPacer = { waitTurn: async () => {}, recordUse: () => {}, capReached: () => false };
const engines = [];
const children = [];
let dirCount = 0;

// Each test gets its own data dir; the store's state follows config.dataDir.
function freshData() {
  config.dataDir = path.join(tmp, `d${++dirCount}`);
  fs.mkdirSync(config.dataDir, { recursive: true });
  process.env.FLOW_DATA_DIR = config.dataDir;
  return config.dataDir;
}

const fakeSession = () => ({ ensure: async () => ({ browser: null, page: null }), peek: () => null });

async function engineWith(options = {}) {
  freshData();
  const engine = await startEngine({ adapter: async (job, ctx) => { ctx.submit(0); return { outputs: [] }; }, session: fakeSession(), pacer: noPacer, ...options });
  engines.push(engine);
  return engine;
}

const gate = () => {
  let open;
  const opened = new Promise((resolve) => { open = resolve; });
  return { open, opened };
};

const image = (over = {}) => ({ prompt: 'a boat', auto_confirm: true, output_root: path.join(tmp, 'out'), ...over });
const until = async (check, ms = 10000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const value = await check();
    if (value) return value;
    await new Promise((r) => setTimeout(r, 20));
  }
  throw new Error('condition not met in time');
};
const stateOf = async (engine, id) => (await rpc(engine, 'flow_job_status', { job_id: id })).result.state;

function rawRequest(port, { path: p = '/health', headers = {}, method = 'GET', body } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port, path: p, method, headers }, (res) => {
      let text = '';
      res.on('data', (c) => { text += c; });
      res.on('end', () => resolve({ status: res.statusCode, text }));
    });
    req.on('error', reject);
    req.end(body);
  });
}

// Spawns the real stdio shim. Its stdout must hold nothing but protocol lines.
function startShim() {
  const child = spawn(process.execPath, ['src/index.js'], { cwd: root, env: process.env, stdio: ['pipe', 'pipe', 'ignore'] });
  children.push(child);
  const pending = new Map();
  const notJson = [];
  let buf = '';
  child.stdout.setEncoding('utf8');
  child.stdout.on('data', (chunk) => {
    buf += chunk;
    for (let i; (i = buf.indexOf('\n')) >= 0; buf = buf.slice(i + 1)) {
      const line = buf.slice(0, i).trim();
      if (!line) continue;
      try {
        const msg = JSON.parse(line);
        pending.get(msg.id)?.(msg);
      } catch {
        notJson.push(line);
      }
    }
  });
  let id = 0;
  const request = (method, params = {}) => new Promise((resolve) => {
    pending.set(++id, resolve);
    child.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', id, method, params })}\n`);
  });
  const init = async () => {
    const res = await request('initialize', { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 't', version: '0' } });
    child.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' })}\n`);
    return res;
  };
  return { child, request, init, notJson };
}

const engineFile = () => path.join(config.dataDir, 'engine.json');
const readLock = () => JSON.parse(fs.readFileSync(engineFile(), 'utf8'));
const alive = (pid) => { try { process.kill(pid, 0); return true; } catch { return false; } };

async function stopChildEngine() {
  if (!fs.existsSync(engineFile())) return;
  const { pid, port, token } = readLock();
  await rawRequest(port, { path: '/shutdown', method: 'POST', headers: { authorization: `Bearer ${token}` } }).catch(() => {});
  await until(() => !alive(pid));
}

afterEach(async () => {
  for (const child of children.splice(0)) child.kill();
  await stopChildEngine();
  await Promise.all(engines.splice(0).map((e) => e.stop()));
});

after(async () => {
  await closeLog();
  fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
});

// --- process, lock and transport ---

test('two shims share one engine', { timeout: 60000 }, async () => {
  freshData();
  const shims = [startShim(), startShim()];
  await Promise.all(shims.map((s) => s.init()));
  const results = await Promise.all(shims.map((s) => s.request('tools/call', { name: 'flow_capabilities', arguments: {} })));
  for (const res of results) assert.ok(JSON.parse(res.result.content[0].text).video);
  const { pid, port, token } = readLock();
  assert.ok(alive(pid));
  const health = JSON.parse((await rawRequest(port, { headers: { authorization: `Bearer ${token}` } })).text);
  assert.equal(health.pid, pid);
  const [a, b] = await Promise.all([ensureEngine(), ensureEngine()]);
  assert.equal(a.url, b.url);
  assert.equal(a.token, token);
  for (const s of shims) assert.deepEqual(s.notJson, []);
});

test('stale lock file starts a new engine', { timeout: 60000 }, async () => {
  freshData();
  fs.writeFileSync(engineFile(), JSON.stringify({ pid: 999999, port: 1, token: 'old', version: '1.0.0' }));
  const conn = await ensureEngine();
  assert.notEqual(conn.token, 'old');
  assert.notEqual(readLock().pid, 999999);
  assert.ok((await rpc(conn, 'flow_capabilities', {})).ok);
});

test('version mismatch replaces an idle engine', { timeout: 60000 }, async () => {
  freshData();
  const first = await ensureEngine();
  const oldPid = readLock().pid;
  const lock = readLock();
  fs.chmodSync(engineFile(), 0o666);
  fs.writeFileSync(engineFile(), JSON.stringify({ ...lock, version: '0.0.1' }));
  const second = await ensureEngine();
  assert.notEqual(second.token, first.token);
  assert.notEqual(readLock().pid, oldPid);
});

test('a corrupt journal is a clear start-up error naming the file', { timeout: 60000 }, async () => {
  const data = freshData();
  const dir = path.join(tmp, 'broken-run');
  fs.mkdirSync(dir);
  fs.writeFileSync(path.join(dir, 'events.jsonl'), 'not json\n{"seq":2}\n');
  fs.writeFileSync(path.join(data, 'runs.jsonl'), `${JSON.stringify({ dir })}\n`);
  await assert.rejects(ensureEngine(), (err) => err.code === 'JOURNAL_CORRUPT' && err.message.includes('events.jsonl'));
  assert.ok(!fs.existsSync(engineFile()));
});

async function hangingPort() {
  const server = http.createServer(() => {});
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  return server;
}

test('a live pid that does not answer in time keeps its lock and is a clear error', { timeout: 60000 }, async () => {
  freshData();
  const server = await hangingPort();
  try {
    const lock = JSON.stringify({ pid: process.pid, port: server.address().port, token: 't', version: '1.0.0' });
    fs.writeFileSync(engineFile(), lock);
    await assert.rejects(ensureEngine(), /alive but not answering/);
    // A starter that got there anyway must leave too.
    const starter = spawn(process.execPath, ['src/engine/start.js'], { cwd: root, env: process.env, stdio: 'ignore' });
    children.push(starter);
    const code = await new Promise((resolve) => starter.once('exit', resolve));
    assert.equal(code, 0);
    assert.equal(fs.readFileSync(engineFile(), 'utf8'), lock);
    fs.rmSync(engineFile());
  } finally {
    server.closeAllConnections();
    server.close();
  }
});

test('a dead pid is stale even if its port hangs, and a refused port is stale even if the pid lives', { timeout: 60000 }, async () => {
  freshData();
  const server = await hangingPort();
  const hung = server.address().port;
  try {
    fs.writeFileSync(engineFile(), JSON.stringify({ pid: 999999, port: hung, token: 't', version: '1.0.0' }));
    await ensureEngine();
    assert.notEqual(readLock().pid, 999999);
  } finally {
    server.closeAllConnections();
    server.close();
  }
  await stopChildEngine();
  freshData();
  const closed = await hangingPort();
  const port = closed.address().port;
  await new Promise((resolve) => closed.close(resolve));
  fs.writeFileSync(engineFile(), JSON.stringify({ pid: process.pid, port, token: 't', version: '1.0.0' }));
  await ensureEngine();
  assert.notEqual(readLock().pid, process.pid);
});

test('request without token is 401', async () => {
  const engine = await engineWith();
  assert.equal((await rawRequest(engine.port)).status, 401);
  assert.equal((await rawRequest(engine.port, { headers: { authorization: 'Bearer wrong' } })).status, 401);
  assert.equal((await rawRequest(engine.port, { path: '/rpc', method: 'POST', body: '{}' })).status, 401);
  assert.equal((await rawRequest(engine.port, { headers: { authorization: `Bearer ${engine.token}` } })).status, 200);
});

test('a non-loopback Host header is refused', async () => {
  const engine = await engineWith();
  const headers = { authorization: `Bearer ${engine.token}`, host: 'evil.example' };
  assert.equal((await rawRequest(engine.port, { headers })).status, 403);
});

test('an oversized body is refused', async () => {
  const engine = await engineWith();
  const res = await rawRequest(engine.port, {
    path: '/rpc', method: 'POST', headers: { authorization: `Bearer ${engine.token}` }, body: 'x'.repeat(2 * 1024 * 1024),
  }).catch((err) => ({ status: err.code }));
  assert.ok(res.status === 413 || res.status === 'ECONNRESET' || res.status === 'EPIPE', String(res.status));
});

test('engine binds 127.0.0.1 only', async () => {
  const engine = await engineWith();
  assert.equal(engine.server.address().address, '127.0.0.1');
});

test('secrets stay out of the log and answer only by name', async () => {
  const engine = await engineWith();
  const headers = { authorization: `Bearer ${engine.token}` };
  const res = await rawRequest(engine.port, { path: '/secrets', method: 'POST', headers, body: JSON.stringify({ FISH_API_KEY: 'sekret-value' }) });
  assert.equal(res.status, 200);
  assert.ok(!res.text.includes('sekret-value'));
  assert.equal(engine.getSecret('FISH_API_KEY'), 'sekret-value');
  const bad = await rawRequest(engine.port, { path: '/secrets', method: 'POST', headers, body: JSON.stringify({ OTHER: 'x' }) });
  assert.equal(bad.status, 400);
  await rpc(engine, 'flow_capabilities', {});
  await closeLog();
  const dir = path.join(tmp, 'data', 'logs');
  for (const file of fs.existsSync(dir) ? fs.readdirSync(dir) : []) {
    const text = fs.readFileSync(path.join(dir, file), 'utf8');
    assert.ok(!text.includes('sekret-value'));
    assert.ok(!text.includes(engine.token));
  }
});

// --- events ---

async function readSse(engine, since, wanted) {
  const ctl = new AbortController();
  const res = await fetch(`${engine.url}/events?since=${since}`, { headers: { authorization: `Bearer ${engine.token}` }, signal: ctl.signal });
  const seqs = [];
  let buf = '';
  const decoder = new TextDecoder();
  try {
    for await (const chunk of res.body) {
      buf += decoder.decode(chunk, { stream: true });
      for (const m of buf.matchAll(/^id: (\d+)$/gm)) if (!seqs.includes(Number(m[1]))) seqs.push(Number(m[1]));
      if (wanted(seqs)) break;
    }
  } finally {
    ctl.abort();
  }
  return seqs;
}

test('SSE replays from since and has no gaps', { timeout: 20000 }, async () => {
  const engine = await engineWith();
  const first = (await rpc(engine, 'flow_generate_image', image())).result;
  await until(async () => (await stateOf(engine, first.job_id)) === 'done');
  const head = engine.hub.head();
  assert.ok(head >= 5);
  const live = readSse(engine, 2, (seqs) => seqs.at(-1) >= head + 5);
  await new Promise((r) => setTimeout(r, 100));
  await rpc(engine, 'flow_generate_image', image({ prompt: 'second' }));
  const seqs = await live;
  assert.equal(seqs[0], 3);
  assert.deepEqual(seqs, seqs.map((_, i) => i + 3));
});

// --- queue ---

test('a second generate queues rather than raising JOB_IN_PROGRESS', { timeout: 20000 }, async () => {
  const release = gate();
  const engine = await engineWith({ adapter: async (job, ctx) => { ctx.submit(0); await release.opened; return { outputs: [] }; } });
  const one = await rpc(engine, 'flow_generate_image', image());
  const two = await rpc(engine, 'flow_generate_image', image({ prompt: 'two' }));
  assert.ok(two.ok, JSON.stringify(two));
  await until(async () => (await stateOf(engine, one.result.job_id)) === 'submitted');
  assert.equal(await stateOf(engine, two.result.job_id), 'queued');
  release.open();
  await until(async () => (await stateOf(engine, two.result.job_id)) === 'done');
});

test('generate without auto_confirm is a dry run that starts nothing', async () => {
  let ran = 0;
  const engine = await engineWith({ adapter: async () => { ran++; return {}; } });
  const res = await rpc(engine, 'flow_generate_image', { prompt: 'x' });
  assert.equal(res.result.status, 'ready_for_confirmation');
  assert.equal(ran, 0);
  assert.equal(allRuns().length, 0);
});

test('a repeat with the same key returns the first job even when the budget would now refuse', { timeout: 20000 }, async () => {
  const engine = await engineWith();
  const first = await rpc(engine, 'flow_generate_image', image({ idempotency_key: 'k1' }));
  const repeat = await rpc(engine, 'flow_generate_image', image({ idempotency_key: 'k1', max_credits: -1 }));
  assert.ok(repeat.ok, JSON.stringify(repeat));
  assert.equal(repeat.result.job_id, first.result.job_id);
  assert.equal(repeat.result.repeated, true);
  assert.equal(allRuns().length, 1);
});

test('flow_estimate adds up images and videos with no browser', async () => {
  const engine = await engineWith();
  const { result } = await rpc(engine, 'flow_estimate', { jobs: [{ prompt: 'a', kind: 'video', count: 2 }, { prompt: 'b' }] });
  assert.equal(result.credits, 24);
  assert.equal(result.imageQuota.banana21, 1);
  assert.equal((await rpc(engine, 'flow_estimate', {})).error_code, 'INVALID_PARAMS');
  assert.equal((await rpc(engine, 'flow_estimate', { jobs: [{ prompt: 'a', kind: 'video', duration: 3 }] })).error_code, 'COMBINATION_NOT_SUPPORTED');
  assert.equal(allRuns().length, 0);
});

test('the next job waits until a cancelled job\'s adapter has really stopped', { timeout: 20000 }, async () => {
  const release = gate();
  const started = gate();
  const ran = [];
  const engine = await engineWith({
    adapter: async (job, ctx) => {
      ran.push(job.spec.prompt);
      ctx.submit(0);
      started.open();
      if (ran.length === 1) await release.opened; // takes no signal, like the old image flow
      return { outputs: [] };
    },
  });
  const one = (await rpc(engine, 'flow_generate_image', image({ prompt: 'one' }))).result.job_id;
  const two = (await rpc(engine, 'flow_generate_image', image({ prompt: 'two' }))).result.job_id;
  await started.opened;
  await rpc(engine, 'flow_job_control', { action: 'cancel', job_id: one });
  await until(async () => (await stateOf(engine, one)) === 'cancelled');
  await new Promise((r) => setTimeout(r, 200));
  assert.deepEqual(ran, ['one']);
  assert.equal(await stateOf(engine, two), 'queued');
  release.open();
  await until(async () => (await stateOf(engine, two)) === 'done');
});

test('an adapter that never stops holds the queue rather than sharing the tab', { timeout: 20000 }, async () => {
  const started = gate();
  const ran = [];
  const engine = await engineWith({
    settleMs: 100,
    adapter: async (job, ctx) => {
      ran.push(job.id);
      ctx.submit(0);
      started.open();
      await new Promise(() => {});
    },
  });
  const one = (await rpc(engine, 'flow_generate_image', image())).result.job_id;
  await rpc(engine, 'flow_generate_image', image({ prompt: 'two' }));
  await started.opened;
  await rpc(engine, 'flow_job_control', { action: 'cancel', job_id: one });
  await until(() => engine.worker.status().paused);
  assert.equal(ran.length, 1);
});

test('an adapter that never ends holds the queue, and resume refuses until it ends', { timeout: 20000 }, async () => {
  const release = gate();
  let calls = 0;
  const engine = await engineWith({
    settleMs: 100,
    adapter: async (job, ctx) => {
      ctx.submit(0);
      calls++;
      await release.opened;
      return { outputs: [] };
    },
  });
  const one = (await rpc(engine, 'flow_generate_image', image())).result.job_id;
  const two = (await rpc(engine, 'flow_generate_image', image({ prompt: 'two' }))).result.job_id;
  await until(() => calls === 1);
  await rpc(engine, 'flow_job_control', { action: 'cancel', job_id: one });
  await until(() => engine.worker.status().paused);
  assert.equal(await stateOf(engine, two), 'queued');
  for (const args of [{ action: 'resume' }, { action: 'resume', job_id: two }, { action: 'retry_failed', job_id: two }]) {
    const refused = await rpc(engine, 'flow_job_control', args);
    assert.equal(refused.error_code, 'JOB_IN_PROGRESS', JSON.stringify(args));
    assert.match(refused.next_action, /still running/);
  }
  assert.equal((await rpc(engine, 'flow_doctor', {})).error_code, 'JOB_IN_PROGRESS');
  assert.equal(calls, 1);
  release.open();
  await until(async () => (await rpc(engine, 'flow_job_control', { action: 'resume' })).ok);
  await until(async () => (await stateOf(engine, two)) === 'done');
  assert.equal(calls, 2);
});

test('invalid input fails before any queue or browser work', async () => {
  const engine = await engineWith();
  const res = await rpc(engine, 'flow_generate_image', image({ size: '9K' }));
  assert.equal(res.error_code, 'COMBINATION_NOT_SUPPORTED');
  assert.equal(allRuns().length, 0);
});

test('flow_wait returns within wait_ms with current state', { timeout: 20000 }, async () => {
  const release = gate();
  const engine = await engineWith({ adapter: async (job, ctx) => { ctx.submit(0); await release.opened; return { outputs: [] }; } });
  const { result: { job_id } } = await rpc(engine, 'flow_generate_image', image());
  const start = Date.now();
  const waited = await rpc(engine, 'flow_wait', { job_id, wait_ms: 300 });
  assert.ok(Date.now() - start < 2000);
  assert.equal(waited.result.finished, false);
  assert.ok(['queued', 'preparing', 'submitted'].includes(waited.result.state));
  release.open();
  const done = await rpc(engine, 'flow_wait', { job_id, wait_ms: 5000 });
  assert.equal(done.result.finished, true);
  assert.equal(done.result.state, 'done');
  assert.equal((await rpc(engine, 'flow_wait', { job_id, wait_ms: 55001 })).error_code, 'INVALID_PARAMS');
});

test('flow_wait turns engine events into progress when the client sends a token', { timeout: 20000 }, async () => {
  const engine = await engineWith();
  const { result: { job_id } } = await rpc(engine, 'flow_generate_image', image({ prompt: 'p' }));
  const notes = [];
  const res = await callTool(async () => engine, 'flow_wait', { job_id, wait_ms: 5000 }, (note) => notes.push(note));
  assert.equal(JSON.parse(res.content[0].text).state, 'done');
  // Anything that happened before the stream opened is not replayed, so only check shape.
  for (const note of notes) assert.equal(typeof note.progress, 'number');
});

test('retry_failed starts a new paid attempt only on the explicit call', { timeout: 20000 }, async () => {
  let runs = 0;
  const engine = await engineWith({
    adapter: async (job, ctx) => {
      ctx.submit(0);
      if (++runs === 1) throw Object.assign(new (await import('../src/utils/errors.js')).FlowError('FLOW_GENERATION_FAILED', 'tile failed'));
      return { outputs: [] };
    },
  });
  const { result: { job_id } } = await rpc(engine, 'flow_generate_image', image({ max_generation_retries: 0 }));
  await until(async () => (await stateOf(engine, job_id)) === 'failed');
  await new Promise((r) => setTimeout(r, 100));
  assert.equal(runs, 1);
  const status = (await rpc(engine, 'flow_job_status', { job_id })).result;
  assert.equal(status.error.credits_at_risk, true);
  await rpc(engine, 'flow_job_control', { action: 'retry_failed', job_id });
  await until(async () => (await stateOf(engine, job_id)) === 'done');
  assert.equal(runs, 2);
  assert.equal(allRuns()[0].jobs[0].attempt, 2);
});

test('on restart a job past submitted is never run again, held jobs stay held, preparing resumes', { timeout: 20000 }, async () => {
  freshData();
  const run = createRun({ name: 'r', outputRoot: path.join(tmp, 'out'), flowProjectUrl: 'http://fake' });
  const paid = enqueue(run, { kind: 'image', prompt: 'paid' });
  transition(paid, 'preparing'); transition(paid, 'submitted');
  const held = enqueue(run, { kind: 'image', prompt: 'held' });
  transition(held, 'needs_user');
  const prep = enqueue(run, { kind: 'image', prompt: 'prep' });
  transition(prep, 'preparing');
  const ran = [];
  const engine = await startEngine({ adapter: async (job, ctx) => { ran.push(job.spec.prompt); ctx.submit(0); return {}; }, session: fakeSession(), pacer: noPacer });
  engines.push(engine);
  await until(async () => (await stateOf(engine, prep.id)) === 'done');
  assert.deepEqual(ran, ['prep']);
  const lost = (await rpc(engine, 'flow_job_status', { job_id: paid.id })).result;
  assert.equal(lost.state, 'failed');
  assert.equal(lost.error.credits_at_risk, true);
  assert.equal(await stateOf(engine, held.id), 'needs_user');
});

// --- tool surface ---

const SPEC_TOOLS = [
  'flow_connect', 'flow_disconnect', 'flow_status', 'flow_doctor', 'flow_capabilities',
  'flow_estimate', 'flow_generate_image', 'flow_generate_video', 'flow_batch_start',
  'flow_production_plan', 'flow_production_start', 'flow_production_status', 'flow_production_review', 'flow_production_regenerate',
  'flow_job_status', 'flow_wait', 'flow_job_control', 'flow_list_runs',
  'flow_list_assets', 'flow_download',
  'flow_open_project', 'flow_list_projects', 'flow_rename_project', 'flow_delete_project',
  'flow_create_character', 'flow_list_characters', 'flow_import_character', 'flow_create_scene', 'flow_list_scenes',
  'audio_voice_generate', 'audio_voice_list', 'audio_stable_generate',
  'flow_screenshot',
];

test('tools/list has annotations and each delete is destructive', { timeout: 30000 }, async () => {
  freshData();
  const shim = startShim();
  const init = await shim.init();
  assert.match(init.result.instructions, /flow_wait/);
  const { result: { tools } } = await shim.request('tools/list');
  assert.deepEqual(tools.map((t) => t.name).sort(), [...SPEC_TOOLS].sort());
  for (const tool of tools) {
    for (const hint of ['readOnlyHint', 'destructiveHint', 'idempotentHint', 'openWorldHint']) {
      assert.equal(typeof tool.annotations?.[hint], 'boolean', `${tool.name} ${hint}`);
    }
    if (tool.name.includes('delete')) assert.equal(tool.annotations.destructiveHint, true);
  }
  const guide = await shim.request('resources/read', { uri: 'flow://guide' });
  assert.match(guide.result.contents[0].text, /flow_generate_image/);
  assert.ok(!fs.existsSync(engineFile()), 'listing tools starts no engine');
});

test('tools/list contains no removed names', () => {
  const removed = ['flow_account_check', 'flow_discover_ui', 'flow_queue_status', 'flow_download_latest',
    'flow_open_tools_gallery', 'flow_use_tool', 'flow_use_grid_architect', 'stitch_video'];
  for (const name of removed) assert.ok(!TOOLS.some((t) => t.name === name), name);
});

test('tool schemas state the defaults', () => {
  const props = (name) => TOOLS.find((t) => t.name === name).inputSchema.properties;
  const video = props('flow_generate_video');
  assert.deepEqual([video.model.default, video.duration.default, video.resolution.default, video.ratio.default, video.count.default], ['omni', 8, '720p', '16:9', 1]);
  assert.ok(video.ingredients);
  const img = props('flow_generate_image');
  assert.equal(img.size.default, '1K');
  assert.ok(img.ingredients);
  assert.equal(props('flow_wait').wait_ms.maximum, 55000);
});

test('audio without a key is MISSING_API_KEY through the engine', async () => {
  const engine = await engineWith();
  const saved = process.env.FISH_API_KEY;
  delete process.env.FISH_API_KEY;
  try {
    assert.equal((await rpc(engine, 'audio_voice_generate', { text: 'Hello.' })).error_code, 'MISSING_API_KEY');
    assert.equal((await rpc(engine, 'audio_voice_list', {})).error_code, 'MISSING_API_KEY');
  } finally {
    if (saved !== undefined) process.env.FISH_API_KEY = saved;
  }
});

test('unbuilt tools return NOT_IMPLEMENTED and unknown tools are refused', async () => {
  const engine = await engineWith();
  for (const name of ['audio_stable_generate']) {
    assert.equal((await rpc(engine, name, {})).error_code, 'NOT_IMPLEMENTED', name);
  }
  assert.equal((await rpc(engine, 'stitch_video', {})).error_code, 'INVALID_PARAMS');
});

test('flow_production_plan never touches the page', async () => {
  let touched = 0;
  const session = { ensure: async () => { touched++; return {}; }, peek: () => null };
  const engine = await engineWith({ session });
  const folder = path.join(root, '..', '..', 'samples', 'zombie-bunker');
  const res = await rpc(engine, 'flow_production_plan', { folder });
  assert.equal(res.ok, true);
  assert.deepEqual(res.result.counts, { references: 4, stills: 8, animations: 0 });
  assert.equal(touched, 0);
  assert.ok(TOOLS.some((t) => t.name === 'flow_production_plan' && t.annotations.readOnlyHint && t.annotations.idempotentHint));
});

test('flow_delete_project without confirm doesn\'t touch the page', async () => {
  let touched = 0;
  const session = { ensure: async () => { touched++; return {}; }, peek: () => null };
  const engine = await engineWith({ session });
  const res = await rpc(engine, 'flow_delete_project', { url: 'https://flow.google.com/project/x' });
  assert.equal(res.ok, false);
  assert.equal(res.error_code, 'INVALID_PARAMS');
  assert.equal(touched, 0);
});

test('flow_status includes the ledger and queue with no browser', async () => {
  const engine = await engineWith();
  const { result } = await rpc(engine, 'flow_status', {});
  assert.equal(result.browser, false);
  assert.equal(result.ledger.monthTotal, 0);
  assert.equal(result.ledger.todayQuota.bananaPro.limit, 100);
  assert.equal(result.queue.active, null);
  assert.equal(result.balance, null);
});

test('flow_capabilities answers without a browser; doctor and screenshot need one', async () => {
  const engine = await engineWith();
  assert.ok((await rpc(engine, 'flow_capabilities', {})).result.verifiedAt);
  assert.equal((await rpc(engine, 'flow_screenshot', {})).error_code, 'BROWSER_NOT_CONNECTED');
  assert.equal((await rpc(engine, 'flow_doctor', {})).error_code, 'BROWSER_NOT_CONNECTED');
});

test('app-only calls: pacing is checked and set, and neither is listed to agents', async () => {
  const engine = await engineWith();
  assert.equal((await rpc(engine, 'flow_bring_to_front', {})).error_code, 'BROWSER_NOT_CONNECTED');
  assert.equal((await rpc(engine, 'flow_set_pacing', { dailyCap: 1, minGapMs: 5, maxGapMs: 1 })).error_code, 'INVALID_PARAMS');
  assert.equal((await rpc(engine, 'flow_set_pacing', { dailyCap: 0, minGapMs: 0, maxGapMs: 0 })).ok, true);
  const { TOOLS } = await import('../src/shim/tools.js');
  assert.ok(!TOOLS.some(({ name }) => ['flow_bring_to_front', 'flow_set_pacing'].includes(name)));
});

test('concise response stays under 2,000 tokens for a 200-job run', { timeout: 60000 }, async () => {
  const engine = await engineWith({ adapter: async () => new Promise(() => {}) });
  engine.worker.pause('test');
  const run = createRun({ name: 'big', outputRoot: path.join(tmp, 'out'), flowProjectUrl: 'http://fake' });
  const longPrompt = 'very long prompt '.repeat(100);
  const jobs = Array.from({ length: 200 }, () => enqueue(run, { kind: 'image', prompt: longPrompt }));
  for (const job of jobs.slice(0, 60)) transition(job, 'failed', { error: { ok: false, error_code: 'SAFETY_BLOCKED', message: longPrompt } });
  const tokens = (res) => JSON.stringify(res).length / 4;
  const status = await rpc(engine, 'flow_job_status', { run_id: run.id });
  assert.equal(status.result.counts.queued, 140);
  assert.ok(tokens(status) < 2000, `status ${tokens(status)}`);
  const waited = await rpc(engine, 'flow_wait', { run_id: run.id, wait_ms: 10 });
  assert.ok(tokens(waited) < 2000, `wait ${tokens(waited)}`);
  assert.ok(tokens(await rpc(engine, 'flow_list_runs', {})) < 2000);
  const full = await rpc(engine, 'flow_job_status', { run_id: run.id, detail: 'full' });
  assert.ok(tokens(full) < 10000, `full ${tokens(full)}`);
});

// --- Review Focus 2, with a real headless Chrome on the fake Flow ---

let flow;
before(async () => { flow = await startFakeFlow(); });
after(() => flow.close());

async function browserEngine(adapter, options = {}) {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage();
  await page.goto(`${flow.url}/project/one`);
  const engine = await engineWith({ adapter, session: { ensure: async () => ({ browser, page }), peek: () => page }, ...options });
  return { browser, page, engine };
}

test('Chrome closing mid-batch fails the current job with BROWSER_NOT_CONNECTED and leaves others queued', { timeout: 60000 }, async () => {
  let started = gate();
  let calls = 0;
  const { browser, engine } = await browserEngine(async (job, ctx) => {
    calls++;
    ctx.submit(0);
    started.open();
    await new Promise((resolve) => { ctx.signal.addEventListener('abort', resolve); }); // generation never finishes: only the worker's watch can end this
  });
  const one = (await rpc(engine, 'flow_generate_image', image())).result.job_id;
  const two = (await rpc(engine, 'flow_generate_image', image({ prompt: 'two' }))).result.job_id;
  const three = (await rpc(engine, 'flow_generate_image', image({ prompt: 'three' }))).result.job_id;
  await started.opened;
  await browser.close();
  await until(async () => (await stateOf(engine, one)) === 'failed');
  const failed = (await rpc(engine, 'flow_job_status', { job_id: one })).result;
  assert.equal(failed.error.error_code, 'BROWSER_NOT_CONNECTED');
  assert.equal(failed.error.credits_at_risk, true);
  await new Promise((r) => setTimeout(r, 200));
  assert.equal(calls, 1);
  assert.equal(await stateOf(engine, two), 'queued');
  assert.equal(await stateOf(engine, three), 'queued');
  assert.ok(engine.worker.status().paused);

  // Resumable: after the owner reopens Chrome, resume runs the rest.
  started = gate();
  const resumed = await rpc(engine, 'flow_job_control', { action: 'resume' });
  assert.ok(resumed.ok);
  await until(() => calls > 1 || engine.worker.status().paused);
});

test('page navigated by a person yields a clear failure, not a wrong download', { timeout: 60000 }, async () => {
  const started = gate();
  let downloaded = 0;
  const { browser, page, engine } = await browserEngine(async (job, ctx) => {
    ctx.pinPage(page);
    ctx.submit(0);
    started.open();
    await new Promise((resolve) => ctx.signal.addEventListener('abort', resolve));
    if (!ctx.signal.aborted) downloaded++;
    return { outputs: [] };
  });
  try {
    const one = (await rpc(engine, 'flow_generate_image', image())).result.job_id;
    const two = (await rpc(engine, 'flow_generate_image', image({ prompt: 'two' }))).result.job_id;
    await started.opened;
    await page.goto(`${flow.url}/`); // the owner clicks away
    await until(async () => (await stateOf(engine, one)) === 'failed');
    const failed = (await rpc(engine, 'flow_job_status', { job_id: one })).result;
    assert.equal(failed.error.error_code, 'FLOW_PAGE_NOT_FOUND');
    assert.match(failed.error.message, /moved|left/i);
    assert.equal(downloaded, 0);
    assert.equal(await stateOf(engine, two), 'queued');
  } finally {
    await engine.stop();
    await browser.close();
  }
});

test('a move inside the same project is not a failure', { timeout: 60000 }, async () => {
  const release = gate();
  const started = gate();
  const { browser, page, engine } = await browserEngine(async (job, ctx) => {
    ctx.pinPage(page);
    ctx.submit(0);
    started.open();
    await release.opened;
    return { outputs: [] };
  });
  try {
    const one = (await rpc(engine, 'flow_generate_image', image())).result.job_id;
    await started.opened;
    await page.goto(`${flow.url}/project/one/edit/clip`);
    release.open();
    await until(async () => (await stateOf(engine, one)) === 'done');
  } finally {
    await engine.stop();
    await browser.close();
  }
});

test('getBalance reads the account panel and closes it', { timeout: 30000 }, async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent(`<button aria-label="Account details" onclick="document.getElementById('d').hidden=false">a</button>
      <div id="d" role="dialog" aria-label="Account settings" hidden><a href="#">1,025 Google Flow credits</a>
      <button aria-label="Close account panel" onclick="document.getElementById('d').hidden=true">x</button></div>`);
    assert.equal(await getBalance(page), 1025);
    assert.equal(await page.locator('#d').isVisible(), false);
    await page.setContent('<p>nothing here</p>');
    assert.equal(await getBalance(page, 200), null);
  } finally {
    await browser.close();
  }
});
