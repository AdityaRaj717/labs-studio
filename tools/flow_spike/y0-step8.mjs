import * as y from './y0lib.mjs';
const { page } = await y.attach();
await page.reload({waitUntil:'domcontentloaded'}); await y.locate(page,'project.prompt').waitFor({timeout:30000}); await page.waitForTimeout(3000);
const t=y.tiles(page); const n=await t.count(); console.log('tiles',n);
for(let i=0;i<Math.min(n,4);i++){const e=t.nth(i);console.log(i,(await e.getAttribute('aria-label')||'').slice(0,50),'|',await e.locator('img').evaluateAll(a=>a.map(x=>x.alt)));}
await y.directMode(page);
await y.settings(page,{kind:'video',mode:'ingredients',model:'omni',ratio:'16:9',count:1,resolution:'360p',duration:'4s'});
console.log('chips',await y.locate(page,'project.chip.ingredient').count());
await y.locate(page,'project.addIngredients').click(); await page.waitForTimeout(1500);
const s=await y.snap(page,'video-ingredients-picker');
console.log(s.split('\n').filter(l=>/Upload|Asset list|tab |Add ingredients/.test(l)).join('\n'));
await y.closeOverlay(page); process.exit(0);
