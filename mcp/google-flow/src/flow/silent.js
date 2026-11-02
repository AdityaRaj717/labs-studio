import { execFile } from 'child_process';
import fs from 'fs';
import path from 'path';
import { promisify } from 'util';
import { get } from '../utils/config.js';
import { createError, ErrorCodes } from '../utils/errors.js';

const run = promisify(execFile);
const RUN_MS = 120000;
const FALLBACK_DIR = 'D:\\Apps\\ffmpeg\\ffmpeg-9.0.2-essentials_build\\bin';

// Setting, then env, then PATH, then the known folder; ffprobe sits beside ffmpeg.
async function tool(name, ffmpegPath = get('ffmpegPath') ?? process.env.FFMPEG_PATH) {
  const candidates = [
    ...(ffmpegPath ? [path.join(path.dirname(ffmpegPath), name)] : []),
    name,
    path.join(FALLBACK_DIR, name),
  ];
  for (const bin of candidates) {
    try {
      await run(bin, ['-version'], { timeout: RUN_MS });
      return bin;
    } catch { /* next */ }
  }
  throw createError(ErrorCodes.FFMPEG_NOT_FOUND, `${name} not found`, { next_action: 'Set ffmpegPath in the engine settings or FFMPEG_PATH.' });
}

export async function checkFfmpeg() {
  await tool('ffmpeg');
  await tool('ffprobe');
}

export async function probeVideo(file, { ffmpegPath } = {}) {
  const { stdout } = await run(await tool('ffprobe', ffmpegPath), ['-v', 'error', '-show_entries', 'stream=codec_type,width,height:format=duration', '-of', 'json', file], { timeout: RUN_MS });
  const { streams, format } = JSON.parse(stdout);
  const video = streams.find(({ codec_type: type }) => type === 'video');
  return { width: video?.width ?? 0, height: video?.height ?? 0, duration: Number(format.duration), audio_streams: streams.filter(({ codec_type: type }) => type === 'audio').length };
}

// Flow's own toggle does not silence (spike C11). The stripped file takes the normal name; a repeat strips from the kept original.
export async function stripAudio(file, { ffmpegPath } = {}) {
  const dir = path.join(path.dirname(file), '_original');
  const original = path.join(dir, `${path.parse(file).name}.flow.mp4`);
  fs.mkdirSync(dir, { recursive: true });
  if (!fs.existsSync(original)) fs.renameSync(file, original);
  const part = `${file}.part.mp4`;
  await run(await tool('ffmpeg', ffmpegPath), ['-y', '-v', 'error', '-i', original, '-an', '-c', 'copy', part], { timeout: RUN_MS });
  fs.renameSync(part, file);
  return { file, original, audio_streams: (await probeVideo(file, { ffmpegPath })).audio_streams };
}
