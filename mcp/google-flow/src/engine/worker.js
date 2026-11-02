import { closeBrowser, getBrowser, getPage, isBrowserConnected } from '../browser/connect.js';
import { launchFlowChrome } from '../browser/launch-profile.js';
import { detectBlock } from '../flow/blocks.js';
import { contract } from '../flow/contract.js';
import { runImageJob } from '../flow/image.js';
import { createError, ERROR_CLASSES, ErrorCodes, toErrorPayload } from '../utils/errors.js';
import { logger } from '../utils/logger.js';
import { takeScreenshot } from '../utils/screenshots.js';
import { allRuns, transition } from './job-store.js';
import { recordSpend } from './ledger.js';
import { withTab } from './tab-lock.js';

const FINISH = ['downloading', 'verifying', 'done'];
const RUNNABLE = ['queued', 'preparing', 'downloading']; // downloading only ever comes back as a retry of the download
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

export const flowAdapter = (job, ctx) => {
  if (job.spec.kind !== 'image') throw createError(ErrorCodes.NOT_IMPLEMENTED, `${job.spec.kind} jobs are not built yet`);
  return runImageJob(ctx, job);
};

// Spec 6.5: a failed generation retries by itself only within this allowance, since each retry spends.
const retriesAllowed = ({ spec }) => spec.max_generation_retries ?? (spec.kind === 'image' ? 1 : 0);

// Spending again can't help a refusal, or a tile that just failed the same way.
function shouldAutoRetry(job, { error_code: code, details }) {
  if (code !== ErrorCodes.FLOW_GENERATION_FAILED || (job.attempt ?? 1) > retriesAllowed(job)) return false;
  const text = details?.tile_text;
  if (!text) return true;
  return !new RegExp(contract.tile.noRetry, 'i').test(text) && !job.history?.some(({ error }) => error?.details?.tile_text === text);
}

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
      await page?.bringToFront().catch(() => {});
    } else if (kind === 'stop_run') {
      if (job.state !== 'queued') transition(job, 'paused', { error: payload });
      pause(code);
    } else {
      const retrying = shouldAutoRetry(job, payload);
      // Not journaled: flow_wait must not take this passing failed for the end of the job.
      Object.defineProperty(job, 'retrying', { value: retrying, configurable: true });
      transition(job, 'failed', { error: payload });
      if (STOPS_QUEUE.includes(code)) pause(code);
      // Through the store, so the attempt is counted and the ledger keys a new spend.
      if (retrying) transition(job, 'queued', undefined, { retry: true });
      Object.defineProperty(job, 'retrying', { value: false, configurable: true });
    }
  }

  // An adapter may still be clicking after its job ended, so the tab isn't handed on until
  // it stops. One that never stops holds the queue for the owner.
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
      get page() { return page; },
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
