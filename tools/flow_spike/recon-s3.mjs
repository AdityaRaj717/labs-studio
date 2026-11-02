// Recon: click Download scene, watch toast text and wait for the download event.
import path from 'node:path';
import * as y from './y0lib.mjs';
const { browser, page } = await y.attach();
const started = Date.now();
const got = page.waitForEvent('download', { timeout: 300000 }).catch((e) => e);
const toast = () => page.locator('body').ariaSnapshot().then((s) => s.split('\n').slice(-4).map((l) => l.trim()).join(' | ').slice(0, 200));
await page.getByRole('button', { name: 'Download scene' }).click();
let dl;
got.then((d) => { dl = d; });
while (!dl && Date.now() - started < 300000) {
  await page.waitForTimeout(5000);
  console.log(Math.round((Date.now() - started) / 1000), await toast());
}
if (dl?.suggestedFilename) {
  const file = path.join(y.OUT, `scene-${dl.suggestedFilename()}`);
  await dl.saveAs(file);
  console.log('saved', file);
} else console.log('no download', String(dl));
await browser.close(); process.exit(0);
