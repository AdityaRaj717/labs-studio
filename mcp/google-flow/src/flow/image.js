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
  ctx.submit(quotedCredits); // the credit line: durable before the click, and nothing but the click after it
  await start.click();
  return before;
}

// Saves each file before naming the next, so names never collide. A saved file survives a later failure.
async function saveAll(ctx, job, media) {
  const { page, signal } = ctx;
  const { spec } = job;
  const dir = path.join(job.run.dir, 'images');
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
      file = await downloadAsset(page, tile, { size: spec.size, signal, dest: (ext) => assetName(seq, spec.prompt, 1, ext, dir) });
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
      size: spec.size,
      flowProjectUrl: page.url().split(/[?#]/)[0],
      quotedCredits: job.data.quotedCredits ?? 0,
      sha256: createHash('sha256').update(fs.readFileSync(file)).digest('hex'),
      ...verifyImage(file, { ratio: spec.ratio, model: spec.model, info: observed }),
      downloadMs: Date.now() - started,
    });
    logger.info('Image saved', { jobId: job.id, file });
  }
  return outputs;
}

function assertAsRequested(job, outputs) {
  const { count } = job.spec;
  const mismatches = outputs.flatMap((out) => out.mismatches);
  if (outputs.length !== count) mismatches.unshift(`count: ${outputs.length} of ${count} images`);
  if (mismatches.length) throw createError(ErrorCodes.RESULT_MISMATCH, `Result is not what was asked for: ${mismatches.join('; ')}`, { mismatches });
}

// Must not fail a job that already has its files.
async function noteBalance(page) {
  const credits = await getBalance(page);
  if (credits === null) return;
  try {
    recordBalance(credits);
  } catch (err) {
    logger.warn('Balance not recorded', { error: err.message });
  }
}

async function finish(ctx, job, media) {
  const outputs = await saveAll(ctx, job, media);
  transition(job, 'verifying', { outputs, saved: null });
  assertAsRequested(job, outputs);
  await noteBalance(ctx.page);
  return { outputs };
}

async function generate(ctx, job) {
  const { page, signal } = ctx;
  const { spec } = job;
  const { quotedCredits } = await applySettings(page, { ...spec, maxCredits: spec.max_credits ?? DEFAULT_MAX_CREDITS });
  const wanted = spec.ingredients?.length ?? 0;
  for (const item of spec.ingredients ?? []) {
    signal.throwIfAborted();
    await addIngredient(page, item);
    await beat(page);
  }
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
    previewDir: path.join(job.run.dir, 'diagnostics'),
    onUpdate(update) {
      job.progress = update;
      jobEvents.emit('event', { type: 'job.progress', runId: job.run.id, jobId: job.id, ...update });
    },
  });
  signal.throwIfAborted();
  if (result.status !== 'done') throw failureOf(result);
  transition(job, 'downloading', { media: result.images });
  return result.images;
}

// A job already in downloading is a retry of the download alone, with no spend.
export async function runImageJob(ctx, job) {
  const { page } = ctx;
  try {
    await openProject(page, job.spec);
    ctx.pinPage(page);
    await resetSession(page);
    const media = job.state === 'downloading' ? job.data.media : await generate(ctx, job);
    return await finish(ctx, job, media);
  } catch (err) {
    if (err instanceof FlowError || err.name !== 'TimeoutError') throw err;
    throw createError(ErrorCodes.UNKNOWN_UI_CHANGE, `Flow did not respond as expected: ${err.message.split('\n')[0]}`);
  }
}
