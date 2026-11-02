// Y0 step 3-4: ingredient limits per mode, then Omni Frames with an uploaded Still and Omni Ingredients with the sheet.
import path from 'node:path';
import fs from 'node:fs';
import * as y from './y0lib.mjs';
const { page } = await y.attach();
await y.directMode(page);
const src=path.join(y.OUT,'y0-place-md01.jpg');
const limit=async(kind,max)=>{
  let n=await y.locate(page,'project.chip.ingredient').count();
  for(let i=1;i<=max;i++){
    const f=path.join(y.OUT,`y0-lim-${kind}-${i}.jpg`); fs.copyFileSync(src,f);
    try{ const r=await y.attachFile(page,f,{search:false}); console.log(kind,i,r.chips);
      if(r.chips===n){console.log(kind,'limit',n);break;} n=r.chips; }
    catch(e){ console.log(kind,'refused at',i,e.message.split('\n')[0]); await y.snap(page,`limit-${kind}`); await y.closeOverlay(page); break; }
  }
  await y.snap(page,`limit-${kind}-end`);
  return n;
};
console.log('image max', await limit('image',16));
await page.reload({waitUntil:'domcontentloaded'}); await y.locate(page,'project.prompt').waitFor({timeout:30000}); await y.directMode(page);
console.log('chips after reload', await y.locate(page,'project.chip.ingredient').count());
process.exit(0);
