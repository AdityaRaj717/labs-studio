import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import fs from 'fs';
import os from 'os';
import path from 'path';

// No browser: real job store and run folders, with the worker's moves played by hand.
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'prod-review-'));
process.env.FLOW_DATA_DIR = path.join(tmp, 'data');
process.env.FLOW_CDP_PORT = '1';
const { default: config } = await import('../src/utils/config.js');
const { allRuns, jobByKey, jobEvents, recover, transition } = await import('../src/engine/job-store.js');
const { createOrchestrator } = await import('../src/production/orchestrator.js');
const { buildPlan } = await import('../src/production/plan.js');
const { createError, toErrorPayload } = await import('../src/utils/errors.js');
const { asAgent } = await import('../src/shim/client.js');

const mixedDir = fileURLToPath(new URL('./fixtures/productions/mixed/', import.meta.url));
const zombie = fileURLToPath(new URL('../../../samples/zombie-bunker/', import.meta.url));
const ZOMBIE = { folder: zombie, overrides: { references: [{ id: 'MD_04', kind: 'place' }] } };
let dirs = 0;
let orch;
let listener;
let pageUses;

function fresh() {
  pageUses = 0;
  if (listener) jobEvents.off('event', listener);
  orch = createOrchestrator({ jobs: { kick: () => {} }, flow: { preflight: async () => ({ balance: 500, project_url: 'https://flow/p' }), createCharacter: async () => { pageUses++; } } });
  listener = orch.onJobEvent;
  jobEvents.on('event', listener);
}

beforeEach(() => {
  config.dataDir = path.join(tmp, `d${++dirs}`);
  fs.mkdirSync(config.dataDir, { recursive: true });
  recover();
  fresh();
});

async function begin(plan = ZOMBIE, over = {}) {
  const { plan_id } = buildPlan(plan);
  return orch.start({ plan_id, cast_confirmed: true, auto_confirm: true, output_root: path.join(tmp, 'out'), ...over });
}
const item = (id, itemId) => orch.get(id).items.find((i) => i.id === itemId);
const jobOf = (id, itemId, n = 1) => jobByKey(`prod:${id}:${itemId}:take:${n}`);
const review = (id, items, action = 'approve', actor = 'app') => orch.review({ production_id: id, items: items.map(([i, take = 1]) => ({ id: i, take })), action, actor });
function finish(job, { credits = 0, audio_streams } = {}) {
  const file = path.join(tmp, `${job.id}.jpg`);
  fs.writeFileSync(file, job.id);
  const outputs = [{ file, sha256: job.id, audio_streams }];
  transition(job, 'preparing');
  transition(job, 'submitted', { quotedCredits: credits });
  transition(job, 'generating');
  transition(job, 'downloading', { media: ['m'] });
  transition(job, 'verifying', { outputs });
  transition(job, 'done', { outputs });
}
async function refsApproved() {
  const { production_id: id } = await begin();
  for (const ref of ['MD_01', 'MD_02', 'MD_03', 'MD_04']) {
    finish(jobOf(id, ref));
    review(id, [[ref]]);
  }
  return id;
}
async function animationReady(max_credits = 100) {
  const { production_id: id } = await begin({ folder: mixedDir }, { max_credits });
  for (const row of ['MD_01', 'MD_02', 'IMG_03', 'IMG_01']) {
    finish(jobOf(id, row));
    review(id, [[row]]);
  }
  return id;
}

test('approve works with no browser connected', async () => {
  const { production_id: id } = await begin();
  finish(jobOf(id, 'MD_01'));
  const before = pageUses;
  const reply = review(id, [['MD_01']]);
  assert.deepEqual(reply.items, [{ id: 'MD_01', state: 'approved', approved_take: 1 }]);
  assert.equal(pageUses, before);
});

test('an approval survives kill and restart', async () => {
  const { production_id: id } = await begin();
  finish(jobOf(id, 'MD_01'));
  review(id, [['MD_01']]);
  recover();
  fresh();
  await orch.recover();
  assert.equal(item(id, 'MD_01').state, 'approved');
  assert.equal(item(id, 'MD_01').takes[0].verdict, 'approved');
});

test('batch approve of 3 changes those 3', async () => {
  const { production_id: id } = await begin(ZOMBIE, { gates: { references: false } });
  const before = [];
  for (const ref of ['MD_01', 'MD_02', 'MD_03']) { finish(jobOf(id, ref)); before.push(ref); }
  const untouched = structuredClone(item(id, 'MD_04'));
  const reply = review(id, before.map((ref) => [ref]));
  assert.ok(reply.items.every(({ state }) => state === 'approved'));
  assert.deepEqual(item(id, 'MD_04'), untouched);
});

test('approve with one illegal item changes nothing and names it', async () => {
  const { production_id: id } = await begin();
  finish(jobOf(id, 'MD_01'));
  assert.throws(() => review(id, [['MD_01'], ['IMG_01']]), (err) => err.code === 'REVIEW_CONFLICT' && err.details.items[0].id === 'IMG_01');
  assert.equal(item(id, 'MD_01').state, 'pending_review');
});

test('approving twice is a no-op; a verdict must name its take', async () => {
  const { production_id: id } = await begin();
  finish(jobOf(id, 'MD_01'));
  review(id, [['MD_01']]);
  const snapshot = structuredClone(item(id, 'MD_01'));
  review(id, [['MD_01']]);
  assert.deepEqual(item(id, 'MD_01'), snapshot);
  assert.throws(() => orch.review({ production_id: id, items: [{ id: 'MD_01' }], action: 'approve', actor: 'app' }), { code: 'INVALID_PARAMS' });
});

test('retry with no prompt makes take 2 with the same prompt', async () => {
  const id = await refsApproved();
  finish(jobOf(id, 'IMG_01'));
  const reply = await orch.regenerate({ production_id: id, item: 'IMG_01', actor: 'app' });
  assert.equal(reply.take, 2);
  assert.equal(reply.state, 'regenerating');
  const [one, two] = item(id, 'IMG_01').takes;
  assert.equal(two.prompt, one.prompt);
  assert.equal(two.of_take, 1);
  assert.equal(jobOf(id, 'IMG_01', 2).spec.output.version, 2);
});

test('modify makes take 2 with the new prompt and leaves the source file and take 1 unchanged', async () => {
  const id = await refsApproved();
  finish(jobOf(id, 'IMG_01'));
  const source = fs.readFileSync(path.join(zombie, 'images.md'));
  const first = structuredClone(item(id, 'IMG_01').takes[0]);
  await orch.regenerate({ production_id: id, item: 'IMG_01', prompt: 'a darker mood', actor: 'app' });
  assert.deepEqual(fs.readFileSync(path.join(zombie, 'images.md')), source);
  assert.deepEqual(item(id, 'IMG_01').takes[0], first);
  assert.equal(item(id, 'IMG_01').prompt, 'a darker mood');
  assert.match(jobOf(id, 'IMG_01', 2).spec.prompt, /^a darker mood\. Style: /);
});

test('regenerating IMG_05 leaves every other item state, takes, and file sha256 identical, and its v1 file on disk', async () => {
  const id = await refsApproved();
  for (const shot of ['IMG_01', 'IMG_02', 'IMG_03', 'IMG_04', 'IMG_05']) finish(jobOf(id, shot));
  const others = structuredClone(orch.get(id).items.filter((i) => i.id !== 'IMG_05'));
  const v1 = item(id, 'IMG_05').takes[0].file;
  const bytes = fs.readFileSync(v1);
  await orch.regenerate({ production_id: id, item: 'IMG_05', actor: 'app' });
  // IMG_06 onwards may not move while one Item is active.
  assert.deepEqual(orch.get(id).items.filter((i) => i.id !== 'IMG_05'), others);
  assert.deepEqual(fs.readFileSync(v1), bytes);
});

test('regenerating an approved reference and approving the new take flags its approved stills stale and changes nothing else', async () => {
  const id = await refsApproved();
  finish(jobOf(id, 'IMG_01'));
  review(id, [['IMG_01']]);
  const still = structuredClone(item(id, 'IMG_01'));
  await orch.regenerate({ production_id: id, item: 'MD_02', actor: 'app' });
  assert.equal(item(id, 'MD_02').approved_take, 1);
  assert.deepEqual(orch.status({ production_id: id }).stale, []);
  finish(jobOf(id, 'MD_02', 2));
  const reply = review(id, [['MD_02', 2]]);
  assert.deepEqual(reply.stale, [{ item: 'IMG_01', because: ['MD_02'] }]);
  assert.deepEqual(item(id, 'IMG_01'), still);
});

test('the same regenerate repeated returns the running take; a double call makes one job', async () => {
  const id = await refsApproved();
  finish(jobOf(id, 'IMG_01'));
  const args = { production_id: id, item: 'IMG_01', expected_take: 1, actor: 'app' };
  const [one, two] = await Promise.all([orch.regenerate(args), orch.regenerate(args)]);
  assert.equal(one.take, 2);
  assert.equal(two.take, 2);
  assert.equal(two.repeated, true);
  assert.equal(two.job_id, one.job_id);
  const run = allRuns().find((r) => r.id === orch.status({ production_id: id }).run_id);
  assert.equal(run.jobs.filter((job) => job.idempotencyKey?.includes(':IMG_01:')).length, 2); // takes 1 and 2
});

test('a different prompt during regenerating is REVIEW_CONFLICT', async () => {
  const id = await refsApproved();
  finish(jobOf(id, 'IMG_01'));
  await orch.regenerate({ production_id: id, item: 'IMG_01', expected_take: 1, actor: 'app' });
  await assert.rejects(orch.regenerate({ production_id: id, item: 'IMG_01', prompt: 'other', expected_take: 1, actor: 'app' }), { code: 'REVIEW_CONFLICT' });
});

test('a stale expected_take when idle is REVIEW_CONFLICT with the current take', async () => {
  const id = await refsApproved();
  finish(jobOf(id, 'IMG_01'));
  await assert.rejects(orch.regenerate({ production_id: id, item: 'IMG_01', expected_take: 7, actor: 'app' }), (err) => err.code === 'REVIEW_CONFLICT' && err.details.current_take === 1);
});

test('a planned item can not regenerate; an unknown item is ITEM_NOT_FOUND', async () => {
  const { production_id: id } = await begin();
  await assert.rejects(orch.regenerate({ production_id: id, item: 'IMG_01', actor: 'app' }), { code: 'REVIEW_CONFLICT' });
  await assert.rejects(orch.regenerate({ production_id: id, item: 'NOPE', actor: 'app' }), { code: 'ITEM_NOT_FOUND' });
});

test('an image regeneration needs no max_credits or confirmation', async () => {
  const id = await refsApproved();
  finish(jobOf(id, 'IMG_01'));
  assert.equal((await orch.regenerate({ production_id: id, item: 'IMG_01', actor: 'app' })).state, 'regenerating');
});

test('an animation regeneration above remaining minus planned is BUDGET_EXCEEDED with the amount; set_budget raises the cap and is journaled', async () => {
  const id = await animationReady(27);
  finish(jobOf(id, 'ANI_01'), { credits: 10, audio_streams: 0 });
  await assert.rejects(orch.regenerate({ production_id: id, item: 'ANI_01', auto_confirm: true, actor: 'app' }), (err) => err.code === 'BUDGET_EXCEEDED' && err.details.credits === 10 && err.details.remaining < 10);
  const { run_id } = orch.status({ production_id: id });
  assert.equal(orch.setBudget({ run_id, max_credits: 200 }).credits.max, 200);
  const run = allRuns().find((r) => r.id === run_id);
  assert.match(fs.readFileSync(path.join(run.dir, 'events.jsonl'), 'utf8'), /"budget_set"/);
  assert.throws(() => orch.setBudget({ run_id, max_credits: -1 }), { code: 'INVALID_PARAMS' });
});

test('dry_run returns the cost with no job; no auto_confirm spends nothing', async () => {
  const id = await animationReady();
  finish(jobOf(id, 'ANI_01'), { credits: 10, audio_streams: 0 });
  const dry = await orch.regenerate({ production_id: id, item: 'ANI_01', dry_run: true, auto_confirm: true, actor: 'app' });
  assert.deepEqual([dry.take, dry.job_id, dry.estimated_credits], [2, null, 10]);
  const asked = await orch.regenerate({ production_id: id, item: 'ANI_01', actor: 'app' });
  assert.equal(asked.status, 'ready_for_confirmation');
  assert.equal(jobOf(id, 'ANI_01', 2), undefined);
  assert.equal(item(id, 'ANI_01').takes.length, 1);
});

test('retry_failed regenerates only failed items within budget', async () => {
  const id = await animationReady(27);
  const job = jobOf(id, 'ANI_01');
  transition(job, 'preparing');
  transition(job, 'submitted', { quotedCredits: 10 });
  transition(job, 'failed', { error: toErrorPayload(createError('SAFETY_BLOCKED', 'no')) });
  finish(jobOf(id, 'ANI_02'), { credits: 7, audio_streams: 0 });
  const { run_id } = orch.status({ production_id: id });
  const blocked = await orch.retryFailed(run_id);
  assert.deepEqual(blocked.changed, []);
  assert.equal(blocked.skipped[0].id, 'ANI_01');
  orch.setBudget({ run_id, max_credits: 100 });
  const retried = await orch.retryFailed(run_id);
  assert.deepEqual(retried.changed, ['ANI_01']);
  assert.equal(item(id, 'ANI_02').takes.length, 1);
});

test('a regenerated job attaches the Approved Take of its deps at that time, and its take waits for review', async () => {
  const id = await refsApproved();
  finish(jobOf(id, 'IMG_01'));
  await orch.regenerate({ production_id: id, item: 'MD_01', actor: 'app' });
  finish(jobOf(id, 'MD_01', 2));
  assert.equal(item(id, 'MD_01').state, 'pending_review');
  review(id, [['MD_01', 2]]);
  await orch.regenerate({ production_id: id, item: 'IMG_01', actor: 'app' });
  const newFile = item(id, 'MD_01').takes[1].file;
  assert.ok(jobOf(id, 'IMG_01', 2).spec.ingredients.some(({ file }) => file === newFile));
  finish(jobOf(id, 'IMG_01', 2));
  assert.equal(item(id, 'IMG_01').state, 'pending_review');
  assert.equal(item(id, 'IMG_01').approved_take, null);
});

test('agent-supplied actor is overwritten with agent; each verdict records actor and time', async () => {
  assert.equal(asAgent('flow_production_review', { actor: 'app', items: [] }).actor, 'agent');
  assert.equal(asAgent('flow_production_regenerate', {}).actor, 'agent');
  assert.equal(asAgent('flow_wait', { actor: 'x' }).actor, 'x');
  const { production_id: id } = await begin();
  finish(jobOf(id, 'MD_01'));
  review(id, [['MD_01']], 'approve', 'agent');
  const { actor, at, verdict } = item(id, 'MD_01').takes[0];
  assert.deepEqual([actor, verdict], ['agent', 'approved']);
  assert.ok(Date.parse(at));
  assert.throws(() => review(id, [['MD_01']], 'approve', 'owner'), { code: 'INVALID_PARAMS' });
});

test('the concise review reply stays under 500 tokens for 30 items', async () => {
  const references = Array.from({ length: 30 }, (_, i) => ({ id: `MD_${i}`, kind: 'place', prompt: 'p' }));
  const { plan_id } = buildPlan({ plan: { ratio: '16:9', references, shots: [{ id: 'IMG_01', kind: 'still', prompt: 'x', refs: ['MD_0'] }] } });
  const { production_id: id } = await orch.start({ plan_id, cast_confirmed: true, auto_confirm: true, output_root: path.join(tmp, 'out'), gates: { references: false } });
  for (let i = 0; i < 30; i++) finish(jobOf(id, `MD_${i}`));
  const reply = review(id, references.map(({ id: ref }) => [ref]));
  assert.ok(JSON.stringify(reply).length / 4 < 500, `${JSON.stringify(reply).length} chars`);
});
