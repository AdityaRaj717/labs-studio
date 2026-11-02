import { test } from 'node:test';
import assert from 'node:assert/strict';
import { applyEvent, depsFor, newProduction, nextItem, staleItems, summary, waitingOn } from '../src/production/state.js';

const plan = (over = {}) => ({
  plan_id: 'p',
  name: 'n',
  mode: 'mixed',
  style: null,
  ratio: '16:9',
  references: [{ id: 'R1', kind: 'character', name: 'A', prompt: 'a', refs: [], estimate: 0 }, { id: 'R2', kind: 'place', name: 'B', prompt: 'b', estimate: 0 }],
  shots: [
    { id: 'S1', kind: 'still', prompt: 's1', refs: ['R1'], start: null, end: null, estimate: 0 },
    { id: 'S2', kind: 'still', prompt: 's2', refs: ['R2'], start: null, end: null, estimate: 0 },
    { id: 'A1', kind: 'animation', prompt: 'a1', refs: [], start: 'S1', end: null, estimate: 10 },
    { id: 'A2', kind: 'animation', prompt: 'a2', refs: ['R1'], start: null, end: null, estimate: 10 },
  ],
  ...over,
});
const make = (opts = {}) => newProduction(plan(), { id: 'x', runId: 'r', maxCredits: 100, ...opts });
const run = (p, ...events) => events.reduce(applyEvent, p);
const item = (p, id) => p.items.find((i) => i.id === id);
const started = (id, n = 1, over = {}) => ({ type: 'take_started', item: id, n, key: `k${n}`, ...over });
const done = (id, n = 1) => ({ type: 'take_done', item: id, n, file: `${id}_v${n}.jpg`, sha256: 'h' });
const failed = (id, n = 1) => ({ type: 'take_failed', item: id, n, code: 'SAFETY_BLOCKED', message: 'no' });
const verdict = (v, id, take = 1) => ({ type: 'reviewed', items: [{ id, take }], verdict: v, actor: 'agent', at: 't' });
const approve = (id, take) => verdict('approved', id, take);
const reject = (id, take) => verdict('rejected', id, take);
const finished = (id, n = 1) => [started(id, n), done(id, n)];
const approved = (p, id, n = 1, deps = {}) => run(p, started(id, n, deps), done(id, n), approve(id, n));
const refsDone = (opts) => approved(approved(make(opts), 'R1'), 'R2');
const conflict = { code: 'REVIEW_CONFLICT' };

test('planned to generating when a take starts', () => {
  assert.equal(item(run(make(), started('R1')), 'R1').state, 'generating');
});
test('generating to pending_review when a take is done', () => {
  assert.equal(item(run(make(), ...finished('R1')), 'R1').state, 'pending_review');
});
test('regenerating to pending_review when a take is done', () => {
  const p = run(make(), ...finished('R1'), approve('R1'), started('R1', 2), done('R1', 2));
  assert.equal(item(p, 'R1').state, 'pending_review');
  assert.equal(item(p, 'R1').approved_take, 1);
});
test('generating to failed when a take fails', () => {
  const p = run(make(), started('R1'), failed('R1'));
  assert.equal(item(p, 'R1').state, 'failed');
  assert.equal(item(p, 'R1').last_error.code, 'SAFETY_BLOCKED');
});
test('a failed regeneration with no approved take is failed', () => {
  const p = run(make(), ...finished('R1'), started('R1', 2), failed('R1', 2));
  assert.equal(item(p, 'R1').state, 'failed');
});
test('pending_review, approved, rejected and failed can be approved', () => {
  assert.equal(item(run(make(), ...finished('R1'), approve('R1')), 'R1').state, 'approved');
  assert.equal(item(run(make(), ...finished('R1'), reject('R1'), approve('R1')), 'R1').state, 'approved');
  const older = run(make(), ...finished('R1'), started('R1', 2), failed('R1', 2), approve('R1'));
  assert.equal(item(older, 'R1').state, 'approved');
});
test('pending_review to rejected', () => {
  const p = run(make(), ...finished('R1'), reject('R1'));
  assert.equal(item(p, 'R1').state, 'rejected');
  assert.equal(item(p, 'R1').takes[0].verdict, 'rejected');
});
test('every finished state can regenerate', () => {
  const forStates = [
    run(make(), ...finished('R1')),
    run(make(), ...finished('R1'), approve('R1')),
    run(make(), ...finished('R1'), reject('R1')),
    run(make(), started('R1'), failed('R1')),
  ];
  for (const p of forStates) assert.equal(item(run(p, started('R1', 2)), 'R1').state, 'regenerating');
});

test('approve from planned throws REVIEW_CONFLICT', () => {
  assert.throws(() => run(make(), approve('R1')), conflict);
});
test('a take can not start on an active item', () => {
  assert.throws(() => run(make(), started('R1'), started('R1', 2)), conflict);
});
test('an unknown item is ITEM_NOT_FOUND', () => {
  assert.throws(() => run(make(), approve('NO')), { code: 'ITEM_NOT_FOUND' });
});
test('a failed take can not be approved', () => {
  assert.throws(() => run(make(), started('R1'), failed('R1'), approve('R1')), conflict);
});

test('regenerating an approved item keeps approved_take', () => {
  assert.equal(item(run(make(), ...finished('R1'), approve('R1'), started('R1', 2)), 'R1').approved_take, 1);
});
test('a failed regeneration returns to approved with last_error', () => {
  const r = item(run(make(), ...finished('R1'), approve('R1'), started('R1', 2), failed('R1', 2)), 'R1');
  assert.equal(r.state, 'approved');
  assert.equal(r.approved_take, 1);
  assert.equal(r.last_error.take, 2);
});
test('rejecting the newer take returns to approved', () => {
  const r = item(run(make(), ...finished('R1'), approve('R1'), started('R1', 2), done('R1', 2), reject('R1', 2)), 'R1');
  assert.equal(r.state, 'approved');
  assert.equal(r.approved_take, 1);
});
test('approve with take restores an older take, from rejected too', () => {
  const p = run(make(), ...finished('R1'), started('R1', 2), done('R1', 2), reject('R1', 2));
  assert.equal(item(p, 'R1').state, 'rejected');
  assert.equal(item(run(p, approve('R1', 1)), 'R1').approved_take, 1);
});
test('approve names exactly its take, not the latest', () => {
  const r = item(run(make(), ...finished('R1'), started('R1', 2), done('R1', 2), approve('R1', 1)), 'R1');
  assert.equal(r.approved_take, 1);
  assert.equal(r.takes[1].verdict, null);
});
test('approving twice changes nothing', () => {
  const once = run(make(), ...finished('R1'), approve('R1'));
  assert.deepEqual(run(once, approve('R1')), once);
});
test('one illegal item in a batch changes nothing and names it', () => {
  const p = run(make(), ...finished('R1'));
  assert.throws(() => run(p, { type: 'reviewed', items: [{ id: 'R1', take: 1 }, { id: 'R2', take: 1 }], verdict: 'approved', actor: 'a', at: 't' }), (err) => err.code === 'REVIEW_CONFLICT' && err.details.items[0].id === 'R2');
  assert.equal(item(p, 'R1').state, 'pending_review');
});

test('take_aborted returns the item to planned, or to its prior state when regenerating, and the next take is n+1', () => {
  const p = run(make(), started('R1'), { type: 'take_aborted', item: 'R1', n: 1, code: 'GOOGLE_LIMIT_REACHED' });
  assert.equal(item(p, 'R1').state, 'planned');
  assert.equal(item(run(p, started('R1', 2)), 'R1').takes[1].n, 2);
  assert.throws(() => run(p, started('R1', 1)), conflict);
  const again = run(make(), ...finished('R1'), approve('R1'), started('R1', 2), { type: 'take_aborted', item: 'R1', n: 2 });
  assert.equal(item(again, 'R1').state, 'approved');
});
test('after a stop then resume, nextItem returns the aborted item and its dependents can run', () => {
  let p = run(make(), started('R1'), { type: 'paused', reason: 'quota', code: 'GOOGLE_LIMIT_REACHED' }, { type: 'take_aborted', item: 'R1', n: 1 });
  assert.equal(nextItem(p), null);
  p = run(p, { type: 'resumed' });
  assert.equal(nextItem(p), 'R1');
  p = approved(approved(p, 'R1', 2), 'R2');
  assert.equal(nextItem(p), 'S1');
  assert.equal(depsFor(p, 'S1').refs_used[0].take, 2);
});

test('gate off skips a rejected take', () => {
  const p = run(make({ gates: { references: false } }), ...finished('R1'), started('R1', 2), done('R1', 2), reject('R1', 2));
  assert.equal(depsFor(p, 'S1').refs_used[0].take, 1);
});
test('all failed or rejected with nothing runnable is needs_action naming the item', () => {
  const p = run(run(make(), started('R1'), failed('R1')), started('R2'), done('R2'), reject('R2'));
  const s = summary(p);
  assert.equal(s.status, 'needs_action');
  assert.match(s.next_action, /R1/);
});
test('estimate_set changes the item estimate', () => {
  assert.equal(item(run(make(), { type: 'estimate_set', item: 'A1', credits: 12 }), 'A1').estimate, 12);
});

test('nextItem returns references first, in file order', () => {
  assert.equal(nextItem(make()), 'R1');
  assert.equal(nextItem(approved(make(), 'R1')), 'R2');
});
test('a still waits for its references with the gate on', () => {
  const p = run(make(), ...finished('R1'));
  assert.deepEqual(waitingOn(p, 'S1'), ['R1']);
  assert.equal(nextItem(run(p, ...finished('R2'))), null);
});
test('a still proceeds on the latest take with the gate off', () => {
  const p = run(make({ gates: { references: false } }), ...finished('R1'), ...finished('R2'));
  assert.equal(nextItem(p), 'S1');
  assert.equal(depsFor(p, 'S1').refs_used[0].file, 'R1_v1.jpg');
});
test('an animation waits for its start still', () => {
  const p = approved(refsDone(), 'S2');
  const q = run(p, ...finished('S1'));
  assert.deepEqual(waitingOn(q, 'A1'), ['S1']);
  assert.equal(nextItem(q), 'A2'); // no start frame: only its references
  const r = approved(p, 'S1');
  assert.equal(depsFor(r, 'A1').start_used.file, 'S1_v1.jpg');
  assert.deepEqual(depsFor(r, 'A1').refs_used, []);
});
test('a ready still beats a ready animation', () => {
  const p = refsDone();
  assert.equal(waitingOn(p, 'A2').length, 0);
  assert.equal(nextItem(p), 'S1');
});
test('a failed reference blocks only its dependents', () => {
  const p = approved(run(make(), started('R1'), failed('R1')), 'R2');
  assert.equal(nextItem(p), 'S2');
  assert.deepEqual(waitingOn(p, 'S1'), ['R1']);
});
test('nothing is returned while paused or cancelled', () => {
  assert.equal(nextItem(run(make(), { type: 'paused', reason: 'x' })), null);
  assert.equal(nextItem(run(make(), { type: 'cancelled' })), null);
});
test('one active item means null', () => {
  assert.equal(nextItem(run(make(), started('R1'))), null);
});

test('stills_only never returns an animation', () => {
  const shots = plan().shots.filter(({ kind }) => kind === 'still');
  let p = newProduction(plan({ shots, mode: 'stills_only' }), { id: 'x', runId: 'r' });
  for (const id of ['R1', 'R2', 'S1', 'S2']) {
    assert.equal(nextItem(p), id);
    p = approved(p, id);
  }
  assert.equal(nextItem(p), null);
  assert.equal(summary(p).status, 'complete');
});
test('complete only when all items are approved', () => {
  assert.notEqual(summary(refsDone()).status, 'complete');
});
test('waiting_review when nothing can run and something is pending', () => {
  const p = run(run(make(), ...finished('R1')), ...finished('R2'));
  assert.equal(summary(p).status, 'waiting_review');
});

test('reviewing one item leaves every other item deep-equal', () => {
  const p = run(run(make(), ...finished('R1')), ...finished('R2'));
  const q = run(p, approve('R1'));
  for (const { id } of p.items.filter((i) => i.id !== 'R1')) assert.deepEqual(item(q, id), item(p, id));
});

function stillBuilt() {
  const p = refsDone();
  return approved(p, 'S1', 1, depsFor(p, 'S1'));
}
test('regenerating a reference alone makes nothing stale', () => {
  assert.deepEqual(staleItems(run(stillBuilt(), started('R1', 2), done('R1', 2))), []);
});
test('approving its new take makes approved dependents stale without changing them', () => {
  const p = stillBuilt();
  const q = run(p, started('R1', 2), done('R1', 2), approve('R1', 2));
  assert.deepEqual(staleItems(q), [{ item: 'S1', because: ['R1'] }]);
  assert.deepEqual(item(q, 'S1'), item(p, 'S1'));
  assert.deepEqual(summary(q).stale, [{ item: 'S1', because: ['R1'] }]);
});
test('animation stale when its still approved take changes', () => {
  const p = stillBuilt();
  const q = approved(p, 'A1', 1, depsFor(p, 'A1'));
  assert.deepEqual(staleItems(run(q, started('S1', 2), done('S1', 2), approve('S1', 2))), [{ item: 'A1', because: ['S1'] }]);
});

test('credits planned sums unstarted animations only', () => {
  const p = make();
  assert.equal(summary(p).credits.planned, 20);
  const q = run(refsDone(), started('A2'));
  assert.equal(summary(q).credits.planned, 10);
});
test('credits for one attempt count once', () => {
  const spend = { type: 'credits_spent', item: 'A2', n: 1, credits: 10, attempt: 1 };
  const p = run(refsDone(), started('A2'), spend, spend);
  assert.equal(p.budget.spent, 10);
  assert.equal(run(p, { ...spend, attempt: 2 }).budget.spent, 20);
});
test('a reuse reference starts approved and generates nothing', () => {
  const p = make({ reused: { R1: { file: 'f.jpg', sha256: 'h' } } });
  assert.equal(item(p, 'R1').state, 'approved');
  assert.equal(item(p, 'R1').takes[0].file, 'f.jpg');
  assert.equal(nextItem(p), 'R2');
});
test('a production event never changes its input', () => {
  const p = make();
  const copy = structuredClone(p);
  run(p, started('R1'));
  assert.deepEqual(p, copy);
});
