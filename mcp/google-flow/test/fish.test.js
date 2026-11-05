import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import config from '../src/utils/config.js';
import { createFish, splitText } from '../src/audio/fish.js';

config.dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'audio-data-'));
const KEY = 'test-value-not-a-real-key';
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'fish-'));
const audio = (text = 'x', status = 200) => new Response(text, { status });
const json = (body, status) => new Response(JSON.stringify(body), { status });

function fish(replies, key = KEY) {
  const calls = [];
  const sleeps = [];
  const client = createFish({
    getSecret: () => key,
    sleep: async (ms) => { sleeps.push(ms); },
    fetch: async (url, init) => {
      calls.push({ url, init, body: init.body && JSON.parse(init.body) });
      const reply = typeof replies === 'function' ? replies(calls.length) : replies.shift();
      if (reply instanceof Error) throw reply;
      return reply;
    },
  });
  return { client, calls, sleeps };
}
const say = (client, extra) => client.generate({ text: 'Hello.', output_root: root, ...extra });
const code = (error_code) => (err) => { assert.equal(err.code, error_code); return true; };

test('model header is always sent, default is the free model', async () => {
  const { client, calls } = fish([audio()]);
  await say(client);
  assert.equal(calls[0].init.headers.model, 's2.1-pro-free');
  assert.equal(calls[0].url, 'https://api.fish.audio/v1/tts');
  const other = fish([audio()]);
  await say(other.client, { model: 's1' });
  assert.equal(other.calls[0].init.headers.model, 's1');
});

test('an unknown model is refused, since the API would make it the paid one', async () => {
  const { client, calls } = fish([]);
  assert.throws(() => say(client, { model: 'free-ish' }), code('INVALID_PARAMS'));
  assert.equal(calls.length, 0);
});

test('body carries the voice, prosody and sampling', async () => {
  const { client, calls } = fish([audio()]);
  await say(client, { voice_id: 'v1', speed: 1.2, volume: -3, temperature: 0.5, top_p: 0.6, language: 'en', format: 'wav' });
  assert.deepEqual(calls[0].body, { format: 'wav', reference_id: 'v1', prosody: { speed: 1.2, volume: -3 }, temperature: 0.5, top_p: 0.6, language: 'en', text: 'Hello.' });
});

test('402 is AUDIO_NO_CREDIT with no fallback to paid', async () => {
  const { client, calls } = fish([json({ status: 402, message: 'none' }, 402)]);
  await assert.rejects(say(client), code('AUDIO_NO_CREDIT'));
  assert.equal(calls.length, 1);
});

test('429 backs off up to 3 times', async () => {
  const { client, calls, sleeps } = fish(() => json({ message: 'slow' }, 429));
  await assert.rejects(say(client));
  assert.equal(calls.length, 4);
  assert.deepEqual(sleeps, [1000, 2000, 4000]);
});

test('503 retries, then succeeds', async () => {
  const { client, calls } = fish([json({}, 503), audio('ok')]);
  const done = await say(client);
  assert.equal(calls.length, 2);
  assert.equal(fs.readFileSync(done.file, 'utf8'), 'ok');
});

test('401 is MISSING_API_KEY with next_action', async () => {
  const { client } = fish([json({ message: 'no' }, 401)]);
  await assert.rejects(say(client), (err) => {
    assert.equal(err.code, 'MISSING_API_KEY');
    assert.match(err.details.next_action, /API keys tab/);
    return true;
  });
});

test('no key means MISSING_API_KEY and no request', async () => {
  const { client, calls } = fish([], '');
  assert.throws(() => say(client), code('MISSING_API_KEY'));
  assert.equal(calls.length, 0);
});

test('long text splits on sentence boundaries, joins in order, reports segments', async () => {
  const sentence = `${'a'.repeat(900)}. `;
  assert.deepEqual(splitText('One. Two! Three?', 6), ['One.', 'Two!', 'Three?']);
  const { client, calls } = fish((n) => audio(`part${n}|`));
  const done = await client.generate({ text: sentence.repeat(3), output_root: root });
  assert.equal(calls.length, 3);
  assert.ok(calls.every(({ body }) => body.text.endsWith('.')));
  assert.equal(done.segments, 3);
  assert.equal(fs.readFileSync(done.file, 'utf8'), 'part1|part2|part3|');
});

test('a sentence longer than a segment is still cut to size, losing nothing', () => {
  const text = 'b'.repeat(25);
  const parts = splitText(text, 10);
  assert.ok(parts.every((p) => p.length <= 10));
  assert.equal(parts.join(''), text);
});

test('long text in a format that cannot join is refused before any request', async () => {
  const { client, calls } = fish([]);
  assert.throws(() => client.generate({ text: `${'a'.repeat(900)}. `.repeat(3), format: 'opus', output_root: root }), code('INVALID_PARAMS'));
  assert.equal(calls.length, 0);
});

test('file lands in voice/ with a manifest entry', async () => {
  const { client } = fish([audio('mp3')]);
  const done = await say(client, { name: 'intro' });
  assert.equal(path.basename(path.dirname(done.file)), 'voice');
  const run = path.dirname(path.dirname(done.file));
  const manifest = JSON.parse(fs.readFileSync(path.join(run, 'manifest.json'), 'utf8'));
  assert.equal(manifest.audio[0].file, done.file);
  assert.equal(manifest.audio[0].model, 's2.1-pro-free');
});

test('the key never appears in events, manifest or errors', async () => {
  const good = fish([audio()]);
  const done = await say(good.client);
  const run = path.dirname(path.dirname(done.file));
  for (const file of ['manifest.json', 'events.jsonl']) assert.ok(!fs.readFileSync(path.join(run, file), 'utf8').includes(KEY));
  const bad = fish([json({ message: `bad token ${KEY}` }, 400)]);
  await assert.rejects(say(bad.client), (err) => {
    assert.ok(!JSON.stringify({ m: err.message, d: err.details }).includes(KEY));
    return true;
  });
});

test('timeouts abort at the limit and are not repeated', async () => {
  const timeout = new DOMException('late', 'TimeoutError');
  const { client, calls } = fish([timeout]);
  await assert.rejects(say(client), (err) => {
    assert.equal(err.code, 'GENERATION_TIMEOUT');
    assert.equal(err.details.credits_at_risk, true);
    return true;
  });
  assert.equal(calls.length, 1);
  const signals = fish([audio()]);
  await say(signals.client);
  assert.ok(signals.calls[0].init.signal instanceof AbortSignal);
});

test('voice list maps query and mine to the documented parameters', async () => {
  const { client, calls } = fish([json({ total: 1, items: [{ _id: 'v', title: 'Narrator', languages: ['en'] }] }, 200)]);
  const list = await client.list({ query: 'narr', mine: true });
  assert.deepEqual(list, { total: 1, voices: [{ voice_id: 'v', title: 'Narrator', languages: ['en'] }] });
  const url = new URL(calls[0].url);
  assert.equal(url.origin + url.pathname, 'https://api.fish.audio/model');
  assert.equal(url.searchParams.get('title'), 'narr');
  assert.equal(url.searchParams.get('self'), 'true');
});
