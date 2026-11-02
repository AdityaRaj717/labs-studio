import { createHash } from 'crypto';
import fs from 'fs';
import path from 'path';
import { assetName } from '../engine/filenames.js';
import { jobEvents, transition } from '../engine/job-store.js';
import { recordBalance } from '../engine/ledger.js';
import { beat } from '../engine/pacer.js';
import { getBalance } from '../tools/flow-status.js';
import { createError, ErrorCodes, FlowError } from '../utils/errors.js';
import { logger } from '../utils/logger.js';
import { locate } from './contract.js';
import { downloadAsset, readAssetInfo } from './download.js';
import { addIngredient, chipCount } from './ingredients.js';
import { baselineTiles, observeGeneration, tileOf } from './observe.js';
import { openProject, resetSession, typePrompt } from './session.js';
import { applySettings } from './settings.js';
import { verifyImage } from './verify.js';

const DEFAULT_MAX_CREDITS = 30;
const START_ENABLED_MS = 10000;

const sentRequest = (spec) => spec.prompt.replace(/\s+/g, ' ').trim();

function failureOf({ status, text, error }) {
  if (status === 'blocked') return createError(error, text);
  if (status === 'timeout') return createError(ErrorCodes.GENERATION_TIMEOUT, error);
  return createError(ErrorCodes.FLOW_GENERATION_FAILED, `Flow failed the generation: ${text || 'no message shown'}`, { tile_text: text });
}

async function submit(ctx, quotedCredits) {
  const { page } = ctx;
  const start = locate(page, 'project.start');
  for (const end = Date.now() + START_ENABLED_MS; !await start.isEnabled();) {
    if (Date.now() > end) throw createError(ErrorCodes.GENERATION_BUTTON_DISABLED, 'Start generation stayed disabled');
    await page.waitForTimeout(250);
  }
  const before = await baselineTiles(page);
  ctx.submit(quotedCredits, before); // the credit line: durable before the click, and nothing but the click after it
  await start.click();
  return before;
}

// Saves each file before naming the next, so names never collide. A saved file survives a later failure.
async function saveAll(ctx, job, media, how) {
  const { page, signal } = ctx;
  const { spec } = job;
  const dir = path.join(job.run.dir, how.dir);
  const seq = job.run.jobs.indexOf(job) + 1;
  const outputs = [...(job.data.saved ?? [])];
  for (const mediaId of media) {
    if (outputs.some((out) => out.mediaId === mediaId)) continue;
    signal.throwIfAborted();
    const tile = tileOf(page, mediaId);
    const started = Date.now();
    const observed = await readAssetInfo(page, tile);
    let file;
    try {
      file = await downloadAsset(page, tile, { size: how.size(spec), signal, dest: (ext) => assetName(seq, spec.prompt, 1, ext, dir) });
    } catch (err) {
      if (err.code === ErrorCodes.DOWNLOAD_FAILED) err.details.saved = outputs;
      throw err;
    }
    outputs.push({
      file,
      mediaId,
      prompt: spec.prompt,
      request: sentRequest(spec),
      model: spec.model,
      observed,
      ratio: spec.ratio,
      count: spec.count,
      flowProjectUrl: page.url().split(/[?#]/)[0],
      quotedCredits: job.data.quotedCredits ?? 0,
      ...await how.check(file, spec, observed),
      downloadMs: Date.now() - started,
    });
    logger.info('Asset saved', { jobId: job.id, file });
  }
  return outputs;
}

function assertAsRequested(job, outputs, tileText) {
  const { count } = job.spec;
  const mismatches = outputs.flatMap((out) => out.mismatches);
  if (tileText) mismatches.push(`a tile failed: ${tileText}`);
  if (outputs.length !== count) mismatches.unshift(`count: ${outputs.length} of ${count} images`);
  if (mismatches.length) throw createError(ErrorCodes.RESULT_MISMATCH, `Result is not what was asked for: ${mismatches.join('; ')}`, { mismatches });
}

// Must not fail a job that already has its files.
export async function noteBalance(page) {
  const credits = await getBalance(page);
  if (credits === null) return;
  try {
    recordBalance(credits);
  } catch (err) {
    logger.warn('Balance not recorded', { error: err.message });
  }
}

async function finish(ctx, job, media, tileText, how) {
  const outputs = await saveAll(ctx, job, media, how);
  transition(job, 'verifying', { outputs, saved: null });
  assertAsRequested(job, outputs, tileText);
  await noteBalance(ctx.page);
  return { outputs };
}

async function generate(ctx, job, how) {
  const { page, signal } = ctx;
  const { spec } = job;
  const { quotedCredits } = await applySettings(page, how.settings(spec));
  const wanted = spec.ingredients?.length ?? 0;
  for (const item of spec.ingredients ?? []) {
    signal.throwIfAborted();
    await addIngredient(page, item);
    await beat(page);
  }
  await how.attachMore?.(page, spec, signal);
  const chips = await chipCount(page);
  if (chips !== wanted) {
    throw createError(ErrorCodes.UNKNOWN_UI_CHANGE, `${chips} ingredients are attached, the job has ${wanted}`, {
      next_action: 'Clear the chips in the Flow composer, then call resume.',
    });
  }
  await typePrompt(page, sentRequest(spec));
  await beat(page);

  const before = await submit(ctx, quotedCredits);
  transition(job, 'generating');
  const result = await observeGeneration(page, {
    before,
    count: spec.count,
    signal,
    timeoutMs: how.timeoutMs,
    previewDir: path.join(job.run.dir, 'diagnostics'),
    onUpdate(update) {
      job.progress = update;
      jobEvents.emit('event', { type: 'job.progress', runId: job.run.id, jobId: job.id, ...update });
    },
  });
  signal.throwIfAborted();
  // Some tiles finished and some failed: keep the good files and stop, since a retry would spend on the full count again.
  const partial = result.status === 'failed' && result.images.length > 0;
  if (result.status !== 'done' && !partial) throw failureOf(result);
  transition(job, 'downloading', { media: result.images, ...(partial ? { tileText: result.text || 'no message shown' } : {}) });
  return result.images;
}

export const sha256 = (file) => createHash('sha256').update(fs.readFileSync(file)).digest('hex');

const IMAGE = {
  dir: 'images',
  size: (spec) => spec.size,
  settings: (spec) => ({ ...spec, maxCredits: spec.max_credits ?? DEFAULT_MAX_CREDITS }),
  check: (file, spec, info) => ({
    size: spec.size,
    sha256: sha256(file),
    ...verifyImage(file, { ratio: spec.ratio, model: spec.model, info }),
  }),
};

export const runImageJob = (ctx, job) => runGeneration(ctx, job, IMAGE);

// A job already in downloading is a retry of the download alone, with no spend.
export async function runGeneration(ctx, job, how) {
  const { page } = ctx;
  try {
    await openProject(page, job.state === 'downloading' && job.data.projectUrl && !page.url().startsWith(job.data.projectUrl) ? { project_url: job.data.projectUrl } : job.spec);
    ctx.pinPage(page);
    await resetSession(page);
    const media = job.state === 'downloading' ? job.data.media : await generate(ctx, job, how);
    return await finish(ctx, job, media, job.data.tileText, how);
  } catch (err) {
    if (err instanceof FlowError || err.name !== 'TimeoutError') throw err;
    throw createError(ErrorCodes.UNKNOWN_UI_CHANGE, `Flow did not respond as expected: ${err.message.split('\n')[0]}`);
  }
}
