import * as y from './y0lib.mjs';
import { PROJECT } from './mcp.mjs';
const { browser, page } = await y.attach();
await page.goto(PROJECT, { waitUntil: 'domcontentloaded' }); await y.locate(page, 'project.prompt').waitFor({ timeout: 30000 }); await page.waitForTimeout(4000);
const r = await y.locate(page, 'project.tile').evaluateAll((els) => els.slice(0, 40).map((el) => { const v = el.querySelector('flow-video-tile'); return v ? ({ label: el.getAttribute('aria-label'), tag: el.tagName, attrs: el.getAttributeNames().join(), text: el.innerText.slice(0, 60), html: v.outerHTML.replace(/data:[^"]+/g,'D').replace(/\s+/g,' ').slice(0, 1500) }) : null; }).filter(Boolean).slice(0, 2));
console.log(JSON.stringify(r, null, 1));
await browser.close(); process.exit(0);
