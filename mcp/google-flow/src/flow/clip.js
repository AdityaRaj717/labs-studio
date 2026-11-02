import fs from 'fs';
import path from 'path';
import { getCapabilities } from '../engine/capabilities.js';
import { assetName } from '../engine/filenames.js';
import { jobEvents, transition } from '../engine/job-store.js';
import { beat } from '../engine/pacer.js';
import { get } from '../utils/config.js';
import { createError, ErrorCodes, FlowError } from '../utils/errors.js';
import { logger } from '../utils/logger.js';
import { detectBlock } from './blocks.js';
import { locate } from './contract.js';
import { noteBalance, sha256 } from './image.js';
import { tileOf } from './observe.js';
import { openProject, resetSession } from './session.js';
import { probeVideo, stripAudio } from './silent.js';
import { verifyVideo } from './verify.js';

const POLL_MS = 2000;
const CHANGE_MS = 60000;
const SETTLE_MS = 2000;
const DOWNLOAD_MS = 300000; // a scene is exported first; 15s live for two clips
const MENU_MS = 1500;
// Clips overlap where they join: two 8s clips exported at 14.9s live.
const SCENE_MIN_SHARE = 0.85;
const PERCENT = /(\d+)%/;

const uiChange = (message) => createError(ErrorCodes.UNKNOWN_UI_CHANGE, message);
const VIEW = /\/(edit|scene)\/[^/?#]+/;

// Source is a clip's page URL, or a mediaId from an earlier output, whose tile must be in the project's grid.
async function openSource(page, source) {
  if (VIEW.test(source)) {
    await page.goto(source, { waitUntil: 'domcontentloaded', timeout: 60000 });
  } else {
    const tile = tileOf(page, source);
    if (!await tile.count()) throw createError(ErrorCodes.INVALID_PARAMS, `No clip with this id in the project's grid: ${source}`, { next_action: 'Pass the page URL of the clip (flowClipUrl of its output).' });
    await tile.locator('img[alt="Generated video thumbnail"], video').first().click();
  }
  await locate(page, 'editor.addClip').waitFor({ state: 'visible', timeout: 30000 }).catch(() => {
    throw uiChange('The clip page did not open: Add clip did not appear');
  });
}

// A finished timeline clip has its thumbnail strip; a pending one is a grey block with none.
const finishedClips = (page) => page.locator('flow-thumbnail-strip').evaluateAll((els) => els.filter((el) => el.querySelector('img[src]')).length);

async function type(page, box, text) {
  await box.click();
  await page.keyboard.insertText(text);
  await beat(page);
}

async function start(ctx, credits) {
  const button = locate(ctx.page, 'project.start');
  for (const end = Date.now() + 10000; !await button.isEnabled();) {
    if (Date.now() > end) throw createError(ErrorCodes.GENERATION_BUTTON_DISABLED, 'Start generation stayed disabled');
    await ctx.page.waitForTimeout(250);
  }
  ctx.submit(credits); // the credit line: durable before the click, and nothing but the click after it
  await button.click();
}

async function poll(ctx, job, timeoutMs, done) {
  const { page, signal } = ctx;
  for (const end = Date.now() + timeoutMs; ;) {
    signal.throwIfAborted();
    const block = await detectBlock(page).catch(() => null);
    if (block) throw createError(block.code, block.text);
    if (await done().catch((err) => { logger.debug('Clip not read', { error: err.message }); return false; })) return;
    if (Date.now() > end) throw createError(ErrorCodes.GENERATION_TIMEOUT, `Clip still not finished after ${Math.round(timeoutMs / 1000)}s`);
    await page.waitForTimeout(POLL_MS);
  }
}

async function extend(ctx, job, credits, timeoutMs) {
  const { page } = ctx;
  await locate(page, 'editor.addClip').click();
  await beat(page);
  const item = locate(page, 'editor.menu.extend');
  await item.waitFor({ state: 'visible', timeout: 10000 });
  // Disabled on Omni clips, and on a Veo clip whose newest version is an Omni edit.
  if (await item.getAttribute('aria-disabled') === 'true' || await item.isDisabled()) {
    throw createError(ErrorCodes.COMBINATION_NOT_SUPPORTED, 'Flow has Extend disabled for this clip: only Veo clips extend', { next_action: 'Pass a Veo clip that has no edited version.' });
  }
  await item.click();
  await beat(page);
  await type(page, locate(page, 'editor.extendPrompt'), job.spec.prompt);
  await page.waitForTimeout(SETTLE_MS);
  const before = await finishedClips(page);
  await start(ctx, credits);
  transition(job, 'generating');
  await poll(ctx, job, timeoutMs, async () => VIEW.test(page.url()) && await finishedClips(page) > before);
}

async function edit(ctx, job, credits, timeoutMs) {
  const { page } = ctx;
  await type(page, locate(page, 'editor.editPrompt'), job.spec.prompt);
  await start(ctx, credits);
  transition(job, 'generating');
  // Download media greys out while the new version runs, and the panel shows "n% <prompt>".
  const download = locate(page, 'editor.downloadMedia');
  await poll(ctx, job, CHANGE_MS, async () => !await download.isEnabled());
  let last = null;
  await poll(ctx, job, timeoutMs, async () => {
    const percent = PERCENT.exec(await page.getByText(/^\d+%/).first().innerText({ timeout: 500 }).catch(() => ''))?.[1];
    if (percent && percent !== last) {
      last = percent;
      job.progress = { progress: Number(percent), source: 'flow' };
      jobEvents.emit('event', { type: 'job.progress', runId: job.run.id, jobId: job.id, ...job.progress });
    }
    return !percent && await download.isEnabled();
  });
}

// One clip downloads at once or from a size menu; a scene exports, then downloads.
async function save(ctx, job, how) {
  const { page, signal } = ctx;
  const { spec } = job;
  signal.throwIfAborted();
  const started = page.waitForEvent('download', { timeout: DOWNLOAD_MS });
  let download;
  try {
    await locate(page, how === 'extend' ? 'editor.downloadScene' : 'editor.downloadMedia').click({ timeout: 15000 });
    const size = locate(page, `download.size.${spec.resolution}`);
    await size.waitFor({ state: 'visible', timeout: MENU_MS }).then(() => size.click()).catch(() => {});
    download = await started;
  } catch (err) {
    started.catch(() => {});
    throw createError(ErrorCodes.DOWNLOAD_FAILED, `Download failed: ${err.message.split('\n')[0]}`);
  }
  const dir = path.join(job.run.dir, 'videos');
  const file = assetName(job.run.jobs.indexOf(job) + 1, spec.prompt, 1, path.extname(download.suggestedFilename()) || '.mp4', dir);
  await download.saveAs(`${file}.part`);
  fs.renameSync(`${file}.part`, file);
  return file;
}

async function totalSeconds(page) {
  const text = await page.getByText(/^Total duration:/).first().innerText({ timeout: 5000 }).catch(() => '');
  // Reads 00:24:00 for 24 seconds: minutes, seconds, frames.
  const match = /(\d+):(\d+):\d+/.exec(text);
  return match ? Number(match[1]) * 60 + Number(match[2]) : null;
}

async function check(page, job, file) {
  const { spec } = job;
  const silent = spec.silent ? await stripAudio(file) : null;
  const probe = await probeVideo(file);
  const { mismatches, ...rest } = verifyVideo(probe, { ratio: spec.ratio, silent: spec.silent });
  const total = await totalSeconds(page);
  if (spec.mode === 'extend' && total && probe.duration < total * SCENE_MIN_SHARE) mismatches.push(`duration ${probe.duration}s is short of the scene's ${total}s`);
  return { ...rest, ok: mismatches.length === 0, mismatches, ...(silent ? { original: silent.original } : {}), scene_seconds: total };
}

// Saves the clip page already open, with no spend.
export const downloadTake = (page, job) => save({ page, signal: new AbortController().signal }, job, job.spec.mode);

export async function runClipJob(ctx, job) {
  const { page } = ctx;
  const { spec } = job;
  const { models } = getCapabilities().video;
  const credits = spec.mode === 'edit' ? models[spec.model].editCredits : models[spec.model].credits[spec.resolution][spec.duration];
  const maxCredits = spec.max_credits ?? credits;
  try {
    if (credits > maxCredits) throw createError(ErrorCodes.BUDGET_EXCEEDED, `${credits} credits is above max_credits ${maxCredits}`);
    if (job.state === 'downloading') {
      await page.goto(job.data.media[0], { waitUntil: 'domcontentloaded', timeout: 60000 });
      ctx.pinPage(page);
    } else {
      await openProject(page, spec);
      ctx.pinPage(page);
      await resetSession(page);
      await openSource(page, spec.extend_from ?? spec.edit_from);
      await (spec.mode === 'extend' ? extend : edit)(ctx, job, credits, get('videoTimeoutMs', 900000));
      await page.waitForTimeout(SETTLE_MS);
      transition(job, 'downloading', { media: [page.url().split(/[?#]/)[0]] });
    }
    const file = await save(ctx, job, spec.mode);
    const result = await check(page, job, file);
    const flowClipUrl = page.url().split(/[?#]/)[0];
    const outputs = [{
      file,
      mediaId: flowClipUrl,
      flowClipUrl,
      prompt: spec.prompt,
      request: spec.prompt,
      model: spec.model,
      ratio: spec.ratio,
      count: 1,
      flowProjectUrl: flowClipUrl.replace(VIEW, ''),
      quotedCredits: job.data.quotedCredits ?? credits,
      sha256: sha256(file),
      ...result,
    }];
    transition(job, 'verifying', { outputs });
    if (result.mismatches.length) throw createError(ErrorCodes.RESULT_MISMATCH, `Result is not what was asked for: ${result.mismatches.join('; ')}`, { mismatches: result.mismatches });
    await noteBalance(page);
    return { outputs };
  } catch (err) {
    if (err instanceof FlowError || err.name !== 'TimeoutError') throw err;
    throw uiChange(`Flow did not respond as expected: ${err.message.split('\n')[0]}`);
  }
}
