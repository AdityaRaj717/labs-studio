import path from 'path';
import { allRuns, registerRun } from '../engine/job-store.js';
import { assetName } from '../engine/filenames.js';
import { appendEvent } from '../engine/journal.js';
import { createRun, writeFileAtomic, writeManifest } from '../engine/run-folder.js';
import { createError, ErrorCodes } from '../utils/errors.js';

export const REQUEST_TIMEOUT_MS = 120000;
const BACKOFF_MS = 1000;
export const MAX_RETRIES = 3;

export const invalid = (message) => createError(ErrorCodes.INVALID_PARAMS, message);
export const realSleep = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });

// One audio request at a time, whatever the number of callers.
let tail = Promise.resolve();
export function oneAtATime(work) {
  const turn = tail.then(work, work);
  tail = turn.catch(() => {});
  return turn;
}

export function keyFor(getSecret, name, provider) {
  const key = getSecret(name);
  if (!key) throw createError(ErrorCodes.MISSING_API_KEY, `No ${provider} API key`, { next_action: `Enter the ${provider} key in the app's API keys tab, or set ${name} before starting the engine.` });
  return key;
}

// A provider's text can quote what it was sent, so the key is cut from anything reported.
export const scrub = (text, key) => String(text ?? '').slice(0, 300).replaceAll(key, '[key]');

// Only for answers that say the request wasn't done: 429 and 503. A timeout may have been charged, so it isn't repeated.
export async function fetchRetrying({ fetch, sleep, url, init, label }) {
  for (let attempt = 0; ; attempt++) {
    let res;
    try {
      res = await fetch(url, { ...init, signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
    } catch (err) {
      if (err.name === 'TimeoutError' || err.name === 'AbortError') {
        throw createError(ErrorCodes.GENERATION_TIMEOUT, `${label} gave no answer in ${REQUEST_TIMEOUT_MS / 1000} s`, { credits_at_risk: true });
      }
      throw createError(ErrorCodes.INTERNAL_ERROR, `${label} could not be reached: ${err.name}`);
    }
    if (![429, 503].includes(res.status) || attempt === MAX_RETRIES) return res;
    await sleep(BACKOFF_MS * 2 ** attempt);
  }
}

export function runFor({ run_id, name, output_root }) {
  if (run_id) {
    const run = allRuns().find(({ id }) => id === run_id);
    if (!run) throw invalid(`No run ${run_id}`);
    return run;
  }
  const run = createRun({ name: name || 'audio', outputRoot: output_root });
  registerRun(run);
  return run;
}

// On disk and in the manifest before the caller hears it is done.
export function saveAudio(run, { folder, name, ext, bytes, meta }) {
  const seq = (run.audio?.length ?? 0) + 1;
  const file = assetName(seq, name, 1, ext, path.join(run.dir, folder));
  writeFileAtomic(file, bytes);
  const entry = { kind: folder, file, bytes: bytes.length, ...meta };
  run.audio = [...(run.audio ?? []), entry];
  appendEvent(run, { type: 'audio.saved', ...entry });
  writeManifest(run);
  return entry;
}
