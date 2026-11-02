import { beat } from '../engine/pacer.js';
import { createError, ErrorCodes } from '../utils/errors.js';
import { closeOverlay, contract, locate } from './contract.js';

const PANEL_MS = 5000;

const uiChange = (message) => createError(ErrorCodes.UNKNOWN_UI_CHANGE, message);
const radioKeys = ({ kind, mode, ratio, resolution, duration, count }) => [
  `settings.kind.${kind}`,
  ...(mode ? [`settings.mode.${mode}`] : []),
  `settings.ratio.${ratio}`,
  ...(resolution ? [`settings.resolution.${resolution}`] : []),
  ...(duration ? [`settings.duration.${duration}s`] : []),
  `settings.count.x${count}`,
];

const isChecked = async (page, key) => (await locate(page, key).getAttribute('aria-checked')) === 'true';

export const modelPattern = (kind, model) => new RegExp(contract.keys[`settings.model.${kind}.${model}`].name.regex);

// Sets, reads back and reads the live quote with the panel open; returns the quote with it closed.
export async function applySettings(page, settings) {
  const { kind, model, maxCredits } = settings;
  if (!await closeOverlay(page)) throw uiChange('An overlay in the Flow tab would not close');
  await locate(page, 'project.settingsTrigger').click();
  await locate(page, 'settings.kind.image').waitFor({ timeout: PANEL_MS });
  const keys = radioKeys(settings);
  const pick = async (key) => {
    if (!await isChecked(page, key)) await locate(page, key).click();
    await beat(page);
  };
  await pick(keys[0]);
  await locate(page, 'settings.modelFamily').click();
  await locate(page, `settings.model.${kind}.${model}`).click();
  await beat(page);
  for (const key of keys.slice(1)) await pick(key);

  for (const key of keys) {
    if (!await isChecked(page, key)) throw uiChange(`Flow did not keep the setting ${key}`);
  }
  // The button also holds its icon's ligature text (arrow_drop_down) on a second line.
  const shown = (await locate(page, 'settings.modelFamily').innerText()).split('
')[0].trim();
  if (!modelPattern(kind, model).test(shown)) throw uiChange(`Flow shows model "${shown}" instead of ${model}`);

  const credits = locate(page, 'settings.credits').first();
  const quote = await credits.isVisible() ? Number((await credits.innerText()).replace(/\D/g, '')) : null;
  // Image models are free of credits; a video with no quote must not look free.
  if (quote === null && kind !== 'image') throw uiChange('Flow shows no credit quote');
  const quotedCredits = quote ?? 0;
  if (quotedCredits > maxCredits) {
    await closeOverlay(page);
    throw createError(ErrorCodes.BUDGET_EXCEEDED, `Flow quotes ${quotedCredits} credits, above max_credits ${maxCredits}`, { quotedCredits, maxCredits });
  }
  if (!await closeOverlay(page)) throw uiChange('The settings panel would not close');
  return { quotedCredits };
}
