import path from 'path';
import { beat, withRetry } from '../engine/pacer.js';
import { get } from '../utils/config.js';
import { createError, ErrorCodes } from '../utils/errors.js';
import { closeOverlay, contract, locate } from './contract.js';

const PICKER_MS = 10000;
const CHOOSER_MS = 15000;
const ATTACH_MS = 20000;
const POLL_MS = 200;

const escapeRegex = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const option = (page, name, exact) => locate(page, 'picker.assetList').getByRole(contract.keys['picker.option'].role, { name, exact });
export const chipCount = (page) => locate(page, 'project.chip.ingredient').count();

async function openPicker(page) {
  await closeOverlay(page);
  await locate(page, 'project.addIngredients').click();
  await locate(page, 'picker.assetList').waitFor({ timeout: PICKER_MS });
}

async function search(page, text) {
  const box = locate(page, 'picker.search');
  if (await box.isVisible()) {
    await box.fill(text);
    await beat(page, 1500);
  }
}

// One ready chip more than before. Clicking an option can attach at once and remove Add to prompt, so that button is optional.
async function attach(page, target, before, stalled) {
  await target.click();
  await beat(page);
  const add = locate(page, 'picker.addToPrompt');
  if (await chipCount(page) <= before && await add.isVisible()) await add.click();
  const chips = locate(page, 'project.chip.ingredient');
  for (const end = Date.now() + ATTACH_MS; Date.now() < end; await page.waitForTimeout(POLL_MS)) {
    const busy = await chips.evaluateAll((els) => els.filter((el) => el.getAttribute('aria-busy') === 'true').length);
    if (await chips.count() > before && !busy) {
      await closeOverlay(page);
      return;
    }
  }
  await closeOverlay(page);
  throw stalled;
}

async function attachFile(page, file) {
  const name = path.basename(file);
  const stalled = createError(ErrorCodes.UPLOAD_STALLED, `The upload of ${name} never reached the prompt`, { file: name });
  const before = await chipCount(page);
  await openPicker(page);
  await search(page, name);
  const listed = option(page, new RegExp(`^${escapeRegex(name)}`)).first();
  if (!await listed.isVisible()) {
    const chooser = page.waitForEvent('filechooser', { timeout: CHOOSER_MS });
    await locate(page, 'picker.upload').click();
    await (await chooser).setFiles(file);
    const uploading = option(page, new RegExp(contract.picker.uploading));
    const end = Date.now() + get('uploadTimeoutMs', 60000);
    while (await uploading.count() > 0 || !await listed.isVisible()) {
      if (Date.now() > end) {
        await closeOverlay(page);
        throw stalled;
      }
      await page.waitForTimeout(POLL_MS);
    }
  }
  await attach(page, listed, before, stalled);
}

async function attachNamed(page, name, project) {
  const before = await chipCount(page);
  await openPicker(page);
  if (project) {
    const switcher = locate(page, 'picker.selectProject');
    if (!(await switcher.innerText()).includes(project)) {
      await switcher.click();
      const choice = locate(page, 'picker.projectList').getByRole(contract.keys['picker.option'].role, { name: project, exact: true });
      if (!await choice.isVisible()) {
        await closeOverlay(page);
        throw createError(ErrorCodes.PROJECT_NOT_FOUND, `No Flow project "${project}" in the picker`, { project });
      }
      await choice.click();
      await beat(page, 1500);
    }
  }
  await locate(page, 'picker.tab.characters').click();
  await search(page, name);
  const target = option(page, name, true).first();
  if (!await target.isVisible()) {
    await closeOverlay(page);
    throw createError(ErrorCodes.INVALID_PARAMS, `No character or scene "${name}" in the Flow picker`, { name, project, next_action: 'Create it with flow_create_character, or fix the name.' });
  }
  await attach(page, target, before, createError(ErrorCodes.UNKNOWN_UI_CHANGE, `"${name}" never reached the prompt`));
}

// A scene is a place kept as a character, so both come from the picker's Characters tab.
export async function addIngredient(page, item) {
  const { file, character, scene, project } = typeof item === 'string' ? { file: item } : item;
  if (file) return withRetry(() => attachFile(page, file));
  if (!character && !scene) throw createError(ErrorCodes.INVALID_PARAMS, 'An ingredient naming only a project has no asset to attach');
  return attachNamed(page, character ?? scene, project);
}
