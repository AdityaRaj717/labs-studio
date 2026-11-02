import { createFish } from '../audio/fish.js';
import { createStable } from '../audio/stable.js';
import { lastFrame, stitchVideo } from './stitch.js';
import { closeBrowser } from '../browser/connect.js';
import config from '../utils/config.js';
import { readAccountStatus } from '../browser/account-check.js';
import { navigateToFlow } from '../browser/launch-profile.js';
import { downloadAgain, downloadLatest, listProjectAssets } from '../flow/reconcile.js';
import { handleCreateCharacter, handleListCharacters } from '../tools/create-character.js';
import { handleCreateScene, handleListScenes } from '../tools/create-scene.js';
import { runDoctor } from '../tools/doctor.js';
import { handleFlowStatus } from '../tools/flow-status.js';
import { handleImportCharacter } from '../tools/import-character.js';
import { handleDeleteProject, handleListProjects, handleOpenProject, handleRenameProject } from '../tools/open-project.js';
import { verifyAccount } from '../browser/account-check.js';
import { checkFfmpeg } from '../flow/silent.js';
import { createOrchestrator } from '../production/orchestrator.js';
import { buildPlan } from '../production/plan.js';
import { getBalance } from '../tools/flow-status.js';
import { TOOLS } from '../shim/tools.js';
import { createError, ERROR_CLASSES, ErrorCodes, toErrorPayload } from '../utils/errors.js';
import { takeScreenshot } from '../utils/screenshots.js';
import { startBatch, validateJob } from './batch.js';
import { checkBudget, estimate } from './budget.js';
import { getCapabilities } from './capabilities.js';
import { allRuns, enqueue, jobByKey, transition } from './job-store.js';
import * as ledger from './ledger.js';
import { createRun } from './run-folder.js';
import { withTab } from './tab-lock.js';
import { validateImage, validateVideo } from './validate.js';

// The app's own calls, not listed to agents: an agent has no business moving the cap.
const APP_ONLY = ['flow_bring_to_front', 'flow_set_pacing'];
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

export function createRpc({ worker, session, hub, getSecret = (name) => process.env[name] }) {
  const fish = createFish({ getSecret });
  const stable = createStable({ getSecret });
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
    const owned = args.run_id && orchestrator.forRun(args.run_id);
    // A Production goes on after each job, so it is finished only when nothing more will run by itself.
    const finished = () => (owned
      ? orchestrator.summaryOf(args.run_id).status !== 'running'
      : jobs.every((job) => SETTLED.includes(job.state) && !job.retrying));
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
    return { ...view(args), finished: finished(), ...(paused ? { paused } : {}), ...queuePaused(), ...(owned ? { production: orchestrator.summaryOf(args.run_id) } : {}) };
  }

  const queueGeneration = (validateJob) => (args) => {
    const { auto_confirm, max_credits, idempotency_key, output_root, ...request } = args;
    // First: a repeat must return its job whatever the budget says now.
    const first = auto_confirm === true && idempotency_key && jobByKey(idempotency_key);
    if (first) return { job_id: first.id, run_id: first.run.id, state: first.state, repeated: true, ...queuePaused() };
    const spec = validateJob(request);
    const estimated = estimate([spec]);
    if (auto_confirm !== true) return { status: 'ready_for_confirmation', estimate: estimated, request: { ...spec, prompt: cut(spec.prompt) } };
    checkBudget(estimated, max_credits, ledger);
    const run = createRun({ name: spec.prompt, outputRoot: output_root, flowProjectUrl: spec.project_url });
    const job = enqueue(run, { ...spec, max_credits }, idempotency_key);
    worker.kick();
    return { job_id: job.id, run_id: run.id, state: job.state, estimate: estimated, ...queuePaused() };
  };

  // A held job past the credit line lost its watcher, so it is looked for rather than run again.
  function resumeJob(job) {
    transition(job, job.heldFrom);
    if (job.submittedAt) worker.adopt([job]);
  }

  const downloadOnly = ({ data: { error, media } }) => error?.error_code === ErrorCodes.DOWNLOAD_FAILED && Boolean(media);

  // Spec 6.1: a download or disk failure retries the download only, never the generation.
  function retryJob(job) {
    if (downloadOnly(job)) transition(job, 'downloading', { error: null, saved: job.data.error.details?.saved ?? [] });
    else transition(job, 'queued', undefined, { retry: true });
  }

  function control({ action, job_id, run_id, max_credits, accept_quote }) {
    if (action === 'resume' || action === 'retry_failed') worker.assertSettled(); // before any job moves
    if (run_id && orchestrator.forRun(run_id) && action === 'set_budget') {
      const production = orchestrator.setBudget({ run_id, max_credits });
      worker.resume();
      return { action, production, ...worker.status() };
    }
    if (run_id && orchestrator.forRun(run_id) && action === 'retry_failed') {
      return orchestrator.retryFailed(run_id).then((result) => {
        worker.resume();
        return { action, ...result, ...worker.status() };
      });
    }
    if (action === 'resume' && !job_id && !run_id) {
      const productions_resumed = orchestrator.resumeAll();
      worker.resume();
      return { ...worker.status(), productions_resumed };
    }
    const jobs = targetOf({ job_id, run_id });
    // The Take is what spends and reviews: a job moved under it would go unseen.
    if (action === 'retry_failed' && job_id && jobs[0].idempotencyKey?.startsWith('prod:')) throw invalid('This job belongs to a Production: use flow_production_regenerate');
    if (run_id && orchestrator.forRun(run_id)) {
      if (action === 'pause') orchestrator.hold(run_id);
      if (action === 'resume') orchestrator.resume(run_id, { accept_quote });
      if (action === 'cancel') orchestrator.cancel(run_id);
    }
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
        // Its credits are spent and the file is on its way: let the download finish.
        if (worker.isActive(job)) { if (!['downloading', 'verifying'].includes(job.state)) worker.cancelActive(); }
        else transition(job, 'cancelled');
      }
    } else if (action === 'retry_failed') {
      changed = pick(['failed']);
      checkBudget(estimate(changed.filter((job) => !downloadOnly(job)).map((job) => job.spec)), max_credits, ledger);
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

  const orchestrator = createOrchestrator({
    jobs: { kick: () => worker.kick() },
    flow: {
      // Doctor needs a project page, so the project opens first: a refusal here can leave an empty new project.
      preflight: ({ needsVideo, project_url, name }) => tab(async (page) => {
        if (needsVideo) await checkFfmpeg();
        const { url } = await handleOpenProject(project_url ? { url: project_url, create_if_missing: false } : { name, create_if_missing: true });
        await verifyAccount(page);
        const doctor = await runDoctor(page);
        if (!doctor.ok) throw createError(ErrorCodes.UNKNOWN_UI_CHANGE, `Flow's page no longer matches the contract: ${doctor.missing.map(({ key }) => key).join(', ')}`, { missing: doctor.missing });
        return { balance: await getBalance(page), project_url: url };
      }),
      createCharacter: (args) => tab(() => handleCreateCharacter(args)),
    },
  });

  function estimateJobs({ jobs }) {
    if (!Array.isArray(jobs) || jobs.length === 0) throw invalid('jobs must be a non-empty list');
    return estimate(jobs.map(validateJob));
  }

  const handlers = {
    flow_estimate: estimateJobs,
    audio_voice_generate: (args) => fish.generate(args),
    audio_voice_list: (args) => fish.list(args),
    audio_stable_generate: (args) => stable.generate(args),
    stitch_video: stitchVideo,
    last_frame: lastFrame,
    flow_production_plan: buildPlan,
    flow_production_start: (args) => orchestrator.start(args),
    flow_production_status: (args) => orchestrator.status(args),
    flow_production_review: (args) => orchestrator.review(args),
    flow_production_regenerate: (args) => orchestrator.regenerate(args),
    flow_batch_start(args) {
      const started = startBatch(args, ledger);
      if (started.run_id) worker.kick();
      return { ...started, ...queuePaused() };
    },
    flow_list_assets(args) {
      if (args.project_url) return tab(async (page) => ({ assets: await listProjectAssets(page, args.project_url), note: 'Only the grid window shows here: the newest 28 tiles.' }));
      const assets = targetOf(args).flatMap((job) => (job.data.outputs ?? []).map(({ file, mediaId, model }) => ({ job_id: job.id, prompt: cut(job.spec.prompt, 80), file, mediaId, model })));
      return { assets };
    },
    flow_download({ job_id, latest, project_url }) {
      if (latest === true) return tab((page) => downloadLatest(page, project_url));
      if (!job_id) throw invalid('Pass job_id, or latest: true');
      const job = findJob(job_id);
      return tab((page) => downloadAgain(page, job));
    },
    flow_connect: connect,
    flow_disconnect: () => withTab('disconnect', async () => {
      await closeBrowser();
      return { status: 'disconnected' };
    }),
    flow_status: status,
    flow_doctor: () => tab((page) => runDoctor(page)),
    flow_capabilities: () => getCapabilities(),
    flow_generate_image: queueGeneration(validateImage),
    flow_generate_video: queueGeneration(validateVideo),
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
    // Never waits on the tab lock: the owner must see a block while a job holds the tab.
    async flow_bring_to_front() {
      const page = session.peek() ?? (await session.ensure()).page;
      if (!page) throw createError(ErrorCodes.BROWSER_NOT_CONNECTED, 'Chrome is not connected');
      try {
        const cdp = await page.context().newCDPSession(page);
        const { windowId } = await cdp.send('Browser.getWindowForTarget');
        await cdp.send('Browser.setWindowBounds', { windowId, bounds: { windowState: 'normal' } });
        await cdp.detach();
      } catch { /* some window managers refuse; focusing the tab still helps */ }
      await page.bringToFront();
      return { status: 'ok' };
    },
    flow_set_pacing({ dailyCap, minGapMs, maxGapMs }) {
      if (![dailyCap, minGapMs, maxGapMs].every((n) => Number.isFinite(n) && n >= 0) || minGapMs > maxGapMs) throw invalid('dailyCap, minGapMs and maxGapMs must be numbers, with min <= max');
      Object.assign(config, { dailyCap, minGapMs, maxGapMs });
      return { dailyCap, minGapMs, maxGapMs };
    },
    async flow_screenshot({ name = 'manual' }) {
      const page = session.peek();
      if (!page) throw createError(ErrorCodes.BROWSER_NOT_CONNECTED, 'Chrome is not connected');
      return { screenshot: await takeScreenshot(page, name.replace(/[^\w-]/g, '_').slice(0, 40)) };
    },
  };

  const known = new Set([...TOOLS.map((t) => t.name), ...APP_ONLY]);

  async function call(tool, args = {}) {
    try {
      if (!known.has(tool)) throw invalid(`Unknown tool: ${String(tool).slice(0, 60)}`);
      const handler = handlers[tool];
      if (!handler) throw createError(ErrorCodes.NOT_IMPLEMENTED, `${tool} is not built yet`);
      return { ok: true, result: await handler(args) };
    } catch (err) {
      return toErrorPayload(err);
    }
  }
  call.orchestrator = orchestrator;
  return call;
}
