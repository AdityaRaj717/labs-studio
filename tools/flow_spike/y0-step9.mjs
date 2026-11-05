import path from 'node:path';
import * as y from './y0lib.mjs';
const { page } = await y.attach();
let n=0;
for(let i=1;i<=10;i++){
  const r=await y.attachFile(page,path.join(y.OUT,`y0-lim-image-${i}.jpg`)).catch(e=>({err:e.message.split('\n')[0]}));
  console.log(i,JSON.stringify(r)); if(r.err){await y.closeOverlay(page);break;} if(r.chips===n){console.log('limit',n);break;} n=r.chips;
}
const s=await y.snap(page,'limit-video-end'); console.log(s.split('\n').filter(l=>/too many|limit|maximum|at most/i.test(l)).slice(0,4).join('\n'));
await page.reload({waitUntil:'domcontentloaded'}); process.exit(0);
