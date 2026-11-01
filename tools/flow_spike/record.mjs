// Read-only recorder for the Flow observation spike (plan Task 2).
// Usage: node tools/flow_spike/record.mjs <project-url-part> <label> [maxSeconds]
// Stops at maxSeconds or when <out>/STOP exists. Never clicks anything.
// Saves accessibility snapshot diffs (email masked) and request method + path only: no bodies, tokens or query strings.
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, '../../mcp/google-flow/package.json'));
const { chromium } = require('playwright');

const [urlPart, label, maxSeconds = '900'] = process.argv.slice(2);
if (!urlPart || !label) {
  console.error('usage: record.mjs <project-url-part> <label> [maxSeconds]');
  process.exit(2);
}

const out = path.join(here, 'out', label);
fs.mkdirSync(out, { recursive: true });
const log = fs.createWriteStream(path.join(out, 'timeline.txt'), { flags: 'a' });
const net = fs.createWriteStream(path.join(out, 'network.txt'), { flags: 'a' });

const mask = (s) => s.replace(/[\w.+-]+@[\w-]+\.[\w.-]+/g, '<email>');

function diff(prev, next) {
  const before = new Set(prev);
  const after = new Set(next);
  return [
    ...prev.filter((l) => !after.has(l)).map((l) => `- ${l}`),
    ...next.filter((l) => !before.has(l)).map((l) => `+ ${l}`),
  ];
}

const browser = await chromium.connectOverCDP('http://127.0.0.1:9333');
const page = browser.contexts()[0].pages().find((p) => p.url().includes(urlPart));
if (!page) {
  console.error('no tab matches', urlPart, browser.contexts()[0].pages().map((p) => p.url()));
  process.exit(1);
}

const t0 = Date.now();
const stamp = () => ((Date.now() - t0) / 1000).toFixed(1).padStart(7);
page.on('request', (r) => {
  const u = new URL(r.url());
  if (['xhr', 'fetch'].includes(r.resourceType())) net.write(`${stamp()} ${r.method()} ${u.host}${u.pathname}\n`);
});

let prev = [];
let frame = 0;
while ((Date.now() - t0) / 1000 < Number(maxSeconds) && !fs.existsSync(path.join(out, 'STOP'))) {
  let lines;
  try {
    lines = mask(await page.locator('body').ariaSnapshot({ timeout: 5000 })).split('\n');
  } catch (err) {
    log.write(`${stamp()} snapshot failed: ${err.message.split('\n')[0]}\n`);
    await new Promise((r) => setTimeout(r, 1000));
    continue;
  }
  const changes = diff(prev, lines);
  if (changes.length) {
    log.write(`\n=== ${stamp()}s url=${new URL(page.url()).pathname}\n${changes.join('\n')}\n`);
    if (frame % 10 === 0) fs.writeFileSync(path.join(out, `full-${String(frame).padStart(4, '0')}.txt`), lines.join('\n'));
    frame += 1;
    prev = lines;
  }
  await new Promise((r) => setTimeout(r, 1000));
}
fs.writeFileSync(path.join(out, 'last.txt'), prev.join('\n'));
log.end();
net.end();
await browser.close();
