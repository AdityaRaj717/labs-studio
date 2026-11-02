import * as y from './y0lib.mjs';
const { browser, page } = await y.attach();
const f = (s) => s.split('\n').filter((l) => /button|textbox|menuitem|%|credit/i.test(l)).map(l=>l.trim().slice(0,80));
console.log(page.url());
await y.locate(page, 'editor.addClip').first().click(); await page.waitForTimeout(800);
await y.locate(page, 'editor.menu.extend').click(); await page.waitForTimeout(1500);
const box = y.locate(page, 'editor.extendPrompt'); await box.click(); await page.keyboard.type('The fox stops and looks back at the camera', { delay: 15 });
await page.waitForTimeout(800);
const before = f(await y.snap(page, 'ext0')); console.log(before.filter((l) => /credit/i.test(l)));
await y.locate(page, 'project.start').click();
const t0 = Date.now(); let last = '';
while (Date.now() - t0 < 180000) { const txt = await page.locator('body').innerText(); const m = (txt.match(/\d+%/g) || []).join(','); const clips = await page.getByRole('button', { name: /clip|Fox/ }).count(); const key = m + '|' + clips + '|' + page.url().slice(-36); if (key !== last) { console.log(Math.round((Date.now() - t0) / 1000), key); last = key; } if (Date.now() - t0 > 40000 && !m) break; await page.waitForTimeout(2000); }
const after = f(await y.snap(page, 'ext1')); console.log(after.slice(0, 40).join('\n')); console.log(page.url());
await browser.close(); process.exit(0);
