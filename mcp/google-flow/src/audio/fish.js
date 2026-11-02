// Fish Audio API, per docs.fish.audio/api-reference (openapi-v1 text-to-speech, list models), read 2026-11-02.
import { createError, ErrorCodes } from '../utils/errors.js';
import { fetchRetrying, invalid, keyFor, oneAtATime, realSleep, runFor, saveAudio, scrub } from './common.js';

const TTS_URL = 'https://api.fish.audio/v1/tts';
const MODELS_URL = 'https://api.fish.audio/model';
export const FREE_MODEL = 's2.1-pro-free';
// The API turns an unknown model name into paid s2.1-pro, so anything else is refused here.
const MODELS = [FREE_MODEL, 's2.1-pro', 's2-pro', 's1', 'drama-3'];
const FORMATS = ['mp3', 'wav', 'pcm', 'opus'];
const JOINABLE = ['mp3', 'pcm']; // both play when their bytes are simply put end to end
const MAX_SEGMENT = 1500;
const MAX_PAGE = 100;

// shortcut: splits on . ! ? and newlines only, upgrade if a language with other sentence marks needs it.
export function splitText(text, max = MAX_SEGMENT) {
  const sentences = text.match(/[^.!?。！？\n]+[.!?。！？\n]*\s*/gu) ?? [text];
  const segments = [];
  let current = '';
  for (const sentence of sentences) {
    if (current && current.length + sentence.length > max) {
      segments.push(current.trim());
      current = '';
    }
    for (let rest = sentence; rest; rest = rest.slice(max)) {
      if (rest.length <= max) current += rest;
      else segments.push(rest.slice(0, max));
      if (rest.length <= max) break;
    }
  }
  if (current.trim()) segments.push(current.trim());
  return segments;
}

function failure(res, body, key) {
  const message = scrub(body.message ?? body.reason ?? `HTTP ${res.status}`, key);
  if (res.status === 401) return createError(ErrorCodes.MISSING_API_KEY, 'Fish Audio refused the API key', { next_action: "Check the Fish Audio key in the app's API keys tab." });
  if (res.status === 402) return createError(ErrorCodes.AUDIO_NO_CREDIT, `Fish Audio has no credit for this model: ${message}`, { next_action: `Top up Fish Audio, or use ${FREE_MODEL}. Nothing moved to another model.` });
  if (res.status === 400 || res.status === 422) return invalid(`Fish Audio refused the request: ${message}`);
  return createError(ErrorCodes.INTERNAL_ERROR, `Fish Audio answered ${res.status}: ${message}`);
}

const errorBody = (res) => res.json().catch(() => ({}));

export function createFish({ getSecret, fetch = globalThis.fetch, sleep = realSleep }) {
  async function speak(key, model, body) {
    const res = await fetchRetrying({
      fetch,
      sleep,
      label: 'Fish Audio',
      url: TTS_URL,
      init: { method: 'POST', headers: { authorization: `Bearer ${key}`, 'content-type': 'application/json', model }, body: JSON.stringify(body) },
    });
    if (!res.ok) throw failure(res, await errorBody(res), key);
    return Buffer.from(await res.arrayBuffer());
  }

  function generate(args) {
    const { text, script, voice_id, name, format = 'mp3', speed, volume, temperature, top_p, model = FREE_MODEL, language } = args;
    const words = text ?? script;
    if (typeof words !== 'string' || !words.trim()) throw invalid('Pass text or script');
    if (!MODELS.includes(model)) throw invalid(`model must be one of: ${MODELS.join(', ')}`);
    if (!FORMATS.includes(format)) throw invalid(`format must be one of: ${FORMATS.join(', ')}`);
    const key = keyFor(getSecret, 'FISH_API_KEY', 'Fish Audio');
    const segments = splitText(words);
    if (segments.length > 1 && !JOINABLE.includes(format)) throw invalid(`Text this long is split into ${segments.length} parts, which only join as: ${JOINABLE.join(', ')}`);
    const prosody = { ...(speed !== undefined ? { speed } : {}), ...(volume !== undefined ? { volume } : {}) };
    const shared = {
      format,
      ...(voice_id ? { reference_id: voice_id } : {}),
      ...(Object.keys(prosody).length ? { prosody } : {}),
      ...(temperature !== undefined ? { temperature } : {}),
      ...(top_p !== undefined ? { top_p } : {}),
      ...(language ? { language } : {}),
    };
    const run = runFor(args);
    return oneAtATime(async () => {
      const parts = [];
      for (const segment of segments) parts.push(await speak(key, model, { ...shared, text: segment }));
      const entry = saveAudio(run, { folder: 'voice', name: name || words.slice(0, 40), ext: format, bytes: Buffer.concat(parts), meta: { provider: 'fish', model, voice_id: voice_id ?? null, segments: segments.length } });
      return { run_id: run.id, ...entry };
    });
  }

  async function list({ query, mine, limit = 20 } = {}) {
    const key = keyFor(getSecret, 'FISH_API_KEY', 'Fish Audio');
    const params = new URLSearchParams({ page_size: String(Math.min(limit, MAX_PAGE)) });
    if (query) params.set('title', query);
    if (mine) params.set('self', 'true');
    const res = await fetchRetrying({ fetch, sleep, label: 'Fish Audio', url: `${MODELS_URL}?${params}`, init: { headers: { authorization: `Bearer ${key}` } } });
    if (!res.ok) throw failure(res, await errorBody(res), key);
    const { total, items } = await res.json();
    return { total, voices: items.map(({ _id, title, languages }) => ({ voice_id: _id, title, languages })) };
  }

  return { generate, list };
}
