import path from 'path';
import { get } from '../utils/config.js';
import { logger } from '../utils/logger.js';
import { detectBlock } from './blocks.js';
import { contract, locate } from './contract.js';

const POLL_MS = 1000;
const NOT_RUNNING_POLLS = 3; // a tile can flip through an empty frame on its way to done
const PREVIEW_MS = 10000;
// Live tiles read "image 97% <prompt>" or "play_circle 3% <prompt>": the kind word or icon ligature first.
const PERCENT = /^\s*(?:[a-z_]+\s+)?(\d+)%/i;
const SETTLE_POLL_MS = 500;
const SETTLE_MAX_MS = 5000;

const css = (key) => contract.keys[key].css;

// A resting video has no media id, so its URL stands in. The thumbnail and video element URLs share only their start, so that start is the id. A running tile is never finished, whatever it shows.
function readTiles(page) {
  return locate(page, 'project.tile').evaluateAll((els, { character, image, video, percent }) => els
    .filter((el) => !el.querySelector(character)) // saved Characters sit among the results
    .map((el) => {
      const text = el.innerText.trim();
      const id = el.querySelector(image)?.getAttribute('data-media-id') ?? el.querySelector(video)?.getAttribute('src')?.slice(0, 90) ?? null;
      return { label: el.getAttribute('aria-label'), mediaId: new RegExp(percent, 'i').test(text) ? null : id, text };
    }), { character: css('tile.character'), image: css('tile.image'), video: css('tile.video'), percent: PERCENT.source });
}

const mediaIds = (tiles) => tiles.flatMap(({ mediaId }) => (mediaId ? [mediaId] : []));

// Taken right before Start, once the grid stops changing: anything finished now is not a result of this job.
export async function baselineTiles(page) {
  let tiles = await readTiles(page);
  let ids = mediaIds(tiles);
  for (const end = Date.now() + SETTLE_MAX_MS; Date.now() < end;) {
    await page.waitForTimeout(SETTLE_POLL_MS);
    tiles = await readTiles(page);
    const next = mediaIds(tiles);
    const same = next.length === ids.length && next.every((id, i) => id === ids[i]);
    ids = next;
    if (same) break;
  }
  return { ids, firstIndex: tiles.findIndex(({ mediaId }) => mediaId) };
}

export const tileOf = (page, mediaId) => locate(page, 'project.tile')
  .filter({ has: page.locator(`[data-media-id=${JSON.stringify(mediaId)}], [src^=${JSON.stringify(mediaId)}]`) }).first();

async function savePreview(page, mediaId, dir) {
  const file = path.join(dir, `preview-${mediaId.slice(0, 40).replace(/[^\w-]/g, '_')}.png`);
  try {
    await tileOf(page, mediaId).screenshot({ path: file, timeout: PREVIEW_MS });
    return file;
  } catch (err) {
    logger.debug('Preview not saved', { error: err.message });
    return null;
  }
}

// Tiles are the only truth in direct mode. Ends on done, a failed tile, a block, or a timeout; never throws for those.
export async function observeGeneration(page, { before, count, previewDir, onUpdate, signal, timeoutMs = get('generationTimeoutMs', 300000) }) {
  const known = new Set(before.ids);
  const started = Date.now();
  const noTileMs = get('noTileTimeoutMs', 60000);
  const graceMs = get('shortResultGraceMs', 20000);
  const runningLabels = new Set();
  let peak = 0;
  let idlePolls = 0;
  let idleSince = null;
  let lastPercent = null;
  let previewed = false;

  while (!signal?.aborted) {
    let tiles;
    let block;
    try {
      block = await detectBlock(page);
      tiles = block ? [] : await readTiles(page);
    } catch (err) {
      // A navigation destroys the context mid-read. The worker's guard judges a move; a reload just reads again.
      logger.debug('Tiles not read', { error: err.message });
      if (Date.now() - started >= timeoutMs) return { status: 'timeout', images: [], text: '', error: `Tiles unreadable for ${Math.round(timeoutMs / 1000)}s` };
      await page.waitForTimeout(POLL_MS);
      continue;
    }
    if (block) return { status: 'blocked', images: [], text: block.text, error: block.code };

    const running = tiles.filter(({ mediaId, text }) => !mediaId && PERCENT.test(text));
    running.forEach(({ label }) => runningLabels.add(label));
    peak = Math.max(peak, running.length);
    // The grid is a fixed window, so its length says nothing. New results push the first known tile down by exactly their number.
    // Ids alone can't say: a video tile may have shown no URL at the baseline (live: saved the wrong clip).
    const firstKnown = tiles.findIndex(({ mediaId }) => known.has(mediaId));
    const candidates = firstKnown < 0 ? tiles : tiles.slice(0, Math.max(0, firstKnown - Math.max(0, before.firstIndex)));
    const images = mediaIds(candidates).filter((id) => !known.has(id)).slice(0, count);

    const percent = running.length ? Number(PERCENT.exec(running[0].text)[1]) : null;
    let previewPath = null;
    if (images.length && !previewed && previewDir) {
      previewed = true;
      previewPath = await savePreview(page, images[0], previewDir);
    }
    if ((percent !== null && percent !== lastPercent) || previewPath) {
      lastPercent = percent ?? lastPercent;
      onUpdate?.({ progress: lastPercent, source: 'flow', ...(previewPath ? { previewPath } : {}) });
    }

    if (images.length >= count) return { status: 'done', images, text: '' };
    if (running.length) {
      idlePolls = 0;
      idleSince = null;
    } else if (images.length || peak) {
      idlePolls++;
      idleSince ??= Date.now();
      // A tile left the running state with no media: failed, with its text kept.
      if (images.length < peak && idlePolls >= NOT_RUNNING_POLLS) {
        const failed = tiles.find(({ mediaId, label }) => !mediaId && runningLabels.has(label));
        return { status: 'failed', images, text: failed?.text ?? '', error: 'tile failed' };
      }
      // Fewer tiles than asked for and nothing still running: hand on what exists, verification reports the count.
      if (images.length >= peak && Date.now() - idleSince >= graceMs) return { status: 'done', images, text: '' };
    } else if (Date.now() - started >= noTileMs) {
      return { status: 'timeout', images, text: '', error: `No new tile within ${Math.round(noTileMs / 1000)}s of Start` };
    }
    if (Date.now() - started >= timeoutMs) {
      return { status: 'timeout', images, text: '', error: `Generation still not finished after ${Math.round(timeoutMs / 1000)}s` };
    }
    await page.waitForTimeout(POLL_MS);
  }
  return { status: 'aborted', images: [], text: '' };
}
