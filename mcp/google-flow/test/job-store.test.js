import { test, before, after, mock, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'fs';
import os from 'os';
import path from 'path';

// config.js reads FLOW_DATA_DIR at load, so point it at a temp dir before importing the engine.
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'job-store-'));
process.env.FLOW_DATA_DIR = path.join(tmp, 'data');
const { createRun, writeManifest } = await import('../src/engine/run-folder.js');
const { appendEvent, readEvents } = await import('../src/engine/journal.js');
const { enqueue, transition, recover } = await import('../src/engine/job-store.js');
const { closeLog } = await import('../src/utils/logger.js');
const { FlowError } = await import('../src/utils/errors.js');

const outputRoot = path.join(tmp, 'out');
const newRun = (name = 'test run') => createRun({ name, outputRoot, flowProjectUrl: 'http://fake/project' });
const events = (run) => readEvents(path.join(run.dir, 'events.jsonl'));
const walk = (job, ...states) => states.forEach((s) => transition(job, s));
const ids = (jobs) => jobs.map((j) => j.id);

before(() => recover());
afterEach(() => mock.restoreAll());
after(async () => {
  await closeLog();
  fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
});

test('createRun makes the spec 6.3 folders', () => {
  const run = newRun('Ünï côde: run?');
  assert.match(path.basename(run.dir), /^\d{8}-\d{6}-[\p{L}\p{N}-]+$/u);
  assert.equal(path.dirname(run.dir), path.join(outputRoot, 'runs'));
  for (const d of ['images', 'videos', 'voice', 'bgm', 'sfx', 'final', 'diagnostics']) {
    assert.ok(fs.statSync(path.join(run.dir, d)).isDirectory(), d);
  }
  assert.ok(fs.existsSync(path.join(run.dir, 'manifest.json')));
  assert.ok(fs.existsSync(path.join(run.dir, 'events.jsonl')));
});

test('createRun never reuses a folder for the same name in the same second', () => {
  const dirs = new Set([newRun('dup'), newRun('dup'), newRun('dup')].map((r) => r.dir));
  assert.equal(dirs.size, 3);
});

test('appendEvent assigns increasing seq', () => {
  const run = newRun();
  const a = appendEvent(run, { type: 'x' });
  const b = appendEvent(run, { type: 'y' });
  assert.equal(b.seq, a.seq + 1);
  assert.deepEqual(events(run).map((e) => e.seq), events(run).map((_, i) => i + 1));
});

test('transition rejects done from queued', () => {
  const job = enqueue(newRun(), { prompt: 'p' });
  assert.throws(() => transition(job, 'done'), /queued.*done/);
  assert.equal(job.state, 'queued');
});

test('transition cannot move a submitted job back before the credit line', () => {
  const job = enqueue(newRun(), { prompt: 'p' });
  walk(job, 'preparing', 'submitted');
  assert.throws(() => transition(job, 'preparing'));
  assert.throws(() => transition(job, 'queued'));
});

test('a paused job returns only to the state it paused from', () => {
  const job = enqueue(newRun(), { prompt: 'p' });
  walk(job, 'preparing', 'submitted', 'generating', 'paused');
  assert.throws(() => transition(job, 'preparing'));
  transition(job, 'generating');
  assert.equal(job.state, 'generating');
});

test('terminal states stay terminal, except an explicit retry of failed', () => {
  const job = enqueue(newRun(), { prompt: 'p' });
  walk(job, 'preparing', 'submitted', 'downloading', 'verifying', 'done');
  assert.throws(() => transition(job, 'queued'));
  const never = enqueue(newRun(), { prompt: 'p' });
  transition(never, 'failed');
  assert.throws(() => transition(never, 'downloading'), /downloading/);
  transition(never, 'queued');
  assert.equal(never.state, 'queued');
});

test('submitted event is on disk before the callback returns', () => {
  const run = newRun();
  const job = enqueue(run, { prompt: 'p' });
  transition(job, 'preparing');
  const fsync = mock.method(fs, 'fsyncSync');
  transition(job, 'submitted');
  assert.ok(fsync.mock.callCount() >= 1);
  const raw = fs.readFileSync(path.join(run.dir, 'events.jsonl'), 'utf8');
  const last = JSON.parse(raw.trimEnd().split('\n').at(-1));
  assert.equal(last.to, 'submitted');
  assert.equal(last.jobId, job.id);
});

test('a failed journal write leaves the job before submitted, so Start is never clicked', () => {
  const job = enqueue(newRun(), { prompt: 'p' });
  transition(job, 'preparing');
  mock.method(fs, 'fsyncSync', () => { throw Object.assign(new Error('disk full'), { code: 'ENOSPC' }); });
  assert.throws(() => transition(job, 'submitted'), /disk full/);
  mock.restoreAll();
  assert.equal(job.state, 'preparing');
  assert.equal(job.submittedAt, undefined);
  transition(job, 'submitted');
  const seqs = events(job.run).map((e) => e.seq);
  assert.deepEqual(seqs, seqs.map((_, i) => i + 1));
});

test('recover returns a job at submitted in reconcile, not resumable', () => {
  const job = enqueue(newRun(), { prompt: 'p' });
  walk(job, 'preparing', 'submitted');
  const { resumable, reconcile } = recover();
  assert.ok(ids(reconcile).includes(job.id));
  assert.ok(!ids(resumable).includes(job.id));
});

test('recover puts running states past the credit line in reconcile and held jobs in held', () => {
  const generating = enqueue(newRun(), { prompt: 'p' });
  walk(generating, 'preparing', 'submitted', 'generating');
  const downloading = enqueue(newRun(), { prompt: 'p' });
  walk(downloading, 'preparing', 'submitted', 'downloading');
  const paused = enqueue(newRun(), { prompt: 'p' });
  walk(paused, 'preparing', 'submitted', 'paused');
  const blocked = enqueue(newRun(), { prompt: 'p' });
  walk(blocked, 'preparing', 'submitted', 'generating', 'needs_user');
  const { resumable, reconcile, held } = recover();
  for (const job of [generating, downloading]) {
    assert.ok(ids(reconcile).includes(job.id), job.state);
    assert.ok(!ids(resumable).includes(job.id), job.state);
  }
  for (const job of [paused, blocked]) {
    assert.ok(ids(held).includes(job.id), job.state);
    assert.ok(!ids(reconcile).includes(job.id), job.state);
    assert.ok(!ids(resumable).includes(job.id), job.state);
  }
});

test('a job held before the credit line stays held, not resumable', () => {
  const job = enqueue(newRun(), { prompt: 'p' });
  transition(job, 'paused');
  const { resumable, held } = recover();
  assert.ok(ids(held).includes(job.id));
  assert.ok(!ids(resumable).includes(job.id));
});

test('retrying a paid job needs the retry flag, keeps history and counts the attempt', () => {
  const job = enqueue(newRun(), { prompt: 'p' });
  walk(job, 'preparing', 'submitted');
  transition(job, 'failed', { error: { error_code: 'FLOW_GENERATION_FAILED' } });
  const firstSubmit = job.submittedAt;
  assert.throws(() => transition(job, 'queued'), /retry/);
  assert.equal(job.submittedAt, firstSubmit);
  transition(job, 'queued', undefined, { retry: true });
  assert.equal(job.attempt, 2);
  assert.equal(job.submittedAt, undefined);
  assert.equal(job.data.error, undefined);
  assert.deepEqual(job.history, [{ attempt: 1, submittedAt: firstSubmit, error: { error_code: 'FLOW_GENERATION_FAILED' } }]);
  const replayed = recover().resumable.find((j) => j.id === job.id);
  assert.equal(replayed.attempt, 2);
  assert.equal(replayed.history[0].submittedAt, firstSubmit);
});

test('enqueue before recover shares one Run object per folder, so seq never repeats', async () => {
  const fresh = await import('../src/engine/job-store.js?fresh');
  const run = newRun();
  const job = fresh.enqueue(run, { prompt: 'p' });
  const found = fresh.recover().resumable.find((j) => j.id === job.id);
  assert.equal(found.run, run);
  fresh.transition(job, 'preparing');
  fresh.transition(found, 'preparing');
  const seqs = events(run).map((e) => e.seq);
  assert.deepEqual(seqs, seqs.map((_, i) => i + 1));
  transition(fresh.recover().resumable.find((j) => j.id === job.id), 'cancelled');
  recover();
});

test('recover resumes a job at preparing', () => {
  const job = enqueue(newRun(), { prompt: 'p' });
  transition(job, 'preparing');
  const { resumable, reconcile } = recover();
  const found = resumable.find((j) => j.id === job.id);
  assert.equal(found.state, 'preparing');
  assert.deepEqual(found.spec, { prompt: 'p' });
  assert.ok(!ids(reconcile).includes(job.id));
  transition(found, 'submitted');
  assert.equal(events(found.run).at(-1).to, 'submitted');
});

test('recover leaves out finished jobs', () => {
  const failed = enqueue(newRun(), { prompt: 'p' });
  transition(failed, 'failed', { credits_at_risk: true });
  const cancelled = enqueue(newRun(), { prompt: 'p' });
  transition(cancelled, 'cancelled');
  const { resumable, reconcile } = recover();
  for (const list of [resumable, reconcile]) {
    assert.ok(!ids(list).includes(failed.id));
    assert.ok(!ids(list).includes(cancelled.id));
  }
});

test('a torn last journal line is dropped and later appends stay readable', () => {
  const run = newRun();
  const job = enqueue(run, { prompt: 'p' });
  transition(job, 'preparing');
  fs.appendFileSync(path.join(run.dir, 'events.jsonl'), '{"seq":99,"type":"job.transition","to":"subm');
  const found = recover().resumable.find((j) => j.id === job.id);
  assert.equal(found.state, 'preparing');
  transition(found, 'submitted');
  const after = recover();
  assert.ok(ids(after.reconcile).includes(job.id));
  const seqs = events(run).map((e) => e.seq);
  assert.deepEqual(seqs, seqs.map((_, i) => i + 1));
});

test('corruption before the last line stops recovery instead of guessing a state', () => {
  const run = newRun();
  enqueue(run, { prompt: 'p' });
  const file = path.join(run.dir, 'events.jsonl');
  const good = fs.readFileSync(file);
  fs.writeFileSync(file, `not json\n${good}`);
  assert.throws(() => recover(), (err) => err instanceof FlowError && err.code === 'JOURNAL_CORRUPT' && err.message.includes(file));
  fs.writeFileSync(file, good);
});

test('a transition with no enqueue is the same coded corruption error', () => {
  const run = newRun();
  const file = path.join(run.dir, 'events.jsonl');
  const good = fs.readFileSync(file);
  appendEvent(run, { type: 'job.transition', jobId: 'ghost', to: 'preparing' });
  assert.throws(() => recover(), (err) => err.code === 'JOURNAL_CORRUPT' && err.message.includes(file));
  fs.writeFileSync(file, good);
});

test('manifest survives a torn temp file', () => {
  const run = newRun();
  enqueue(run, { prompt: 'p' });
  const file = path.join(run.dir, 'manifest.json');
  const good = fs.readFileSync(file, 'utf8');
  fs.writeFileSync(`${file}.tmp`, '{"torn":');
  recover();
  assert.equal(fs.readFileSync(file, 'utf8'), good);
  writeManifest(run);
  assert.equal(JSON.parse(fs.readFileSync(file, 'utf8')).jobs.length, 1);
  assert.ok(!fs.existsSync(`${file}.tmp`));
});

test('a failed manifest rename keeps the old manifest and does not fail the transition', () => {
  const run = newRun();
  const job = enqueue(run, { prompt: 'p' });
  const file = path.join(run.dir, 'manifest.json');
  const good = fs.readFileSync(file, 'utf8');
  mock.method(fs, 'renameSync', () => { throw Object.assign(new Error('nope'), { code: 'ENOSPC' }); });
  assert.throws(() => writeManifest(run), /nope/);
  transition(job, 'preparing');
  assert.equal(job.state, 'preparing');
  assert.equal(fs.readFileSync(file, 'utf8'), good);
});

test('writeManifest retries a rename blocked by another process', () => {
  const run = newRun();
  const real = fs.renameSync;
  let calls = 0;
  mock.method(fs, 'renameSync', (a, b) => {
    if (++calls < 3) throw Object.assign(new Error('locked'), { code: 'EPERM' });
    real(a, b);
  });
  writeManifest(run);
  assert.equal(calls, 3);
});

test('manifest records job state and transition data', () => {
  const run = newRun();
  const job = enqueue(run, { prompt: 'p' });
  transition(job, 'preparing', { quotedCredits: 20 });
  const saved = JSON.parse(fs.readFileSync(path.join(run.dir, 'manifest.json'), 'utf8'));
  assert.equal(saved.flowProjectUrl, 'http://fake/project');
  assert.equal(saved.jobs[0].state, 'preparing');
  assert.equal(saved.jobs[0].data.quotedCredits, 20);
});

test('same idempotency key returns the same job', () => {
  const key = `k-${Date.now()}`;
  const run = newRun();
  const first = enqueue(run, { prompt: 'p' }, key);
  assert.equal(enqueue(run, { prompt: 'other' }, key), first);
  assert.equal(run.jobs.length, 1);
  assert.equal(enqueue(newRun(), { prompt: 'p' }, key).id, first.id);
  recover();
  assert.equal(enqueue(run, { prompt: 'p' }, key).id, first.id);
});
