// Live acceptance helper: a real MCP client over stdio against the shim. Controller only.
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, '../../mcp/google-flow');
const require = createRequire(path.join(root, 'package.json'));
const { Client } = require('@modelcontextprotocol/sdk/client/index.js');
const { StdioClientTransport } = require('@modelcontextprotocol/sdk/client/stdio.js');
export const PROJECT = 'https://flow.google.com/project/065acc3b-852c-4cf2-84c6-80359d0543bd';
export async function connect() {
  const client = new Client({ name: 'live', version: '1' });
  await client.connect(new StdioClientTransport({ command: process.execPath, args: [path.join(root, 'src/index.js')], cwd: root, stderr: 'ignore', env: { ...process.env, FLOW_DATA_DIR: path.join(here, 'out', 'live-data') } }));
  const call = async (name, args = {}) => {
    const r = await client.callTool({ name, arguments: args }, undefined, { timeout: 120000 });
    const t = r.content?.[0]?.text ?? '';
    try { return JSON.parse(t); } catch { return t; }
  };
  const wait = async (job_id, onTick) => {
    for (let i = 0; i < 80; i++) {
      const s = await call('flow_wait', { job_id, wait_ms: 15000 });
      onTick?.(s);
      if (s.finished) return s;
    }
    throw new Error('never finished');
  };
  return { client, call, wait };
}
