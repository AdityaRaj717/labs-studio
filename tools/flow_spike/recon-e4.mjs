import * as y from './y0lib.mjs';
const { browser, page } = await y.attach();
await page.screenshot({ path: 'out/scene.jpg', type: 'jpeg', quality: 50, timeout: 10000 }).catch((e) => console.log(e.message));
const s = await y.snap(page, 'ext3'); console.log(s.split('\n').slice(-30).map((l) => l.trim().slice(0, 90)).join('\n'));
await browser.close(); process.exit(0);
