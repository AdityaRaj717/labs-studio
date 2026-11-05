import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { assetName } from '../src/engine/filenames.js';

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'filenames-'));
after(() => fs.rmSync(dir, { recursive: true, force: true }));

const base = (...args) => path.basename(assetName(...args, dir));

test('names follow <seq>_<slug>_v<n>.<ext> inside the directory', () => {
  const file = assetName(3, 'A Paper Boat!', 1, 'mp4', dir);
  assert.equal(file, path.join(dir, '3_a-paper-boat_v1.mp4'));
});

test('assetName handles Japanese', () => {
  assert.equal(base(1, '紙の船が水に浮かぶ', 1, 'jpg'), '1_紙の船が水に浮かぶ_v1.jpg');
});

test('combining marks survive and input is NFC', () => {
  assert.equal(base(1, 'हिन्दी', 1, 'jpg'), '1_हिन्दी_v1.jpg');
  assert.equal(base(1, 'é', 1, 'jpg'), '1_é_v1.jpg');
});

test('assetName handles reserved names (CON)', () => {
  for (const name of ['CON', 'con', 'NUL', 'COM1', 'LPT9', 'AUX.']) {
    const stem = base(1, name, 1, 'jpg').split('.')[0];
    assert.doesNotMatch(stem, /^(con|prn|aux|nul|com\d|lpt\d)$/i);
    assert.match(stem, /^1_[a-z0-9]+_v1$/);
  }
});

test('trailing dots and spaces never reach the name', () => {
  assert.equal(base(1, 'boat. . ', 1, 'jpg'), '1_boat_v1.jpg');
});

test('a prompt with no letters or numbers still gets a name', () => {
  assert.equal(base(1, '🌊🌊 ...', 1, 'jpg'), '1_asset_v1.jpg');
});

test('path characters in the prompt and extension cannot escape the directory', () => {
  const file = assetName(1, '..\\..\\evil/CON:x*?"<>|', 1, '../.MP4', dir);
  assert.equal(path.dirname(file), dir);
  assert.equal(path.basename(file), '1_evil-con-x_v1.mp4');
});

test('assetName handles 5000 characters within the Windows path limit', () => {
  for (const ch of ['a', '紙', '😀a']) {
    const file = assetName(1, ch.repeat(5000), 1, 'mp4', dir);
    assert.ok(file.length <= 259, `${file.length} UTF-16 units`);
    assert.ok(path.basename(file).length <= 255);
    assert.equal(file, file.toWellFormed());
  }
});

test('a surrogate pair is not split when the slug is cut', () => {
  assert.equal(base(1, `${'a'.repeat(59)}𠮷𠮷`, 1, 'mp4'), `1_${'a'.repeat(59)}_v1.mp4`);
});

test('a deep directory shortens the slug to fit', () => {
  const deep = path.join(dir, 'd'.repeat(259 - dir.length - 30));
  const file = assetName(1, 'x'.repeat(5000), 1, 'mp4', deep);
  assert.equal(file.length, 259);
  assert.ok(path.basename(file).startsWith('1_x'));
});

test('a directory too deep for any name is INVALID_PARAMS with a next_action', () => {
  assert.throws(() => assetName(1, 'boat', 1, 'mp4', path.join(dir, 'd'.repeat(270))), (err) => {
    assert.equal(err.code, 'INVALID_PARAMS');
    assert.ok(err.details.next_action);
    return true;
  });
});

test('never overwrites: an existing name moves to the next version', () => {
  const sub = fs.mkdtempSync(path.join(dir, 'dup-'));
  const first = assetName(7, 'same prompt', 1, 'mp4', sub);
  fs.writeFileSync(first, 'original');
  const second = assetName(7, 'same prompt', 1, 'mp4', sub);
  assert.equal(path.basename(second), '7_same-prompt_v2.mp4');
  fs.writeFileSync(second, 'x');
  assert.equal(path.basename(assetName(7, 'SAME PROMPT', 1, 'mp4', sub)), '7_same-prompt_v3.mp4');
  assert.equal(fs.readFileSync(first, 'utf8'), 'original');
});

test('an empty extension is rejected', () => {
  assert.throws(() => assetName(1, 'boat', 1, '...', dir), { code: 'INVALID_PARAMS' });
});

test('assetName rejects a seq that is not an integer', () => {
  for (const seq of [1.5, '1', NaN, undefined, -1]) {
    assert.throws(() => assetName(seq, 'p', 1, 'mp4', os.tmpdir()), /seq/);
  }
});
