import fs from 'fs';
import { contract } from './contract.js';

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

const labelShown = (key, info) => new RegExp(contract.keys[key].name.regex.replace(/\$$/, '')).test(info);

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
  // Only a different recognised model is a mismatch; text with no model label is just recorded by the caller.
  mismatches.push(...modelMismatch('image', model, info));
  return { ok: mismatches.length === 0, mismatches, ...size };
}

function modelMismatch(kind, model, info) {
  if (!info || !model || labelShown(`settings.model.${kind}.${model}`, info)) return [];
  const other = Object.keys(contract.keys).find((key) => key.startsWith('settings.model.') && labelShown(key, info));
  return other ? [`model: Flow reports "${info}", not ${model}`] : [];
}

const DURATION_TOLERANCE = 0.5;

// probe comes from probeVideo.
export function verifyVideo(probe, { ratio, duration, resolution, model, silent, info }) {
  const mismatches = [];
  const [w, h] = ratio.split(':').map(Number);
  const got = probe.width / probe.height;
  if (Math.abs(got - w / h) / (w / h) > RATIO_TOLERANCE) mismatches.push(`ratio ${probe.width}x${probe.height} is not ${ratio}`);
  if (resolution && Math.min(probe.width, probe.height) !== parseInt(resolution, 10)) mismatches.push(`resolution ${probe.width}x${probe.height} is not ${resolution}`);
  if (duration && Math.abs(probe.duration - duration) > DURATION_TOLERANCE) mismatches.push(`duration ${probe.duration}s is not ${duration}s`);
  if (silent && probe.audio_streams > 0) mismatches.push(`${probe.audio_streams} audio stream(s) in a silent video`);
  mismatches.push(...modelMismatch('video', model, info));
  return { ok: mismatches.length === 0, mismatches, width: probe.width, height: probe.height, duration: probe.duration, audio_streams: probe.audio_streams };
}
