import fs from 'fs';
import path from 'path';
import { createError, ErrorCodes } from '../utils/errors.js';

const MAX_PATH = 259; // Windows MAX_PATH less the terminator; ffmpeg and browsers may not accept longer paths.
const MAX_SLUG = 60;

// By code point, so a surrogate pair is never split.
function cut(text, max) {
  let out = '';
  for (const ch of text) {
    if (out.length + ch.length > max) break;
    out += ch;
  }
  return out;
}

// The seq prefix means a slug like CON can never be the whole stem, so reserved names are safe.
// shortcut: checks and returns without reserving, fine while one worker saves at a time; upgrade to open('wx') with parallel saves.
export function assetName(seq, prompt, version, ext, dir) {
  if (!Number.isInteger(seq) || seq < 0) throw createError(ErrorCodes.INVALID_PARAMS, `bad seq: ${seq}`, { next_action: 'Pass seq as a whole number.' });
  const safeExt = ext.toLowerCase().replace(/[^a-z0-9]/g, '');
  if (!safeExt) throw createError(ErrorCodes.INVALID_PARAMS, `bad file extension: ${ext}`, { next_action: 'Pass an extension such as mp4.' });
  const root = path.resolve(dir);
  const slug = prompt.normalize('NFC').toLowerCase().replace(/[^\p{L}\p{M}\p{N}]+/gu, '-').replace(/^-+/, '');

  for (let v = version; ; v++) {
    const tail = `_v${v}.${safeExt}`;
    const room = MAX_PATH - root.length - 1 - `${seq}_`.length - tail.length;
    const stem = cut(slug, Math.min(MAX_SLUG, room)).replace(/-+$/, '') || 'asset';
    const file = path.join(root, `${seq}_${stem}${tail}`);
    if (file.length > MAX_PATH) {
      throw createError(ErrorCodes.INVALID_PARAMS, `output folder path is too long: ${root}`, { next_action: 'Use a shorter output_root.' });
    }
    if (!fs.existsSync(file)) return file;
  }
}
