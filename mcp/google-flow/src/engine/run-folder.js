import fs from 'fs';
import path from 'path';
import { getDataDir } from '../utils/config.js';
import { appendEvent, appendLine } from './journal.js';
import { createError, ErrorCodes } from '../utils/errors.js';

const SUBFOLDERS = ['images', 'videos', 'voice', 'bgm', 'sfx', 'final', 'diagnostics', 'references', 'inputs'];
const RENAME_ATTEMPTS = 6;
const RENAME_RETRY_MS = 50;

// Runs can live under any output root, so recover() finds them through this list.
export const runsRegistry = () => path.join(getDataDir(), 'runs.jsonl');

const stamp = (d) => {
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
};

const slugify = (name) =>
  name.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '-').slice(0, 40).replace(/^-+|-+$/g, '') || 'run';

function makeUniqueDir(base) {
  for (let n = 1; ; n++) {
    const dir = n === 1 ? base : `${base}-${n}`;
    try {
      fs.mkdirSync(dir);
      return dir;
    } catch (err) {
      if (err.code !== 'EEXIST') throw err;
    }
  }
}

export function createRun({ name, outputRoot, flowProjectUrl }) {
  const root = outputRoot ?? path.join(process.env.APPDATA, 'LabsStudio', 'outputs');
  const runs = path.join(root, 'runs');
  fs.mkdirSync(runs, { recursive: true });
  const now = new Date();
  const dir = makeUniqueDir(path.join(runs, `${stamp(now)}-${slugify(name)}`));
  for (const sub of SUBFOLDERS) fs.mkdirSync(path.join(dir, sub));

  const run = { id: path.basename(dir), name, dir, flowProjectUrl, createdAt: now.toISOString(), seq: 0, jobs: [] };
  appendEvent(run, { type: 'run.created', id: run.id, name, flowProjectUrl, createdAt: run.createdAt });
  writeManifest(run);
  fs.mkdirSync(getDataDir(), { recursive: true });
  appendLine(runsRegistry(), JSON.stringify({ dir }));
  return run;
}

// Windows: antivirus or an indexer can hold the target for a moment.
function renameWithRetry(from, to) {
  for (let attempt = 1; ; attempt++) {
    try {
      return fs.renameSync(from, to);
    } catch (err) {
      if (!['EPERM', 'EBUSY', 'EACCES'].includes(err.code) || attempt === RENAME_ATTEMPTS) throw err;
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, RENAME_RETRY_MS * attempt);
    }
  }
}

export function writeManifest(run) {
  writeFileAtomic(path.join(run.dir, 'manifest.json'), JSON.stringify(run, null, 2));
}

export function writeFileAtomic(file, text) {
  const tmp = `${file}.tmp`;
  const fd = fs.openSync(tmp, 'w');
  try {
    fs.writeFileSync(fd, text);
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  // shortcut: no directory fsync, Windows refuses it; a power cut leaves the previous version at worst.
  renameWithRetry(tmp, file);
}

// null means never written. Corrupt state is an error: guessing would reset a cap or hide spend.
export function readStateFile(file) {
  let text;
  try {
    text = fs.readFileSync(file, 'utf8');
  } catch (err) {
    if (err.code === 'ENOENT') return null;
    throw err;
  }
  try {
    return JSON.parse(text);
  } catch {
    throw createError(ErrorCodes.INTERNAL_ERROR, `Corrupt state file: ${file}`, {
      next_action: `Restore or repair ${file}; deleting it forgets what it recorded.`,
    });
  }
}
