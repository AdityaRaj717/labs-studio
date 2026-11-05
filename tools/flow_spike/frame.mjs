// Latest run's video: argv[2] run-name fragment. Writes a mid frame to out/frame.jpg and prints the balance from the real panel.
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
const root = path.join(process.env.APPDATA, 'LabsStudio/outputs/runs');
const run = fs.readdirSync(root).filter((d) => d.includes(process.argv[2])).sort().pop();
const dir = path.join(root, run, 'videos');
for (const f of fs.readdirSync(dir)) console.log(path.join(dir, f), fs.statSync(path.join(dir, f)).size);
const file = path.join(dir, fs.readdirSync(dir)[0]);
const bin = 'D:/Apps/ffmpeg/ffmpeg-9.0.2-essentials_build/bin/';
console.log(execFileSync(`${bin}ffprobe.exe`, ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', file]).toString().trim());
execFileSync(`${bin}ffmpeg.exe`, ['-y', '-v', 'error', '-ss', process.argv[3] ?? '4', '-i', file, '-frames:v', '1', '-vf', 'scale=640:-1', 'out/frame.jpg']);
