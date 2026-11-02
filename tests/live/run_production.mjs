// Live Production driver on real Flow. node run_production.mjs <folder> <name> [max_credits] [gates json], or: watch <production_id>
// Exits when nothing is generating and the Production waits for review or has ended. Review happens in the app.
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '../../mcp/google-flow');
const require = createRequire(path.join(root, 'package.json'));
const { Client } = require('@modelcontextprotocol/sdk/client/index.js');
const { StdioClientTransport } = require('@modelcontextprotocol/sdk/client/stdio.js');
const client = new Client({ name: 'live-production', version: '1' });
await client.connect(new StdioClientTransport({ command: process.execPath, args: [path.join(root, 'src/index.js')], cwd: root, stderr: 'ignore', env: process.env }));
const call = async (name, args = {}) => {
  const r = await client.callTool({ name, arguments: args }, undefined, { timeout: 120000 });
  const t = r.content?.[0]?.text ?? '';
  try { return JSON.parse(t); } catch { return t; }
};
const [first, second, max, gates] = process.argv.slice(2);
let id = second; let run;
if (first !== 'watch') {
  const plan = await call('flow_production_plan', { folder: path.resolve(first), name: second, overrides: { references: [{ id: 'MD_04', kind: 'place' }] } });
  console.log('plan', plan.plan_id, plan.mode, JSON.stringify(plan.estimate));
  const started = await call('flow_production_start', { plan_id: plan.plan_id, cast_confirmed: true, auto_confirm: true, new_run: true, ...(max ? { max_credits: Number(max) } : {}), ...(gates ? { gates: JSON.parse(gates) } : {}) });
  console.log('start', JSON.stringify(started).slice(0, 400));
  if (!started.production_id) process.exit(1);
  id = started.production_id; run = started.run_id;
}
for (let i = 0; i < 240; i++) {
  await new Promise((r) => setTimeout(r, 20000));
  const st = await call('flow_production_status', { production_id: id, detail: 'full' });
  const items = st.items ?? [];
  const n = (s) => items.filter((x) => x.state === s).length;
  console.log(new Date().toISOString().slice(11, 19), id, st.status, `gen ${n('generating') + n('regenerating')} review ${n('pending_review')} ok ${n('approved')} rej ${n('rejected')} fail ${n('failed')} plan ${n('planned')}`, JSON.stringify(st.credits), st.paused ? JSON.stringify(st.paused).slice(0, 200) : '');
  const busy = n('generating') + n('regenerating');
  if (!busy && (n('pending_review') || n('failed') || st.paused || /complete|done|cancel|finished/.test(st.status ?? ''))) break;
}
console.log('balance', JSON.stringify((await call('flow_status')).balance));
await client.close(); process.exit(0);
