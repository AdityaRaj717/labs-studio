import path from 'node:path';
import { execFileSync } from 'node:child_process';
import * as y from './y0lib.mjs';
const { browser, page } = await y.attach();
console.log(page.url());
const clips = await page.evaluate(() => [...document.querySelectorAll('video,[class*=clip i]')].slice(0, 12).map((e) => e.tagName + '.' + String(e.className).slice(0, 40) + ' ' + (e.innerText || '').replace(/\s+/g, ' ').slice(0, 40) + ' ' + (e.duration || '')));
console.log(clips.join('\n'));
await page.getByRole('button', { name: 'Download scene' }).click(); await page.waitForTimeout(1500);
const menu = (await y.snap(page, 'ext2')).split('\n').filter((l) => /menuitem|dialog|radio/.test(l)).map((l) => l.trim().slice(0, 80)); console.log('menu', menu.join(' | '));
const item = page.getByRole('menuitem').filter({ hasText: /720p/ }).first();
if (await item.count()) { const d = page.waitForEvent('download', { timeout: 180000 }); await item.click(); const dl = await d; const file = path.join(y.OUT, 'scene-' + dl.suggestedFilename()); await dl.saveAs(file); console.log(file, execFileSync('D:/Apps/ffmpeg/ffmpeg-9.0.2-essentials_build/bin/ffprobe.exe', ['-v', 'error', '-show_entries', 'stream=codec_type,width,height:format=duration', '-of', 'csv=p=0', file]).toString().replace(/\r?\n/g, ' ; ')); }
await browser.close(); process.exit(0);
