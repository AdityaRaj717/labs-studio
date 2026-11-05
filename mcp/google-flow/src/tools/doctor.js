#!/usr/bin/env node
import { pathToFileURL } from 'node:url';
import { chromium } from 'playwright';
import { locate, closeOverlay } from '../flow/contract.js';

// Only what shows in every mode. Chips, resolution and the like depend on current settings.
const PROJECT_KEYS = ['project.agent', 'project.settingsTrigger', 'project.start', 'project.prompt'];
const SETTINGS_KEYS = ['settings.kind.image', 'settings.kind.video', 'settings.ratio.16:9', 'settings.count.x1', 'settings.modelFamily', 'settings.credits'];
// A new project's picker has no asset list, and Add to prompt shows only after a pick (both live).
const PICKER_KEYS = ['picker.tab.all', 'picker.upload'];
// The Start chip's picker has only Images and Uploads tabs (live).
const FRAME_PICKER_KEYS = ['picker.tab.images', 'picker.upload'];

const isVisibleSoon = (page, key) =>
  locate(page, key).first().waitFor({ state: 'visible', timeout: 2000 }).then(() => true, () => false);

// Read-only: it opens and closes panels, and never clicks anything that spends, saves or creates.
export async function runDoctor(page) {
  const missing = [];
  let checked = 0;
  const check = async (keys, where) => {
    for (const key of keys) {
      checked++;
      if (!(await isVisibleSoon(page, key))) missing.push({ key, where });
    }
  };
  const close = async (where) => {
    checked++;
    if (!(await closeOverlay(page))) missing.push({ key: 'overlay.close', where });
  };
  const clickIfShown = async (key) => {
    const target = locate(page, key).first();
    if (await target.isVisible()) await target.click({ timeout: 5000 }).catch(() => {});
  };

  await close('start');
  await clickIfShown('project.promoDismiss');
  await clickIfShown('project.chatClose');
  await check(PROJECT_KEYS, 'project');

  await clickIfShown('project.settingsTrigger');
  await check(SETTINGS_KEYS, 'settings');
  await close('settings');

  // Frames mode has chips instead of the Add ingredients button; both open the picker.
  const hasAddButton = await isVisibleSoon(page, 'project.addIngredients');
  await clickIfShown(hasAddButton ? 'project.addIngredients' : 'project.chip.start');
  await check(hasAddButton ? PICKER_KEYS : FRAME_PICKER_KEYS, 'picker');
  await close('picker');

  return { ok: missing.length === 0, checked, missing, host: new URL(page.url()).host };
}

async function main() {
  const urlPart = process.argv[2] || '/project/';
  const port = process.env.FLOW_CDP_PORT || 9333;
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  try {
    const pages = browser.contexts().flatMap((context) => context.pages());
    const page = pages.find((p) => p.url().includes(urlPart));
    const result = page
      ? await runDoctor(page)
      : { ok: false, checked: 0, missing: [{ key: 'project.page', where: urlPart }], host: null };
    console.log(JSON.stringify(result, null, 2));
    process.exitCode = result.ok ? 0 : 1;
  } finally {
    // Over CDP this only disconnects; the owner's pages stay open.
    await browser.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((err) => {
    console.error(err.message);
    process.exitCode = 2;
  });
}
