import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import fs from 'fs';
import os from 'os';
import path from 'path';

process.env.FLOW_DATA_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'prod-parse-'));
const { discoverFiles, parseMoodboard, parseShots } = await import('../src/production/parse.js');
const { buildPlan } = await import('../src/production/plan.js');

const fixtures = new URL('./fixtures/productions/', import.meta.url);
const read = (rel) => fs.readFileSync(new URL(rel, fixtures));
const sample = new URL('../../../samples/zombie-bunker/', import.meta.url);
const hasError = (result, line, pattern) => assert.ok(result.errors.some((e) => e.line === line && e.file && pattern.test(e.message)), JSON.stringify(result.errors));

test('zombie sample parses to 4 references and 8 stills with no errors', () => {
  const mood = parseMoodboard(fs.readFileSync(new URL('moodboard.md', sample)), 'moodboard.md');
  const shots = parseShots(fs.readFileSync(new URL('images.md', sample)), 'images.md');
  assert.deepEqual([mood.errors, shots.errors], [[], []]);
  assert.equal(mood.references.length, 4);
  assert.equal(shots.shots.length, 8);
  const byId = Object.fromEntries(mood.references.map((r) => [r.id, r]));
  assert.equal(byId.MD_02.kind, 'character');
  assert.equal(byId.MD_02.name, 'The narrator');
  assert.equal(byId.MD_01.kind, 'place');
  assert.equal(byId.MD_04.kind, null);
  assert.deepEqual(shots.shots[2].refs, ['MD_02', 'MD_03']);
  assert.equal(shots.ratio, '16:9');
  assert.equal(shots.shots[0].line_id, 'L01');
});

test('scene table yields S01_IMG and S01_ANI with an explicit start', () => {
  const { shots, errors } = parseShots(read('scene-table/animation-prompts.md'), 'p.md');
  assert.deepEqual(errors, []);
  assert.deepEqual(shots.map((s) => [s.id, s.kind, s.prompt]), [['S01_IMG', 'still', 'Dock at dawn'], ['S01_ANI', 'animation', 'Camera drifts']]);
  assert.equal(shots[1].start, 'S01_IMG');
  assert.equal(shots[1].duration, 6);
});

test('blocks under Characters get CH_ ids', () => {
  const { references, style, errors } = parseMoodboard(read('blocks/moodboard.md'), 'm.md');
  assert.deepEqual(errors, []);
  assert.equal(style, 'ink wash');
  assert.deepEqual(references.map((r) => [r.id, r.kind, r.name]), [['CH_the_old_sailor', 'character', 'The Old Sailor'], ['PL_01', 'place', 'Harbour']]);
  assert.equal(references[0].prompt, 'A sailor with a grey beard');
  const { shots } = parseShots(read('blocks/stills.md'), 's.md');
  assert.deepEqual(shots[0].refs, ['CH_the_old_sailor']);
  assert.equal(shots[0].kind, 'still');
});

test('refs and frames separate absent from explicit none', () => {
  const text = '| ID | Refs | Start | Prompt |\n|---|---|---|---|\n| ANI_01 | none | none | a |\n| ANI_02 | | | b |\n';
  const { shots } = parseShots(text, 'p.md');
  assert.deepEqual([shots[0].refs, shots[0].start], [[], null]);
  assert.deepEqual([shots[1].refs, shots[1].start], [null, undefined]);
  assert.equal(parseShots('| ID | Prompt |\n|---|---|\n| IMG_01 | a |\n', 'p.md').shots[0].refs, null);
});

test('escaped pipe stays in the prompt', () => {
  const { shots } = parseShots('| ID | Prompt |\n|---|---|\n| IMG_01 | a \\| b |\n', 'p.md');
  assert.equal(shots[0].prompt, 'a | b');
});

test('BOM is accepted', () => {
  const { references, errors } = parseMoodboard(Buffer.from('﻿| ID | Prompt |\n|---|---|\n| MD_01 | a |\n'), 'm.md');
  assert.deepEqual(errors, []);
  assert.equal(references[0].id, 'MD_01');
});

test('non-UTF-8 is an error with file and line', () => {
  const bytes = Buffer.concat([Buffer.from('| ID | Prompt |\n|---|---|\n| MD_01 | caf'), Buffer.from([0xe9]), Buffer.from(' |\n')]);
  hasError(parseMoodboard(bytes, 'm.md'), 3, /UTF-8/);
});

test('bad files report each problem with its line', () => {
  const mood = parseMoodboard(read('bad/moodboard.md'), 'm.md');
  hasError(mood, 5, /Duplicate ID MD_01/);
  hasError(mood, 6, /Empty prompt/);
  hasError(mood, 7, /columns/);
  const shots = parseShots(read('bad/images.md'), 'i.md');
  hasError(shots, 1, /Two different ratios/);
  hasError(shots, 4, /conflicts/);
});

test('duplicate ID across both files', () => {
  const report = buildPlan({ plan: { ratio: '16:9', references: [{ id: 'A', kind: 'place', prompt: 'a' }], shots: [{ id: 'A', kind: 'still', prompt: 'b', refs: [] }] } });
  assert.ok(report.errors.some((e) => /Duplicate ID A/.test(e.message)));
  assert.equal(buildPlan({ folder: fileURLToPath(new URL('bad/', fixtures)) }).ok, false);
});

test('discovery prefers animation over still, and errors on two equal matches listing both', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'disc-'));
  for (const f of ['Moodboard.md', 'stills.md', 'Animations.md', 'script.md']) fs.writeFileSync(path.join(dir, f), 'x');
  const found = discoverFiles(dir);
  assert.equal(path.basename(found.prompts), 'Animations.md');
  assert.equal(path.basename(found.moodboard), 'Moodboard.md');
  fs.writeFileSync(path.join(dir, 'animation2.md'), 'x');
  assert.throws(() => discoverFiles(dir), (err) => err.code === 'PROMPT_FILE_INVALID' && /Animations\.md/.test(err.message) && /animation2\.md/.test(err.message));
});
