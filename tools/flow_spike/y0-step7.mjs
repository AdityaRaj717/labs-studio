import path from 'node:path';
import fs from 'node:fs';
import * as y from './y0lib.mjs';
const { page } = await y.attach();
await y.closeOverlay(page); await page.mouse.click(5,5);
const t=y.tiles(page); const n=await t.count(); console.log('tiles',n);
for(let i=0;i<Math.min(n,5);i++){const e=t.nth(i);console.log(i,await e.getAttribute('aria-label'),'|imgs',await e.locator('img').evaluateAll(a=>a.map(x=>x.alt)),'|',(await e.innerText()).slice(0,40).replace(/\s+/g,' '));}
console.log('groups', await page.getByRole('group',{name:'y0 narrator'}).count(), await page.getByRole('group',{name:'y0 narrator'}).first().evaluate(e=>e.tagName+' '+e.parentElement.tagName));
let idx=-1; for(let i=0;i<Math.min(n,5);i++){ if(/sits alone on a bunk|bunk/i.test(await t.nth(i).getAttribute('aria-label')||'')&&idx<0) idx=i; }
console.log('idx',idx);
const e=t.nth(idx<0?0:idx); await e.hover(); await e.getByRole('button',{name:'More options'}).click(); await page.waitForTimeout(500);
console.log((await y.snap(page,'tile-menu')).split('\n').filter(l=>/menuitem/.test(l)).join('\n'));
await page.getByRole('menuitem',{name:'Download'}).click(); await page.waitForTimeout(500);
console.log((await y.snap(page,'tile-menu2')).split('\n').filter(l=>/menuitem/.test(l)).join('\n'));
const w=page.waitForEvent('download',{timeout:60000}); await page.getByRole('menuitem',{name:/^2K/}).click(); const d=await w; const f=path.join(y.OUT,'y0-char-img01.jpg'); await d.saveAs(f); console.log(f, d.suggestedFilename());
// video limit
await y.settings(page,{kind:'video',mode:'ingredients',model:'omni',ratio:'16:9',count:1,resolution:'360p',duration:'4s'});
const src=path.join(y.OUT,'y0-place-md01.jpg'); let c=await y.locate(page,'project.chip.ingredient').count(); console.log('video chips start',c);
for(let i=1;i<=8;i++){const x=path.join(y.OUT,`y0-limv-${i}.jpg`);fs.copyFileSync(src,x);
 try{const r=await y.attachFile(page,x,{search:false});console.log('v',i,r.chips);if(r.chips===c){console.log('video limit',c);break;}c=r.chips;}catch(er){console.log('v refused',i,er.message.split('\n')[0]);await y.closeOverlay(page);break;}}
const s=await y.snap(page,'limit-video-end'); console.log(s.split('\n').filter(l=>/too many|limit|maximum|Dismiss/i.test(l)).slice(0,5).join('\n'));
await page.reload({waitUntil:'domcontentloaded'});
process.exit(0);
