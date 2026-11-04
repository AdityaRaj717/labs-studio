import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import config from '../src/utils/config.js';
import { jobEvents, registerRun } from '../src/engine/job-store.js';
import { autoSpec, cancelStitch, findStitch, lastFrame, stitchVideo, useLauncher } from '../src/engine/stitch.js';
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

test('auto with no videos and a call with neither spec nor auto are refused', () => {
  const run = runWith();
  assert.throws(() => stitchVideo({ run_id: run.id, auto: true }), { code: 'INVALID_PARAMS' });
  assert.throws(() => stitchVideo({ run_id: run.id }), { code: 'INVALID_PARAMS' });
  assert.throws(() => stitchVideo({ run_id: 'nope', auto: true }), { code: 'INVALID_PARAMS' });
});

const settled = (id) => new Promise((resolve) => {
  const on = (event) => { if (event.type === 'stitch.settled' && event.stitchId === id) { jobEvents.off('event', on); resolve(findStitch(id)); } };
  jobEvents.on('event', on);
});

// A stand-in for the Python CLI: writes a partial, reports progress, finishes after ms or removes the partial when stdin closes.
function fakeCli(ms) {
  return (specFile) => {
    const { output } = JSON.parse(fs.readFileSync(specFile, 'utf8'));
    const script = `const fs=require('fs');fs.writeFileSync(${JSON.stringify(output)},'part');
console.log(JSON.stringify({type:'progress',progress:0.5}));
const t=setTimeout(()=>{console.log(JSON.stringify({type:'done',file:${JSON.stringify(output)}}));process.exit(0)},${ms});
process.stdin.on('end',()=>{clearTimeout(t);fs.rmSync(${JSON.stringify(output)},{force:true});console.log(JSON.stringify({type:'error',error_code:'CANCELLED',message:'cancelled'}));process.exit(1)});process.stdin.resume();`;
    return spawn(process.execPath, ['-e', script], { stdio: ['pipe', 'pipe', 'pipe'] });
  };
}

test('long stitch outlives the rpc limit', async (t) => {
  t.after(() => useLauncher(undefined));
  useLauncher(fakeCli(400));
  const run = runWith([video('a', 'one.mp4')]);
  const started = stitchVideo({ run_id: run.id, auto: true, name: 'long' });
  // The call returns before the edit is done, so no RPC limit applies to the edit.
  assert.equal(started.state, 'running');
  assert.equal(started.progress_source, 'phase');
  const done = await settled(started.stitch_id);
  assert.equal(done.state, 'done');
  assert.equal(path.basename(done.file), 'long.mp4');
});

test('cancel removes the partial', async (t) => {
  t.after(() => useLauncher(undefined));
  useLauncher(fakeCli(60000));
  const run = runWith([video('a', 'one.mp4')]);
  const started = stitchVideo({ run_id: run.id, auto: true, name: 'cut' });
  const finished = settled(started.stitch_id);
  // The stand-in writes its partial before its first progress line.
  if (findStitch(started.stitch_id).progress === 0) await new Promise((resolve) => {
    const on = (event) => { if (event.type === 'job.progress' && event.stitchId === started.stitch_id) { jobEvents.off('event', on); resolve(); } };
    jobEvents.on('event', on);
  });
  assert.ok(fs.existsSync(started.output));
  cancelStitch(started.stitch_id);
  const task = await finished;
  assert.equal(task.state, 'cancelled');
  assert.equal(fs.existsSync(started.output), false);
  assert.throws(() => findStitch('nope'), { code: 'JOB_NOT_FOUND' });
});

test('stitch and last frame run for real on generated media', { timeout: 60000 }, async () => {
  const ffmpeg = await tool('ffmpeg');
  const run = runWith();
  const clip = path.join(run.dir, 'videos', 'a.mp4');
  execFileSync(ffmpeg, ['-y', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=s=160x90:r=10:d=1', '-pix_fmt', 'yuv420p', clip]);
  run.jobs = [video('a', clip)];
  const done = await settled(stitchVideo({ run_id: run.id, spec: { clips: [{ path: clip }, { path: clip }], size: '160x90', fps: 10 }, name: 'joined' }).stitch_id);
  assert.equal(path.basename(done.file), 'joined.mp4');
  assert.ok(fs.statSync(done.file).size > 0);
  const frame = await lastFrame({ run_id: run.id, asset_id: 'a' });
  assert.ok(fs.statSync(frame.file).size > 0);
  const bad = await settled(stitchVideo({ run_id: run.id, spec: { clips: [{ path: path.join(root, 'gone.mp4') }] }, name: 'bad' }).stitch_id);
  assert.equal(bad.state, 'failed');
  assert.match(bad.error.message, /gone\.mp4/);
});
