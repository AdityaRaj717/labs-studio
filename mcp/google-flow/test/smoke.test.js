import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

test('MCP server answers initialize and tools/list', { timeout: 30000 }, async () => {
  const child = spawn(process.execPath, ['src/index.js'], { cwd: root, stdio: ['pipe', 'pipe', 'pipe'] });
  try {
    const pending = new Map();
    let buf = '';
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', (chunk) => {
      buf += chunk;
      let i;
      while ((i = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, i).trim();
        buf = buf.slice(i + 1);
        if (!line) continue;
        let msg;
        try { msg = JSON.parse(line); } catch { continue; }
        if (msg.id !== undefined && pending.has(msg.id)) {
          pending.get(msg.id)(msg);
          pending.delete(msg.id);
        }
      }
    });
    const send = (m) => child.stdin.write(JSON.stringify(m) + '\n');
    const request = (id, method, params = {}) =>
      new Promise((resolve) => {
        pending.set(id, resolve);
        send({ jsonrpc: '2.0', id, method, params });
      });

    const init = await request(1, 'initialize', {
      protocolVersion: '2024-11-05',
      capabilities: {},
      clientInfo: { name: 'smoke-test', version: '0.0.0' },
    });
    assert.ok(init.result, 'initialize returned a result');
    send({ jsonrpc: '2.0', method: 'notifications/initialized' });

    const list = await request(2, 'tools/list');
    assert.ok(Array.isArray(list.result.tools));
    assert.ok(list.result.tools.length > 0, 'tools/list is non-empty');
  } finally {
    child.kill();
  }
});
