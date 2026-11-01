import { logger } from '../utils/logger.js';
import { getPage } from '../browser/connect.js';
import { jobQueue } from '../queue/job-queue.js';
import { FlowError, ErrorCodes } from '../utils/errors.js';
import { takeScreenshot } from '../utils/screenshots.js';
import { getDataDir } from '../utils/config.js';
import { gotoProject, projectBase } from './open-project.js';
import { contract, locate } from '../flow/contract.js';
import fs from 'fs';
import path from 'path';

// Flow characters (seen live Oct 2026):
//  - each project has its own Characters section (Project navigation > Characters). With no
//    characters that button opens the New character page (/project/<id>/character) instead.
//  - New character page: "Describe your character…" + Start generation makes a portrait
//    (a Nano Banana generation, so it spends credits). "Upload" or "Add from project" with an
//    existing image makes the character straight from that image: free, no generation.
//  - a character is an entity at /character/<uuid>: a name, optional "Character info" the agent
//    reads, a voice, a portrait ("Create body" adds a full-body image, a generation).
//  - characters are per project. Pasting one into another project is refused by Flow ("Pasting
//    characters across projects is not currently supported"); the prompt picker can still
//    reference another project's character through its project switcher.
//  - Flow's own "Scenes" are video timelines, not places. A place for image work is kept as a
//    character whose info starts with PLACE_PREFIX (Flow: "anything can be a character").

const ACTIVE_NAV_CLASS = 'mdc-list-item--activated';

export const PLACE_PREFIX = 'Place (a location, not a person): ';

async function need(page, locator, what, timeout = 15000) {
  try {
    await locator.waitFor({ state: 'visible', timeout });
    return locator;
  } catch {
    await takeScreenshot(page, 'ui-missing').catch(() => {});
    throw new FlowError(ErrorCodes.UNKNOWN_UI_CHANGE, `Flow UI not recognised: ${what} not found`, { what });
  }
}

export async function withJob(type, params, fn) {
  const job = jobQueue.createJob(type, params);
  const page = getPage();
  try {
    jobQueue.startJob(job.id);
    const result = await fn(page);
    jobQueue.completeJob(job.id, result);
    return result;
  } catch (err) {
    await takeScreenshot(page, `${type}-error`).catch(() => {});
    jobQueue.failJob(job.id, err);
    throw err;
  }
}

export async function openProjectOrFail(page, url) {
  if (!url) throw new FlowError(ErrorCodes.INVALID_PARAMS, 'project_url is required');
  if (!await gotoProject(page, url)) {
    throw new FlowError(ErrorCodes.PROJECT_NOT_FOUND, `Flow project not found: ${url}`, { url });
  }
  return projectBase(page.url());
}

// Character names in the open project, read from its Characters section.
async function readCharacterNames(page, base) {
  if (page.url().split('?')[0] !== base) await gotoProject(page, base);
  const section = await need(page, locate(page, 'character.section'), 'Characters section button');
  await section.click();
  const end = Date.now() + 10000;
  let names = [];
  let stable = 0;
  while (Date.now() < end) {
    await page.waitForTimeout(700);
    // No characters: Flow jumps to the New character page.
    if (page.url().includes('/character')) return [];
    // With the section filter on, every tile in the grid is a character (thumbnails load lazily).
    if (!(await section.getAttribute('class') || '').includes(ACTIVE_NAV_CLASS)) continue;
    const now = await page.evaluate(() => [...document.querySelectorAll('[role=group]')]
      .map(g => g.getAttribute('aria-label') || '').filter(Boolean));
    // The section fills in over a second or two: wait until the list stops changing.
    stable = now.length && now.join('|') === names.join('|') ? stable + 1 : 0;
    names = now;
    if (stable >= 2) break;
  }
  return names;
}

// Open one character's page (/character/<uuid>) from the Characters section.
async function openCharacter(page, base, name) {
  const names = await readCharacterNames(page, base);
  if (!names.includes(name)) {
    throw new FlowError(ErrorCodes.INVALID_PARAMS, `No character "${name}" in this project. Characters: ${names.join(', ') || '(none)'}`,
      { name, characters: names });
  }
  await page.getByRole('group', { name, exact: true }).first().click();
  await page.waitForURL(/\/character\/[^/?#]+/, { timeout: 20000 });
  await need(page, locate(page, 'character.name'), 'character name box', 20000);
  await page.waitForTimeout(800);
  return page.url();
}

async function readCharacterInfo(page) {
  return (await locate(page, 'character.info').inputValue().catch(() => '')).trim();
}

function kindOf(info) {
  return info.startsWith(PLACE_PREFIX.trim().split(' ')[0]) ? 'place' : 'person';
}

// [{ name, kind?, info?, url? }]. details opens every character to read its info (slower).
export async function listCharacters(page, base, details = false) {
  const names = await readCharacterNames(page, base);
  if (!details) return names.map(name => ({ name }));
  const out = [];
  for (const name of names) {
    const url = await openCharacter(page, base, name);
    const info = await readCharacterInfo(page);
    out.push({ name, kind: kindOf(info), info, url });
  }
  await gotoProject(page, base);
  return out;
}

async function waitForCharacterPage(page, timeout = 180000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (/\/character\/[^/?#]+/.test(page.url())
        && await locate(page, 'character.name').isVisible().catch(() => false)) return page.url();
    await page.waitForTimeout(1000);
  }
  await takeScreenshot(page, 'character-not-created');
  throw new FlowError(ErrorCodes.GENERATION_TIMEOUT, `The new character page did not appear after ${Math.round(timeout / 1000)}s`);
}

// Start a character from one image: a local file (Upload) or an image already in a project
// (Add from project, found by its name in the asset search; from_project switches projects).
async function startFromImage(page, image, fromProjectTitle) {
  if (fs.existsSync(image)) {
    const chooser = page.waitForEvent('filechooser', { timeout: 15000 });
    await (await need(page, locate(page, 'character.upload'), 'Upload button')).click();
    await (await chooser).setFiles(image);
    return 'upload';
  }
  await (await need(page, locate(page, 'character.addFromProject'), 'Add from project button')).click();
  const dialog = await need(page, page.getByRole('dialog').first(), 'Select media dialog');
  if (fromProjectTitle) {
    await locate(page, 'picker.selectProject', { root: dialog }).click();
    const opt = page.getByRole('listbox', { name: contract.keys['picker.selectProject'].name }).getByRole('option', { name: fromProjectTitle, exact: true });
    await need(page, opt, `project "${fromProjectTitle}" in the project switcher`, 8000);
    await opt.click();
    await page.waitForTimeout(2000);
  }
  await locate(page, 'picker.search', { root: dialog }).fill(image);
  await page.waitForTimeout(2000);
  const option = locate(page, 'picker.assetList', { root: dialog }).getByRole('option', { name: image, exact: true }).first();
  if (!await option.isVisible().catch(() => false)) {
    await page.keyboard.press('Escape');
    throw new FlowError(ErrorCodes.INVALID_PARAMS, `"${image}" is neither a local file nor an image in the project`, { image });
  }
  await option.click();
  return 'project';
}

async function setNameAndInfo(page, name, info) {
  const box = locate(page, 'character.name');
  await box.click();
  await box.fill(name);
  await box.press('Enter');
  await page.waitForTimeout(1000);
  if (info) {
    const infoBox = locate(page, 'character.info');
    await infoBox.click();
    await infoBox.fill(info);
    await page.waitForTimeout(1200);
  }
  const got = (await box.inputValue().catch(() => '')).trim();
  if (got !== name) logger.warn('Character name did not stick', { wanted: name, got });
  await locate(page, 'character.done').click();
  await page.waitForTimeout(2500);
  return got;
}

/**
 * Create a character (or, with kind 'place', a reusable place) in one project.
 * args: { project_url, name, prompt?, images?[], info?, kind?, format?, auto_confirm?, from_project_title? }
 *  - images[0]: local file (uploaded) or the name of an image in the project ("MD_02.jpg"):
 *    free, the character is that image. Extra images are ignored (a character has one portrait).
 *  - otherwise prompt: Flow generates a portrait (credits) and only with auto_confirm: true.
 * An existing character with the same name is reused, not duplicated.
 */
export async function createCharacter(page, args) {
  const name = String(args.name || '').trim();
  if (!name) throw new FlowError(ErrorCodes.INVALID_PARAMS, 'name is required');
  const images = args.images || [];
  if (!images.length && !args.prompt) throw new FlowError(ErrorCodes.INVALID_PARAMS, 'Give images or a prompt');
  const base = await openProjectOrFail(page, args.project_url);
  const info = args.kind === 'place' ? PLACE_PREFIX + (args.info || args.prompt || name) : (args.info || '');

  const existing = await readCharacterNames(page, base);
  if (existing.includes(name)) {
    await gotoProject(page, base);
    return { status: 'success', name, created: false, message: 'A character with this name already exists; reused.' };
  }

  await page.goto(`${base}/character`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await need(page, locate(page, 'character.prompt'), 'New character page', 20000);
  let source;
  if (images.length) {
    source = await startFromImage(page, images[0], args.from_project_title);
    if (images.length > 1) logger.warn('Only the first image is used for a character', { name, ignored: images.slice(1) });
  } else {
    const prompt = String(args.prompt).replace(/\s+/g, ' ').trim();
    const box = locate(page, 'character.prompt');
    await box.click();
    await page.keyboard.insertText(prompt);
    if (args.format) {
      // "Format" rewrites the text into a studio portrait prompt (free, no image).
      await locate(page, 'character.format').click();
      const end = Date.now() + 30000;
      while (Date.now() < end && (await box.innerText()).trim() === prompt) await page.waitForTimeout(800);
    }
    if (args.auto_confirm !== true) {
      const shot = await takeScreenshot(page, 'character-ready-for-confirmation');
      return {
        status: 'ready_for_confirmation', name,
        message: 'Prompt typed on the New character page. Nothing generated. Call again with auto_confirm=true (spends credits).',
        prompt: (await box.innerText()).trim(), screenshot: shot,
      };
    }
    const start = locate(page, 'project.start');
    await need(page, start, 'Start generation button');
    await start.click();
    source = 'prompt';
  }
  const url = await waitForCharacterPage(page);
  if (source === 'prompt') {
    // The character page opens while the portrait is still generating; leaving it early
    // (Done) loses the portrait, so wait for it.
    try {
      await locate(page, 'character.portrait').first().waitFor({ state: 'visible', timeout: Number(args.timeout_ms) || 240000 });
    } catch {
      await takeScreenshot(page, 'character-no-portrait');
      throw new FlowError(ErrorCodes.GENERATION_TIMEOUT, 'The character page opened but its portrait never appeared', { url });
    }
  }
  const got = await setNameAndInfo(page, name, info);
  logger.info('Character created', { name: got, source, url });
  return { status: 'success', name: got, created: true, kind: args.kind === 'place' ? 'place' : 'person', source, url };
}

// Save a character's portrait to the data dir (Download image on its page). Free.
export async function downloadPortrait(page, base, name) {
  const url = await openCharacter(page, base, name);
  const info = await readCharacterInfo(page);
  const dir = path.join(getDataDir(), 'characters');
  fs.mkdirSync(dir, { recursive: true });
  // "Download image" saves a 512 px preview; the portrait URL with "=s0" is the original size.
  const img = await need(page, locate(page, 'character.portrait').first(), 'character portrait');
  const src = await img.getAttribute('src');
  const got = await page.evaluate(async (u) => {
    const res = await fetch(u.replace(/=[sw]\d+[^/]*$/, '') + '=s0', { credentials: 'include' });
    if (!res.ok) return { error: res.status };
    const bytes = new Uint8Array(await res.arrayBuffer());
    let bin = '';
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return { type: res.headers.get('content-type') || '', data: btoa(bin) };
  }, src);
  if (got.error) throw new FlowError(ErrorCodes.DOWNLOAD_FAILED, `Character portrait download failed (HTTP ${got.error})`);
  const ext = got.type.includes('png') ? '.png' : got.type.includes('webp') ? '.webp' : '.jpg';
  const file = path.join(dir, `${name.replace(/[\\/:*?"<>|]/g, '_')}_${Date.now()}${ext}`);
  fs.writeFileSync(file, Buffer.from(got.data, 'base64'));
  return { file, info, url };
}

/** args: { project_url, details? } -> { characters: [{ name, kind?, info?, url? }] } (people and places). Free. */
export async function handleListCharacters(args = {}) {
  return withJob('list_characters', { project_url: args.project_url }, async (page) => {
    const base = await openProjectOrFail(page, args.project_url);
    const characters = await listCharacters(page, base, args.details === true);
    await gotoProject(page, base);
    return { status: 'success', count: characters.length, characters };
  });
}

/** args: { project_url, name, prompt?, images?, info?, format?, auto_confirm? } */
export async function handleCreateCharacter(args = {}) {
  return withJob('create_character', { project_url: args.project_url, name: args.name },
    page => createCharacter(page, { ...args, kind: args.kind === 'place' ? 'place' : 'person' }));
}
