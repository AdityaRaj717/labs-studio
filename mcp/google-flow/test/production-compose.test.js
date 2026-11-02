import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'fs';
import os from 'os';
import path from 'path';

process.env.FLOW_DATA_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'prod-compose-'));
const { composeJob, takeKey } = await import('../src/production/compose.js');
const { applyEvent, depsFor, newProduction } = await import('../src/production/state.js');
const { assetName } = await import('../src/engine/filenames.js');
const { validateImage, validateVideo } = await import('../src/engine/validate.js');
const { outputName } = await import('../src/flow/image.js');
const { noteStripDrift } = await import('../src/flow/video.js');
const { assertChips, clearChips } = await import('../src/flow/ingredients.js');

const video = { model: 'omni', duration: 6, resolution: '720p' };
const image = { model: 'banana21', size: '2K' };
const plan = {
  plan_id: 'p', name: 'n', mode: 'mixed', style: 'noir', ratio: '16:9',
  references: [{ id: 'R1', kind: 'character', name: 'A', prompt: 'sheet', settings: image }, { id: 'R2', kind: 'place', name: 'B', prompt: 'dock', settings: image }],
  shots: [
    { id: 'S1', kind: 'still', prompt: 'still', refs: ['R2', 'R1'], settings: image },
    { id: 'A1', kind: 'animation', prompt: 'walk', refs: ['R1'], start: 'S1', settings: video, estimate: 10 },
    { id: 'A2', kind: 'animation', prompt: 'run', refs: ['R1'], start: null, settings: video, estimate: 10 },
  ],
};
const finish = (p, id, n = 1) => [
  { type: 'take_started', item: id, n, key: 'k' },
  { type: 'take_done', item: id, n, file: `/run/${id}_v${n}.jpg` },
  { type: 'reviewed', items: [{ id, take: n }], verdict: 'approved', actor: 'app', at: 't' },
].reduce(applyEvent, p);
const ready = (opts = {}) => ['R1', 'R2', 'S1'].reduce((p, id) => finish(p, id), newProduction(plan, { id: 'abc12345', runId: 'r', maxCredits: 25, flowProjectUrl: 'https://flow/project/1', ...opts }));
const compose = (p, id, n = 1) => composeJob(p, id, n, depsFor(p, id));

test('takeKey is derived from intent', () => {
  assert.equal(takeKey('abc', 'IMG_01', 2), 'prod:abc:IMG_01:take:2');
});

test('sheet job has no ingredients and uses 2K', () => {
  const job = compose(newProduction(plan, { id: 'x', runId: 'r' }), 'R1');
  assert.deepEqual(job.ingredients, []);
  assert.equal(job.size, '2K');
  assert.equal(job.count, 1);
  assert.equal(job.kind, 'image');
  assert.equal(job.prompt, 'sheet. Style: noir');
  assert.equal(job.silent, undefined);
  assert.equal(job.output.dir, 'references');
});

test('still job lists approved reference files in order', () => {
  const job = compose(ready(), 'S1', 2);
  assert.deepEqual(job.ingredients, [{ file: '/run/R2_v1.jpg' }, { file: '/run/R1_v1.jpg' }]);
  assert.equal(job.output.dir, 'images');
});

test('animation with a start uses frames and attaches no references', () => {
  const job = compose(ready(), 'A1');
  assert.equal(job.mode, 'frames');
  assert.equal(job.start_frame, '/run/S1_v1.jpg');
  assert.deepEqual(job.ingredients, []);
});

test('animation with no start uses ingredients', () => {
  const job = compose(ready(), 'A2');
  assert.equal(job.mode, 'ingredients');
  assert.deepEqual(job.ingredients, [{ file: '/run/R1_v1.jpg' }]);
  assert.equal(job.start_frame, undefined);
});

test('video job always has silent true and a limit of the smaller of estimate and what is left', () => {
  for (const id of ['A1', 'A2']) assert.equal(compose(ready(), id).silent, true);
  assert.equal(compose(ready(), 'A1').max_credits, 10);
  const spent = applyEvent(applyEvent(ready(), { type: 'take_started', item: 'A2', n: 1, key: 'k' }), { type: 'credits_spent', item: 'A2', n: 1, credits: 20 });
  assert.equal(compose(spent, 'A1').max_credits, 5);
});

test('filename carries the production short id and take', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'run-'));
  fs.mkdirSync(path.join(dir, 'references'));
  const spec = compose(ready(), 'R1', 2);
  const file = outputName({ spec, run: { dir } }, 99, 'unused', '.jpg');
  assert.equal(path.basename(file), `${spec.output.seq}_abc12345-r1_v2.jpg`);
  assert.equal(path.dirname(file), path.join(dir, 'references'));
  // A job with no output keeps the default name.
  assert.equal(outputName({ spec: { prompt: 'a boat' }, run: { dir } }, 3, dir, '.jpg'), assetName(3, 'a boat', 1, '.jpg', dir));
});

test('character mode gives character ingredients', () => {
  let p = ready({ referenceMode: 'character' });
  p = applyEvent(p, { type: 'character_created', item: 'R1', take: 1, name: 'abc-R1-v1' });
  assert.deepEqual(compose(p, 'A2').ingredients, [{ character: 'abc-R1-v1' }]);
});

test('composed jobs pass the job validators when their files exist', () => {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'f-')), 'a.jpg');
  fs.writeFileSync(file, 'x');
  const deps = { refs_used: [{ item: 'R1', take: 1, file }], start_used: null, end_used: null };
  assert.equal(validateVideo(composeJob(ready(), 'A2', 1, deps)).mode, 'ingredients');
  assert.equal(validateVideo(composeJob(ready(), 'A1', 1, { ...deps, refs_used: [], start_used: { file } })).mode, 'frames');
  assert.equal(validateImage(composeJob(ready(), 'S1', 2, deps)).size, '2K');
});

// A page stub with only what the chip gate reads.
const pageWith = (chips) => ({
  reloads: 0,
  locator: () => ({
    evaluateAll: async (fn) => fn(chips.map((busy) => ({ getAttribute: () => (busy ? 'true' : 'false') }))),
    count: async () => chips.length,
    first: () => ({ waitFor: async () => {} }),
  }),
  getByRole: () => ({ first: () => ({ waitFor: async () => {} }) }),
  async reload() { this.reloads++; chips.length = 0; },
});

test('chip count below refs means no Start click: the gate throws', async () => {
  await assert.rejects(assertChips(pageWith([false]), 2), { code: 'UPLOAD_STALLED' });
});
test('a chip still uploading does not count as ready', async () => {
  await assert.rejects(assertChips(pageWith([false, true]), 2), { code: 'UPLOAD_STALLED' });
  await assertChips(pageWith([false, false]), 2);
});
test('chips left over refuse the next Shot', async () => {
  await assert.rejects(assertChips(pageWith([false]), 0), { code: 'UPLOAD_STALLED' });
});
test('chips left by the last job are cleared by a reload before the next Shot', async () => {
  const page = pageWith([false]);
  await clearChips(page);
  assert.equal(page.reloads, 1);
  await assertChips(page, 0);
  await clearChips(page);
  assert.equal(page.reloads, 1);
});

test('a strip that changed the length is a mismatch', () => {
  const verified = { ok: true, mismatches: [], duration: 4 };
  noteStripDrift(verified, { duration: 4.3 });
  assert.equal(verified.ok, true);
  noteStripDrift(verified, { duration: 6 });
  assert.equal(verified.ok, false);
});
