import * as y from './y0lib.mjs';
const { browser, page } = await y.attach();
console.log(page.url());
console.log(await y.tiles(page).evaluateAll((els) => els.slice(0, 8).map((e) => [e.getAttribute('aria-label'), e.innerText.slice(0, 50), !!e.querySelector('video,img[alt="Generated video thumbnail"]')])));
await browser.close(); process.exit(0);
