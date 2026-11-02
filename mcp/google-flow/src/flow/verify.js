import fs from 'fs';
import { modelPattern } from './settings.js';

const RATIO_TOLERANCE = 0.03; // 16:9 images come back 1.79:1

// Walks JPEG segments to the frame header. null for anything else; Flow's downloads are JPEG.
function jpegSize(buffer) {
  if (buffer[0] !== 0xff || buffer[1] !== 0xd8) return null;
  for (let i = 2; i + 9 <= buffer.length;) {
    if (buffer[i] !== 0xff) return null;
    const marker = buffer[i + 1];
    if (marker >= 0xc0 && marker <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(marker)) {
      return { height: buffer.readUInt16BE(i + 5), width: buffer.readUInt16BE(i + 7) };
    }
    i += 2 + buffer.readUInt16BE(i + 2);
  }
  return null;
}

// request: { ratio, model?, info? }, info being the text Flow shows for the asset.
export function verifyImage(file, { ratio, model, info }) {
  const size = jpegSize(fs.readFileSync(file));
  const mismatches = [];
  if (!size) {
    mismatches.push('not a readable JPEG');
  } else {
    const [w, h] = ratio.split(':').map(Number);
    const wanted = w / h;
    const got = size.width / size.height;
    if (Math.abs(got - wanted) / wanted > RATIO_TOLERANCE) mismatches.push(`ratio ${size.width}x${size.height} is not ${ratio}`);
  }
  if (info && model) {
    const label = new RegExp(modelPattern('image', model).source.replace(/\$$/, ''));
    if (!label.test(info)) mismatches.push(`model: Flow reports "${info}", not ${model}`);
  }
  return { ok: mismatches.length === 0, mismatches, ...size };
}
