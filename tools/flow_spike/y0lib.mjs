// Live helpers for spike Y0 (controller only). Uses the UI contract; page interaction only.
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { locate, closeOverlay } from '../../mcp/google-flow/src/flow/contract.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, '../../mcp/google-flow/package.json'));
const { chromium } = require('playwright');

export const OUT = path.join(here, 'out', 'y0');
fs.mkdirSync(OUT, { recursive: true });
export { locate, closeOverlay };

export async function attach() {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9333');
  const page = browser.contexts()[0].pages().find((p) => p.url().includes('flow.google.com'));
  if (!page) throw new Error('no Flow tab');
  return { browser, page };
}

const mask = (s) => s.replace(/[\w.+-]+@[\w-]+\.[\w.-]+/g, '<email>');
export async function snap(page, name) {
  const text = mask(await page.locator('body').ariaSnapshot());
  fs.writeFileSync(path.join(OUT, `${name}.txt`), text);
  return text;
}

export async function directMode(page) {
  const close = locate(page, 'project.chatClose');
  if (await close.first().isVisible()) await close.first().click();
  const promo = locate(page, 'project.promoDismiss');
  if (await promo.first().isVisible()) await promo.first().click();
  const agent = locate(page, 'project.agent');
  await agent.waitFor({ timeout: 15000 });
  if ((await agent.getAttribute('aria-pressed')) === 'true') await agent.click();
  if ((await agent.getAttribute('aria-pressed')) === 'true') throw new Error('agent still on');
}

async function pick(page, key) {
  const el = locate(page, key);
  if ((await el.getAttribute('aria-checked')) !== 'true') await el.click();
}

// Returns the quoted credits, with the panel closed again.
export async function settings(page, { kind, model, mode, ratio, count, resolution, duration }) {
  const trigger = locate(page, 'project.settingsTrigger');
  await trigger.click();
  await locate(page, 'settings.kind.image').waitFor({ timeout: 5000 });
  await pick(page, `settings.kind.${kind}`);
  if (mode) await pick(page, `settings.mode.${mode}`);
  await locate(page, 'settings.modelFamily').click();
  await locate(page, `settings.model.${kind}.${model}`).click();
  await page.waitForTimeout(300);
  await pick(page, `settings.ratio.${ratio}`);
  if (resolution) await pick(page, `settings.resolution.${resolution}`);
  if (duration) await pick(page, `settings.duration.${duration}`);
  await pick(page, `settings.count.x${count}`);
  const credits = await locate(page, 'settings.credits').first().textContent().catch(() => '0 credits');
  await trigger.click();
  await page.waitForTimeout(300);
  return { credits: credits.trim(), label: (await trigger.textContent()).trim() };
}

export const tiles = (page) => locate(page, 'project.tile');

export async function typePrompt(page, text) {
  const box = locate(page, 'project.prompt');
  await box.click();
  await page.keyboard.press('Control+A');
  await page.keyboard.press('Delete');
  await page.keyboard.insertText(text);
}

// Submits, then waits for count new top tiles to hold finished media. Returns their indexes' text.
export async function submitAndWait(page, count, { timeoutMs = 300000, video = false } = {}) {
  const before = await tiles(page).count();
  const log = [];
  await locate(page, 'project.start').click();
  const started = Date.now();
  const media = video ? 'img[alt="Generated video thumbnail"]' : 'img[alt="Tile displaying a user\'s image"]';
  while (Date.now() - started < timeoutMs) {
    await page.waitForTimeout(3000);
    const now = await tiles(page).count();
    if (now - before >= count) {
      let done = 0;
      const states = [];
      for (let i = 0; i < count; i++) {
        const tile = tiles(page).nth(i);
        const ok = (await tile.locator(media).count()) > 0;
        if (ok) done++;
        states.push(ok ? 'done' : (await tile.innerText()).slice(0, 60).replace(/\s+/g, ' '));
      }
      log.push(`${Math.round((Date.now() - started) / 1000)}s ${states.join(' | ')}`);
      if (done === count) return { ok: true, seconds: (Date.now() - started) / 1000, log };
    } else if (Date.now() - started > 60000) {
      return { ok: false, reason: 'no new tile in 60s', log };
    }
  }
  return { ok: false, reason: 'timeout', log };
}

export async function download(page, index, size, name) {
  const tile = tiles(page).nth(index);
  await tile.hover();
  await tile.getByRole('button', { name: 'More options' }).click();
  await page.getByRole('menuitem', { name: 'Download' }).click();
  const wait = page.waitForEvent('download', { timeout: 120000 });
  await page.getByRole('menuitem', { name: new RegExp(`^${size}`) }).click();
  const dl = await wait;
  const ext = path.extname(dl.suggestedFilename());
  const file = path.join(OUT, `${name}${ext}`);
  await dl.saveAs(file);
  return file;
}

// Search by exact name first, upload only if absent. Returns {found, reused, chips}.
export async function attachFile(page, file, { search = true } = {}) {
  const name = path.basename(file);
  await locate(page, 'project.addIngredients').click();
  await locate(page, 'picker.assetList').waitFor({ timeout: 10000 });
  const box = locate(page, 'picker.search');
  let reused = false;
  if (search && (await box.isVisible())) {
    await box.fill(name);
    await page.waitForTimeout(1500);
    reused = (await locate(page, 'picker.assetList').getByRole('option', { name: new RegExp(name.replace(/[.]/g, '\\.')) }).count()) > 0;
  }
  if (!reused) {
    const chooser = page.waitForEvent('filechooser', { timeout: 15000 });
    await locate(page, 'picker.upload').click();
    await (await chooser).setFiles(file);
    await page.waitForTimeout(1500);
    await page.getByRole('option', { name: new RegExp(`^${name.replace(/[.]/g, '\\.')}`) }).first().waitFor({ timeout: 60000 });
    for (let i = 0; i < 40; i++) {
      const uploading = await page.getByRole('option', { name: new RegExp(`Uploading`) }).count();
      if (!uploading) break;
      await page.waitForTimeout(1000);
    }
  }
  await page.getByRole('option', { name: new RegExp(`^${name.replace(/[.]/g, '\\.')}`) }).first().click();
  const add = locate(page, 'picker.addToPrompt');
  if (await add.isVisible()) await add.click();
  await page.waitForTimeout(1500);
  await closeOverlay(page);
  return { reused, chips: await locate(page, 'project.chip.ingredient').count() };
}
