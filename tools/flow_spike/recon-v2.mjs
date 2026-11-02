import * as y from './y0lib.mjs';
const { browser, page } = await y.attach();
const read = () => y.locate(page, 'project.tile').evaluateAll((els) => els.slice(0, 3).map((el) => { const i = el.querySelector('img'); return { l: el.getAttribute('aria-label'), alt: i?.alt, src: i?.getAttribute('src')?.slice(0, 70), text: el.innerText.slice(0, 30), vid: !!el.querySelector('video'), vsrc: el.querySelector('video')?.getAttribute('src')?.slice(0, 70) }; }));
console.log(JSON.stringify(await read()));
await page.waitForTimeout(3000); console.log(JSON.stringify(await read()));
await page.reload({ waitUntil: 'domcontentloaded' }); await y.locate(page, 'project.prompt').waitFor({ timeout: 30000 }); await page.waitForTimeout(4000);
console.log(JSON.stringify(await read()));
await browser.close(); process.exit(0);
