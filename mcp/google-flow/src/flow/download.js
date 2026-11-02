import fs from 'fs';
import path from 'path';
import { beat, withRetry } from '../engine/pacer.js';
import { createError, ErrorCodes } from '../utils/errors.js';
import { logger } from '../utils/logger.js';
import { closeOverlay, contract, locate } from './contract.js';

const MENU_MS = 15000;
const DOWNLOAD_MS = 120000; // a 2K upscale took 15s live; the bound is for a Download that never starts
const INFO_MS = 3000;

async function once(page, tile, size, dest) {
  // Live, one Download hung until the overlays were closed.
  if (!await closeOverlay(page)) throw new Error('an overlay would not close');
  await tile.hover({ timeout: MENU_MS });
  await locate(page, 'tile.moreOptions', { root: tile }).click({ timeout: MENU_MS });
  await beat(page);
  await locate(page, 'tile.download').click({ timeout: MENU_MS });
  await beat(page);
  const started = page.waitForEvent('download', { timeout: DOWNLOAD_MS });
  try {
    await locate(page, `download.size.${size}`).click({ timeout: MENU_MS });
  } catch (err) {
    started.catch(() => {}); // nothing will arrive; its timeout must not go unhandled
    throw err;
  }
  const download = await started;
  // Named only now: the extension comes from Flow, and a name is free until its file is saved.
  const file = dest(path.extname(download.suggestedFilename()) || '.jpg');
  const part = `${file}.part`;
  try {
    await download.saveAs(part);
    fs.renameSync(part, file);
  } catch (err) {
    fs.rmSync(part, { force: true, recursive: true });
    throw err;
  }
  return file;
}

// Repeats no spend: nothing here regenerates, so it is safe to call again after any failure.
export function downloadAsset(page, tile, { size, dest, signal }) {
  return withRetry(() => once(page, tile, size, dest).catch((err) => {
    throw createError(ErrorCodes.DOWNLOAD_FAILED, `Download failed: ${err.message.split('\n')[0]}`);
  }), { signal });
}

// Flow's own record of what it made. null when it can't be read: info is a check, never a reason to fail.
export async function readAssetInfo(page, tile) {
  try {
    const title = tile.getByRole(contract.keys['tile.moreOptions'].role, { name: await tile.getAttribute('aria-label', { timeout: INFO_MS }), exact: true });
    await tile.hover({ timeout: INFO_MS });
    await title.click({ timeout: INFO_MS });
    const info = await page.getByText(new RegExp(contract.tile.assetInfo)).first().innerText({ timeout: INFO_MS });
    await title.click({ timeout: INFO_MS });
    return info.trim();
  } catch (err) {
    logger.debug('Asset info not read', { error: err.message });
    return null;
  }
}
