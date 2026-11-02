// Recon: screenshot the open scene and dump timeline DOM near "Add clip". No spend.
import * as y from './y0lib.mjs';
const { browser, page } = await y.attach();
await page.screenshot({ path: 'out/scene.jpg', type: 'jpeg', quality: 60, timeout: 10000 }).catch((e) => console.log(e.message));
const dump = await page.evaluate(() => {
  const add = [...document.querySelectorAll('button')].find((b) => b.innerText.includes('Add clip') || b.getAttribute('aria-label') === 'Add clip');
  let el = add;
  for (let i = 0; i < 3 && el?.parentElement; i++) el = el.parentElement;
  const imgs = [...document.querySelectorAll('img[alt="Generated video thumbnail"]')].map((i) => { const r = i.getBoundingClientRect(); return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), src: i.src.slice(0, 70) }; });
  return { imgs, html: el?.outerHTML.replace(/style="[^"]*"/g, '').replace(/class="[^"]*"/g, '').slice(0, 2500) };
});
console.log(JSON.stringify(dump, null, 1));
await browser.close(); process.exit(0);
