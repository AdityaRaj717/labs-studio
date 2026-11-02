import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { getCapabilities } from '../src/engine/capabilities.js';
import { validateImage, validateVideo } from '../src/engine/validate.js';
import { estimate, checkBudget } from '../src/engine/budget.js';

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'validate-'));
const frame = path.join(tmp, 'frame.png');
fs.writeFileSync(frame, 'x');
after(() => fs.rmSync(tmp, { recursive: true, force: true }));

const prompt = 'a paper boat';
const rejects = (fn, code, check = () => {}) =>
  assert.throws(fn, (err) => {
    assert.equal(err.name, 'FlowError');
    assert.equal(err.code, code);
    check(err);
    return true;
  });
const video = (args) => validateVideo({ prompt, ...args });
const credits = (args) => estimate([video(args)]).credits;
const ledger = (total) => ({ monthTotal: () => total });

test('getCapabilities has the verified values and hands out a copy', () => {
  const caps = getCapabilities();
  assert.deepEqual(caps.image.ratios, ['16:9', '4:3', '1:1', '3:4', '9:16']);
  assert.deepEqual(caps.video.ratios, ['16:9', '9:16']);
  assert.equal(caps.limits.monthlyCredits, 1000);
  assert.equal(caps.verifiedAt, '2026-11-02');
  caps.video.ratios.push('1:1');
  assert.deepEqual(getCapabilities().video.ratios, ['16:9', '9:16']);
});

for (const [name, args] of [['empty', { prompt: '' }], ['whitespace', { prompt: ' \n\t' }], ['missing', {}], ['non-string', { prompt: 5 }]]) {
  test(`${name} prompt is INVALID_PARAMS with no page use`, () => {
    rejects(() => validateImage(args), 'INVALID_PARAMS');
    rejects(() => validateVideo(args), 'INVALID_PARAMS');
  });
}

test('missing reference path is INVALID_PARAMS naming the file', () => {
  const gone = path.join(tmp, 'gone.png');
  const names = (err) => assert.match(err.message, /gone\.png/);
  rejects(() => validateImage({ prompt, ingredients: [gone] }), 'INVALID_PARAMS', names);
  rejects(() => video({ ingredients: [{ file: gone }] }), 'INVALID_PARAMS', names);
  rejects(() => video({ start_frame: gone }), 'INVALID_PARAMS', names);
  rejects(() => video({ end_frame: gone }), 'INVALID_PARAMS', names);
  rejects(() => video({ start_frame: tmp }), 'INVALID_PARAMS');
});

test('existing references and library ingredients pass', () => {
  assert.deepEqual(validateImage({ prompt, ingredients: [frame] }).ingredients, [frame]);
  assert.equal(video({ start_frame: frame, end_frame: frame }).mode, 'frames');
  assert.equal(video({ ingredients: [{ character: 'Ana' }] }).mode, 'ingredients');
});

for (const count of [0, 5, 1.5, '2']) {
  test(`count ${JSON.stringify(count)} rejected`, () => {
    rejects(() => validateImage({ prompt, count }), 'INVALID_PARAMS');
    rejects(() => video({ count }), 'INVALID_PARAMS');
  });
}

test('7:3 lists valid ratios', () => {
  rejects(() => validateImage({ prompt, ratio: '7:3' }), 'RATIO_NOT_AVAILABLE', (err) => {
    assert.deepEqual(err.details.valid, getCapabilities().image.ratios);
  });
});

test('video 1:1 rejected', () => {
  rejects(() => video({ ratio: '1:1' }), 'RATIO_NOT_AVAILABLE', (err) => {
    assert.deepEqual(err.details.valid, ['16:9', '9:16']);
  });
});

test('4K rejected on Pro with a next_action', () => {
  const hasAction = (err) => assert.ok(err.details.next_action);
  rejects(() => validateImage({ prompt, size: '4K' }), 'COMBINATION_NOT_SUPPORTED', hasAction);
  rejects(() => video({ model: 'omni', resolution: '4K' }), 'COMBINATION_NOT_SUPPORTED', hasAction);
  rejects(() => video({ model: 'veoLite', resolution: '4K' }), 'COMBINATION_NOT_SUPPORTED', hasAction);
  assert.equal(validateImage({ prompt, size: '2K' }).size, '2K');
});

test('unknown models list the valid ones, including names on Object.prototype', () => {
  for (const model of ['Omni Flash', 'constructor']) {
    rejects(() => video({ model }), 'MODEL_NOT_AVAILABLE', (err) => assert.ok(err.details.valid.includes('omni')));
    rejects(() => validateImage({ prompt, model }), 'MODEL_NOT_AVAILABLE', (err) => assert.ok(err.details.valid.includes('bananaPro')));
  }
});

test('Veo accepts duration 8 or omitted and resolution 720p or omitted', () => {
  for (const model of ['veoLite', 'veoFast', 'veoQuality']) {
    for (const args of [{}, { duration: 8 }, { resolution: '720p' }, { duration: 8, resolution: '720p' }]) {
      const job = video({ model, ...args });
      assert.equal(job.duration, 8);
      assert.equal(job.resolution, '720p');
    }
    for (const args of [{ duration: 4 }, { duration: 6 }, { duration: 10 }, { duration: '8' }, { resolution: '360p' }]) {
      rejects(() => video({ model, ...args }), 'COMBINATION_NOT_SUPPORTED');
    }
  }
});

test('Omni rejects durations and resolutions Flow does not offer', () => {
  rejects(() => video({ model: 'omni', duration: 5 }), 'COMBINATION_NOT_SUPPORTED');
  rejects(() => video({ model: 'omni', resolution: '1080p' }), 'COMBINATION_NOT_SUPPORTED');
});

test('ingredients with Veo Quality is COMBINATION_NOT_SUPPORTED', () => {
  rejects(() => video({ model: 'veoQuality', ingredients: [frame] }), 'COMBINATION_NOT_SUPPORTED');
});

test('ingredients with 4s Veo Lite rejected', () => {
  rejects(() => video({ model: 'veoLite', duration: 4, ingredients: [frame] }), 'COMBINATION_NOT_SUPPORTED');
  assert.equal(video({ model: 'veoLite', ingredients: [frame] }).mode, 'ingredients');
});

test('extend needs a Veo model and edit needs Omni', () => {
  rejects(() => video({ model: 'omni', extend_from: 'clip' }), 'COMBINATION_NOT_SUPPORTED');
  rejects(() => video({ model: 'veoLite', edit_from: 'clip' }), 'COMBINATION_NOT_SUPPORTED');
  assert.equal(video({ model: 'veoLite', extend_from: 'clip' }).mode, 'extend');
  assert.equal(video({ model: 'omni', edit_from: 'clip' }).mode, 'edit');
});

test('modes cannot be mixed', () => {
  rejects(() => video({ model: 'omni', start_frame: frame, ingredients: [frame] }), 'COMBINATION_NOT_SUPPORTED');
  rejects(() => video({ model: 'veoLite', extend_from: 'clip', start_frame: frame }), 'COMBINATION_NOT_SUPPORTED');
});

test('non-array ingredients are INVALID_PARAMS', () => {
  rejects(() => video({ ingredients: frame }), 'INVALID_PARAMS');
});

test('other job args survive normalizing', () => {
  const job = video({ silent: true, auto_confirm: true, max_credits: 20 });
  assert.equal(job.silent, true);
  assert.equal(job.auto_confirm, true);
  assert.equal(job.max_credits, 20);
});

test('Omni 10s 720p estimates 15', () => assert.equal(credits({ model: 'omni', duration: 10, resolution: '720p' }), 15));
test('Omni 4s 360p estimates 4', () => assert.equal(credits({ model: 'omni', duration: 4, resolution: '360p' }), 4));
test('Veo Lite estimates 10', () => assert.equal(credits({ model: 'veoLite' }), 10));
test('Veo Fast estimates 20', () => assert.equal(credits({ model: 'veoFast' }), 20));
test('Veo Quality 100', () => assert.equal(credits({ model: 'veoQuality' }), 100));
test('Omni edit estimates 40', () => assert.equal(credits({ model: 'omni', edit_from: 'clip' }), 40));
test('x2 doubles', () => assert.equal(credits({ model: 'omni', duration: 8, resolution: '720p', count: 2 }), 24));

test('images estimate 0 credits and count against quota', () => {
  const result = estimate([
    validateImage({ prompt, model: 'bananaPro', count: 2 }),
    validateImage({ prompt, model: 'bananaPro' }),
    validateImage({ prompt, model: 'banana21', count: 4 }),
  ]);
  assert.equal(result.credits, 0);
  assert.deepEqual(result.imageQuota, { bananaPro: 3, banana21: 4 });
  assert.deepEqual(result.warnings, []);
});

test('a run above a daily image limit warns, and the shared pool is summed', () => {
  const jobs = (model, n) => Array.from({ length: n }, () => validateImage({ prompt, model, count: 4 }));
  assert.match(estimate(jobs('bananaPro', 26)).warnings[0], /bananaPro.*100/);
  assert.equal(estimate(jobs('bananaPro', 25)).warnings.length, 0);
  assert.match(estimate([...jobs('banana21', 125), ...jobs('banana2Lite', 126)]).warnings[0], /1000/);
  assert.equal(estimate([...jobs('banana21', 125), ...jobs('banana2Lite', 125)]).warnings.length, 0);
});

test('spend above max_credits is BUDGET_EXCEEDED', () => {
  rejects(() => checkBudget({ credits: 31 }, 30, ledger(0)), 'BUDGET_EXCEEDED', (err) => assert.ok(err.details.next_action));
  checkBudget({ credits: 30 }, 30, ledger(0));
});

test('max_credits defaults to 30 and bad values never mean unlimited', () => {
  rejects(() => checkBudget({ credits: 31 }, undefined, ledger(0)), 'BUDGET_EXCEEDED');
  for (const bad of ['lots', NaN, null, -1]) {
    rejects(() => checkBudget({ credits: 0 }, bad, ledger(0)), 'INVALID_PARAMS');
  }
});

test('spend past the monthly allowance is BUDGET_EXCEEDED', () => {
  rejects(() => checkBudget({ credits: 11 }, 30, ledger(990)), 'BUDGET_EXCEEDED');
  checkBudget({ credits: 10 }, 30, ledger(990));
});
