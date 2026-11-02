import { gotoProject } from '../tools/open-project.js';
import { ensureProjectInContext } from '../navigation/project-navigator.js';
import { beat } from '../engine/pacer.js';
import { createError, ErrorCodes } from '../utils/errors.js';
import { closeOverlay, locate } from './contract.js';

const COMPOSER_MS = 20000;

const uiChange = (message) => createError(ErrorCodes.UNKNOWN_UI_CHANGE, message);

export async function openProject(page, { project_url, project_name }) {
  if (project_url) {
    if (!await gotoProject(page, project_url)) throw createError(ErrorCodes.PROJECT_NOT_FOUND, `Flow project not found: ${project_url}`, { url: project_url });
  } else {
    await ensureProjectInContext(page, { name: project_name });
  }
  // The editor and other sub-views have no composer.
  const base = /^https?:\/\/[^/]+\/project\/[^/?#]+/.exec(page.url())?.[0];
  if (base && page.url().split(/[?#]/)[0] !== base) await page.goto(base, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await locate(page, 'project.prompt').first().waitFor({ state: 'visible', timeout: COMPOSER_MS }).catch(() => {
    throw uiChange('Flow project page not recognised: the prompt box did not appear');
  });
}

// Direct composer, spike ruling C10: chat closed, Agent off, asserted for every job.
export async function resetSession(page) {
  if (!await closeOverlay(page)) throw uiChange('An overlay in the Flow tab would not close');
  for (const key of ['project.promoDismiss', 'project.chatClose']) {
    const button = locate(page, key).first();
    if (await button.isVisible()) {
      await button.click();
      await beat(page);
    }
  }
  const agent = locate(page, 'project.agent');
  await agent.waitFor({ state: 'visible', timeout: COMPOSER_MS });
  if (await agent.getAttribute('aria-pressed') === 'true') {
    await agent.click();
    await beat(page);
  }
  if (await agent.getAttribute('aria-pressed') === 'true') throw uiChange('The Agent toggle stayed on; refusing to generate through the agent');
}

export async function typePrompt(page, text) {
  await locate(page, 'project.prompt').first().click();
  await page.keyboard.press('Control+A');
  await page.keyboard.press('Delete');
  await page.keyboard.insertText(text);
}
