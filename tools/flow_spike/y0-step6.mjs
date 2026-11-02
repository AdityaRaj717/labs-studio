import path from 'node:path';
import fs from 'node:fs';
import * as y from './y0lib.mjs';
const { page } = await y.attach();
const base=page.url().match(/.*\/project\/[^/]+/)[0];

await page.goto(base,{waitUntil:'domcontentloaded'}); await y.locate(page,'project.prompt').waitFor({timeout:30000});
await y.directMode(page);
await y.settings(page,{kind:'image',model:'banana21',ratio:'16:9',count:1});
await y.locate(page,'project.addIngredients').click();
await y.locate(page,'picker.assetList').waitFor({timeout:10000});
await y.locate(page,'picker.tab.characters').click(); await page.waitForTimeout(2000);
await y.snap(page,'picker-characters');
await page.getByRole('option',{name:/y0 narrator/}).first().click();
const add=y.locate(page,'picker.addToPrompt'); await page.waitForTimeout(1200); await add.click({timeout:3000}).catch(()=>console.log("no add button, option attached directly"));
await page.waitForTimeout(1500); await y.closeOverlay(page);
await y.snap(page,'character-chip');
console.log('chips',await y.locate(page,'project.chip.ingredient').count());
await y.typePrompt(page,'The man from the reference sits alone on a bunk inside a concrete bunker, scratching a tally mark into the wall, candlelight, quiet and lonely mood');
const r=await y.submitAndWait(page,1); console.log('character shot',r.ok,r.seconds??r.reason);
if(r.ok) console.log(await y.download(page,0,'2K','y0-char-img01'));
// video ingredient limit, no generation
await y.settings(page,{kind:'video',mode:'ingredients',model:'omni',ratio:'16:9',count:1,resolution:'360p',duration:'4s'});
const src=path.join(y.OUT,'y0-place-md01.jpg'); let n=await y.locate(page,'project.chip.ingredient').count(); console.log('video chips start',n);
for(let i=1;i<=8;i++){const f=path.join(y.OUT,`y0-limv-${i}.jpg`);fs.copyFileSync(src,f);
 try{const c=await y.attachFile(page,f,{search:false});console.log('v',i,c.chips);if(c.chips===n){console.log('video limit',n);break;}n=c.chips;}catch(e){console.log('v refused',i,e.message.split('\n')[0]);await y.closeOverlay(page);break;}}
await y.snap(page,'limit-video-end');
await page.reload({waitUntil:'domcontentloaded'});
await y.settings; 
process.exit(0);
