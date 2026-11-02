// Y0 step 2: upload sheet and place, generate IMG_01 and IMG_04, check search reuse, chip clearing, limit.
import path from 'node:path';
import fs from 'node:fs';
import * as y from './y0lib.mjs';
const IMG01='The man from the reference sits alone on the bunk inside the concrete bunker from the reference, scratching a fortieth tally mark into the wall, candlelight, quiet and lonely mood';
const IMG04='The man from the reference sits at a small crate table in the bunker from the reference, eating from one can of beans by candlelight, wary glance, warm amber light';
const { page } = await y.attach();
await y.directMode(page);
const sheet=path.join(y.OUT,'y0-sheet-md02.jpg'), place=path.join(y.OUT,'y0-place-md01.jpg');
console.log('sheet', await y.attachFile(page, sheet));
console.log('place', await y.attachFile(page, place));
await y.snap(page,'chips-attached');
await y.typePrompt(page, IMG01);
let r=await y.submitAndWait(page,1); console.log('IMG01',r.ok,r.seconds??r.reason);
console.log(await y.download(page,0,'2K','y0-ing-img01'));
console.log('chips after job', await y.locate(page,'project.chip.ingredient').count());
await y.snap(page,'after-job-chips');
const left=await y.locate(page,'project.chip.ingredient').count();
if(!left){ console.log('sheet again', await y.attachFile(page, sheet)); console.log('place again', await y.attachFile(page, place)); }
await y.typePrompt(page, IMG04);
r=await y.submitAndWait(page,1); console.log('IMG04',r.ok,r.seconds??r.reason);
console.log(await y.download(page,0,'2K','y0-ing-img04'));
process.exit(0);
