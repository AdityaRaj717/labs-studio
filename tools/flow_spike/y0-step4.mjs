import path from 'node:path';
import { execFileSync } from 'node:child_process';
import * as y from './y0lib.mjs';
const FF='D:/Apps/ffmpeg/ffmpeg-9.0.2-essentials_build/bin/ffprobe.exe';
const probe=f=>execFileSync(FF,['-v','error','-show_entries','stream=codec_type,width,height,duration','-of','csv=p=0',f]).toString().trim().replace(/\r?\n/g,' ; ');
const { page } = await y.attach();
await y.directMode(page);
const still=path.join(y.OUT,'y0-ing-img01.jpg'), sheet=path.join(y.OUT,'y0-sheet-md02.jpg');
// Frames
let s=await y.settings(page,{kind:'video',mode:'frames',model:'omni',ratio:'16:9',count:1,resolution:'360p',duration:'4s'}); console.log('frames quote',s);
await y.snap(page,'frames-composer');
await y.locate(page,'project.chip.start').click();
await y.locate(page,'picker.assetList').waitFor({timeout:10000});
await y.snap(page,'frames-picker');
const chooser=page.waitForEvent('filechooser',{timeout:15000});
await y.locate(page,'picker.upload').click();
await (await chooser).setFiles(still);
await page.waitForTimeout(8000);
await y.snap(page,'frames-uploaded');
const opt=page.getByRole('option',{name:/^y0-ing-img01\.jpg/}).first();
await opt.click(); 
const add=y.locate(page,'picker.addToPrompt'); if(await add.isVisible()) await add.click();
await page.waitForTimeout(2000); await y.closeOverlay(page);
await y.snap(page,'frames-chip-set');
await y.typePrompt(page,'The man slowly finishes the tally mark and lowers his hand, candle flames flicker, subtle camera push in');
let r=await y.submitAndWait(page,1,{video:true}); console.log('frames',r.ok,r.seconds??r.reason,r.log.slice(-1));
if(r.ok){const f=await y.download(page,0,'360p','y0-vid-frames'); console.log(f,probe(f));}
// Ingredients
s=await y.settings(page,{kind:'video',mode:'ingredients',model:'omni',ratio:'16:9',count:1,resolution:'360p',duration:'4s'}); console.log('ingr quote',s);
await y.snap(page,'ingredients-composer');
console.log('chips before', await y.locate(page,'project.chip.ingredient').count());
console.log(await y.attachFile(page,sheet));
await y.typePrompt(page,'The man from the reference walks toward the camera down a dim concrete corridor, flashlight in hand');
r=await y.submitAndWait(page,1,{video:true}); console.log('ingredients',r.ok,r.seconds??r.reason,r.log.slice(-1));
if(r.ok){const f=await y.download(page,0,'360p','y0-vid-ingredients'); console.log(f,probe(f));}
process.exit(0);
