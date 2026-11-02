import { EventEmitter } from 'events';
import fs from 'fs';
import path from 'path';
import { randomUUID } from 'crypto';
import { createError, ErrorCodes } from '../utils/errors.js';
import { logger } from '../utils/logger.js';
import { appendEvent, corruptJournal, readEvents } from './journal.js';
import { runsRegistry, writeManifest } from './run-folder.js';

const HOLDS = ['needs_user', 'paused'];
const EXITS = ['needs_user', 'failed', 'cancelled', 'paused'];
const TERMINAL = ['done', 'failed', 'cancelled'];

// Spec 6.1. submitted can go straight to downloading when reconcile finds the result in the project.
const MOVES = {
  queued: ['preparing', ...EXITS],
  preparing: ['submitted', ...EXITS],
  submitted: ['generating', 'downloading', ...EXITS],
  generating: ['downloading', ...EXITS],
  downloading: ['verifying', ...EXITS],
  verifying: ['done', 'downloading', ...EXITS],
  needs_user: ['failed', 'cancelled'],
  paused: ['failed', 'cancelled'],
  done: [],
  failed: ['queued', 'downloading'],
  cancelled: [],
};

let byKey = null;
const runs = new Map(); // by dir: one Run object per folder, or two would hand out the same seq

// Every enqueue and transition, for the engine's event stream.
export const jobEvents = new EventEmitter();

function isLegal(job, to, retry) {
  // Going back behind the credit line spends again, so it takes an explicit retry.
  if (job.state === 'failed' && to === 'queued' && job.submittedAt && !retry) return false;
  if (HOLDS.includes(job.state) && to === job.heldFrom) return true;
  // Only a job that really reached Flow has anything to download.
  if (job.state === 'failed' && to === 'downloading' && !job.submittedAt) return false;
  return MOVES[job.state].includes(to);
}

// Shared by live transitions and journal replay, so both reach the same job state.
function apply(job, { to, data, ts }) {
  if (to === 'submitted') job.submittedAt ??= ts;
  // A new paid attempt: the old one moves to history, and job.attempt keys the ledger.
  if (to === 'queued' && job.submittedAt) {
    const attempt = job.attempt ?? 1;
    (job.history ??= []).push({ attempt, submittedAt: job.submittedAt, error: job.data.error });
    job.attempt = attempt + 1;
    delete job.submittedAt;
    delete job.data.error;
  }
  if (HOLDS.includes(to)) job.heldFrom = job.state;
  else delete job.heldFrom;
  job.state = to;
  job.updatedAt = ts;
  if (data) Object.assign(job.data, data);
}

function addJob(run, { jobId, spec, idempotencyKey, ts }) {
  const job = { id: jobId, idempotencyKey, spec, state: 'queued', data: {}, createdAt: ts, updatedAt: ts };
  Object.defineProperty(job, 'run', { value: run }); // non-enumerable: keeps the manifest free of a cycle
  run.jobs.push(job);
  if (idempotencyKey) byKey.set(idempotencyKey, job);
  return job;
}

// The journal is the truth and already fsynced; a manifest failure must not fail the job.
function saveManifest(run) {
  try {
    writeManifest(run);
  } catch (err) {
    logger.warn('Manifest write failed', { run: run.id, error: err.message });
  }
}

function loadRun(dir, known) {
  const file = path.join(dir, 'events.jsonl');
  if (!fs.existsSync(file)) {
    logger.warn('Run folder missing, skipped in recovery', { dir });
    return [];
  }
  const events = readEvents(file);
  const created = events.find((e) => e.type === 'run.created');
  if (!created) return [];
  const { id, name, flowProjectUrl, createdAt } = created;
  const run = known.get(dir) ?? { id, name, dir, flowProjectUrl, createdAt, jobs: [] };
  run.seq = events.at(-1).seq;
  run.jobs.length = 0;
  runs.set(dir, run);
  const jobs = new Map();
  for (const event of events) {
    if (event.type === 'job.enqueued') jobs.set(event.jobId, addJob(run, event));
    else if (event.type === 'job.transition') {
      const job = jobs.get(event.jobId);
      if (!job) throw corruptJournal(file, `transition at seq ${event.seq} for a job never enqueued`);
      apply(job, event);
    }
  }
  const audio = events.filter((e) => e.type === 'audio.saved').map(({ seq, ts, type, ...entry }) => entry);
  if (audio.length) run.audio = audio;
  return run.jobs;
}

function load() {
  byKey = new Map();
  // Live objects from enqueue stay the ones in use; anything off the registry is gone.
  const known = new Map(runs);
  runs.clear();
  const registry = runsRegistry();
  if (!fs.existsSync(registry)) return [];
  // shortcut: replays every run ever made on each load, prune the registry if startup slows.
  return readEvents(registry).flatMap(({ dir }) => loadRun(dir, known));
}

export const jobByKey = (key) => {
  if (!byKey) load();
  return byKey.get(key);
};

export function enqueue(run, jobSpec, idempotencyKey) {
  runs.set(run.dir, run);
  if (!byKey) load();
  const existing = idempotencyKey && byKey.get(idempotencyKey);
  if (existing) return existing;
  const event = appendEvent(run, { type: 'job.enqueued', jobId: randomUUID(), spec: jobSpec, idempotencyKey });
  const job = addJob(run, event);
  saveManifest(run);
  jobEvents.emit('event', { type: 'job.enqueued', runId: run.id, jobId: job.id, state: job.state });
  return job;
}

// Durable on return: the caller clicks Start only after transition(job, 'submitted') comes back.
// retry: true is the explicit call that lets a job past the credit line spend again.
export function transition(job, state, data, { retry = false } = {}) {
  if (!isLegal(job, state, retry)) {
    const hint = job.state === 'failed' && state === 'queued' ? ' without an explicit retry' : '';
    throw createError(ErrorCodes.INVALID_PARAMS, `Illegal job move ${job.state} -> ${state}${hint}`, { jobId: job.id, from: job.state, to: state });
  }
  const event = appendEvent(job.run, { type: 'job.transition', jobId: job.id, from: job.state, to: state, data });
  apply(job, event);
  saveManifest(job.run);
  jobEvents.emit('event', { type: 'job.transition', runId: job.run.id, jobId: job.id, from: event.from, state });
  return job;
}

export const allRuns = () => [...runs.values()];

// A Production's Run exists before its first job, and may never have one if everything is reused.
export const registerRun = (run) => { runs.set(run.dir, run); };

// Rebuilds all state from disk. Past the credit line a running job only ever goes to reconcile; a held one waits for its owner.
export function recover() {
  const open = load().filter((job) => !TERMINAL.includes(job.state));
  const running = open.filter((job) => !HOLDS.includes(job.state));
  return {
    resumable: running.filter((job) => !job.submittedAt),
    reconcile: running.filter((job) => job.submittedAt),
    held: open.filter((job) => HOLDS.includes(job.state)),
  };
}
