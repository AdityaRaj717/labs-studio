import { logger } from '../utils/logger.js';
import { getPage } from '../browser/connect.js';
import { jobQueue } from '../queue/job-queue.js';
import { FlowError, ErrorCodes } from '../utils/errors.js';
import { takeScreenshot } from '../utils/screenshots.js';

// Open (or create) one Flow project and give it a title, for hosts that keep one Flow
// project per project of their own (Labs Studio). Flow UI facts (Oct 2026):
//  - home (flow.google.com/) has a "New project" button that lands in /project/<uuid>;
//  - inside a project the title is an <input aria-label="Editable text"> in the header;
//  - a project that no longer exists redirects to /404?reason=project.

const HOME = 'https://flow.google.com/';
const UI = {
  account: 'Account details',
  newProject: 'New project',
  title: 'Editable text',
};
const LOGIN_URLS = ['accounts.google.com', 'flow.google.com/about'];

export function projectBase(url) {
  const m = (url || '').match(/^(https:\/\/[^/]+\/project\/[^/?#]+)/);
  return m ? m[1] : null;
}

function checkLogin(url) {
  if (LOGIN_URLS.some(u => url.includes(u))) {
    throw new FlowError(ErrorCodes.NOT_LOGGED_IN, 'Google Flow wants you to sign in. Sign in by hand in the Chrome window.');
  }
}

// Wait until the page is a project (title box visible), a 404, or a sign-in page.
async function landed(page, timeout = 30000) {
  const title = page.getByRole('textbox', { name: UI.title }).first();
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const url = page.url();
    checkLogin(url);
    if (url.includes('/404')) return 'gone';
    if (projectBase(url) && await title.isVisible().catch(() => false)) return 'project';
    await page.waitForTimeout(500);
  }
  return projectBase(page.url()) ? 'no-title' : 'unknown';
}

// Open a project URL. Returns true when it is there, false when Flow says it is gone.
export async function gotoProject(page, url) {
  const base = projectBase(url);
  if (!base) throw new FlowError(ErrorCodes.INVALID_PARAMS, `Not a Flow project URL: ${url}`);
  if (page.url().split('?')[0] !== base) {
    await page.goto(base, { waitUntil: 'domcontentloaded', timeout: 60000 });
  }
  let state = await landed(page);
  if (state !== 'project' && state !== 'gone') {
    // Seen once mid-batch: the project loaded without its header. One reload fixes it.
    logger.warn('Project page incomplete; reloading once', { url: page.url(), state });
    await page.goto(base, { waitUntil: 'domcontentloaded', timeout: 60000 });
    state = await landed(page);
  }
  if (state === 'gone') return false;
  if (state !== 'project') {
    await takeScreenshot(page, 'open-project-unknown');
    throw new FlowError(ErrorCodes.UNKNOWN_UI_CHANGE, 'Flow project page not recognised: project title box not found');
  }
  return true;
}

async function createProject(page) {
  await page.goto(HOME, { waitUntil: 'domcontentloaded', timeout: 60000 });
  checkLogin(page.url());
  const account = page.getByRole('button', { name: UI.account }).first();
  try {
    await account.waitFor({ state: 'visible', timeout: 15000 });
  } catch {
    checkLogin(page.url());
    throw new FlowError(ErrorCodes.NOT_LOGGED_IN, 'Google Flow is not signed in. Sign in by hand in the Chrome window.');
  }
  const btn = page.getByRole('button', { name: UI.newProject }).first();
  try {
    await btn.waitFor({ state: 'visible', timeout: 15000 });
  } catch {
    await takeScreenshot(page, 'no-new-project-btn');
    throw new FlowError(ErrorCodes.UNKNOWN_UI_CHANGE, 'Flow home page not recognised: "New project" button not found');
  }
  await btn.click();
  await page.waitForURL(/\/project\/[^/?#]+/, { timeout: 30000 });
  if (await landed(page) !== 'project') {
    await takeScreenshot(page, 'new-project-unknown');
    throw new FlowError(ErrorCodes.UNKNOWN_UI_CHANGE, 'New Flow project opened but its title box was not found');
  }
  return projectBase(page.url());
}

async function setTitle(page, name) {
  const box = page.getByRole('textbox', { name: UI.title }).first();
  const current = (await box.inputValue().catch(() => '')).trim();
  if (current === name) return current;
  await box.click();
  await box.fill(name);
  await box.press('Enter');
  await page.waitForTimeout(1000);
  // Leave the field so Flow saves it even if Enter only commits on blur.
  await page.keyboard.press('Tab').catch(() => {});
  await page.waitForTimeout(800);
  const after = (await box.inputValue().catch(() => '')).trim();
  if (after !== name) logger.warn('Flow project title did not stick', { wanted: name, got: after });
  return after;
}

/**
 * args: { url?, name?, create_if_missing = true }
 * Opens `url` if it still exists, else (create_if_missing) creates a new project.
 * When `name` is given the project title is set to it.
 * Returns { status, url, created, title }. PROJECT_NOT_FOUND when gone and not creating.
 */
export async function handleOpenProject(args = {}) {
  const job = jobQueue.createJob('open_project', { url: args.url, name: args.name });
  const page = getPage();
  try {
    jobQueue.startJob(job.id);
    const create = args.create_if_missing !== false;
    let url = null;
    let created = false;
    if (args.url) {
      if (await gotoProject(page, args.url)) url = projectBase(page.url());
      else if (!create) {
        throw new FlowError(ErrorCodes.PROJECT_NOT_FOUND, `Flow project not found: ${args.url}`, { url: args.url });
      } else logger.info('Stored Flow project is gone; creating a new one', { url: args.url });
    }
    if (!url) {
      if (!create) throw new FlowError(ErrorCodes.INVALID_PARAMS, 'No url given and create_if_missing is false');
      url = await createProject(page);
      created = true;
      logger.info('Created Flow project', { url });
    }
    const title = args.name ? await setTitle(page, String(args.name).trim())
      : (await page.getByRole('textbox', { name: UI.title }).first().inputValue().catch(() => ''));
    const result = { status: 'success', url, created, title };
    jobQueue.completeJob(job.id, result);
    return result;
  } catch (err) {
    await takeScreenshot(page, 'open-project-error').catch(() => {});
    jobQueue.failJob(job.id, err);
    throw err;
  }
}

async function gotoHome(page) {
  await page.goto(HOME, { waitUntil: 'domcontentloaded', timeout: 60000 });
  checkLogin(page.url());
  try {
    await page.getByRole('button', { name: UI.account }).first().waitFor({ state: 'visible', timeout: 15000 });
  } catch {
    checkLogin(page.url());
    throw new FlowError(ErrorCodes.NOT_LOGGED_IN, 'Google Flow is not signed in. Sign in by hand in the Chrome window.');
  }
  await page.waitForTimeout(1500);
}

// Project cards on the home page: [{ title, url }] (newest first, as Flow lists them).
async function readProjects(page) {
  return page.evaluate(() => [...document.querySelectorAll('a[aria-label="Open project"][href*="/project/"]')].map((a) => {
    let card = a.parentElement;
    for (let i = 0; i < 4 && card && !card.querySelector('button[aria-label="Delete project"]'); i++) card = card.parentElement;
    const title = (card ? card.innerText : '').split('\n').map(s => s.trim())
      .filter(s => s && !['edit', 'delete'].includes(s))[0] || '';
    return { title, url: new URL(a.getAttribute('href'), location.origin).href };
  }));
}

async function withJob(type, params, fn) {
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

/** args: { query? } -> { projects: [{ title, url }] } (query filters titles, case-insensitive). */
export async function handleListProjects(args = {}) {
  return withJob('list_projects', {}, async (page) => {
    await gotoHome(page);
    let projects = await readProjects(page);
    if (args.query) projects = projects.filter(p => p.title.toLowerCase().includes(String(args.query).toLowerCase()));
    return { status: 'success', count: projects.length, projects };
  });
}

/** args: { url, name } -> { url, title }. PROJECT_NOT_FOUND when the project is gone. */
export async function handleRenameProject(args = {}) {
  if (!args.url || !args.name) throw new FlowError(ErrorCodes.INVALID_PARAMS, 'url and name are required');
  return handleOpenProject({ url: args.url, name: args.name, create_if_missing: false });
}

/**
 * args: { url, confirm }. Flow deletes a project PERMANENTLY (clips, ingredients, prompts),
 * so nothing happens unless confirm === true.
 */
export async function handleDeleteProject(args = {}) {
  const base = projectBase(args.url);
  if (!base) throw new FlowError(ErrorCodes.INVALID_PARAMS, `Not a Flow project URL: ${args.url}`);
  if (args.confirm !== true) {
    throw new FlowError(ErrorCodes.INVALID_PARAMS,
      'Deleting a Flow project is permanent. Call again with confirm: true once the user has agreed.');
  }
  return withJob('delete_project', { url: base }, async (page) => {
    await gotoHome(page);
    const href = new URL(base).pathname;
    const link = page.locator(`a[aria-label="Open project"][href="${href}"]`).first();
    if (!await link.count()) throw new FlowError(ErrorCodes.PROJECT_NOT_FOUND, `Flow project not found: ${base}`, { url: base });
    let card = link.locator('xpath=..');
    for (let i = 0; i < 4 && !(await card.getByRole('button', { name: 'Delete project' }).count()); i++) card = card.locator('xpath=..');
    await card.hover();
    await card.getByRole('button', { name: 'Delete project' }).first().click();
    const dialog = page.getByRole('dialog').first();
    await dialog.waitFor({ state: 'visible', timeout: 10000 });
    await dialog.getByRole('button', { name: 'Delete project' }).click();
    await page.waitForTimeout(2500);
    const gone = !(await page.locator(`a[aria-label="Open project"][href="${href}"]`).count());
    if (!gone) throw new FlowError(ErrorCodes.UNKNOWN_UI_CHANGE, 'Pressed Delete project but the project is still listed');
    return { status: 'success', deleted: base };
  });
}
