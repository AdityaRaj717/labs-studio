import { execFile, spawn } from 'child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { promisify } from 'util';
import { tool } from '../flow/silent.js';
import { get } from '../utils/config.js';
import { createError, ErrorCodes } from '../utils/errors.js';
import { randomUUID } from 'crypto';
import { allRuns, jobEvents } from './job-store.js';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..');
const FRAME_MS = 60000;
// shortcut: stitches live in memory; one cut short by an engine restart is free to start again.
const stitches = new Map();

const invalid = (message) => createError(ErrorCodes.INVALID_PARAMS, message);

function runOf(run_id) {
  const run = allRuns().find(({ id }) => id === run_id);
  if (!run) throw invalid(`No run ${run_id}`);
  return run;
}

function pythonPath() {
  const venv = path.join(REPO_ROOT, '.venv', 'Scripts', 'python.exe');
  return get('pythonPath') ?? process.env.PYTHON_PATH ?? (fs.existsSync(venv) ? venv : 'python');
}

// The run's videos by sequence, its voice in a row, its first music.
export function autoSpec(run) {
  const clips = run.jobs.filter((job) => job.spec.kind === 'video' && job.state === 'done')
    .flatMap((job) => (job.data.outputs ?? []).map(({ file }) => ({ path: file })));
  if (!clips.length) throw invalid(`Run ${run.id} has no finished videos`);
  const audio = run.audio ?? [];
  const bgm = audio.find(({ kind }) => kind === 'bgm');
  return {
    clips,
    voice: audio.filter(({ kind }) => kind === 'voice').map(({ file, duration }, n) => ({ path: file, ...(duration ? { start: duration * n } : {}) })),
    ...(bgm ? { bgm: { path: bgm.file, volume: 0.3, duck: true } } : {}),
  };
}

const python = (specFile) => spawn(pythonPath(), ['-m', 'src.stitch_cli', specFile], { cwd: REPO_ROOT, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'], env: { ...process.env, ...(get('ffmpegPath') ? { FFMPEG_PATH: get('ffmpegPath') } : {}) } });

let launch = python;

// Tests swap the Python CLI for a stand-in; no argument puts it back.
export const useLauncher = (fn = python) => { launch = fn; };

function runCli(child, onLine) {
  return new Promise((resolve) => {
    let last = null;
    let rest = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => {
      const lines = (rest + chunk).split(/\r?\n/);
      rest = lines.pop();
      for (const line of lines) {
        try {
          last = JSON.parse(line);
          onLine(last);
        } catch { /* a stray print from a library */ }
      }
    });
    child.stderr.on('data', (chunk) => { stderr = (stderr + chunk).slice(-500); });
    child.on('error', (err) => resolve({ last: { type: 'error', error_code: 'NO_PYTHON', message: `Could not start Python: ${err.code}` }, stderr }));
    child.on('close', () => resolve({ last, stderr }));
  });
}

const STITCH_ERRORS = { FFMPEG_NOT_FOUND: ErrorCodes.FFMPEG_NOT_FOUND, NO_PYTHON: ErrorCodes.INTERNAL_ERROR };

function settle(task, { last, stderr }) {
  if (last?.type === 'done') Object.assign(task, { state: 'done', file: last.file, progress: 1 });
  else if (task.cancelling || last?.error_code === 'CANCELLED') task.state = 'cancelled';
  else {
    task.state = 'failed';
    task.error = { error_code: STITCH_ERRORS[last?.error_code] ?? ErrorCodes.GENERATION_REFUSED, message: last?.message ?? `The stitcher stopped: ${stderr}`, next_action: 'Fix the spec and call again. Nothing was spent.' };
  }
  // The CLI removes its partial on cancel; a killed one may not have.
  if (task.state === 'cancelled') fs.rmSync(task.output, { force: true });
  jobEvents.emit('event', { type: 'stitch.settled', runId: task.run_id, stitchId: task.stitch_id, state: task.state });
}

export const stitchView = ({ child, cancelling, ...task }) => task;

export function findStitch(stitch_id) {
  const task = stitches.get(stitch_id);
  if (!task) throw createError(ErrorCodes.JOB_NOT_FOUND, `No stitch ${stitch_id}`);
  return task;
}

// Returns at once: the edit runs as long as it needs, polled with flow_wait and stopped with flow_job_control cancel.
export function stitchVideo({ run_id, spec, auto, name = 'final' }) {
  const run = runOf(run_id);
  if (!spec && auto !== true) throw invalid('Pass spec, or auto: true');
  const slug = String(name).replace(/[^\p{L}\p{N}_-]+/gu, '-').slice(0, 60) || 'final';
  const final = path.join(run.dir, 'final');
  fs.mkdirSync(final, { recursive: true });
  const full = { ...(spec ?? autoSpec(run)) };
  full.output ??= path.join(final, `${slug}.mp4`);
  const specFile = path.join(final, `${slug}.spec.json`);
  fs.writeFileSync(specFile, JSON.stringify(full, null, 2));
  const task = { stitch_id: randomUUID(), run_id: run.id, state: 'running', progress: 0, progress_source: 'phase', output: full.output, spec_file: specFile };
  stitches.set(task.stitch_id, task);
  Object.defineProperty(task, 'child', { value: launch(specFile), enumerable: false });
  runCli(task.child, (line) => {
    if (line.type !== 'progress') return;
    task.progress = line.progress;
    jobEvents.emit('event', { type: 'job.progress', runId: run.id, stitchId: task.stitch_id, stage: 'stitch', progress: Math.round(line.progress * 100), source: 'phase' });
  }).then((result) => settle(task, result));
  return stitchView(task);
}

export function cancelStitch(stitch_id) {
  const task = findStitch(stitch_id);
  if (task.state === 'running') {
    Object.defineProperty(task, 'cancelling', { value: true, enumerable: false });
    task.child.stdin.end(); // closing stdin is the CLI's cancel: it removes the partial file
  }
  return stitchView(task);
}

export async function lastFrame({ run_id, asset_id }) {
  const job = runOf(run_id).jobs.find(({ id }) => id === asset_id);
  const file = job?.data.outputs?.[0]?.file;
  if (!file) throw invalid(`No finished video ${asset_id} in run ${run_id}`);
  const output = path.join(path.dirname(path.dirname(file)), 'images', `${path.parse(file).name}_last.png`);
  // Decode the last 3 s and keep overwriting one file: the last write is the last frame.
  await promisify(execFile)(await tool('ffmpeg'), ['-y', '-v', 'error', '-sseof', '-3', '-i', file, '-map', '0:v:0', '-update', '1', output], { timeout: FRAME_MS, windowsHide: true });
  return { run_id, file: output };
}
