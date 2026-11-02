import { closeBrowser } from '../browser/connect.js';
import { readAccountStatus } from '../browser/account-check.js';
import { navigateToFlow } from '../browser/launch-profile.js';
import { handleCreateCharacter, handleListCharacters } from '../tools/create-character.js';
import { handleCreateScene, handleListScenes } from '../tools/create-scene.js';
import { runDoctor } from '../tools/doctor.js';
import { handleFlowStatus } from '../tools/flow-status.js';
import { handleImportCharacter } from '../tools/import-character.js';
import { handleDeleteProject, handleListProjects, handleOpenProject, handleRenameProject } from '../tools/open-project.js';
import { TOOLS } from '../shim/tools.js';
import { createError, ERROR_CLASSES, ErrorCodes, toErrorPayload } from '../utils/errors.js';
import { takeScreenshot } from '../utils/screenshots.js';
import { checkBudget, estimate } from './budget.js';
import { getCapabilities } from './capabilities.js';
import { allRuns, enqueue, jobByKey, transition } from './job-store.js';
import * as ledger from './ledger.js';
import { createRun } from './run-folder.js';
import { withTab } from './tab-lock.js';
import { validateImage, validateVideo } from './validate.js';

const MAX_WAIT_MS = 55000;
const DEFAULT_WAIT_MS = 30000;
const FULL_PAGE = 50;
const MAX_TEXT = 200;
const MAX_LISTED_FAILURES = 5;
const SETTLED = ['done', 'failed', 'cancelled', 'needs_user', 'paused'];
const HELD = ['needs_user', 'paused'];

const cut = (text, max = MAX_TEXT) => (text?.length > max ? `${text.slice(0, max)}...` : text);
const invalid = (message) => createError(ErrorCodes.INVALID_PARAMS, message);

function errorView(error) {
  const { error_code, message, credits_at_risk, next_action, retryable, screenshot } = error;
  return { error_code, message: cut(message), credits_at_risk, next_action, retryable, screenshot };
}

// Spec 6.2: Flow's own number while it shows one, otherwise only the engine's stage.
const jobView = (job) => ({
  job_id: job.id,
  run_id: job.run.id,
  state: job.state,
  attempt: job.attempt ?? 1,
  prompt: cut(job.spec.prompt, 80),
  progress: job.state === 'generating' && job.progress ? job.progress : { source: 'phase', stage: job.state },
  ...(job.data.outputs ? { outputs: job.data.outputs } : {}),
  ...(job.data.error ? { error: errorView(job.data.error) } : {}),
});

function runView(run) {
  const counts = {};
  for (const { state } of run.jobs) counts[state] = (counts[state] ?? 0) + 1;
  const failed = run.jobs.filter((job) => job.state === 'failed');
  return {
    run_id: run.id,
    name: cut(run.name, 60),
    total: run.jobs.length,
    counts,
    failed: failed.slice(0, MAX_LISTED_FAILURES).map((job) => ({ job_id: job.id, error_code: job.data.error?.error_code })),
  };
}

function findJob(id) {
  const job = allRuns().flatMap((run) => run.jobs).find((j) => j.id === id);
  if (!job) throw createError(ErrorCodes.JOB_NOT_FOUND, `No job ${id}`);
  return job;
}

function findRun(id) {
  const run = allRuns().find((r) => r.id === id);
  if (!run) throw createError(ErrorCodes.JOB_NOT_FOUND, `No run ${id}`);
  return run;
}

function targetOf({ job_id, run_id }) {
  if (Boolean(job_id) === Boolean(run_id)) throw invalid('Pass exactly one of job_id and run_id');
  return job_id ? [findJob(job_id)] : findRun(run_id).jobs;
}

// After a crash nothing watches a paid job. Finding it in the project comes in a later task; until then it is reported, never rerun.
export function failLostJob(job) {
  transition(job, 'failed', {
    error: toErrorPayload(createError(ErrorCodes.FLOW_GENERATION_FAILED, 'The engine lost track of this job after it reached Flow', {
      credits_at_risk: true,
      next_action: 'Check the project in Flow for the result. retry_failed spends again.',
    })),
  });
}

export function createRpc({ worker, session, hub }) {
  // shortcut: refuses rather than queues while a job runs, or the call could wait out a whole batch.
  const tab = (fn) => {
    if (worker.busy()) {
      throw createError(ErrorCodes.JOB_IN_PROGRESS, 'A job is using the Flow tab', { active: worker.status().active });
    }
    return withTab('tool', async () => {
      const open = await session.ensure();
      if (!open.page) throw createError(ErrorCodes.BROWSER_NOT_CONNECTED, 'Chrome is not connected');
      return fn(open.page);
    });
  };
  const onTab = (handler) => (args) => tab(() => handler(args));

  // A queued job does not move while this holds, so every caller waiting on one must be told.
  function queuePaused() {
    const reason = worker.status().paused;
    if (!reason) return {};
    return { queue_paused: { reason, next_action: `${ERROR_CLASSES[reason].next_action} Then flow_job_control with action resume runs the queue.` } };
  }

  function view({ job_id, run_id, detail, offset = 0 }) {
    if (job_id) return jobView(findJob(job_id));
    if (!run_id) throw invalid('Pass job_id or run_id');
    const run = findRun(run_id);
    return {
      ...runView(run),
      ...(detail === 'full' ? { offset, jobs: run.jobs.slice(offset, offset + FULL_PAGE).map(jobView) } : {}),
    };
  }

  async function wait(args) {
    const { wait_ms = DEFAULT_WAIT_MS } = args;
    if (!Number.isInteger(wait_ms) || wait_ms < 0 || wait_ms > MAX_WAIT_MS) throw invalid(`wait_ms must be 0 to ${MAX_WAIT_MS}`);
    const jobs = targetOf(args);
    const finished = () => jobs.every((job) => SETTLED.includes(job.state) && !job.retrying);
    // Nothing will move on a paused queue, so waiting would only hide that.
    if (!finished() && !(worker.status().paused && !worker.busy())) {
      await new Promise((resolve) => {
        let unsubscribe;
        const done = () => {
          clearTimeout(timer);
          unsubscribe();
          resolve();
        };
        const timer = setTimeout(done, wait_ms);
        unsubscribe = hub.subscribe(() => { if (finished()) done(); });
      });
    }
    const { paused } = worker.status();
    return { ...view(args), finished: finished(), ...(paused ? { paused } : {}), ...queuePaused() };
  }

  function generateImage(args) {
    const { auto_confirm, max_credits, idempotency_key, output_root, ...request } = args;
    // First: a repeat must return its job whatever the budget says now.
    const first = auto_confirm === true && idempotency_key && jobByKey(idempotency_key);
    if (first) return { job_id: first.id, run_id: first.run.id, state: first.state, repeated: true, ...queuePaused() };
    const spec = validateImage(request);
    const estimated = estimate([spec]);
    if (auto_confirm !== true) return { status: 'ready_for_confirmation', estimate: estimated, request: { ...spec, prompt: cut(spec.prompt) } };
    checkBudget(estimated, max_credits, ledger);
    const run = createRun({ name: spec.prompt, outputRoot: output_root, flowProjectUrl: spec.project_url });
    const job = enqueue(run, { ...spec, max_credits }, idempotency_key);
    worker.kick();
    return { job_id: job.id, run_id: run.id, state: job.state, estimate: estimated, ...queuePaused() };
  }

  // A held job past the credit line lost its watcher, so it is settled rather than run again.
  function resumeJob(job) {
    transition(job, job.heldFrom);
    if (job.submittedAt) failLostJob(job);
  }

  // Spec 6.1: a download or disk failure retries the download only, never the generation.
  function retryJob(job) {
    const { error, media } = job.data;
    if (error?.error_code === ErrorCodes.DOWNLOAD_FAILED && media) transition(job, 'downloading', { error: null, saved: error.details?.saved ?? [] });
    else transition(job, 'queued', undefined, { retry: true });
  }

  function control({ action, job_id, run_id }) {
    if (action === 'resume' || action === 'retry_failed') worker.assertSettled(); // before any job moves
    if (action === 'resume' && !job_id && !run_id) {
      worker.resume();
      return worker.status();
    }
    const jobs = targetOf({ job_id, run_id });
    const pick = (states) => jobs.filter((job) => states.includes(job.state));
    let changed;
    if (action === 'pause') {
      changed = pick(['queued']);
      changed.forEach((job) => transition(job, 'paused'));
    } else if (action === 'resume') {
      changed = pick(HELD);
      changed.forEach(resumeJob);
      worker.resume();
    } else if (action === 'cancel') {
      changed = jobs.filter((job) => !['done', 'failed', 'cancelled'].includes(job.state));
      for (const job of changed) {
        if (worker.isActive(job)) worker.cancelActive();
        else transition(job, 'cancelled');
      }
    } else if (action === 'retry_failed') {
      changed = pick(['failed']);
      changed.forEach(retryJob);
      worker.resume();
    } else {
      throw invalid(`Unknown action: ${action}`);
    }
    return { action, changed: changed.length, ...worker.status() };
  }

  async function status(args) {
    const busy = worker.busy();
    const read = () => handleFlowStatus({ ...args, busy });
    const result = await (busy ? read() : withTab('status', read));
    result.queue.paused = worker.status().paused;
    return result;
  }

  const connect = ({ open_flow = true }) => tab(async (page) => {
    const signIn = open_flow && (await navigateToFlow(page)).authenticated === false;
    const check = signIn ? null : await readAccountStatus(page);
    return { status: signIn ? 'oauth_required' : 'connected', account: check?.account ?? null, accountStatus: check?.status ?? 'unverified', url: page.url().split(/[?#]/)[0] };
  });

  function estimateJobs({ jobs }) {
    if (!Array.isArray(jobs) || jobs.length === 0) throw invalid('jobs must be a non-empty list');
    return estimate(jobs.map((job) => (job?.kind === 'video' ? validateVideo(job) : validateImage(job))));
  }

  const handlers = {
    flow_estimate: estimateJobs,
    flow_connect: connect,
    flow_disconnect: () => withTab('disconnect', async () => {
      await closeBrowser();
      return { status: 'disconnected' };
    }),
    flow_status: status,
    flow_doctor: () => tab((page) => runDoctor(page)),
    flow_capabilities: () => getCapabilities(),
    flow_generate_image: generateImage,
    flow_job_status: view,
    flow_wait: wait,
    flow_job_control: control,
    flow_list_runs: ({ limit = 20 }) => ({ runs: allRuns().slice(-Math.min(limit, 50)).reverse().map(runView) }),
    flow_open_project: onTab(handleOpenProject),
    flow_list_projects: onTab(handleListProjects),
    flow_rename_project: onTab(handleRenameProject),
    flow_delete_project(args) {
      if (args.confirm !== true) throw invalid('Deleting a Flow project is permanent. Call again with confirm: true once the owner has agreed.');
      return tab(() => handleDeleteProject(args));
    },
    flow_create_character: onTab(handleCreateCharacter),
    flow_list_characters: onTab(handleListCharacters),
    flow_import_character: onTab(handleImportCharacter),
    flow_create_scene: onTab(handleCreateScene),
    flow_list_scenes: onTab(handleListScenes),
    async flow_screenshot({ name = 'manual' }) {
      const page = session.peek();
      if (!page) throw createError(ErrorCodes.BROWSER_NOT_CONNECTED, 'Chrome is not connected');
      return { screenshot: await takeScreenshot(page, name.replace(/[^\w-]/g, '_').slice(0, 40)) };
    },
  };

  const known = new Set(TOOLS.map((t) => t.name));

  return async function call(tool, args = {}) {
    try {
      if (!known.has(tool)) throw invalid(`Unknown tool: ${String(tool).slice(0, 60)}`);
      const handler = handlers[tool];
      if (!handler) throw createError(ErrorCodes.NOT_IMPLEMENTED, `${tool} is not built yet`);
      return { ok: true, result: await handler(args) };
    } catch (err) {
      return toErrorPayload(err);
    }
  };
}
