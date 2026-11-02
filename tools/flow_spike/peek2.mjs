import * as y from './y0lib.mjs';
const { browser, page } = await y.attach();
await page.screenshot({ path: 'out/now.jpg', type: 'jpeg', quality: 45, timeout: 10000 }).catch((e) => console.log(e.message));
console.log(page.url(), await page.getByRole('button', { name: 'Upload media' }).count(), await page.locator('button.empty-chip').count());
await browser.close(); process.exit(0);
