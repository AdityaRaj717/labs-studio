import { getCapabilities } from '../engine/capabilities.js';
import { beat } from '../engine/pacer.js';
import { get } from '../utils/config.js';
import { runGeneration, sha256 } from './image.js';
import { addFrame } from './ingredients.js';
import { probeVideo, stripAudio } from './silent.js';
import { verifyVideo } from './verify.js';

const isOmni = ({ model }) => model === 'omni';

const VIDEO = {
  dir: 'videos',
  size: (spec) => spec.resolution,
  timeoutMs: get('videoTimeoutMs', 900000),
  settings(spec) {
    const { models } = getCapabilities().video;
    return {
      ...spec,
      mode: spec.mode === 'ingredients' ? 'ingredients' : 'frames', // text is frames mode with empty chips
      // Veo has no duration or resolution control on Pro.
      resolution: isOmni(spec) ? spec.resolution : undefined,
      duration: isOmni(spec) ? spec.duration : undefined,
      maxCredits: spec.max_credits ?? models[spec.model].credits[spec.resolution][spec.duration] * spec.count,
    };
  },
  async attachMore(page, spec, signal) {
    for (const [key, which] of [['start_frame', 'start'], ['end_frame', 'end']]) {
      if (!spec[key]) continue;
      signal.throwIfAborted();
      await addFrame(page, spec[key], which);
      await beat(page);
    }
  },
  async check(file, spec, info) {
    const silent = spec.silent ? await stripAudio(file) : null;
    return {
      resolution: spec.resolution,
      duration_requested: spec.duration,
      ...(silent ? { original: silent.original } : {}),
      sha256: sha256(file),
      ...verifyVideo(await probeVideo(file), { ...spec, info }),
    };
  },
};

export const runVideoJob = (ctx, job) => runGeneration(ctx, job, VIDEO);
