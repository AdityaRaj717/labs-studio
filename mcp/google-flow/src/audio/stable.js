// Stable Audio 3, per docs.stability.ai/api-reference/stable-audio/text-to-audio, read 2026-11-02.
import { createError, ErrorCodes } from '../utils/errors.js';
import { fetchRetrying, invalid, keyFor, oneAtATime, realSleep, REQUEST_TIMEOUT_MS, runFor, saveAudio, scrub } from './common.js';

const POST_URL = 'https://api.stability.ai/v2beta/audio/stable-audio/text-to-audio';
const RESULT_URL = 'https://api.stability.ai/v2beta/audio/results';
const MODEL = 'stable-audio-3';
export const STABILITY_CREDITS = 8;
const POLL_MS = 10000; // the docs' own examples
const POLL_LIMIT_MS = 300000;
const FOLDERS = { music: 'bgm', sfx: 'sfx' };
const MAX_PROMPT = 10000;

const inRange = (value, min, max) => Number.isFinite(value) && value >= min && value <= max;

function validate({ kind, prompt, duration, seed, steps, cfg_scale, output_format }) {
  if (!FOLDERS[kind]) throw invalid('kind must be music or sfx');
  if (typeof prompt !== 'string' || !prompt.trim() || prompt.length > MAX_PROMPT) throw invalid(`prompt must be 1 to ${MAX_PROMPT} characters`);
  // Always sent: left out, the API makes 190 s at the same price.
  if (!inRange(duration, 1, 380)) throw invalid('duration must be 1 to 380 seconds');
  if (seed !== undefined && !inRange(seed, 0, 4294967294)) throw invalid('seed must be 0 to 4294967294');
  if (!Number.isInteger(steps) || !inRange(steps, 4, 8)) throw invalid('steps must be a whole number, 4 to 8');
  if (!inRange(cfg_scale, 1, 25)) throw invalid('cfg_scale must be 1 to 25');
  if (!['wav', 'mp3'].includes(output_format)) throw invalid('output_format must be wav or mp3');
}

async function failure(res, key) {
  const body = await res.json().catch(() => ({}));
  const message = scrub((body.errors ?? []).join('; ') || body.name || `HTTP ${res.status}`, key);
  if (res.status === 401) return createError(ErrorCodes.MISSING_API_KEY, 'Stability refused the API key', { next_action: "Check the Stability key in the app's API keys tab." });
  if (res.status === 402) return createError(ErrorCodes.AUDIO_NO_CREDIT, `Stability has no credits left: ${message}`);
  if (res.status === 403) return createError(ErrorCodes.SAFETY_BLOCKED, `Stability's moderation refused this, at no charge: ${message}`, { next_action: 'Reword the prompt and call again.' });
  if (res.status === 422) return createError(ErrorCodes.GENERATION_REFUSED, `Stability refused this, at no charge: ${message}`);
  if (res.status === 400) return invalid(`Stability refused the request: ${message}`);
  return createError(ErrorCodes.INTERNAL_ERROR, `Stability answered ${res.status}: ${message}`);
}

export function createStable({ getSecret, fetch = globalThis.fetch, sleep = realSleep, now = Date.now }) {
  async function poll(id, key, accept) {
    const deadline = now() + POLL_LIMIT_MS;
    for (;;) {
      await sleep(POLL_MS);
      // A dropped poll costs nothing, so it just waits for the next one.
      const res = await fetch(`${RESULT_URL}/${id}`, { headers: { authorization: `Bearer ${key}`, accept }, signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) }).catch(() => null);
      if (res?.status === 200) return Buffer.from(await res.arrayBuffer());
      if (res && res.status !== 202 && res.status !== 429 && res.status < 500) throw await failure(res, key);
      if (now() >= deadline) {
        throw createError(ErrorCodes.GENERATION_TIMEOUT, `Stable Audio had no result in ${POLL_LIMIT_MS / 1000} s`, { credits_at_risk: true, generation_id: id, next_action: 'Stability keeps results for 24 hours; the charge applies if it finishes.' });
      }
    }
  }

  function generate(args) {
    const { kind, prompt, duration, seed, steps = 8, cfg_scale = 1, output_format = 'wav', name, auto_confirm } = args;
    validate({ kind, prompt, duration, seed, steps, cfg_scale, output_format });
    if (auto_confirm !== true) return { status: 'ready_for_confirmation', estimated_stability_credits: STABILITY_CREDITS, next_action: 'Call again with auto_confirm: true to spend them.' };
    const key = keyFor(getSecret, 'STABILITY_API_KEY', 'Stability');
    const form = new FormData();
    Object.entries({ prompt, model: MODEL, duration, steps, cfg_scale, output_format, ...(seed !== undefined ? { seed } : {}) })
      .forEach(([field, value]) => form.append(field, String(value)));
    const run = runFor(args);
    const accept = 'audio/*';
    return oneAtATime(async () => {
      const started = await fetchRetrying({ fetch, sleep, label: 'Stability', url: POST_URL, init: { method: 'POST', headers: { authorization: `Bearer ${key}`, accept: 'application/json' }, body: form } });
      if (started.status !== 202) throw await failure(started, key);
      const { id } = await started.json();
      const bytes = await poll(id, key, accept);
      const entry = saveAudio(run, { folder: FOLDERS[kind], name: name || prompt.slice(0, 40), ext: output_format, bytes, meta: { provider: 'stability', model: MODEL, prompt, duration, stability_credits: STABILITY_CREDITS } });
      return { run_id: run.id, ...entry };
    });
  }

  return { generate };
}
