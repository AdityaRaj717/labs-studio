import fs from 'fs';
import path from 'path';
import { createError, ErrorCodes } from '../utils/errors.js';
import { checkBudget, estimate } from './budget.js';
import { enqueue, jobByKey, transition } from './job-store.js';
import { createRun } from './run-folder.js';
import { validateImage, validateVideo } from './validate.js';

const NUMBERS = ['count', 'duration', 'max_generation_retries', 'max_credits'];

const invalid = (message) => createError(ErrorCodes.INVALID_PARAMS, message);

export const validateJob = (job) => (job?.kind === 'video' ? validateVideo(job) : validateImage(job));

// RFC 4180: quoted cells may hold commas, newlines and doubled quotes.
function csvRows(text) {
  const rows = [];
  let row = [];
  let cell = '';
  let quoted = false;
  const endCell = () => { row.push(cell); cell = ''; };
  const endRow = () => { endCell(); rows.push(row); row = []; };
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch !== '"') cell += ch;
      else if (text[i + 1] === '"') { cell += '"'; i++; } else quoted = false;
    } else if (ch === '"') quoted = true;
    else if (ch === ',') endCell();
    else if (ch === '\n') endRow();
    else if (ch !== '\r') cell += ch;
  }
  if (quoted) throw invalid('CSV has an unterminated quote');
  if (cell || row.length) endRow();
  return rows.filter((cells) => cells.some((c) => c.trim()));
}

// Ingredients separate with ";": a file path, character:Name or scene:Name.
function ingredientOf(text) {
  const [, kind, name] = /^(character|scene):(.+)$/.exec(text) ?? [];
  return kind ? { [kind]: name.trim() } : text;
}

function jobFromCsv(headers, cells, line) {
  if (cells.length > headers.length) throw invalid(`CSV row ${line} has more cells than the header`);
  const job = {};
  headers.forEach((key, i) => {
    const value = cells[i]?.trim();
    if (!value) return;
    if (NUMBERS.includes(key)) job[key] = Number(value);
    else if (key === 'silent') job[key] = value.toLowerCase() === 'true';
    else if (key === 'ingredients') job[key] = value.split(';').map((s) => s.trim()).filter(Boolean).map(ingredientOf);
    else job[key] = value;
  });
  return job;
}

export function parseCsv(text) {
  const [header, ...rows] = csvRows(text);
  if (!header) throw invalid('The CSV is empty');
  const headers = header.map((h) => h.trim().toLowerCase());
  if (!headers.includes('prompt')) throw invalid('The CSV needs a prompt column');
  return rows.map((cells, i) => jobFromCsv(headers, cells, i + 2));
}

export function readJobsFile(file) {
  let text;
  try {
    text = fs.readFileSync(file, 'utf8').replace(/^﻿/, '');
  } catch (err) {
    throw invalid(`Could not read the batch file ${file}: ${err.code ?? err.message}`);
  }
  if (path.extname(file).toLowerCase() === '.csv') return parseCsv(text);
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw invalid(`The batch file is not valid JSON: ${file}`);
  }
  return Array.isArray(parsed) ? parsed : parsed?.jobs;
}

function specsOf({ jobs, file, defaults, project, stop_on }) {
  if (Boolean(jobs) === Boolean(file)) throw invalid('Pass exactly one of jobs and file');
  const list = jobs ?? readJobsFile(file);
  if (!Array.isArray(list) || list.length === 0) throw invalid('jobs must be a non-empty list');
  if (stop_on !== undefined && stop_on !== 'failure' && !Array.isArray(stop_on)) throw invalid('stop_on must be "failure" or a list of error codes');
  const where = /^https?:/.test(project ?? '') ? { project_url: project } : (project ? { project_name: project } : {});
  return list.map((job, i) => {
    try {
      return validateJob({ ...defaults, ...where, ...job, ...(stop_on ? { stop_on } : {}) });
    } catch (err) {
      throw createError(err.code ?? ErrorCodes.INVALID_PARAMS, `Job ${i + 1}: ${err.message}`, err.details);
    }
  });
}

// Every row is checked and the whole estimate settled before anything queues, so a bad row or an overrun spends nothing.
export function startBatch(args, ledger) {
  const { name, file, project, max_credits, auto_confirm, idempotency_key, output_root } = args;
  const rowKey = (i) => idempotency_key && `${idempotency_key}:${i}`;
  const first = auto_confirm === true && idempotency_key && jobByKey(rowKey(0));
  if (first) return { run_id: first.run.id, queued: first.run.jobs.length, repeated: true };
  const specs = specsOf(args);
  const estimated = estimate(specs);
  if (auto_confirm !== true) return { status: 'ready_for_confirmation', queued: 0, jobs: specs.length, estimate: estimated };
  checkBudget(estimated, max_credits, ledger);
  const run = createRun({
    name: name ?? (file ? path.parse(file).name : 'batch'),
    outputRoot: output_root,
    flowProjectUrl: specs[0].project_url,
  });
  specs.forEach((spec, i) => enqueue(run, spec, rowKey(i)));
  return { run_id: run.id, queued: specs.length, estimate: estimated };
}

// The rest stay resumable: flow_job_control resume with the run_id runs them.
export function holdRest(job, code) {
  const { stop_on: on } = job.spec;
  if (on !== 'failure' && !(Array.isArray(on) && on.includes(code))) return;
  job.run.jobs.filter(({ state }) => state === 'queued').forEach((other) => transition(other, 'paused'));
}
