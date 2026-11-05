#!/usr/bin/env node
// The engine process. Winning engine.json is what makes it the only one on this machine.
import { spawnSync } from 'child_process';
import fs from 'fs';
import os from 'os';
import { setTimeout as sleep } from 'timers/promises';
import { engineFile, probe, readLock, startErrorFile, VERSION } from '../shim/client.js';
import { getDataDir } from '../utils/config.js';
import { closeLog, logger } from '../utils/logger.js';
import { listenEngine } from './server.js';

const CLAIM_SETTLE_MS = 150;

// Node's mode bits do nothing on Windows, so the ACL is cut down to this user where icacls allows.
function restrict(file) {
  if (process.platform !== 'win32') return;
  const { status } = spawnSync('icacls', [file, '/inheritance:r', '/grant:r', `${os.userInfo().username}:F`], { stdio: 'ignore', windowsHide: true });
  if (status !== 0) logger.warn('Could not restrict engine.json', { event: 'lock_acl_failed', status });
}

// A hard link is an atomic create-if-absent of a complete file, so a reader never sees half of it.
async function claim(engine) {
  const file = engineFile();
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify({ pid: process.pid, port: engine.port, token: engine.token, version: VERSION }), { mode: 0o600 });
  restrict(tmp);
  try {
    for (;;) {
      try {
        fs.linkSync(tmp, file);
        break;
      } catch (err) {
        if (err.code !== 'EEXIST') throw err;
        const lock = readLock();
        if (lock && (await probe(lock)).state !== 'stale') return false;
        // Re-read at the last moment: another starter may just have replaced the stale file.
        if (readLock()?.pid === lock?.pid) fs.rmSync(file, { force: true });
      }
    }
  } finally {
    fs.rmSync(tmp, { force: true });
  }
  // shortcut: two starters racing over one stale file can still cross; the loser sees it here and leaves.
  await sleep(CLAIM_SETTLE_MS);
  return readLock()?.pid === process.pid;
}

function release() {
  if (readLock()?.pid === process.pid) fs.rmSync(engineFile(), { force: true });
}

async function exit(code) {
  release();
  await closeLog();
  process.exit(code);
}

async function main() {
  fs.mkdirSync(getDataDir(), { recursive: true });
  const engine = await listenEngine({ onShutdown: () => exit(0) });
  if (!await claim(engine)) {
    await engine.stop();
    await closeLog();
    process.exit(0);
  }
  try {
    engine.begin();
  } catch (err) {
    // The client spawned us with no console, so this file is how the error reaches it.
    fs.writeFileSync(startErrorFile(), JSON.stringify({ code: err.code ?? 'INTERNAL_ERROR', message: err.message, details: err.details ?? {} }));
    logger.error('Engine failed to start', { event: 'engine_start_failed', code: err.code, error: err.message });
    await exit(1);
  }
  const shutdown = () => engine.stop().then(() => exit(0));
  process.on('SIGTERM', shutdown);
  process.on('SIGINT', shutdown);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
