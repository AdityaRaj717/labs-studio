import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import fs from 'fs';
import os from 'os';
import path from 'path';

process.env.FLOW_DATA_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'prod-plan-'));
const { buildPlan, finalPrompt, loadPlan } = await import('../src/production/plan.js');

const dirOf = (name) => fileURLToPath(new URL(`./fixtures/productions/${name}/`, import.meta.url));
const zombie = fileURLToPath(new URL('../../../samples/zombie-bunker/', import.meta.url));
const MD_04 = { references: [{ id: 'MD_04', kind: 'place' }] };
const base = { ratio: '16:9', references: [{ id: 'R1', kind: 'character', name: 'Ana', prompt: 'a woman' }] };
const planOf = (shots, over = {}) => buildPlan({ plan: { ...base, shots, ...over } });
const doc = (report) => JSON.parse(fs.readFileSync(path.join(process.env.FLOW_DATA_DIR, 'plans', `${report.plan_id}.json`), 'utf8'));
const shot = (report, id) => doc(report).shots.find((s) => s.id === id);

test('zombie plan is stills_only, 0 credits, quota 12 on Nano Banana 2.1, no ffmpeg need', () => {
  const report = buildPlan({ folder: zombie, overrides: MD_04 });
  assert.equal(report.ok, true, JSON.stringify(report.errors));
  assert.equal(report.mode, 'stills_only');
  assert.equal(report.estimate.credits, 0);
  assert.equal(report.estimate.image_quota.banana21, 12);
  assert.equal(report.estimate.two_k, 12);
  assert.deepEqual(report.counts, { references: 4, stills: 8, animations: 0 });
});

test('zombie plan lists MD_04 in analysis_needed until an override sets it to place', () => {
  assert.deepEqual(buildPlan({ folder: zombie }).analysis_needed.map((a) => a.item), ['MD_04']);
  assert.deepEqual(buildPlan({ folder: zombie, overrides: MD_04 }).analysis_needed, []);
});

test('a mixed plan with ratio 1:1 is an error naming the animation', () => {
  const report = planOf([{ id: 'ANI_01', kind: 'animation', prompt: 'x', refs: [] }], { ratio: '1:1' });
  assert.equal(report.ok, false);
  assert.ok(report.errors.some((e) => /ANI_01/.test(e.message) && e.code === 'RATIO_NOT_AVAILABLE'));
});

test('maxIngredients null skips the refs limit', () => {
  const references = Array.from({ length: 20 }, (_, i) => ({ id: `R${i}`, kind: 'place', prompt: 'p' }));
  const report = planOf([{ id: 'ANI_01', kind: 'animation', prompt: 'x', refs: references.map((r) => r.id) }], { references });
  assert.equal(report.ok, true, JSON.stringify(report.errors));
});

test('refs above maxIngredients is an error', () => {
  const references = Array.from({ length: 17 }, (_, i) => ({ id: `R${i}`, kind: 'place', prompt: 'p' }));
  const report = planOf([{ id: 'IMG_01', kind: 'still', prompt: 'x', refs: references.map((r) => r.id) }], { references });
  assert.ok(report.errors.some((e) => /17 refs, the limit is 16/.test(e.message)));
});

test('mixed plan estimates Omni 720p 6s at 10 each', () => {
  const report = planOf([{ id: 'ANI_01', kind: 'animation', prompt: 'x', refs: [] }, { id: 'ANI_02', kind: 'animation', prompt: 'y', refs: [] }]);
  assert.equal(report.mode, 'mixed');
  assert.equal(report.estimate.credits, 20);
  assert.equal(report.estimate.credits_by_model.omni, 20);
});

test('Duration column overrides the default; prose duration is ignored', () => {
  const report = buildPlan({ folder: dirOf('mixed') });
  assert.equal(report.ok, true, JSON.stringify(report.errors));
  assert.equal(shot(report, 'ANI_02').settings.duration, 4);
  assert.equal(shot(report, 'ANI_02').estimate, 7);
  assert.equal(shot(report, 'ANI_01').settings.duration, 6);
});

test('ANI_03 pairs with IMG_03 and appears in implied; Start none opts out', () => {
  const report = buildPlan({ folder: dirOf('mixed') });
  assert.deepEqual(report.implied, [{ item: 'ANI_03', start: 'IMG_03' }]);
  assert.equal(shot(report, 'ANI_03').start, 'IMG_03');
  assert.equal(shot(report, 'ANI_01').start, null);
});

test('Start naming an Animation is an error', () => {
  const report = planOf([{ id: 'ANI_01', kind: 'animation', prompt: 'x', refs: [] }, { id: 'ANI_02', kind: 'animation', prompt: 'y', refs: [], start: 'ANI_01' }]);
  assert.ok(report.errors.some((e) => /Start ANI_01 is not a Still/.test(e.message)));
});

test('unknown ref is an error', () => {
  assert.ok(planOf([{ id: 'IMG_01', kind: 'still', prompt: 'x', refs: ['NOPE'] }]).errors.some((e) => /unknown ref NOPE/.test(e.message)));
});

test('exact name in the prompt adds a ref with source name', () => {
  const report = planOf([{ id: 'IMG_01', kind: 'still', prompt: 'Ana waits', refs: null }, { id: 'IMG_02', kind: 'still', prompt: 'Banana bread', refs: [] }]);
  assert.deepEqual(shot(report, 'IMG_01').refs, ['R1']);
  assert.equal(shot(report, 'IMG_01').ref_source, 'name');
  assert.deepEqual(shot(report, 'IMG_02').refs, []);
});

test('no refs and no name match is analysis_needed; kind undetermined is analysis_needed', () => {
  const report = buildPlan({ folder: dirOf('prose') });
  assert.deepEqual(report.analysis_needed.map((a) => a.item), ['IMG_01']);
  const undetermined = planOf([{ id: 'IMG_01', kind: 'still', prompt: 'x', refs: [] }], { references: [{ id: 'R1', prompt: 'p' }] });
  assert.deepEqual(undetermined.analysis_needed.map((a) => a.item), ['R1']);
});

test('overrides split one row into two references and remap Shots', () => {
  const report = buildPlan({
    folder: dirOf('two-people'),
    overrides: {
      references: [
        { id: 'CH_M', split_from: 'MD_01', kind: 'character', name: 'The man', prompt: 'A man in grey' },
        { id: 'CH_W', split_from: 'MD_01', kind: 'character', name: 'The woman', prompt: 'A woman in blue' },
      ],
      shots: { IMG_01: { refs: ['CH_M', 'CH_W'] } },
    },
  });
  assert.equal(report.ok, true, JSON.stringify(report.errors));
  assert.deepEqual(report.cast.map((c) => c.id), ['CH_M', 'CH_W']);
  assert.deepEqual(shot(report, 'IMG_01').refs, ['CH_M', 'CH_W']);
});

test('an override naming an unknown ID is an error', () => {
  assert.equal(buildPlan({ folder: zombie, overrides: { references: [{ id: 'NOPE', kind: 'place' }] } }).ok, false);
  assert.equal(buildPlan({ folder: zombie, overrides: { shots: { NOPE: { refs: [] } } } }).ok, false);
});

test('plan JSON goes through the same validator', () => {
  const report = planOf([{ id: 'ANI_01', kind: 'animation', prompt: 'x', refs: [], duration: 3 }]);
  assert.ok(report.errors.some((e) => e.code === 'COMBINATION_NOT_SUPPORTED'));
});

test('a plan prompt missing from the sources warns', () => {
  const report = buildPlan({ folder: zombie, plan: { ...base, shots: [{ id: 'IMG_01', kind: 'still', prompt: 'not in any file', refs: ['R1'] }] } });
  assert.ok(report.warnings.some((w) => /IMG_01 is not in the source files/.test(w.message)));
});

test('Veo Quality with Ingredients is COMBINATION_NOT_SUPPORTED', () => {
  const report = planOf([{ id: 'ANI_01', kind: 'animation', prompt: 'x', refs: ['R1'], model: 'Veo 3.1 Quality', duration: 8 }]);
  assert.ok(report.errors.some((e) => e.code === 'COMBINATION_NOT_SUPPORTED' && /ANI_01/.test(e.message)));
});

test('same inputs give the same plan_id; an edited file makes loadPlan throw PLAN_CHANGED', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'edit-'));
  for (const f of ['moodboard.md', 'animations.md']) fs.copyFileSync(path.join(dirOf('mixed'), f), path.join(dir, f));
  const one = buildPlan({ folder: dir });
  assert.equal(buildPlan({ folder: dir }).plan_id, one.plan_id);
  assert.equal(loadPlan(one.plan_id).plan_id, one.plan_id);
  fs.appendFileSync(path.join(dir, 'animations.md'), '\n');
  assert.throws(() => loadPlan(one.plan_id), { code: 'PLAN_CHANGED' });
  assert.throws(() => loadPlan('missing'), { code: 'PLAN_CHANGED' });
});

test('a plan with errors has no plan_id and is not kept', () => {
  assert.equal(planOf([{ id: 'IMG_01', kind: 'still', prompt: 'x', refs: ['NOPE'] }]).plan_id, null);
});

test('sheet prompt uses the template for characters, unchanged prompt for places, style appended, sheet_prompt override wins', () => {
  const report = buildPlan({ folder: dirOf('mixed') });
  const refs = doc(report).references;
  assert.match(refs[0].prompt, /^Character reference sheet of A woman in a red coat\. One image showing/);
  assert.equal(refs[1].prompt, 'A foggy dock');
  assert.equal(finalPrompt(refs[1], doc(report).style), 'A foggy dock. Style: photoreal');
  const custom = buildPlan({ folder: dirOf('mixed'), overrides: { references: [{ id: 'MD_01', sheet_prompt: 'own sheet' }] } });
  assert.equal(doc(custom).references[0].prompt, 'own sheet');
});
