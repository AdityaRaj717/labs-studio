import path from 'path';
import { get } from '../utils/config.js';
import { logger } from '../utils/logger.js';
import { detectBlock } from './blocks.js';
import { contract, locate } from './contract.js';

const POLL_MS = 1000;
const NOT_RUNNING_POLLS = 3; // a tile can flip through an empty frame on its way to done
const PREVIEW_MS = 10000;
const PERCENT = /^\s*(\d+)%/;

const css = (key) => contract.keys[key].css;

// shortcut: finished means an image tile, video tiles have no media id; Task 10 adds its own marker.
function readTiles(page) {
  return locate(page, 'project.tile').evaluateAll((els, { character, image }) => els
    .filter((el) => !el.querySelector(character)) // saved Characters sit among the results
    .map((el) => ({
      label: el.getAttribute('aria-label'),
      mediaId: el.querySelector(image)?.getAttribute('data-media-id') ?? null,
      text: el.innerText.trim(),
    })), { character: css('tile.character'), image: css('tile.image') });
}

// Taken right before Start: anything finished now is not a result of this job.
export async function baselineTiles(page) {
  return (await readTiles(page)).flatMap(({ mediaId }) => (mediaId ? [mediaId] : []));
}

export const tileOf = (page, mediaId) => locate(page, 'project.tile')
  .filter({ has: page.locator(`[data-media-id=${JSON.stringify(mediaId)}]`) }).first();

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
export async function observeGeneration(page, { before, count, previewDir, onUpdate, signal }) {
  const known = new Set(before);
  const started = Date.now();
  const timeoutMs = get('generationTimeoutMs', 300000);
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

    const images = tiles.flatMap(({ mediaId }) => (mediaId && !known.has(mediaId) ? [mediaId] : [])).slice(0, count);
    const running = tiles.filter(({ mediaId, text }) => !mediaId && PERCENT.test(text));
    running.forEach(({ label }) => runningLabels.add(label));
    peak = Math.max(peak, running.length);

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
