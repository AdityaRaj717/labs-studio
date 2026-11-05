// Task 9 live checks through a real MCP client.
import path from 'node:path';
import crypto from 'node:crypto';
import fs from 'node:fs';
import { connect, PROJECT } from './mcp.mjs';
const OUT = path.resolve('out/y0');
const { call, wait, client } = await connect();
const run = async (label, args) => {
  const j = await call('flow_generate_image', { project_url: PROJECT, auto_confirm: true, ...args });
  if (!j.job_id) { console.log(label, 'REFUSED', JSON.stringify(j).slice(0, 400)); return null; }
  const seen = new Set();
  const s = await wait(j.job_id, (t) => { const p = t.progress; seen.add(`${t.state}:${p?.source ?? ''}:${p?.percent ?? p?.value ?? ''}`); });
  const full = await call('flow_job_status', { job_id: j.job_id });
  const outs = full.outputs ?? s.outputs ?? [];
  console.log(`\n== ${label}: ${s.state} ${s.error ? JSON.stringify(s.error).slice(0, 500) : ''}`);
  console.log('progress', [...seen].slice(0, 8).join(' '));
  for (const o of outs) { const f = o.file ?? o.path; const sha = f && fs.existsSync(f) ? crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex').slice(0, 10) : 'MISSING'; console.log(path.basename(f ?? '?'), sha, JSON.stringify({ w: o.width, h: o.height, observed: o.observed })?.slice(0, 220)); }
  if (!outs.length) console.log(JSON.stringify(full).slice(0, 700));
  return s;
};
const before = await call('flow_status'); console.log('balance', before.balance, 'quota', before.ledger?.todayQuota?.banana21?.used);
await run('1 x1 2K', { prompt: 'A red paper boat on a calm pond, morning mist, photoreal', size: '2K' });
await run('2 x2 2K', { prompt: 'A brass compass on a weathered map, side light, photoreal', size: '2K', count: 2 });
await run('7a file ingredient', { prompt: 'The man from the reference reads a map under a caged bulb', ingredients: [path.join(OUT, 'y0-sheet-md02.jpg')] });
await run('7b character', { prompt: 'The man from the reference climbs a steel ladder toward a hatch', ingredients: [{ character: 'y0 narrator' }] });
const after = await call('flow_status'); console.log('\nbalance', after.balance, 'quota', after.ledger?.todayQuota?.banana21?.used);
await client.close(); process.exit(0);
