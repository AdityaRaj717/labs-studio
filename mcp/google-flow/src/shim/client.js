import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import fs from 'fs';
import path from 'path';
import { getDataDir } from '../utils/config.js';
import { createError, ErrorCodes, FlowError } from '../utils/errors.js';

export const VERSION = JSON.parse(fs.readFileSync(new URL('../../package.json', import.meta.url), 'utf8')).version;
export const engineFile = () => path.join(getDataDir(), 'engine.json');
export const startErrorFile = () => path.join(getDataDir(), 'engine-error.json');

const START_SCRIPT = fileURLToPath(new URL('../engine/start.js', import.meta.url));
const START_TIMEOUT_MS = 20000;
const STOP_TIMEOUT_MS = 10000;
const HEALTH_TIMEOUT_MS = 2000;
const POLL_MS = 100;
const RPC_TIMEOUT_MS = 300000; // legacy project tools can take minutes; flow_wait is capped at 55s

const sleep = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });
const headers = ({ token }) => ({ authorization: `Bearer ${token}`, 'content-type': 'application/json' });
const connOf = ({ port, token }) => ({ url: `http://127.0.0.1:${port}`, token });

export function readLock() {
  try {
    return JSON.parse(fs.readFileSync(engineFile(), 'utf8'));
  } catch {
    return null; // missing, or torn: either way it can't be used
  }
}

const pidAlive = (pid) => {
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    return err.code === 'EPERM'; // exists, but isn't ours to signal
  }
};

// stale: only a dead pid or a refused port. A live pid that is slow may be driving a paid job,
// and replacing it would put two engines on one Chrome, so that is 'stalled', never stale.
export async function probe(lock) {
  if (!pidAlive(lock.pid)) return { state: 'stale' };
  try {
    const conn = connOf(lock);
    const res = await fetch(`${conn.url}/health`, { headers: headers(conn), signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS) });
    return res.ok ? { state: 'up', ...(await res.json()) } : { state: 'stalled' };
  } catch (err) {
    return { state: err.cause?.code === 'ECONNREFUSED' ? 'stale' : 'stalled' };
  }
}

async function retire(lock) {
  const conn = connOf(lock);
  const res = await fetch(`${conn.url}/shutdown`, { method: 'POST', headers: headers(conn), signal: AbortSignal.timeout(2000) });
  if (res.status === 409) {
    throw createError(ErrorCodes.INTERNAL_ERROR, `Engine ${lock.version} is running a job and this client needs ${VERSION}`, {
      next_action: 'Wait for the current job to finish, then call again.',
    });
  }
  const end = Date.now() + STOP_TIMEOUT_MS;
  while (Date.now() < end && (await probe(lock)).state === 'up') await sleep(POLL_MS);
}

async function launch() {
  fs.mkdirSync(getDataDir(), { recursive: true });
  fs.rmSync(startErrorFile(), { force: true });
  spawn(process.execPath, [START_SCRIPT], { detached: true, stdio: 'ignore', windowsHide: true }).unref();
  const end = Date.now() + START_TIMEOUT_MS;
  while (Date.now() < end) {
    const lock = readLock();
    if (lock?.version === VERSION && (await probe(lock)).ready) return connOf(lock);
    if (fs.existsSync(startErrorFile())) {
      const { code, message, details } = JSON.parse(fs.readFileSync(startErrorFile(), 'utf8'));
      throw new FlowError(code, message, details);
    }
    await sleep(POLL_MS);
  }
  throw createError(ErrorCodes.INTERNAL_ERROR, `The Flow engine did not start within ${START_TIMEOUT_MS / 1000}s`, {
    next_action: `Read the log under ${path.join(getDataDir(), 'logs')}.`,
  });
}

export async function ensureEngine() {
  const lock = readLock();
  const found = lock && await probe(lock);
  if (found?.state === 'stalled') {
    throw createError(ErrorCodes.INTERNAL_ERROR, `Engine pid ${lock.pid} is alive but not answering on port ${lock.port}`, {
      next_action: `It may be mid-job, so it was not replaced. Try again shortly; if it stays stuck, end process ${lock.pid} yourself.`,
    });
  }
  if (found?.ready) {
    if (lock.version === VERSION) return connOf(lock);
    await retire(lock);
  }
  return launch();
}

export async function rpc(conn, tool, args = {}) {
  const res = await fetch(`${conn.url}/rpc`, {
    method: 'POST',
    headers: headers(conn),
    body: JSON.stringify({ tool, args }),
    signal: AbortSignal.timeout(RPC_TIMEOUT_MS),
  });
  if (!res.ok) throw createError(ErrorCodes.INTERNAL_ERROR, `Engine answered ${res.status}: ${await res.text()}`);
  return res.json();
}

// Ends when signal aborts. Parses only the data lines the server writes.
async function followEvents(conn, since, onEvent, signal) {
  const res = await fetch(`${conn.url}/events?since=${since}`, { headers: headers(conn), signal });
  const decoder = new TextDecoder();
  let buf = '';
  for await (const chunk of res.body) {
    buf += decoder.decode(chunk, { stream: true });
    for (let i; (i = buf.indexOf('\n\n')) >= 0; buf = buf.slice(i + 2)) {
      const data = buf.slice(0, i).split('\n').find((line) => line.startsWith('data: '));
      if (data) onEvent(JSON.parse(data.slice(6)));
    }
  }
}

// onProgress is set only when the MCP client sent a progress token.
export async function callTool(getConn, name, args = {}, onProgress) {
  const conn = await getConn();
  const stop = new AbortController();
  if (onProgress && name === 'flow_wait') {
    let progress = 0;
    followEvents(conn, 0, (event) => {
      if (event.state && (event.jobId === args.job_id || event.runId === args.run_id)) {
        onProgress({ progress: ++progress, message: `${event.jobId}: ${event.state}` });
      }
    }, stop.signal).catch(() => {}); // progress is optional: the call's own result still arrives
  }
  try {
    const { ok, result, ...failure } = await rpc(conn, name, args);
    return { content: [{ type: 'text', text: JSON.stringify(ok ? result : { ok, ...failure }) }], ...(ok ? {} : { isError: true }) };
  } finally {
    stop.abort();
  }
}
