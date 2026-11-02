import { execFile, spawn } from 'child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { promisify } from 'util';
import { tool } from '../flow/silent.js';
import { get } from '../utils/config.js';
import { createError, ErrorCodes } from '../utils/errors.js';
import { allRuns, jobEvents } from './job-store.js';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..');
// shortcut: runs inside the call, stopped under the shim's 300 s RPC limit; upgrade to a queued job if longer edits are needed.
const LIMIT_MS = 280000;
const FRAME_MS = 60000;

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

function runCli(specFile, onLine) {
  return new Promise((resolve, reject) => {
    const child = spawn(pythonPath(), ['-m', 'src.stitch_cli', specFile], { cwd: REPO_ROOT, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'], env: { ...process.env, ...(get('ffmpegPath') ? { FFMPEG_PATH: get('ffmpegPath') } : {}) } });
    let last = null;
    let rest = '';
    let stderr = '';
    const timer = setTimeout(() => child.stdin.end(), LIMIT_MS); // closing stdin is the CLI's cancel: it removes the partial file
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
    child.on('error', (err) => { clearTimeout(timer); reject(createError(ErrorCodes.INTERNAL_ERROR, `Could not start Python: ${err.code}`, { next_action: 'Set the pythonPath setting.' })); });
    child.on('close', () => { clearTimeout(timer); resolve({ last, stderr }); });
  });
}

export async function stitchVideo({ run_id, spec, auto, name = 'final' }) {
  const run = runOf(run_id);
  if (!spec && auto !== true) throw invalid('Pass spec, or auto: true');
  const slug = String(name).replace(/[^\p{L}\p{N}_-]+/gu, '-').slice(0, 60) || 'final';
  const final = path.join(run.dir, 'final');
  fs.mkdirSync(final, { recursive: true });
  const full = { ...(spec ?? autoSpec(run)) };
  full.output ??= path.join(final, `${slug}.mp4`);
  const specFile = path.join(final, `${slug}.spec.json`);
  fs.writeFileSync(specFile, JSON.stringify(full, null, 2));
  const { last, stderr } = await runCli(specFile, (line) => {
    if (line.type === 'progress') jobEvents.emit('event', { type: 'job.progress', runId: run.id, stage: 'stitch', progress: Math.round(line.progress * 100), source: 'phase' });
  });
  if (last?.type === 'done') return { run_id: run.id, file: last.file, spec_file: specFile };
  if (last?.error_code === 'FFMPEG_NOT_FOUND') throw createError(ErrorCodes.FFMPEG_NOT_FOUND, last.message);
  throw createError(ErrorCodes.GENERATION_REFUSED, last?.message ?? `The stitcher stopped: ${stderr}`, { next_action: 'Fix the spec and call again. Nothing was spent.' });
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
