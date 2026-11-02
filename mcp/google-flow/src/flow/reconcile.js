import fs from 'fs';
import path from 'path';
import { assetName } from '../engine/filenames.js';
import { get, getDataDir } from '../utils/config.js';
import { createError, ErrorCodes } from '../utils/errors.js';
import { downloadTake } from './clip.js';
import { downloadAsset } from './download.js';
import { baselineTiles, PERCENT, readTiles, tileOf } from './observe.js';
import { openProject } from './session.js';

const POLL_MS = 2000;
const VIDEO_SIZE = '720p';
const IMAGE_SIZE = '1K';

const clean = (text) => (text ?? '').replace(/\s+/g, ' ').trim();

// What sits above where the baseline's first visible tile now is must be new. Once the baseline has left the 28-tile window only the prompt can say, and a finished tile may by then show an auto-generated title instead: not found, never a guess.
export function matchTiles(tiles, { prompt, before, count }) {
  const known = new Set(before.ids);
  const request = clean(prompt);
  const anchor = tiles.findIndex(({ mediaId }) => known.has(mediaId));
  let fresh;
  if (anchor >= 0) fresh = tiles.slice(0, Math.max(0, anchor - before.slots.indexOf(tiles[anchor].mediaId)));
  else if (before.ids.length) fresh = tiles.filter(({ label, text }) => clean(label) === request || clean(text).includes(request));
  else fresh = tiles;
  const running = fresh.filter(({ mediaId, text }) => !mediaId && PERCENT.test(text));
  // Nearest the baseline: anything above it came later than this job.
  const assets = fresh.flatMap(({ mediaId }) => (mediaId && !known.has(mediaId) ? [mediaId] : [])).slice(-count);
  return { running, assets };
}

// A job past the credit line after a restart: did Flow make it? Waits out a tile still running. Spends nothing.
// shortcut: extend and edit results live on a clip page, not the grid, so they are reported as not found; upgrade by journaling the clip URL before Start.
export async function reconcile(page, job, signal) {
  const { before, projectUrl } = job.data;
  if (!before || !projectUrl || ['extend', 'edit'].includes(job.spec.mode)) return { found: false, assets: [] };
  await openProject(page, { project_url: projectUrl });
  await baselineTiles(page); // only to let the grid finish loading
  const timeoutMs = job.spec.kind === 'video' ? get('videoTimeoutMs', 900000) : get('generationTimeoutMs', 300000);
  const query = { prompt: job.spec.prompt, before, count: job.spec.count ?? 1 };
  // Live: a kill seconds after Start reopened a grid with no tile yet, and the clip appeared after.
  const noTileEnd = Date.now() + get('noTileTimeoutMs', 60000);
  for (const end = Date.now() + timeoutMs; ;) {
    signal?.throwIfAborted();
    const { running, assets } = matchTiles(await readTiles(page), query);
    const tooSoon = !running.length && !assets.length && Date.now() < noTileEnd;
    if (!tooSoon && (!running.length || assets.length >= query.count || Date.now() > end)) return { found: assets.length > 0, assets };
    await page.waitForTimeout(POLL_MS);
  }
}

// Only what the grid window shows, so an older asset can be missing here.
export async function listProjectAssets(page, projectUrl) {
  await openProject(page, { project_url: projectUrl });
  await baselineTiles(page);
  const tiles = await readTiles(page);
  return tiles.flatMap(({ mediaId, label }) => (mediaId ? [{ mediaId, label }] : []));
}

function fromGrid(page, mediaId, size, dest) {
  const tile = tileOf(page, mediaId);
  return tile.count().then((n) => {
    if (!n) {
      throw createError(ErrorCodes.DOWNLOAD_FAILED, `Asset is not in the project's visible grid: ${mediaId}`, {
        next_action: 'The grid shows only the newest 28 tiles. Download it in Flow by hand.',
      });
    }
    return downloadAsset(page, tile, { size, dest });
  });
}

// Repeats no generation. A silent job's copy is not stripped again.
export async function downloadAgain(page, job) {
  const { spec, data, run } = job;
  const media = data.media ?? data.outputs?.map(({ mediaId }) => mediaId) ?? [];
  if (!media.length) throw createError(ErrorCodes.INVALID_PARAMS, `Job ${job.id} has no result to download`);
  if (['extend', 'edit'].includes(spec.mode)) {
    await page.goto(media[0], { waitUntil: 'domcontentloaded', timeout: 60000 });
    return { files: [await downloadTake(page, job)] };
  }
  await openProject(page, data.projectUrl ? { project_url: data.projectUrl } : spec);
  const video = spec.kind === 'video';
  const dir = path.join(run.dir, video ? 'videos' : 'images');
  const dest = (ext) => assetName(run.jobs.indexOf(job) + 1, spec.prompt, 1, ext, dir);
  const files = [];
  for (const mediaId of media) files.push(await fromGrid(page, mediaId, video ? spec.resolution : spec.size, dest));
  return { files };
}

export async function downloadLatest(page, projectUrl) {
  if (projectUrl) await openProject(page, { project_url: projectUrl });
  else if (!page.url().includes('/project/')) throw createError(ErrorCodes.INVALID_PARAMS, 'No project is open: pass project_url');
  await baselineTiles(page);
  const latest = (await readTiles(page)).find(({ mediaId }) => mediaId);
  if (!latest) throw createError(ErrorCodes.DOWNLOAD_FAILED, 'The project shows no finished asset');
  const dir = path.join(getDataDir(), 'downloads');
  fs.mkdirSync(dir, { recursive: true });
  // A video's stand-in id is its URL; an image's is a bare media id.
  const size = latest.mediaId.startsWith('http') ? VIDEO_SIZE : IMAGE_SIZE;
  const file = await fromGrid(page, latest.mediaId, size, (ext) => assetName(1, latest.label ?? 'latest', 1, ext, dir));
  return { files: [file], mediaId: latest.mediaId };
}
