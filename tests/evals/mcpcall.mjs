// One MCP call for a cold eval agent: node mcpcall.mjs <log> list | <tool> <json file or json>. Every call is logged for scoring.
import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '../../mcp/google-flow');
const require = createRequire(path.join(root, 'package.json'));
const { Client } = require('@modelcontextprotocol/sdk/client/index.js');
const { StdioClientTransport } = require('@modelcontextprotocol/sdk/client/stdio.js');
const [log, tool, input = '{}'] = process.argv.slice(2);
const args = JSON.parse(fs.existsSync(input) ? fs.readFileSync(input, 'utf8') : input);
const client = new Client({ name: 'eval', version: '1' });
await client.connect(new StdioClientTransport({ command: process.execPath, args: [path.join(root, 'src/index.js')], cwd: root, stderr: 'ignore', env: process.env }));
if (tool === 'list') {
  for (const t of (await client.listTools()).tools) console.log(`${t.name}: ${t.description}\n  ${JSON.stringify(t.inputSchema.properties ?? {})}`);
} else {
  const r = await client.callTool({ name: tool, arguments: args }, undefined, { timeout: 120000 });
  const text = r.content?.[0]?.text ?? '';
  fs.appendFileSync(log, `${JSON.stringify({ tool, args, error: /"ok":\s*false|error_code/.test(text) })}\n`);
  console.log(text);
}
await client.close(); process.exit(0);
