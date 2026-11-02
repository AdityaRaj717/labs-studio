import fs from 'fs';
import path from 'path';
import { setTimeout as sleep } from 'timers/promises';
import { get, getDataDir } from '../utils/config.js';
import { createError, ErrorCodes } from '../utils/errors.js';
import { readStateFile, writeFileAtomic } from './run-folder.js';

const DEFAULT_MIN_GAP_MS = 8000;
const DEFAULT_MAX_GAP_MS = 20000;

const stateFile = () => path.join(getDataDir(), 'pacer.json');
const today = () => new Date().toLocaleDateString('sv'); // local YYYY-MM-DD
const maxGap = () => get('maxGapMs', DEFAULT_MAX_GAP_MS);
const randomGap = () => {
  const min = get('minGapMs', DEFAULT_MIN_GAP_MS);
  return min + Math.random() * (maxGap() - min);
};

function load() {
  const saved = readStateFile(stateFile()) ?? {};
  return { day: today(), uses: saved.day === today() ? saved.uses : 0, nextAt: saved.nextAt ?? 0 };
}

function save(state) {
  fs.mkdirSync(getDataDir(), { recursive: true });
  writeFileAtomic(stateFile(), JSON.stringify(state));
}

// The cap comes from the existing setting; 0 means none, as it did in the app.
function capReached() {
  const cap = get('dailyCap', 0);
  return cap > 0 && load().uses >= cap;
}

function assertUnderCap() {
  if (capReached()) throw createError(ErrorCodes.DAILY_CAP_REACHED, `Daily cap of ${get('dailyCap')} uses reached`);
}

let restarted = true;

async function waitTurn(signal) {
  assertUnderCap();
  const state = load();
  const now = Date.now();
  // A queue of waiters from a previous process, or a clock change, must not hold up this one.
  if (restarted) state.nextAt = Math.min(state.nextAt, now + maxGap());
  restarted = false;
  // Reserved before sleeping, so clients waiting at once get separate turns.
  const turnAt = Math.max(now, state.nextAt);
  save({ ...state, nextAt: turnAt + randomGap() });
  await sleep(turnAt - now, undefined, { signal });
  assertUnderCap();
}

// Call when the generation really starts: the gap and the count run from here.
function recordUse() {
  const state = load();
  state.uses += 1;
  state.nextAt = Math.max(state.nextAt, Date.now() + randomGap());
  save(state);
  return state.uses;
}

export const pacer = { waitTurn, recordUse, capReached };
