import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import config from '../src/utils/config.js';
import { registerRun } from '../src/engine/job-store.js';
import { autoSpec, lastFrame, stitchVideo } from '../src/engine/stitch.js';
import { createRun } from '../src/engine/run-folder.js';
import { tool } from '../src/flow/silent.js';

config.dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'stitch-data-'));
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'stitch-'));

function runWith(jobs = [], audio = []) {
  const run = createRun({ name: 'stitch test', outputRoot: root });
  run.jobs = jobs;
  run.audio = audio;
  registerRun(run);
  return run;
}
const video = (id, file, state = 'done') => ({ id, state, spec: { kind: 'video' }, data: { outputs: [{ file }] } });

test('auto orders the run videos by sequence and uses voice and music', () => {
  const run = runWith(
    [video('a', 'one.mp4'), { id: 'i', state: 'done', spec: { kind: 'image' }, data: { outputs: [{ file: 'x.jpg' }] } }, video('b', 'two.mp4'), video('c', 'lost.mp4', 'failed')],
    [{ kind: 'voice', file: 'v.mp3' }, { kind: 'bgm', file: 'm.wav' }, { kind: 'sfx', file: 's.wav' }],
  );
  const spec = autoSpec(run);
  assert.deepEqual(spec.clips, [{ path: 'one.mp4' }, { path: 'two.mp4' }]);
  assert.deepEqual(spec.voice, [{ path: 'v.mp3' }]);
  assert.equal(spec.bgm.path, 'm.wav');
});

test('auto with no videos and a call with neither spec nor auto are refused', async () => {
  const run = runWith();
  await assert.rejects(stitchVideo({ run_id: run.id, auto: true }), { code: 'INVALID_PARAMS' });
  await assert.rejects(stitchVideo({ run_id: run.id }), { code: 'INVALID_PARAMS' });
  await assert.rejects(stitchVideo({ run_id: 'nope', auto: true }), { code: 'INVALID_PARAMS' });
});

test('stitch and last frame run for real on generated media', { timeout: 60000 }, async () => {
  const ffmpeg = await tool('ffmpeg');
  const run = runWith();
  const clip = path.join(run.dir, 'videos', 'a.mp4');
  execFileSync(ffmpeg, ['-y', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=s=160x90:r=10:d=1', '-pix_fmt', 'yuv420p', clip]);
  run.jobs = [video('a', clip)];
  const done = await stitchVideo({ run_id: run.id, spec: { clips: [{ path: clip }, { path: clip }], size: '160x90', fps: 10 }, name: 'joined' });
  assert.equal(path.basename(done.file), 'joined.mp4');
  assert.ok(fs.statSync(done.file).size > 0);
  const frame = await lastFrame({ run_id: run.id, asset_id: 'a' });
  assert.ok(fs.statSync(frame.file).size > 0);
  await assert.rejects(stitchVideo({ run_id: run.id, spec: { clips: [{ path: path.join(root, 'gone.mp4') }] }, name: 'bad' }), /gone\.mp4/);
});
