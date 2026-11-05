import { chromium } from 'playwright';
import path from 'path';
import fs from 'fs';
import { spawn } from 'child_process';
import { logger } from '../utils/logger.js';
import { get } from '../utils/config.js';
import { FlowError, ErrorCodes } from '../utils/errors.js';
import { takeScreenshot } from '../utils/screenshots.js';
import { isFlowHost } from './host.js';

let browser = null;
let context = null;
let page = null;
let isConnected = false;

export async function connectToBrowser(options = {}) {
  if (isConnected && page) {
    logger.info('Already connected to browser');
    return { browser, context, page };
  }

  const cdpPort = options.cdpPort || get('cdpPort', 9333);
  const cdpUrl = `http://127.0.0.1:${cdpPort}`;

  try {
    // Try connecting to existing Chrome instance via CDP
    logger.info('Attempting CDP connection', { url: cdpUrl });
    browser = await chromium.connectOverCDP(cdpUrl);
    logger.info('Connected via CDP');

    const contexts = browser.contexts();
    if (contexts.length > 0) {
      context = contexts[0];
    } else {
      context = await browser.newContext();
    }

    page = pickFlowPage(context) || await context.newPage();
    isConnected = true;
    logger.info('Browser connected successfully');
    return { browser, context, page };
  } catch (err) {
    logger.warn('CDP connection failed, will launch new browser', { error: err.message });
    return await launchNewBrowser(cdpPort, options);
  }
}

async function launchNewBrowser(cdpPort, options = {}) {
  return await launchChromeDirect({ ...options, cdpPort });
}

/**
 * Launch Chrome DIRECTLY (not via Playwright) to avoid automation detection
 * (navigator.webdriver=false), on the dedicated persistent profile, then connects
 * Playwright via CDP.
 */
export async function launchChromeDirect(options = {}) {
  const chromePath = options.chromePath || get('chromePath', 'C:/Program Files/Google/Chrome/Application/chrome.exe');
  const cdpPort = options.cdpPort || get('cdpPort', 9333);
  const headless = options.headless ?? get('headless', false);
  const profileDir = options.profileDir || get('chromeProfileDir', 'D:/glabs_web/chrome-profile');

  if (isConnected && page) {
    logger.info('Already connected, reusing browser');
    return { browser, context, page };
  }

  if (!fs.existsSync(chromePath)) {
    throw new FlowError(ErrorCodes.PLAYWRIGHT_ERROR, `Chrome not found at ${chromePath}`);
  }

  // Dedicated persistent profile: the user signs in once; the main Chrome profile is never copied.
  fs.mkdirSync(profileDir, { recursive: true });

  const args = [
    `--remote-debugging-port=${cdpPort}`,
    `--user-data-dir=${profileDir}`,
    '--no-first-run', '--no-default-browser-check',
    '--window-size=1920,1080',
  ];
  if (headless) args.push('--headless=new');

  logger.info('Launching Chrome directly', { chromePath, cdpPort, headless, profileDir });

  const chromeProcess = spawn(chromePath, args, { stdio: 'ignore', detached: true });
  chromeProcess.unref();

  const cdpUrl = `http://127.0.0.1:${cdpPort}`;
  let attempts = 0;
  while (attempts < 20) {
    try {
      const resp = await fetch(`${cdpUrl}/json/version`);
      if (resp.ok) break;
    } catch { }
    await new Promise(r => setTimeout(r, 1000));
    attempts++;
  }
  if (attempts >= 20) {
    throw new FlowError(ErrorCodes.PLAYWRIGHT_ERROR, 'Chrome CDP failed to start in time');
  }

  browser = await chromium.connectOverCDP(cdpUrl);
  context = browser.contexts()[0];
  page = pickFlowPage(context) || await context.newPage();
  isConnected = true;
  return { browser, context, page };
}

export async function closeBrowser() {
  if (browser) {
    try {
      // Attached over CDP, so this only disconnects: Chrome and its tabs stay (issues.test.js).
      await browser.close();
    } catch (err) {
      logger.warn('Error closing browser', { error: err.message });
    }
  }
  browser = null;
  context = null;
  page = null;
  isConnected = false;
  logger.info('Browser disconnected');
}

export function getPage() {
  if (!page) {
    throw new FlowError(ErrorCodes.BROWSER_NOT_CONNECTED, 'Browser not connected. Call connectToBrowser() first.');
  }
  return page;
}

export function getContext() {
  return context;
}

export function isBrowserConnected() {
  return isConnected;
}

export function setPage(newPage) {
  page = newPage;
}

export function getBrowser() {
  return browser;
}

export function setBrowser(b) {
  browser = b;
}

export function setConnected(connected) {
  isConnected = connected;
}

export function setContext(ctx) {
  context = ctx;
}

// Prefer a tab already on Flow, so other tabs in the same Chrome are left alone.
export function pickFlowPage(ctx) {
  const pages = ctx ? ctx.pages() : [];
  return pages.find((p) => isFlowHost(p.url())) || pages[0] || null;
}
