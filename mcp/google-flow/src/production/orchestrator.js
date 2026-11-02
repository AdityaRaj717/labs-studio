import { randomUUID } from 'crypto';
import fs from 'fs';
import path from 'path';
import { validateJob } from '../engine/batch.js';
import { checkBudget } from '../engine/budget.js';
import { assetName } from '../engine/filenames.js';
import { allRuns, enqueue, jobByKey, jobEvents, registerRun, transition } from '../engine/job-store.js';
import * as ledger from '../engine/ledger.js';
import { createRun } from '../engine/run-folder.js';
import { sha256 } from '../flow/image.js';
import { createError, ErrorCodes } from '../utils/errors.js';
import { logger } from '../utils/logger.js';
import { composeJob, takeKey } from './compose.js';
import { loadPlan, productionConfig } from './plan.js';
import * as realStore from './store.js';
import { depsFor, newProduction, nextItem, staleItems, summary, waitingOn } from './state.js';

const KEY = /^prod:([^:]+):(.+):take:(\d+)$/;
const REUSE_DIRS = { reference: 'references', still: 'images' };
const STOPS_PRODUCTION = [ErrorCodes.BROWSER_NOT_CONNECTED, ErrorCodes.FLOW_PAGE_NOT_FOUND];
const ENDS = ['done', 'failed', 'cancelled', 'needs_user', 'paused'];
const REFERENCE_MODES = ['ingredient', 'character'];
const TAB_BUSY_RETRY_MS = 5000;
const PAGE = 50;
const MAX_TEXT = 120;
const REVIEW_VERDICTS = { approve: 'approved', reject: 'rejected' };
const ACTORS = ['agent', 'app'];
const CAN_REGENERATE = ['pending_review', 'approved', 'rejected', 'failed'];
const conflict = (message, details) => createError(ErrorCodes.REVIEW_CONFLICT, message, details);

const invalid = (message, details) => createError(ErrorCodes.INVALID_PARAMS, message, details);
const cut = (text, max = MAX_TEXT) => (text?.length > max ? `${text.slice(0, max)}...` : text);
const latestOf = ({ takes }) => takes.at(-1) ?? null;

// jobs: { kick }, the worker's. flow: { preflight({needsVideo, project_url, name}) -> {balance, project_url}, createCharacter(args) }.
export function createOrchestrator({ jobs, store = realStore, flow }) {
  const entries = new Map();
  const starting = new Map();

  const entryOf = (id) => {
    const entry = id ? entries.get(id) : [...entries.values()].at(-1);
    if (!entry) throw createError(ErrorCodes.PRODUCTION_NOT_FOUND, id ? `No production ${id}` : 'No production yet', { production_id: id });
    return entry;
  };
  const forRun = (runId) => [...entries.values()].find(({ run }) => run.id === runId) ?? null;
  const itemOf = ({ production }, id) => {
    const item = production.items.find((candidate) => candidate.id === id);
    if (!item) throw createError(ErrorCodes.ITEM_NOT_FOUND, `No item ${id}`, { item: id });
    return item;
  };

  function itemView(entry, item, extra = {}) {
    const take = latestOf(item);
    const names = item.refs.map((id) => itemOf(entry, id).name);
    const stale = staleItems(entry.production).find((row) => row.item === item.id)?.because ?? [];
    return {
      production_id: entry.production.id,
      item: item.id,
      stage: item.stage,
      state: item.state,
      take: take?.n ?? null,
      approved_take: item.approved_take,
      prompt: item.prompt,
      // A Take under review shows itself, or the owner would approve what they never saw.
      file: (item.approved_take !== null && item.state !== 'pending_review' ? item.takes.find(({ n }) => n === item.approved_take) : take)?.file ?? null,
      ref_names: names,
      stale,
      error: item.last_error,
      progress: null,
      source: 'phase',
      ...extra,
    };
  }

  const publishItem = (entry, item, extra) => jobEvents.emit('event', { type: 'production.item', runId: entry.run.id, ...itemView(entry, item, extra) });
  const publishSummary = (entry) => jobEvents.emit('event', { type: 'production.summary', runId: entry.run.id, production_id: entry.production.id, ...summary(entry.production) });

  function record(entry, event) {
    entry.production = store.commit(entry.run, entry.production, event);
    const touched = new Set(event.items?.map(({ id }) => id) ?? (event.item ? [event.item] : []));
    if (event.type === 'reviewed') staleItems(entry.production).forEach(({ item }) => touched.add(item));
    touched.forEach((id) => publishItem(entry, itemOf(entry, id)));
    publishSummary(entry);
  }

  function pauseFor(entry, event) {
    if (!entry.production.paused && !entry.production.cancelled) record(entry, { type: 'paused', ...event });
  }

  function heldReason(item, error) {
    const quoted = error?.details?.quotedCredits;
    if (error?.error_code !== ErrorCodes.BUDGET_EXCEEDED || quoted === undefined) return { reason: error ? 'stopped' : 'owner', code: error?.error_code ?? null };
    return { reason: quoted > item.estimate ? 'quote_drift' : 'budget', code: error.error_code, quoted, item: item.id };
  }

  function outcomeOf(job, take, item) {
    const output = job.data.outputs?.[0];
    if (!output) return { type: 'take_failed', code: ErrorCodes.RESULT_MISMATCH, message: 'The job finished with no file', credits_at_risk: true };
    // The anti-goal itself, whatever the worker reported: an Animation with sound never reaches review.
    if (item.stage === 'animation' && output.audio_streams !== 0) {
      return { type: 'take_failed', code: ErrorCodes.RESULT_MISMATCH, message: `${output.audio_streams} audio streams in the deliverable`, file: output.file };
    }
    return { type: 'take_done', file: output.file, original: output.original ?? null, sha256: output.sha256 ?? null, audio_streams: output.audio_streams ?? null, quoted_credits: take.quoted_credits };
  }

  // Brings one Take in line with its job. Safe to repeat, so recovery uses it too.
  function sync(entry, job) {
    const [, , itemId, number] = KEY.exec(job.idempotencyKey ?? '') ?? [];
    if (!itemId) return;
    const n = Number(number);
    const takeNow = () => itemOf(entry, itemId).takes.find((candidate) => candidate.n === n);
    if (!takeNow()) return;
    const base = { item: itemId, n };
    if (job.submittedAt) record(entry, { type: 'credits_spent', ...base, credits: job.data.quotedCredits ?? 0, attempt: job.attempt ?? 1 });
    const item = itemOf(entry, itemId);
    const take = takeNow();
    if (take.status !== 'generating') return;
    const { state, submittedAt, data: { error } } = job;
    if (state === 'done') {
      record(entry, { ...outcomeOf(job, take, item), ...base });
    } else if (state === 'failed' && !job.retrying) {
      if (error?.error_code === ErrorCodes.DOWNLOAD_FAILED && job.data.media) {
        // Paid for and made: resume downloads it, never a second generation.
        pauseFor(entry, { reason: 'download', code: error.error_code, item: itemId });
      } else if (!submittedAt && STOPS_PRODUCTION.includes(error?.error_code)) {
        record(entry, { type: 'take_aborted', ...base, code: error.error_code });
        pauseFor(entry, { reason: 'stopped', code: error.error_code });
      } else {
        record(entry, { type: 'take_failed', ...base, code: error?.error_code ?? ErrorCodes.INTERNAL_ERROR, message: cut(error?.message), credits_at_risk: Boolean(submittedAt || error?.credits_at_risk), file: job.data.outputs?.[0]?.file ?? null });
      }
    } else if (state === 'needs_user' || state === 'paused') {
      pauseFor(entry, heldReason(item, error));
      if (!submittedAt) {
        record(entry, { type: 'take_aborted', ...base, code: error?.error_code ?? null });
        transition(job, 'cancelled'); // the next attempt is a new Take with its own key
      }
    } else if (state === 'cancelled') {
      if (submittedAt) record(entry, { type: 'take_failed', ...base, code: 'CANCELLED', message: 'Cancelled after it reached Flow', credits_at_risk: true });
      else record(entry, { type: 'take_aborted', ...base, code: null });
    }
  }

  // The Take is on disk before this runs, and the key makes a repeat return the same job.
  function queueTake(entry, id, n) {
    const { run, production } = entry;
    const take = itemOf(entry, id).takes.find((candidate) => candidate.n === n);
    const deps = { refs_used: take.refs_used, start_used: take.start_used, end_used: take.end_used };
    let spec;
    try {
      spec = validateJob(composeJob(production, id, n, deps));
    } catch (err) {
      record(entry, { type: 'take_failed', item: id, n, code: err.code ?? ErrorCodes.INTERNAL_ERROR, message: cut(err.message) });
      return null;
    }
    const job = enqueue(run, spec, take.key);
    record(entry, { type: 'take_queued', item: id, n, job_id: job.id });
    jobs.kick();
    return job;
  }

  function startTake(entry, id, { of_take = null, prompt } = {}) {
    const item = itemOf(entry, id);
    const n = item.takes.length + 1;
    const deps = depsFor(entry.production, id);
    record(entry, { type: 'take_started', item: id, n, of_take, key: takeKey(entry.production.id, id, n), prompt, ...deps });
    return queueTake(entry, id, n);
  }

  // Spec section 6: the Flow Character is a scheduler step, so approval itself never needs Chrome.
  const missingCharacters = ({ production }, id) => (production.reference_mode === 'character'
    ? depsFor(production, id).refs_used.filter(({ item, take }) => production.items.find((row) => row.id === item).character?.take !== take)
    : []);

  async function ensureCharacters(entry, id) {
    const { production } = entry;
    for (const { item: refId, take, file } of missingCharacters(entry, id)) {
      const ref = itemOf(entry, refId);
      const name = `${production.id}-${refId}-v${take}`;
      await flow.createCharacter({ project_url: production.flow_project_url, name, images: [file], kind: ref.kind === 'place' ? 'place' : 'person' });
      record(entry, { type: 'character_created', item: refId, take, name });
    }
  }

  async function pump(entry) {
    if (entry.pumping) { entry.again = true; return; }
    entry.pumping = true;
    try {
      do {
        entry.again = false;
        for (let id; (id = nextItem(entry.production));) {
          if (missingCharacters(entry, id).length) await ensureCharacters(entry, id);
          if (nextItem(entry.production) === id) startTake(entry, id);
        }
      } while (entry.again);
    } catch (err) {
      // Another job holds the tab, or the one that just finished has not let go: no later job need come, so try again.
      if (err.code === ErrorCodes.JOB_IN_PROGRESS) {
        setTimeout(() => pump(entry), TAB_BUSY_RETRY_MS).unref();
      } else {
        logger.warn('Production stopped', { event: 'production_stopped', id: entry.production.id, code: err.code, error: err.message });
        pauseFor(entry, { reason: 'error', code: err.code ?? ErrorCodes.INTERNAL_ERROR });
      }
    } finally {
      entry.pumping = false;
    }
  }

  const pumpAll = () => Promise.all([...entries.values()].map(pump));

  function onJobEvent(event) {
    const entry = forRun(event.runId);
    if (event.type === 'job.progress' && entry) {
      const [, , itemId] = KEY.exec(entry.run.jobs.find(({ id }) => id === event.jobId)?.idempotencyKey ?? '') ?? [];
      if (itemId) publishItem(entry, itemOf(entry, itemId), { progress: event.progress, source: event.source });
    }
    if (event.type !== 'job.transition') return;
    const job = entry?.run.jobs.find(({ id }) => id === event.jobId);
    if (job) sync(entry, job);
    if (ENDS.includes(event.state)) pumpAll();
  }

  function resolveReuse(plan) {
    const rows = [...plan.references.map((row) => [row, 'reference']), ...plan.shots.filter(({ kind }) => kind === 'still').map((row) => [row, 'still'])];
    return rows.filter(([row]) => row.reuse).map(([row, stage]) => {
      const source = itemOf(entryOf(row.reuse.production_id), row.reuse.item);
      const take = source.takes.find(({ n }) => n === source.approved_take);
      if (!take) throw createError(ErrorCodes.REVIEW_CONFLICT, `${row.reuse.item} of ${row.reuse.production_id} has no Approved Take`, { item: row.reuse.item });
      return { id: row.id, stage, file: take.file };
    });
  }

  function copyInputs(run, plan) {
    for (const { path: file } of plan.sources) fs.copyFileSync(file, path.join(run.dir, 'inputs', path.basename(file)));
  }

  function copyReused(run, id, reuse) {
    return Object.fromEntries(reuse.map(({ id: itemId, stage, file }) => {
      const copy = assetName(0, `${id}-${itemId}`, 1, path.extname(file), path.join(run.dir, REUSE_DIRS[stage]));
      fs.copyFileSync(file, copy);
      return [itemId, { file: copy, sha256: sha256(copy) }];
    }));
  }

  const startView = ({ production, run }, extra = {}) => {
    const { status, next_action } = summary(production);
    return { production_id: production.id, run_id: run.id, status, next_action, ...extra };
  };

  async function begin(args) {
    const { plan_id, cast_confirmed, auto_confirm, max_credits, project_url, output_root, gates, reference_mode } = args;
    if (auto_confirm !== true) throw invalid('Starting a Production needs auto_confirm: true');
    if (cast_confirmed !== true) throw invalid('cast_confirmed: true means you read both files and every Reference is exactly one subject');
    const plan = loadPlan(plan_id);
    if (plan.analysis_needed.length) {
      throw createError(ErrorCodes.ANALYSIS_REQUIRED, `${plan.analysis_needed.length} items need your judgement: ${plan.analysis_needed.map(({ item }) => item).join(', ')}`, { analysis_needed: plan.analysis_needed });
    }
    const { credits } = plan.estimate;
    if (plan.mode !== 'stills_only' && !Number.isFinite(max_credits)) throw invalid(`A Production with Animations needs max_credits. The estimate is ${credits} credits.`, { credits });
    const cap = plan.mode === 'stills_only' ? max_credits ?? null : max_credits;
    checkBudget({ credits }, cap ?? credits, ledger);
    const mode = reference_mode ?? productionConfig().referenceMode;
    if (!REFERENCE_MODES.includes(mode)) throw invalid(`reference_mode must be one of: ${REFERENCE_MODES.join(', ')}`);
    const reuse = resolveReuse(plan);

    const id = randomUUID().slice(0, 8);
    const { balance, project_url: flowProjectUrl } = await flow.preflight({ needsVideo: plan.mode !== 'stills_only', project_url, name: `${plan.name} ${id}` });
    if (Number.isFinite(balance) && credits > balance) {
      throw createError(ErrorCodes.BUDGET_EXCEEDED, `The estimate of ${credits} credits is above the balance of ${balance}`, { credits, balance });
    }
    const run = createRun({ name: plan.name, outputRoot: output_root, flowProjectUrl });
    registerRun(run);
    copyInputs(run, plan);
    const reused = copyReused(run, id, reuse);
    const production = store.saveNew(run, newProduction(plan, { id, runId: run.id, flowProjectUrl, maxCredits: cap, gates, referenceMode: mode, reused, at: new Date().toISOString() }));
    const entry = { run, production };
    entries.set(id, entry);
    publishSummary(entry);
    logger.info('Production started', { event: 'production_started', id, runId: run.id, balance });
    await pump(entry);
    return startView(entry, { balance });
  }

  async function start(args) {
    const { plan_id, project_url, new_run } = args;
    const repeated = !new_run && [...entries.values()].find(({ production }) => production.plan_id === plan_id && !production.cancelled && (!project_url || production.flow_project_url === project_url));
    if (repeated) return startView(repeated, { repeated: true });
    // A double call must not create two Flow projects while the first waits on preflight.
    if (!new_run && starting.has(plan_id)) return starting.get(plan_id);
    const running = begin(args).finally(() => starting.delete(plan_id));
    if (!new_run) starting.set(plan_id, running);
    return running;
  }

  function status({ production_id, stage, state, detail = 'concise', cursor = 0, limit = PAGE }) {
    const entry = entryOf(production_id);
    const { production, run } = entry;
    const base = { production_id: production.id, run_id: run.id, name: production.name, ...summary(production) };
    const full = detail === 'full';
    if (!stage && !state && !full) return base;
    const rows = production.items.filter((item) => (!stage || item.stage === stage) && (!state || item.state === state));
    const page = rows.slice(cursor, cursor + Math.min(limit, PAGE));
    const items = page.map((item) => (full
      ? itemView(entry, item, { takes: item.takes })
      : { id: item.id, state: item.state, take: latestOf(item)?.n ?? null, approved_take: item.approved_take }));
    return { ...base, items, ...(cursor + page.length < rows.length ? { next_cursor: cursor + page.length } : {}) };
  }

  function resume(runId, { accept_quote } = {}) {
    const entry = forRun(runId);
    const { paused } = entry.production;
    if (!paused) return null;
    if (paused.reason === 'quote_drift') {
      if (accept_quote !== true) throw createError(ErrorCodes.BUDGET_EXCEEDED, `Flow quoted ${paused.quoted} credits for ${paused.item}, above its estimate`, { quoted: paused.quoted, item: paused.item, next_action: 'Call resume with accept_quote: true to proceed at that price.' });
      record(entry, { type: 'estimate_set', item: paused.item, credits: paused.quoted });
    }
    if (paused.reason === 'budget') throw createError(ErrorCodes.BUDGET_EXCEEDED, `Flow quoted ${paused.quoted} credits for ${paused.item}, past max_credits`, { quoted: paused.quoted, item: paused.item, next_action: 'Raise the cap with flow_job_control set_budget.' });
    record(entry, { type: 'resumed' });
    entry.run.jobs.filter((job) => job.state === 'failed' && job.data.error?.error_code === ErrorCodes.DOWNLOAD_FAILED && job.data.media)
      .filter((job) => itemOf(entry, KEY.exec(job.idempotencyKey)[2]).takes.some(({ key, status: st }) => key === job.idempotencyKey && st === 'generating'))
      .forEach((job) => transition(job, 'downloading', { error: null, saved: job.data.error.details?.saved ?? [] }));
    pump(entry);
    return summary(entry.production);
  }

  // A stop with no target still lets everything go that needs no decision about money.
  function resumeAll() {
    const resumed = [];
    for (const entry of entries.values()) {
      const { paused } = entry.production;
      if (!paused || ['quote_drift', 'budget'].includes(paused.reason)) continue;
      resume(entry.run.id);
      resumed.push(entry.production.id);
    }
    return resumed;
  }

  function hold(runId) {
    pauseFor(forRun(runId), { reason: 'owner' });
  }

  function cancel(runId) {
    const entry = forRun(runId);
    if (!entry.production.cancelled) record(entry, { type: 'cancelled' });
  }

  // Needs no Chrome: the verdict is on disk before this returns. Next jobs follow from the queue.
  function review({ production_id, items, action, note, actor }) {
    if (!REVIEW_VERDICTS[action]) throw invalid('action must be approve or reject');
    if (!ACTORS.includes(actor)) throw invalid(`actor must be one of: ${ACTORS.join(', ')}`);
    if (!Array.isArray(items) || !items.length) throw invalid('items must be a non-empty list of { id, take }');
    if (items.some(({ take }) => !Number.isInteger(take))) throw invalid('Every item names its take: a verdict never means "the latest"');
    const entry = entryOf(production_id);
    record(entry, { type: 'reviewed', items: items.map(({ id, take }) => ({ id, take })), verdict: REVIEW_VERDICTS[action], actor, note: note ?? null, at: new Date().toISOString() });
    pump(entry);
    const { status, next_action, credits, stale } = summary(entry.production);
    return {
      items: items.map(({ id }) => {
        const { state, approved_take } = itemOf(entry, id);
        return { id, state, approved_take };
      }),
      summary: { status, next_action, credits },
      stale,
    };
  }

  // A queued job has not spent yet, but its quote is coming, so it counts with the planned ones.
  const notYetSpent = (item) => item.state === 'planned' || (['generating', 'regenerating'].includes(item.state) && !latestOf(item)?.spent_attempt);
  const remaining = ({ budget: { max_credits: cap, spent }, items }) => cap - spent - items.filter(notYetSpent).reduce((sum, { estimate }) => sum + estimate, 0);

  // Spec section 7's order: a repeat first, then anything else during a regeneration, then a stale expected_take.
  async function regenerate({ production_id, item: id, prompt, expected_take, auto_confirm, dry_run, actor }) {
    const entry = entryOf(production_id);
    const { production } = entry;
    const item = itemOf(entry, id);
    const latest = latestOf(item);
    if (prompt !== undefined && !String(prompt).trim()) throw invalid('prompt must not be empty');
    if (item.state === 'regenerating') {
      if ((prompt === undefined || prompt === latest.prompt) && (expected_take === undefined || expected_take === latest.of_take)) {
        return { take: latest.n, job_id: latest.job_id, state: item.state, estimated_credits: item.estimate, repeated: true };
      }
      throw conflict(`${id} is already regenerating as take ${latest.n}`, { item: id, current_take: latest.n });
    }
    if (!CAN_REGENERATE.includes(item.state)) throw conflict(`${id} is ${item.state}, it can't regenerate`, { item: id, state: item.state });
    if (expected_take !== undefined && expected_take !== latest.n) throw conflict(`${id}: the latest take is ${latest.n}, not ${expected_take}`, { item: id, current_take: latest.n });
    if (production.cancelled || production.paused) throw conflict(`The Production is ${production.cancelled ? 'cancelled' : 'paused'}`, { paused: production.paused });
    const waiting = waitingOn(production, id);
    if (waiting.length) throw conflict(`${id} waits on ${waiting.join(', ')}`, { item: id, waiting_on: waiting });
    const cost = item.estimate;
    const left = remaining(production);
    if (item.stage === 'animation' && production.budget.max_credits !== null && cost > left) {
      throw createError(ErrorCodes.BUDGET_EXCEEDED, `${id} would cost ${cost} credits and ${left} are left after what is planned`, { credits: cost, remaining: left, max_credits: production.budget.max_credits, run_id: entry.run.id, next_action: 'Raise the cap with flow_job_control set_budget.' });
    }
    const ready = { take: latest.n + 1, job_id: null, state: item.state, estimated_credits: cost };
    if (dry_run === true) return ready;
    if (item.stage === 'animation' && auto_confirm !== true) return { ...ready, status: 'ready_for_confirmation' };
    logger.info('Regenerate', { event: 'production_regenerate', id: production.id, item: id, actor });
    if (missingCharacters(entry, id).length) await ensureCharacters(entry, id);
    const job = startTake(entry, id, { of_take: latest.n, prompt });
    const now = itemOf(entry, id);
    return { take: latestOf(now).n, job_id: job?.id ?? null, state: now.state, estimated_credits: cost };
  }

  function setBudget({ run_id, max_credits }) {
    if (!Number.isFinite(max_credits) || max_credits < 0) throw invalid('max_credits must be a number, 0 or more');
    const entry = forRun(run_id);
    record(entry, { type: 'budget_set', max_credits });
    if (entry.production.paused?.reason === 'budget') record(entry, { type: 'resumed' });
    pump(entry);
    return summary(entry.production);
  }

  // Current prompts, and only what fits: the rest stay failed and are named.
  async function retryFailed(runId) {
    const entry = forRun(runId);
    const changed = [];
    const skipped = [];
    for (const { id, state } of entry.production.items) {
      if (state !== 'failed') continue;
      try {
        await regenerate({ production_id: entry.production.id, item: id, auto_confirm: true, actor: 'agent' });
        changed.push(id);
      } catch (err) {
        if (err.code !== ErrorCodes.BUDGET_EXCEEDED && err.code !== ErrorCodes.REVIEW_CONFLICT) throw err;
        skipped.push({ id, error_code: err.code, message: cut(err.message) });
      }
    }
    return { changed, skipped };
  }

  // Job store first: its recover() has rebuilt the runs from disk.
  function recover() {
    for (const run of allRuns()) {
      const production = store.loadProduction(run);
      if (production) entries.set(production.id, { run, production });
    }
    for (const entry of entries.values()) {
      for (const item of entry.production.items) {
        const take = latestOf(item);
        if (take?.status !== 'generating') continue;
        const job = jobByKey(take.key);
        if (job) sync(entry, job);
        else queueTake(entry, item.id, take.n);
      }
    }
    return pumpAll();
  }

  return {
    start,
    status,
    resume,
    resumeAll,
    hold,
    cancel,
    review,
    regenerate,
    setBudget,
    retryFailed,
    onJobEvent,
    recover,
    forRun,
    summaryOf: (runId) => summary(forRun(runId).production),
    get: (id) => entryOf(id).production,
    // For tests and the review tools: one event through the same durable path.
    record: (id, event) => { const entry = entryOf(id); record(entry, event); return pump(entry); },
  };
}
