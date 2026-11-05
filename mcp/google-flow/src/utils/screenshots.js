import path from 'path';
import fs from 'fs';
import { getDataDir } from './config.js';
import { logger } from './logger.js';

const SCREENSHOT_DIR = path.join(getDataDir(), 'screenshots-debug');

function ensureDir() {
  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }
}

// CDP, not page.screenshot: that hung on Flow waiting for fonts. Never throws; a job must not fail on this.
export async function takeScreenshot(page, name, timeoutMs = 10000) {
  let timer;
  try {
    ensureDir();
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const filename = `${timestamp}_${name}.png`;
    const filepath = path.join(SCREENSHOT_DIR, filename);
    const capture = async () => {
      const session = await page.context().newCDPSession(page);
      const { data } = await session.send('Page.captureScreenshot', { format: 'png' });
      session.detach().catch(() => {});
      return data;
    };
    const timeout = new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`timed out after ${timeoutMs}ms`)), timeoutMs);
    });
    const data = await Promise.race([capture(), timeout]);
    fs.writeFileSync(filepath, Buffer.from(data, 'base64'));
    logger.info('Screenshot saved', { name, path: filepath });
    return filepath;
  } catch (err) {
    logger.warn('Failed to take screenshot', { name, error: err.message });
    return null;
  } finally {
    clearTimeout(timer);
  }
}

export function getLatestScreenshot(namePattern) {
  if (!fs.existsSync(SCREENSHOT_DIR)) return null;
  const files = fs.readdirSync(SCREENSHOT_DIR)
    .filter(f => f.includes(namePattern))
    .map(f => path.join(SCREENSHOT_DIR, f))
    .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
  return files[0] || null;
}
