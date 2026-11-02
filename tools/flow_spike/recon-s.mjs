// Recon: open a scene (argv[2] URL path), print the aria tail and timeline facts. No spend.
import * as y from './y0lib.mjs';
import { createRequire } from 'node:module';
const require = createRequire(new URL('../../mcp/google-flow/package.json', import.meta.url));
const { chromium } = require('playwright');
const browser = await chromium.connectOverCDP('http://127.0.0.1:9333');
const ctx = browser.contexts()[0];
const page = ctx.pages().find((p) => p.url().includes('flow.google.com')) ?? await ctx.newPage();
const PROJECT = '065acc3b-852c-4cf2-84c6-80359d0543bd';
await page.goto(`https://flow.google.com/project/${PROJECT}/${process.argv[2] ?? ''}`, { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(8000);
console.log(page.url());
const s = await y.snap(page, 'scene');
console.log(s.split('\n').map((l) => l.trimEnd().slice(0, 110)).join('\n').slice(0, 7000));
console.log(await page.evaluate(() => [...document.querySelectorAll('video')].map((v) => ({ d: v.duration, w: v.videoWidth, src: (v.currentSrc || v.src).slice(0, 80) }))));
await page.screenshot({ path: 'out/scene.jpg', type: 'jpeg', quality: 50, timeout: 10000 }).catch((e) => console.log(e.message));
await browser.close(); process.exit(0);
