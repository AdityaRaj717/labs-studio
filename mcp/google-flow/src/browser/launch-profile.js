import { chromium } from 'playwright';
import path from 'path';
import fs from 'fs';
import { logger } from '../utils/logger.js';
import { locate } from '../flow/contract.js';
import { get } from '../utils/config.js';
import { FlowError, ErrorCodes } from '../utils/errors.js';
import { launchChromeDirect, pickFlowPage, setPage, setContext, setConnected, setBrowser, isBrowserConnected } from './connect.js';

const CDP_PORT = get('cdpPort', 9333);
const FLOW_URL = get('flowUrl', 'https://flow.google.com/');

export async function launchFlowChrome(headless = false) {
  if (isBrowserConnected()) {
    logger.info('Browser already connected, reusing');
    return { success: true, message: 'Already connected' };
  }

  logger.info('Launching Chrome with the dedicated Flow profile');

  try {
    // Try connecting to existing Chrome instance first
    const existing = await chromium.connectOverCDP(`http://127.0.0.1:${CDP_PORT}`);
    logger.info('Found existing Chrome instance, reusing');
    const ctx = existing.contexts()[0];
    const pg = pickFlowPage(ctx);
    setBrowser(existing);
    setContext(ctx);
    setConnected(true);
    if (pg) { setPage(pg); return { browser: existing, context: ctx, page: pg }; }
    const newPage = await ctx.newPage();
    setPage(newPage);
    return { browser: existing, context: ctx, page: newPage };
  } catch {
    // Launch Chrome directly (not via Playwright) for anti-detection
    return await launchChromeDirect({ cdpPort: CDP_PORT, headless });
  }
}

export async function navigateToFlow(page) {
  logger.info('Navigating to Google Flow', { url: FLOW_URL });
  await page.goto(FLOW_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
  // Signed out shows neither control, so a miss falls through to the URL check below.
  await locate(page, 'account.open').or(locate(page, 'home.newProject')).first()
    .waitFor({ state: 'visible', timeout: 15000 }).catch(() => {});

  const currentUrl = page.url();
  logger.info('Flow page loaded', { url: currentUrl.substring(0, 100) });

  if (currentUrl.includes('accounts.google.com')) {
    return { authenticated: false, url: currentUrl,
      message: 'Google Flow wants you to sign in. Sign in by hand in the Chrome window.' };
  }

  return { authenticated: true, url: currentUrl };
}
