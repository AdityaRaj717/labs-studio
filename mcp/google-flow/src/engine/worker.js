import { closeBrowser, getBrowser, getPage, isBrowserConnected } from '../browser/connect.js';
import { launchFlowChrome } from '../browser/launch-profile.js';
import { detectBlock } from '../flow/blocks.js';
import { handleGenerateImage } from '../tools/generate-image.js';
import { createError, ERROR_CLASSES, ErrorCodes, toErrorPayload } from '../utils/errors.js';
import { logger } from '../utils/logger.js';
import { takeScreenshot } from '../utils/screenshots.js';
import { allRuns, transition } from './job-store.js';
import { recordSpend } from './ledger.js';
import { withTab } from './tab-lock.js';

const FINISH = ['downloading', 'verifying', 'done'];
const RUNNABLE = ['queued', 'preparing'];
// Someone else moved or closed the tab: going on would fail every job or save the wrong one.
const STOPS_QUEUE = [ErrorCodes.BROWSER_NOT_CONNECTED, ErrorCodes.FLOW_PAGE_NOT_FOUND];
const SETTLE_MS = 600000;
const BLOCK_CHECK_MS = 5000;

const projectId = (url) => /\/project\/([^/?#]+)/.exec(url)?.[1] ?? null;

// The engine owns Chrome: it attaches, or launches on the configured port and profile.
export const chromeSession = {
  peek: () => (isBrowserConnected() ? getPage() : null),
  async ensure() {
    if (isBrowserConnected() && getBrowser()?.isConnected() === false) await closeBrowser();
    try {
      if (!isBrowserConnected()) await launchFlowChrome();
      return { browser: getBrowser(), page: getPage() };
    } catch (err) {
      throw err.code === ErrorCodes.BROWSER_NOT_CONNECTED
        ? err
        : createError(ErrorCodes.BROWSER_NOT_CONNECTED, `Could not attach to Chrome: ${err.message}`);
    }
  },
};

const LEGACY_MODELS = { banana21: 'Nano Banana 2.1', bananaPro: 'Nano Banana Pro', banana2Lite: 'Nano Banana 2 Lite' };

// shortcut: the old image flow clicks Start inside one call, so the credit line is written before it and a failure
// before the click still reads credits_at_risk. Task 9 replaces this with the direct composer.
export const createLegacyAdapter = (generate) => async (job, ctx) => {
  const { spec } = job;
  if (spec.kind !== 'image') throw createError(ErrorCodes.NOT_IMPLEMENTED, `${spec.kind} jobs are not built yet`);
  const pick = (key) => spec.ingredients.flatMap((item) => (item?.[key] ? [item[key]] : []));
  ctx.submit(0);
  const result = await generate({
    prompt: spec.prompt,
    model: LEGACY_MODELS[spec.model],
    ratio: spec.ratio,
    count: spec.count,
    download_size: spec.size,
    auto_confirm: true,
    reference_images: spec.ingredients.flatMap((item) => (typeof item === 'string' ? [item] : item?.file ? [item.file] : [])),
    characters: pick('character'),
    scenes: pick('scene'),
    project_url: spec.project_url,
    project_name: spec.project_name,
    output_folder: `${job.run.dir}/images`,
    wait_for_run: true,
    onProjectOpen: ctx.pinPage,
  });
  if (result.status !== 'success') throw createError(ErrorCodes.GENERATION_TIMEOUT, `Image job ended as ${result.status}`);
  return { outputs: result.files ?? [] };
};

export const legacyAdapter = createLegacyAdapter(handleGenerateImage);

export function createWorker({ adapter, session, pacer, settleMs = SETTLE_MS }) {
  let paused = null;
  let current = null;
  let controller = null;
  let looping = false;
  let stopped = false;
  let unsettled = false; // an adapter outlived its wait and may still be clicking

  const pause = (reason) => {
    paused = reason;
    logger.warn('Queue paused', { event: 'queue_paused', reason });
  };

  const nextJob = () => allRuns().flatMap((run) => run.jobs)
    .filter((job) => RUNNABLE.includes(job.state))
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt))[0];

  async function failureOf(err, page) {
    if (!page || err.code === ErrorCodes.BROWSER_NOT_CONNECTED) return { error: err };
    const timeout = new Promise((resolve) => { setTimeout(resolve, BLOCK_CHECK_MS, null).unref(); });
    const block = await Promise.race([detectBlock(page), timeout]).catch(() => null);
    return {
      error: block ? createError(block.code, block.text) : err,
      screenshot: await takeScreenshot(page, 'job-failed'),
    };
  }

  async function settle(job, err, page) {
    const { error, screenshot } = await failureOf(err, page);
    const payload = toErrorPayload(error);
    payload.credits_at_risk ||= Boolean(job.submittedAt);
    payload.screenshot = screenshot ?? null;
    const { error_code: code } = payload;
    const kind = ERROR_CLASSES[code].class;
    logger.warn('Job stopped', { event: 'job_stopped', jobId: job.id, runId: job.run.id, code, kind, creditsAtRisk: payload.credits_at_risk });
    if (kind === 'owner') {
      transition(job, 'needs_user', { error: payload });
      pause(code);
    } else if (kind === 'stop_run') {
      if (job.state !== 'queued') transition(job, 'paused', { error: payload });
      pause(code);
    } else {
      transition(job, 'failed', { error: payload });
      if (STOPS_QUEUE.includes(code)) pause(code);
    }
  }

  // The old flow takes no signal and may still be clicking after its job ended, so the tab
  // isn't handed on until it stops. One that never stops holds the queue for the owner.
  async function waitForAdapter(running) {
    let timer;
    const expired = new Promise((resolve) => {
      timer = setTimeout(resolve, settleMs, true);
      timer.unref();
    });
    const stuck = await Promise.race([running.then(() => false, () => false), expired]);
    clearTimeout(timer);
    if (!stuck) return;
    unsettled = true;
    running.then(() => { unsettled = false; }, () => { unsettled = false; });
    pause(ErrorCodes.INTERNAL_ERROR);
  }

  async function runOne(job) {
    current = job;
    const control = new AbortController();
    controller = control;
    const { signal } = control;
    const cleanups = [];
    let page = null;
    let running = null;
    let interrupt;
    const interrupted = new Promise((_, reject) => { interrupt = reject; });
    // stop and cancel; a lost or moved tab rejects with its own error first.
    signal.addEventListener('abort', () => interrupt(signal.reason));
    const lose = (error) => {
      interrupt(error);
      control.abort(error);
    };

    const ctx = {
      signal,
      // Durable before return: call right before clicking Start.
      submit(credits = 0) {
        if (signal.aborted) throw createError(ErrorCodes.INTERNAL_ERROR, 'Job was stopped; Start must not be clicked');
        transition(job, 'submitted', { quotedCredits: credits });
        pacer.recordUse();
        recordSpend(job, credits);
      },
      // After this, leaving this project fails the job rather than saving another project's result.
      pinPage(pinned) {
        const home = projectId(pinned.url());
        const onMove = (frame) => {
          if (frame !== pinned.mainFrame() || projectId(frame.url()) === home) return;
          const { origin, pathname } = new URL(frame.url());
          lose(createError(ErrorCodes.FLOW_PAGE_NOT_FOUND, `The Flow tab moved away from project ${home} to ${origin}${pathname} while the job ran`, {
            next_action: 'Leave the Flow tab alone while a job runs, reopen the project, then call resume and retry_failed.',
          }));
        };
        pinned.on('framenavigated', onMove);
        cleanups.push(() => pinned.off('framenavigated', onMove));
      },
    };

    const watchChrome = (browser, tab) => {
      const lost = () => lose(createError(ErrorCodes.BROWSER_NOT_CONNECTED, 'Chrome or the Flow tab closed while the job ran'));
      browser?.once('disconnected', lost);
      tab?.once('close', lost);
      cleanups.push(() => { browser?.off('disconnected', lost); tab?.off('close', lost); });
    };

    try {
      await Promise.race([pacer.waitTurn(signal), interrupted]);
      await withTab(job.id, async () => {
        const open = await session.ensure();
        page = open.page;
        watchChrome(open.browser, open.page);
        if (job.state === 'queued') transition(job, 'preparing');
        running = adapter(job, ctx);
        const result = await Promise.race([running, interrupted]);
        if (!job.submittedAt) throw createError(ErrorCodes.INTERNAL_ERROR, 'The job ended without reaching Flow');
        const steps = FINISH.slice(FINISH.indexOf(job.state) + 1);
        steps.forEach((state, i) => transition(job, state, i === steps.length - 1 ? { outputs: result?.outputs ?? [] } : undefined));
        logger.info('Job done', { event: 'job_done', jobId: job.id, runId: job.run.id });
      });
    } catch (err) {
      if (signal.reason === 'stop') return; // the journal keeps the state for the next engine
      if (signal.reason === 'cancel') {
        transition(job, 'cancelled', { credits_at_risk: Boolean(job.submittedAt) });
        return;
      }
      await settle(job, signal.reason ?? err, page);
    } finally {
      cleanups.forEach((fn) => fn());
      if (!signal.aborted) control.abort('done'); // the adapter's listeners must not outlive the job
      if (running && !stopped) await waitForAdapter(running);
      current = null;
      controller = null;
    }
  }

  async function loop() {
    for (let job; !stopped && !paused && (job = nextJob());) {
      try {
        await runOne(job);
      } catch (err) {
        // The journal refused the failure record too: don't spin on the same job.
        logger.error('Worker could not record a job', { event: 'worker_error', jobId: job.id, error: err.message });
        pause(ErrorCodes.INTERNAL_ERROR);
      }
    }
  }

  function kick() {
    if (looping || stopped) return;
    looping = true;
    loop().finally(() => {
      looping = false;
    });
  }

  return {
    kick,
    pause,
    assertSettled() {
      if (!unsettled) return;
      throw createError(ErrorCodes.JOB_IN_PROGRESS, 'The previous job\'s handler has not stopped, so another job could spend on the same tab', {
        next_action: 'It is still running: check the Flow tab, wait for it to end, or close Chrome to end it, then call resume.',
      });
    },
    resume() {
      this.assertSettled();
      paused = null;
      kick();
    },
    status: () => ({ paused, active: current?.id ?? null }),
    isActive: (job) => current === job,
    busy: () => current !== null || unsettled,
    cancelActive() { controller?.abort('cancel'); },
    stop() {
      stopped = true;
      controller?.abort('stop');
    },
  };
}
