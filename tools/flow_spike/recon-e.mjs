import * as y from './y0lib.mjs';
const { browser, page } = await y.attach();
const f = (s) => s.split('\n').filter((l) => /button|textbox|menuitem|radio/.test(l) && !/^\s+- button "[A-Z][a-z]+ [a-z].*":$/.test(l)).join('\n');
await page.getByRole('button', { name: 'Fox trotting through snow' }).first().click(); await page.waitForTimeout(5000);
console.log(page.url()); console.log(f(await y.snap(page, 'editor1')));
const add = y.locate(page, 'editor.addClip');
console.log('addClip', await add.count());
if (await add.count()) { await add.first().click(); await page.waitForTimeout(1200); console.log('--menu\n' + f(await y.snap(page, 'editor2')).split('\n').filter((l) => /menuitem/.test(l)).join('\n')); const ext = y.locate(page, 'editor.menu.extend'); if (await ext.isEnabled()) { await ext.click(); await page.waitForTimeout(2500); console.log('--extend\n' + f(await y.snap(page, 'editor3'))); console.log(page.url()); await y.locate(page,'editor.exitExtend').click().catch(()=>{}); } }
await browser.close(); process.exit(0);
