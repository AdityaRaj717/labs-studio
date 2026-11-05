// Recon: on the open scene, try Download scene and keep the file. No generation spend.
import * as y from './y0lib.mjs';
const { browser, page } = await y.attach();
console.log(page.url());
await page.getByRole('button', { name: 'Download scene' }).click();
await page.waitForTimeout(1500);
const items = await page.getByRole('menuitem').allTextContents();
console.log('menu', items);
const s = await y.snap(page, 'scene-dl');
console.log(s.split('\n').slice(-25).map((l) => l.trim().slice(0, 100)).join('\n'));
await page.screenshot({ path: 'out/scene.jpg', type: 'jpeg', quality: 50, timeout: 10000 }).catch((e) => console.log(e.message));
await browser.close(); process.exit(0);
