import { createHash, randomBytes, randomUUID, timingSafeEqual } from 'crypto';
import http from 'http';
import { VERSION } from '../shim/client.js';
import { logger } from '../utils/logger.js';
import { jobEvents, recover } from './job-store.js';
import { pacer as realPacer } from './pacer.js';
import { createRpc } from './rpc.js';
import { chromeSession, createWorker, flowAdapter } from './worker.js';

const HOST = '127.0.0.1';
const MAX_BODY = 1024 * 1024;
const KEEPALIVE_MS = 15000;
const LOOPBACK_NAMES = ['127.0.0.1', 'localhost'];
const SECRET_NAMES = ['FISH_API_KEY', 'STABILITY_API_KEY'];

const digest = (text) => createHash('sha256').update(String(text)).digest();

// shortcut: events live in memory and grow with the engine's life, so a restart starts over with a reset event; the manifests hold the durable state.
function createHub() {
  const events = [];
  const subscribers = new Set();
  const subscribe = (fn) => {
    subscribers.add(fn);
    return () => subscribers.delete(fn);
  };
  return {
    head: () => events.length,
    publish(event) {
      const record = { seq: events.length + 1, ts: new Date().toISOString(), ...event };
      events.push(record);
      subscribers.forEach((fn) => fn(record));
    },
    // Replay and subscribe in one tick, so nothing can fall between them.
    follow(since, fn) {
      events.slice(since).forEach(fn);
      return subscribe(fn);
    },
    subscribe,
  };
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY) reject(Object.assign(new Error('Body too large'), { status: 413 }));
      else chunks.push(chunk);
    });
    req.on('end', () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}'));
      } catch {
        reject(Object.assign(new Error('Body is not JSON'), { status: 400 }));
      }
    });
    req.on('error', reject);
  });
}

function send(res, status, body) {
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(JSON.stringify(body));
}

export async function listenEngine({ adapter = flowAdapter, session = chromeSession, pacer = realPacer, settleMs, reconcile, onShutdown } = {}) {
  const token = randomBytes(32).toString('hex');
  const tokenDigest = digest(`Bearer ${token}`);
  const secrets = new Map();
  const hub = createHub();
  const worker = createWorker({ adapter, session, pacer, settleMs, reconcile });
  const call = createRpc({ worker, session, hub });
  const startedAt = Date.now();
  const streams = new Set();
  let engine;
  let ready = false; // lock won and recovery passed; a client must not use the engine before that

  const isAllowedHost = (req) => {
    const host = req.headers.host ?? '';
    return LOOPBACK_NAMES.some((name) => host === name || host.startsWith(`${name}:`));
  };

  function events(res, url) {
    const asked = Number(url.searchParams.get('since') ?? 0);
    res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-store', connection: 'keep-alive' });
    let since = Number.isInteger(asked) && asked >= 0 ? asked : 0;
    // A client ahead of us saw an engine that has since restarted.
    if (since > hub.head()) {
      res.write(`event: reset\ndata: ${JSON.stringify({ seq: hub.head() })}\n\n`);
      since = 0;
    }
    const unfollow = hub.follow(since, (event) => res.write(`id: ${event.seq}\ndata: ${JSON.stringify(event)}\n\n`));
    const keepalive = setInterval(() => res.write(': ping\n\n'), KEEPALIVE_MS);
    keepalive.unref();
    streams.add(res);
    res.on('close', () => {
      unfollow();
      clearInterval(keepalive);
      streams.delete(res);
    });
  }

  async function route(req, res, url, requestId) {
    const where = `${req.method} ${url.pathname}`;
    if (where === 'GET /events') return events(res, url);
    if (where === 'GET /health') {
      return send(res, 200, { ok: true, ready, version: VERSION, pid: process.pid, uptimeMs: Date.now() - startedAt, seq: hub.head(), worker: worker.status() });
    }
    if (where === 'POST /rpc') {
      const { tool, args } = await readBody(req);
      const started = Date.now();
      const out = await call(tool, args);
      // Name and outcome only: arguments can hold prompts and paths.
      logger.info('rpc', { event: 'rpc', requestId, tool: String(tool).slice(0, 60), ms: Date.now() - started, ok: out.ok, code: out.error_code });
      return send(res, 200, out);
    }
    if (where === 'POST /secrets') {
      const body = await readBody(req);
      const names = Object.keys(body);
      if (names.some((name) => !SECRET_NAMES.includes(name) || typeof body[name] !== 'string')) {
        return send(res, 400, { ok: false, message: `Only string values for: ${SECRET_NAMES.join(', ')}` });
      }
      names.forEach((name) => secrets.set(name, body[name]));
      logger.info('secrets', { event: 'secrets_set', requestId, count: names.length });
      return send(res, 200, { ok: true, names });
    }
    if (where === 'POST /shutdown') {
      if (worker.busy()) return send(res, 409, { ok: false, message: 'A job is running', worker: worker.status() });
      send(res, 200, { ok: true });
      setImmediate(() => engine.stop().then(() => onShutdown?.()));
      return undefined;
    }
    return send(res, 404, { ok: false, message: 'Not found' });
  }

  const server = http.createServer((req, res) => {
    const requestId = randomUUID().slice(0, 8);
    res.setHeader('x-request-id', requestId);
    // DNS rebinding: a hostile page's name resolving to us still carries its own Host.
    if (!isAllowedHost(req)) return send(res, 403, { ok: false, message: 'Bad Host header' });
    if (!timingSafeEqual(digest(req.headers.authorization ?? ''), tokenDigest)) return send(res, 401, { ok: false, message: 'Bad or missing token' });
    const url = new URL(req.url, `http://${HOST}`);
    route(req, res, url, requestId).catch((err) => {
      if (err.status === 413) {
        res.setHeader('connection', 'close');
        res.once('finish', () => req.destroy()); // stop reading whatever is left of the body
      }
      if (!res.headersSent) send(res, err.status ?? 500, { ok: false, message: err.status ? err.message : 'Engine error' });
      if (!err.status) logger.error('Request failed', { event: 'request_failed', requestId, error: err.message });
    });
    return undefined;
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, HOST, resolve);
  });

  const onJobEvent = (event) => hub.publish(event);
  let stopping;
  engine = {
    server,
    hub,
    worker,
    token,
    port: server.address().port,
    url: `http://${HOST}:${server.address().port}`,
    getSecret: (name) => secrets.get(name) ?? process.env[name],
    // Call once this process has won the lock: recovery may truncate a torn journal tail.
    begin() {
      const { reconcile: lost } = recover();
      jobEvents.on('event', onJobEvent);
      worker.adopt(lost);
      logger.info('Engine started', { event: 'engine_started', pid: process.pid, version: VERSION, port: engine.port, lostJobs: lost.length });
      ready = true;
      worker.kick();
    },
    stop: () => (stopping ??= new Promise((resolve) => {
      worker.stop();
      jobEvents.off('event', onJobEvent);
      streams.forEach((res) => res.end());
      server.closeAllConnections();
      server.close(resolve);
    })),
  };
  return engine;
}

export async function startEngine(options) {
  const engine = await listenEngine(options);
  engine.begin();
  return engine;
}
