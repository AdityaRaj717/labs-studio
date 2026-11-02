import fs from 'fs';
import path from 'path';
import { randomUUID } from 'crypto';
import { createError, ErrorCodes } from '../utils/errors.js';
import { logger } from '../utils/logger.js';
import { appendEvent, readEvents } from './journal.js';
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

function isLegal(job, to) {
  if (HOLDS.includes(job.state) && to === job.heldFrom) return true;
  // Only a job that really reached Flow has anything to download.
  if (job.state === 'failed' && to === 'downloading' && !job.submittedAt) return false;
  return MOVES[job.state].includes(to);
}

// Shared by live transitions and journal replay, so both reach the same job state.
function apply(job, { to, data, ts }) {
  if (to === 'submitted') job.submittedAt ??= ts;
  // queued is only reachable again through an explicit retry, which clears the credit line.
  if (to === 'queued') delete job.submittedAt;
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

function loadRun(dir) {
  const file = path.join(dir, 'events.jsonl');
  if (!fs.existsSync(file)) {
    logger.warn('Run folder missing, skipped in recovery', { dir });
    return [];
  }
  const events = readEvents(file);
  const created = events.find((e) => e.type === 'run.created');
  if (!created) return [];
  const { id, name, flowProjectUrl, createdAt } = created;
  const run = { id, name, dir, flowProjectUrl, createdAt, seq: events.at(-1).seq, jobs: [] };
  const jobs = new Map();
  for (const event of events) {
    if (event.type === 'job.enqueued') jobs.set(event.jobId, addJob(run, event));
    else if (event.type === 'job.transition') apply(jobs.get(event.jobId), event);
  }
  return run.jobs;
}

function load() {
  byKey = new Map();
  const registry = runsRegistry();
  if (!fs.existsSync(registry)) return [];
  // shortcut: replays every run ever made on each load, prune the registry if startup slows.
  return readEvents(registry).flatMap(({ dir }) => loadRun(dir));
}

export function enqueue(run, jobSpec, idempotencyKey) {
  if (!byKey) load();
  const existing = idempotencyKey && byKey.get(idempotencyKey);
  if (existing) return existing;
  const event = appendEvent(run, { type: 'job.enqueued', jobId: randomUUID(), spec: jobSpec, idempotencyKey });
  const job = addJob(run, event);
  saveManifest(run);
  return job;
}

// Durable on return: the caller clicks Start only after transition(job, 'submitted') comes back.
export function transition(job, state, data) {
  if (!isLegal(job, state)) {
    throw createError(ErrorCodes.INVALID_PARAMS, `Illegal job move ${job.state} -> ${state}`, { jobId: job.id, from: job.state, to: state });
  }
  const event = appendEvent(job.run, { type: 'job.transition', jobId: job.id, from: job.state, to: state, data });
  apply(job, event);
  saveManifest(job.run);
  return job;
}

// Rebuilds all state from disk. Past the credit line a job only ever goes to reconcile.
export function recover() {
  const open = load().filter((job) => !TERMINAL.includes(job.state));
  return {
    resumable: open.filter((job) => !job.submittedAt),
    reconcile: open.filter((job) => job.submittedAt),
  };
}
