import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import fs from 'fs';
import os from 'os';
import path from 'path';

// No browser: real job store and run folders, with the worker's moves played by hand.
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'prod-run-'));
process.env.FLOW_DATA_DIR = path.join(tmp, 'data');
process.env.FLOW_CDP_PORT = '1';
const { default: config } = await import('../src/utils/config.js');
const { allRuns, jobByKey, jobEvents, recover, transition } = await import('../src/engine/job-store.js');
const { createOrchestrator } = await import('../src/production/orchestrator.js');
const { buildPlan } = await import('../src/production/plan.js');
const { createError } = await import('../src/utils/errors.js');
const { toErrorPayload } = await import('../src/utils/errors.js');

const zombie = fileURLToPath(new URL('../../../samples/zombie-bunker/', import.meta.url));
const mixedDir = fileURLToPath(new URL('./fixtures/productions/mixed/', import.meta.url));
const ZOMBIE = { folder: zombie, overrides: { references: [{ id: 'MD_04', kind: 'place' }] } };
let dirs = 0;
let orch;
let flow;
let listener;

function fresh(over = {}) {
  flow = { preflights: 0, characters: [], preflight: async ({ project_url }) => { flow.preflights++; return { balance: 500, project_url: project_url ?? 'https://flow/project/new' }; }, createCharacter: async (args) => { flow.characters.push(args); }, ...over };
  if (listener) jobEvents.off('event', listener);
  orch = createOrchestrator({ jobs: { kick: () => {} }, flow });
  listener = orch.onJobEvent;
  jobEvents.on('event', listener);
  return orch;
}

beforeEach(() => {
  config.dataDir = path.join(tmp, `d${++dirs}`);
  fs.mkdirSync(config.dataDir, { recursive: true });
  recover();
  fresh();
});

const startArgs = (plan_id, over = {}) => ({ plan_id, cast_confirmed: true, auto_confirm: true, output_root: path.join(tmp, 'out'), ...over });
async function begin(plan = ZOMBIE, over) {
  const report = buildPlan(plan);
  assert.equal(report.ok, true, JSON.stringify(report.errors));
  return orch.start(startArgs(report.plan_id, over));
}
const production = (id) => orch.get(id);
const item = (id, itemId) => production(id).items.find((i) => i.id === itemId);
const keyOf = (id, itemId, n = 1) => `prod:${id}:${itemId}:take:${n}`;
const jobOf = (id, itemId, n) => jobByKey(keyOf(id, itemId, n));

// The worker's path for a job that ends well.
function finishJob(job, { credits = 0, audio_streams, file = makeFile(job) } = {}) {
  transition(job, 'preparing');
  transition(job, 'submitted', { quotedCredits: credits });
  transition(job, 'generating');
  transition(job, 'downloading', { media: ['m'] });
  transition(job, 'verifying', { outputs: [{ file, sha256: 'h', audio_streams }] });
  transition(job, 'done', { outputs: [{ file, sha256: 'h', audio_streams }] });
}
const approve = (id, itemId, take = 1) => orch.record(id, { type: 'reviewed', items: [{ id: itemId, take }], verdict: 'approved', actor: 'app', at: 't' });
function makeFile(job) {
  const file = path.join(tmp, `${job.spec.output.name}-${job.id}.jpg`);
  fs.writeFileSync(file, 'x');
  return file;
}
async function finishApprove(id, itemId, opts = {}) {
  const job = jobOf(id, itemId);
  finishJob(job, { file: makeFile(job), ...opts });
  await approve(id, itemId);
}

const fail = (job, code, details = {}, after) => {
  transition(job, 'preparing');
  if (after) transition(job, 'submitted', { quotedCredits: after });
  return toErrorPayload(createError(code, 'stopped', details));
};
const hold = (job, code, details, after) => transition(job, 'paused', { error: fail(job, code, details, after) });

test('stills-only production generates references then stills, with no ffmpeg need and no video job', async () => {
  let needsVideo;
  fresh({ preflight: async (args) => { needsVideo = args.needsVideo; return { balance: 500, project_url: 'https://flow/p' }; } });
  const { production_id: id, status } = await begin();
  assert.equal(status, 'running');
  assert.equal(needsVideo, false);
  for (const ref of ['MD_01', 'MD_02', 'MD_03', 'MD_04']) await finishApprove(id, ref);
  assert.ok(jobOf(id, 'IMG_01'));
  const run = allRuns().find((r) => r.id === orch.status({ production_id: id }).run_id);
  assert.ok(run.jobs.every((job) => job.spec.kind === 'image'));
  assert.equal(run.jobs[0].spec.project_url, 'https://flow/p');
  assert.ok(fs.existsSync(path.join(run.dir, 'inputs', 'images.md')));
  assert.equal(jobOf(id, 'IMG_01').spec.ingredients.length, 2);
});

test('start with gates on stops at review after references; approving continues to stills', async () => {
  const { production_id: id } = await begin();
  for (const ref of ['MD_01', 'MD_02', 'MD_03', 'MD_04']) finishJob(jobOf(id, ref));
  await new Promise(setImmediate);
  assert.equal(orch.status({ production_id: id }).status, 'waiting_review');
  assert.equal(jobOf(id, 'IMG_01'), undefined);
  for (const ref of ['MD_01', 'MD_02', 'MD_03']) await approve(id, ref);
  assert.equal(item(id, 'IMG_01').state, 'generating');
});

async function mixed(over = { max_credits: 100 }) {
  return (await begin({ folder: mixedDir }, over)).production_id;
}
const makeStillsReady = async (id) => {
  await finishApprove(id, 'MD_01');
  await finishApprove(id, 'MD_02');
  await finishApprove(id, 'IMG_03'); // needs only MD_01, so it goes first
  await finishApprove(id, 'IMG_01');
};

test('mixed production: an animation starts only after its still is approved, and its start chip holds that file', async () => {
  const id = await mixed();
  await finishApprove(id, 'MD_01');
  await finishApprove(id, 'MD_02');
  await finishApprove(id, 'IMG_03');
  finishJob(jobOf(id, 'IMG_01'));
  // ANI_01 has no start and may run; ANI_02 waits for IMG_01.
  assert.equal(item(id, 'ANI_01').state, 'generating');
  finishJob(jobOf(id, 'ANI_01'), { credits: 10, audio_streams: 0 });
  finishJob(jobOf(id, 'ANI_03'), { credits: 10, audio_streams: 0 });
  assert.equal(item(id, 'ANI_02').state, 'planned');
  await approve(id, 'IMG_01');
  const job = jobOf(id, 'ANI_02');
  assert.equal(job.spec.start_frame, item(id, 'IMG_01').takes[0].file);
  assert.equal(job.spec.silent, true);
  assert.equal(job.spec.mode, 'frames');
});

test('refusals touch no page', async () => {
  const report = buildPlan({ folder: mixedDir });
  const code = async (args, expected) => {
    await assert.rejects(orch.start(args), (err) => err.code === expected, expected);
    assert.equal(flow.preflights, 0);
  };
  await code(startArgs(report.plan_id, { cast_confirmed: false, max_credits: 100 }), 'INVALID_PARAMS');
  await code(startArgs(report.plan_id, { auto_confirm: false, max_credits: 100 }), 'INVALID_PARAMS');
  await assert.rejects(orch.start(startArgs(report.plan_id)), (err) => err.code === 'INVALID_PARAMS' && /estimate is 27 credits/.test(err.message));
  await code(startArgs(report.plan_id, { max_credits: 5 }), 'BUDGET_EXCEEDED');
  await code(startArgs(buildPlan({ folder: zombie }).plan_id), 'ANALYSIS_REQUIRED');
});

test('an edited file at start is PLAN_CHANGED, no spend', async () => {
  const dir = fs.mkdtempSync(path.join(tmp, 'edit-'));
  for (const f of ['moodboard.md', 'animations.md']) fs.copyFileSync(path.join(mixedDir, f), path.join(dir, f));
  const report = buildPlan({ folder: dir });
  fs.appendFileSync(path.join(dir, 'moodboard.md'), '\n');
  await assert.rejects(orch.start(startArgs(report.plan_id, { max_credits: 100 })), { code: 'PLAN_CHANGED' });
  assert.equal(flow.preflights, 0);
});

test('preflight failures stop before any job, and the estimate must fit the live balance', async () => {
  fresh({ preflight: async () => { throw createError('UNKNOWN_UI_CHANGE', 'doctor'); } });
  await assert.rejects(mixed(), { code: 'UNKNOWN_UI_CHANGE' });
  fresh({ preflight: async () => { throw createError('FFMPEG_NOT_FOUND', 'no'); } });
  await assert.rejects(mixed(), { code: 'FFMPEG_NOT_FOUND' });
  fresh({ preflight: async () => ({ balance: 1, project_url: 'u' }) });
  await assert.rejects(mixed(), { code: 'BUDGET_EXCEEDED' });
  assert.equal(allRuns().flatMap((r) => r.jobs).length, 0);
});

test('start repeated with the same plan_id returns the same production; new_run starts a second', async () => {
  const one = await begin();
  const two = await begin();
  assert.equal(two.production_id, one.production_id);
  assert.equal(two.repeated, true);
  const three = await begin(ZOMBIE, { new_run: true });
  assert.notEqual(three.production_id, one.production_id);
  assert.equal(flow.preflights, 2);
});

test('two starts at once make one production', async () => {
  const report = buildPlan(ZOMBIE);
  const [a, b] = await Promise.all([orch.start(startArgs(report.plan_id)), orch.start(startArgs(report.plan_id))]);
  assert.equal(a.production_id, b.production_id);
  assert.equal(flow.preflights, 1);
});

test('reuse copies the approved file, records sha256 and generates nothing', async () => {
  const { production_id: source } = await begin();
  await finishApprove(source, 'MD_01');
  const plan = { ...ZOMBIE, overrides: { references: [{ id: 'MD_04', kind: 'place' }, { id: 'MD_01', reuse: { production_id: source, item: 'MD_01' } }] } };
  const { production_id: id } = await begin(plan);
  const copy = item(id, 'MD_01');
  assert.equal(copy.state, 'approved');
  assert.notEqual(copy.takes[0].file, item(source, 'MD_01').takes[0].file);
  assert.ok(fs.existsSync(copy.takes[0].file));
  assert.match(copy.takes[0].sha256, /^[0-9a-f]{64}$/);
  assert.equal(jobOf(id, 'MD_01'), undefined);
  assert.equal(item(id, 'MD_02').state, 'generating');
});

test('reuse refusals', async () => {
  const { production_id: source } = await begin();
  const reuse = (r) => ({ ...ZOMBIE, overrides: { references: [{ id: 'MD_04', kind: 'place' }, { id: 'MD_01', reuse: r }] } });
  await assert.rejects(begin(reuse({ production_id: 'nope', item: 'MD_01' })), { code: 'PRODUCTION_NOT_FOUND' });
  await assert.rejects(begin(reuse({ production_id: source, item: 'NOPE' })), { code: 'ITEM_NOT_FOUND' });
  await assert.rejects(begin(reuse({ production_id: source, item: 'MD_02' })), { code: 'REVIEW_CONFLICT' });
});

test('character mode creates the Flow Character once, before the first dependent, and approval alone never touches the page', async () => {
  const { production_id: id } = await begin(ZOMBIE, { reference_mode: 'character' });
  for (const ref of ['MD_01', 'MD_02', 'MD_03']) {
    const job = jobOf(id, ref);
    finishJob(job, { file: makeFile(job) });
  }
  const job = jobOf(id, 'MD_04');
  finishJob(job, { file: makeFile(job) });
  await new Promise(setImmediate);
  await approve(id, 'MD_01');
  assert.equal(flow.characters.length, 0);
  await approve(id, 'MD_02');
  assert.equal(flow.characters.length, 2);
  assert.deepEqual(flow.characters.map((c) => c.kind), ['place', 'person']);
  assert.deepEqual(jobOf(id, 'IMG_01').spec.ingredients, flow.characters.map((c) => ({ character: c.name })));
  assert.equal(flow.characters.length, 2);
});

test('quota text pauses the production, aborts the unsubmitted take, and planned items stay planned; resume is a new take', async () => {
  const { production_id: id, run_id } = await begin();
  await finishApprove(id, 'MD_01');
  const held = jobOf(id, 'MD_02');
  hold(held, 'GOOGLE_LIMIT_REACHED');
  assert.equal(orch.status({ production_id: id }).status, 'paused');
  assert.equal(production(id).paused.code, 'GOOGLE_LIMIT_REACHED');
  assert.equal(item(id, 'MD_02').state, 'planned');
  assert.equal(item(id, 'MD_02').takes[0].status, 'aborted');
  assert.equal(held.state, 'cancelled');
  assert.equal(item(id, 'MD_03').state, 'planned');
  orch.resume(run_id);
  await new Promise(setImmediate);
  assert.equal(item(id, 'MD_02').takes[1].n, 2);
  assert.notEqual(jobOf(id, 'MD_02', 2).id, held.id);
});

test('CAPTCHA pauses with needs_user and nothing moves', async () => {
  const { production_id: id } = await begin();
  const job = jobOf(id, 'MD_01');
  transition(job, 'needs_user', { error: fail(job, 'MANUAL_VERIFICATION_REQUIRED') });
  assert.equal(production(id).paused.code, 'MANUAL_VERIFICATION_REQUIRED');
  assert.equal(orch.status({ production_id: id }).status, 'paused');
});

test('a job-only failure fails one item and others go on; a failed reference leaves dependents waiting', async () => {
  const { production_id: id } = await begin();
  const job = jobOf(id, 'MD_01');
  transition(job, 'failed', { error: fail(job, 'SAFETY_BLOCKED', {}, 1) });
  await new Promise(setImmediate);
  assert.equal(item(id, 'MD_01').state, 'failed');
  assert.equal(item(id, 'MD_02').state, 'generating');
  for (const ref of ['MD_02', 'MD_03', 'MD_04']) await finishApprove(id, ref);
  assert.equal(item(id, 'IMG_01').state, 'planned'); // needs MD_01
  assert.equal(item(id, 'IMG_03').state, 'generating');
  assert.ok(orch.status({ production_id: id }).waiting_on.includes('MD_01'));
});

test('RESULT_MISMATCH never reaches pending_review and keeps the file', async () => {
  const { production_id: id } = await begin();
  const job = jobOf(id, 'MD_01');
  transition(job, 'preparing');
  transition(job, 'submitted', { quotedCredits: 0 });
  transition(job, 'downloading', { media: ['m'] });
  transition(job, 'verifying', { outputs: [{ file: 'kept.jpg' }] });
  transition(job, 'failed', { error: toErrorPayload(createError('RESULT_MISMATCH', 'wrong ratio')) });
  assert.equal(item(id, 'MD_01').state, 'failed');
  assert.equal(item(id, 'MD_01').takes[0].file, 'kept.jpg');
});

test('an animation with audio in its deliverable never reaches review', async () => {
  const id = await mixed();
  await makeStillsReady(id);
  const job = jobOf(id, 'ANI_01');
  finishJob(job, { credits: 10, audio_streams: 1 });
  assert.equal(item(id, 'ANI_01').state, 'failed');
  assert.equal(item(id, 'ANI_01').last_error.code, 'RESULT_MISMATCH');
});

test('a retrying image attempt stays inside its take; an animation has no automatic retry', async () => {
  const { production_id: id } = await begin();
  const job = jobOf(id, 'MD_01');
  const payload = fail(job, 'FLOW_GENERATION_FAILED', {}, 1);
  Object.defineProperty(job, 'retrying', { value: true, configurable: true });
  transition(job, 'failed', { error: payload });
  assert.equal(item(id, 'MD_01').state, 'generating');
  Object.defineProperty(job, 'retrying', { value: false, configurable: true });
  const other = await mixed();
  await makeStillsReady(other);
  assert.equal(jobOf(other, 'ANI_01').spec.max_generation_retries, undefined);
  assert.equal(jobOf(other, 'ANI_01').spec.kind, 'video'); // the worker allows video no automatic retries
});

test('a quote above the item estimate stops with quote_drift; accept_quote then proceeds at the new estimate', async () => {
  const id = await mixed();
  await makeStillsReady(id);
  const { run_id } = orch.status({ production_id: id });
  const job = jobOf(id, 'ANI_01');
  assert.equal(job.spec.max_credits, 10);
  hold(job, 'BUDGET_EXCEEDED', { quotedCredits: 14, maxCredits: 10 });
  assert.equal(production(id).paused.reason, 'quote_drift');
  assert.equal(job.submittedAt, undefined);
  assert.throws(() => orch.resume(run_id), { code: 'BUDGET_EXCEEDED' });
  orch.resume(run_id, { accept_quote: true });
  await new Promise(setImmediate);
  assert.equal(item(id, 'ANI_01').estimate, 14);
  assert.equal(jobOf(id, 'ANI_01', 2).spec.max_credits, 14);
});

test('spent plus quote above max_credits stops as budget', async () => {
  const id = await mixed({ max_credits: 27 });
  await makeStillsReady(id);
  finishJob(jobOf(id, 'ANI_01'), { credits: 25, audio_streams: 0 });
  await approve(id, 'ANI_01');
  const job = jobOf(id, 'ANI_02');
  assert.equal(job.spec.max_credits, 2);
  hold(job, 'BUDGET_EXCEEDED', { quotedCredits: 7, maxCredits: 2 });
  assert.equal(production(id).paused.reason, 'budget');
  assert.throws(() => orch.resume(orch.status({ production_id: id }).run_id), { code: 'BUDGET_EXCEEDED' });
});

test('a failed download pauses and resume downloads again with no new take', async () => {
  const { production_id: id, run_id } = await begin();
  const job = jobOf(id, 'MD_01');
  transition(job, 'preparing');
  transition(job, 'submitted', { quotedCredits: 0 });
  transition(job, 'downloading', { media: ['m'] });
  transition(job, 'failed', { error: toErrorPayload(createError('DOWNLOAD_FAILED', 'no', { saved: [] })) });
  assert.equal(item(id, 'MD_01').state, 'generating');
  assert.equal(production(id).paused.reason, 'download');
  orch.resume(run_id);
  assert.equal(job.state, 'downloading');
  assert.equal(item(id, 'MD_01').takes.length, 1);
});

// Crash matrix: a new orchestrator over what the disk holds.
async function restart() {
  const { reconcile } = recover();
  fresh();
  await orch.recover();
  return reconcile;
}

test('crash before the Take is recorded: the item is planned and runs normally', async () => {
  const { production_id: id, run_id } = await begin();
  orch.hold(run_id);
  await finishApprove(id, 'MD_01');
  await restart();
  assert.equal(item(id, 'MD_01').approved_take, 1);
  assert.equal(item(id, 'MD_02').state, 'planned');
});

test('crash with the Take recorded and no job: the same key queues it once', async () => {
  const { production_id: id } = await begin();
  const run = allRuns().find((r) => r.id === orch.status({ production_id: id }).run_id);
  // Rewind to the moment before the job was queued.
  const file = path.join(run.dir, 'events.jsonl');
  const lines = fs.readFileSync(file, 'utf8').trim().split('\n');
  const keep = lines.filter((line) => !['job.enqueued', 'production.event'].includes(JSON.parse(line).type) || JSON.parse(line).event?.type === 'take_started');
  fs.writeFileSync(file, `${keep.join('\n')}\n`);
  const saved = JSON.parse(fs.readFileSync(path.join(run.dir, 'production.json'), 'utf8'));
  saved.items[0].state = 'planned';
  saved.items[0].takes = [];
  saved.last_seq = 1;
  fs.writeFileSync(path.join(run.dir, 'production.json'), JSON.stringify(saved));
  await restart();
  assert.equal(item(id, 'MD_01').takes.length, 1);
  assert.equal(item(id, 'MD_01').takes[0].job_id, jobOf(id, 'MD_01').id);
  assert.equal(allRuns().find((r) => r.id === run.id).jobs.length, 1);
});

test('crash with a job before submitted: the job is resumed, no new take', async () => {
  const { production_id: id } = await begin();
  transition(jobOf(id, 'MD_01'), 'preparing');
  const { resumable } = (recover(), { resumable: [] });
  assert.deepEqual(resumable, []);
  await restart();
  assert.equal(item(id, 'MD_01').takes.length, 1);
  assert.equal(item(id, 'MD_01').state, 'generating');
});

test('crash past submitted: it goes to reconcile, never a second Start', async () => {
  const { production_id: id } = await begin();
  const job = jobOf(id, 'MD_01');
  transition(job, 'preparing');
  transition(job, 'submitted', { quotedCredits: 3 });
  const lost = await restart();
  assert.deepEqual(lost.map((j) => j.id), [job.id]);
  assert.equal(item(id, 'MD_01').takes.length, 1);
  assert.equal(production(id).budget.spent, 3);
  // Reconcile finds nothing: the Take fails with credits at risk.
  const again = jobOf(id, 'MD_01');
  transition(again, 'failed', { error: toErrorPayload(createError('FLOW_GENERATION_FAILED', 'lost', { credits_at_risk: true })) });
  assert.equal(item(id, 'MD_01').takes[0].credits_at_risk, true);
  assert.equal(item(id, 'MD_01').state, 'failed');
});

test('crash with the job finished and the Production not updated: recovery applies it', async () => {
  const { production_id: id, run_id } = await begin();
  jobEvents.off('event', listener); // the crash: nothing heard the job end
  finishJob(jobOf(id, 'MD_01'), { credits: 0, file: 'made.jpg' });
  await restart();
  assert.equal(item(id, 'MD_01').state, 'pending_review');
  assert.equal(item(id, 'MD_01').takes[0].file, 'made.jpg');
  assert.ok(run_id);
});

test('events past last_seq replay on load', async () => {
  const { production_id: id } = await begin();
  const run = allRuns().find((r) => r.id === orch.status({ production_id: id }).run_id);
  const before = fs.readFileSync(path.join(run.dir, 'production.json'));
  finishJob(jobOf(id, 'MD_01'));
  // The crash: journaled, but production.json was never rewritten.
  fs.writeFileSync(path.join(run.dir, 'production.json'), before);
  await restart();
  assert.equal(item(id, 'MD_01').state, 'pending_review');
});

test('status for 300 items stays under 2,000 tokens; item listing pages with cursor', async () => {
  const references = [{ id: 'R0', kind: 'character', name: 'Zed', prompt: 'p' }];
  const shots = Array.from({ length: 299 }, (_, i) => ({ id: `IMG_${i}`, kind: 'still', prompt: `shot ${i}`, refs: ['R0'] }));
  const { production_id: id } = await begin({ plan: { ratio: '16:9', references, shots } });
  const concise = orch.status({ production_id: id });
  assert.ok(JSON.stringify(concise).length / 4 < 2000);
  assert.equal(concise.items, undefined);
  const first = orch.status({ production_id: id, stage: 'still', limit: 100 });
  assert.equal(first.items.length, 50);
  assert.equal(first.next_cursor, 50);
  const second = orch.status({ production_id: id, stage: 'still', cursor: first.next_cursor });
  assert.equal(second.items[0].id, 'IMG_50');
});

test('detail full carries every production.item field, and events arrive in order with progress only from Flow', async () => {
  const seen = [];
  const watch = (event) => { if (event.type?.startsWith('production.')) seen.push(event); };
  jobEvents.on('event', watch);
  const { production_id: id, run_id } = await begin();
  const job = jobOf(id, 'MD_01');
  jobEvents.emit('event', { type: 'job.progress', runId: run_id, jobId: job.id, progress: 42, source: 'flow', tiles: 4 });
  finishJob(job);
  jobEvents.off('event', watch);
  const events = seen.filter((e) => e.type === 'production.item' && e.item === 'MD_01');
  assert.deepEqual(events.map((e) => e.state).at(-1), 'pending_review');
  const progress = events.find((e) => e.progress === 42);
  assert.equal(progress.source, 'flow');
  assert.equal(progress.tiles, 4);
  assert.equal(typeof progress.job_state, 'string');
  assert.ok('submitted_at' in progress && 'attempt' in progress);
  assert.ok(events.filter((e) => e.progress === null).every((e) => e.source === 'phase'));
  assert.ok(seen.some((e) => e.type === 'production.summary'));
  const full = orch.status({ production_id: id, detail: 'full', stage: 'reference' }).items[0];
  for (const key of Object.keys(events.at(-1)).filter((k) => !['type', 'runId'].includes(k))) assert.ok(key in full, key);
  assert.ok(full.takes);
});

test('the latest production is the default and an unknown one is PRODUCTION_NOT_FOUND', async () => {
  assert.throws(() => orch.status({}), { code: 'PRODUCTION_NOT_FOUND' });
  const { production_id: id } = await begin();
  assert.equal(orch.status({}).production_id, id);
  assert.throws(() => orch.status({ production_id: 'x' }), { code: 'PRODUCTION_NOT_FOUND' });
});
