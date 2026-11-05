import { logger } from '../utils/logger.js';
import { getPage } from '../browser/connect.js';
import { get, getDataDir } from '../utils/config.js';
import { takeScreenshot } from '../utils/screenshots.js';
import { locate } from '../flow/contract.js';
import { FlowError, ErrorCodes } from '../utils/errors.js';
import fs from 'fs';
import path from 'path';

const PROJECTS_FILE = path.join(getDataDir(), 'config', 'flow.projects.json');

function loadProjects() {
  try {
    if (fs.existsSync(PROJECTS_FILE)) {
      return JSON.parse(fs.readFileSync(PROJECTS_FILE, 'utf-8'));
    }
  } catch (e) {
    logger.warn('Could not load projects file', { error: e.message });
  }
  return { projects: [] };
}

function saveProjects(data) {
  const dir = path.dirname(PROJECTS_FILE);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(PROJECTS_FILE, JSON.stringify(data, null, 2));
}

// Cards can hydrate after the New project button, so a page showing only the button gets a short grace.
export async function waitForProjectCards(page, timeout = 15000) {
  const cards = locate(page, 'home.openProject').first();
  await cards.or(locate(page, 'home.newProject')).first().waitFor({ state: 'visible', timeout }).catch(() => {});
  await cards.waitFor({ state: 'visible', timeout: 5000 }).catch(() => {});
}

/**
 * Create a new project from Flow home and store it in the local registry.
 * Flow lands straight in the project; it has no naming dialog.
 * Returns { url, id, name }.
 */
export async function createNewProject(page, name, campaign) {
  await page.goto(get('flowUrl', 'https://flow.google.com/'), { waitUntil: 'domcontentloaded', timeout: 30000 });
  await waitForProjectCards(page);
  const newProject = locate(page, 'home.newProject').first();
  if (!await newProject.isVisible().catch(() => false)) {
    await takeScreenshot(page, 'no-new-project-btn');
    throw new FlowError(ErrorCodes.UNKNOWN_UI_CHANGE, 'Could not find "New project" button on the Flow page');
  }
  await newProject.click();
  await page.waitForURL(/\/project\/[^/?#]+/, { timeout: 30000 });

  const store = loadProjects();
  const entry = {
    id: `proj_${Date.now()}`,
    url: page.url(),
    campaign,
    name: name || `Project ${new Date().toISOString().slice(0, 10)}`,
    created_at: new Date().toISOString(),
    last_used: new Date().toISOString(),
    tasks: [],
  };
  store.projects.push(entry);
  saveProjects(store);
  await takeScreenshot(page, 'new-project');
  return { url: entry.url, id: entry.id, name: entry.name };
}

/**
 * Ensure we are inside a project context.
 * Rules:
 * 1. If already in a project → reuse it
 * 2. If context.campaign matches a stored project → reopen that project
 * 3. If context.forceNew → always create new
 * 4. Otherwise → create new project
 *
 * context = { campaign, name, forceNew }
 * Returns { url, reused, id, name }
 */
export async function ensureProjectInContext(page, context = {}) {
  const currentUrl = page.url();

  // Already inside a project? Use it, unless a campaign names a different project.
  if (currentUrl.includes('/project/')) {
    const match = context.campaign && loadProjects().projects.find(p =>
      p.campaign && p.campaign.toLowerCase() === context.campaign.toLowerCase());
    if (!context.campaign || (match && currentUrl.startsWith(match.url))) {
      logger.info('Already in a project — reusing', { url: currentUrl });
      return { url: currentUrl, reused: true };
    }
  }

  // If forceNew, skip matching
  if (!context.forceNew) {
    // Try to find a matching project from history
    const store = loadProjects();
    if (context.campaign) {
      const match = store.projects.find(p =>
        p.campaign && p.campaign.toLowerCase() === context.campaign.toLowerCase()
      );
      if (match) {
        logger.info('Found matching project from history', {
          campaign: context.campaign, name: match.name, url: match.url,
        });
        await page.goto(match.url, { waitUntil: 'domcontentloaded', timeout: 30000 });
        await locate(page, 'project.prompt').first().waitFor({ state: 'visible', timeout: 15000 }).catch(() => {});
        match.last_used = new Date().toISOString();
        saveProjects(store);
        return { url: match.url, reused: true, id: match.id, name: match.name };
      }
    }
  }

  // Create new project
  return await createNewProject(page, context.name, context.campaign);
}
