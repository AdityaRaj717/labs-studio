import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { createStable } from '../src/audio/stable.js';

const KEY = 'test-value-not-a-real-key';
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'stable-'));
const accepted = () => new Response(JSON.stringify({ id: 'gen1' }), { status: 202 });
const err = (status) => new Response(JSON.stringify({ id: 'e', name: 'n', errors: ['why'] }), { status });

function stable(replies, { key = KEY, clockStep = 0 } = {}) {
  const calls = [];
  let t = 0;
  const client = createStable({
    getSecret: () => key,
    sleep: async () => {},
    now: () => { t += clockStep; return t; },
    fetch: async (url, init) => {
      calls.push({ url, init });
      return typeof replies === 'function' ? replies(calls.length) : replies.shift();
    },
  });
  return { client, calls };
}
const make = (client, extra) => client.generate({ kind: 'sfx', prompt: 'door slam', duration: 10, auto_confirm: true, output_root: root, ...extra });
const code = (c) => (e) => { assert.equal(e.code, c); return true; };

test('multipart body has the spec fields', async () => {
  const { client, calls } = stable([accepted(), new Response('wav')]);
  await make(client, { seed: 7 });
  const { url, init } = calls[0];
  assert.equal(url, 'https://api.stability.ai/v2beta/audio/stable-audio/text-to-audio');
  assert.deepEqual(Object.fromEntries(init.body.entries()), { prompt: 'door slam', model: 'stable-audio-3', duration: '10', steps: '8', cfg_scale: '1', output_format: 'wav', seed: '7' });
});

test('202 then poll then saved in sfx/ or bgm/', async () => {
  const one = stable([accepted(), new Response('', { status: 202 }), new Response('sound')]);
  const done = await make(one.client);
  assert.equal(one.calls[1].url, 'https://api.stability.ai/v2beta/audio/results/gen1');
  assert.equal(one.calls.length, 3);
  assert.equal(path.basename(path.dirname(done.file)), 'sfx');
  assert.equal(done.stability_credits, 8);
  const two = stable([accepted(), new Response('m')]);
  assert.equal(path.basename(path.dirname((await make(two.client, { kind: 'music' })).file)), 'bgm');
});

test('results are saved before reporting done', async () => {
  const { client } = stable([accepted(), new Response('sound')]);
  const done = await make(client);
  assert.equal(fs.readFileSync(done.file, 'utf8'), 'sound');
  const manifest = JSON.parse(fs.readFileSync(path.join(path.dirname(path.dirname(done.file)), 'manifest.json'), 'utf8'));
  assert.equal(manifest.audio[0].file, done.file);
});

test('poll has a bounded timeout', async () => {
  const { client } = stable((n) => (n === 1 ? accepted() : new Response('', { status: 202 })), { clockStep: 60000 });
  await assert.rejects(make(client), (e) => {
    assert.equal(e.code, 'GENERATION_TIMEOUT');
    assert.equal(e.details.credits_at_risk, true);
    return true;
  });
});

test('403 is SAFETY_BLOCKED; 402 is AUDIO_NO_CREDIT; 422 fails the job', async () => {
  await assert.rejects(make(stable([err(403)]).client), code('SAFETY_BLOCKED'));
  await assert.rejects(make(stable([err(402)]).client), code('AUDIO_NO_CREDIT'));
  await assert.rejects(make(stable([err(422)]).client), code('GENERATION_REFUSED'));
  await assert.rejects(make(stable([accepted(), err(422)]).client), code('GENERATION_REFUSED'));
});

test('no auto_confirm returns an estimate only', async () => {
  const { client, calls } = stable([]);
  const reply = await make(client, { auto_confirm: false });
  assert.equal(reply.estimated_stability_credits, 8);
  assert.equal(calls.length, 0);
});

test('no key is MISSING_API_KEY; an estimate needs none', () => {
  const { client, calls } = stable([], { key: '' });
  assert.throws(() => make(client), code('MISSING_API_KEY'));
  assert.equal(make(client, { auto_confirm: false }).status, 'ready_for_confirmation');
  assert.equal(calls.length, 0);
});

test('bad values are refused with no request', () => {
  const { client, calls } = stable([]);
  for (const bad of [{ duration: undefined }, { duration: 381 }, { steps: 3 }, { cfg_scale: 26 }, { output_format: 'ogg' }, { kind: 'voice' }, { prompt: ' ' }]) {
    assert.throws(() => make(client, bad), code('INVALID_PARAMS'));
  }
  assert.equal(calls.length, 0);
});

test('the key never appears in errors or files', async () => {
  const { client } = stable([new Response(JSON.stringify({ errors: [`bad ${KEY}`] }), { status: 400 })]);
  await assert.rejects(make(client), (e) => { assert.ok(!e.message.includes(KEY)); return true; });
  const good = stable([accepted(), new Response('x')]);
  const done = await make(good.client);
  const dir = path.dirname(path.dirname(done.file));
  for (const f of ['manifest.json', 'events.jsonl']) assert.ok(!fs.readFileSync(path.join(dir, f), 'utf8').includes(KEY));
});
