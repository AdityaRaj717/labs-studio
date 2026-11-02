// Live: regenerate the failed Animation, kill the engine seconds after Start, expect recovery with no second spend.
import fs from 'node:fs';
import { connect } from './mcp.mjs';
const short = (o, n = 300) => JSON.stringify(o)?.slice(0, n);
const I = JSON.parse(fs.readFileSync('out/prod-status.json')).production_id;
let { call, client } = await connect();
await call('flow_job_control', { action: 'resume' });
const r = await call('flow_production_regenerate', { production_id: I, item: 'ANI_03', auto_confirm: true, expected_take: 4 });
console.log(short(r));
for (let i = 0; i < 800 && r.job_id; i++) { const s = await call('flow_job_status', { job_id: r.job_id }); if (s.state === 'generating') { console.log('at generating'); await new Promise((x) => setTimeout(x, 3000)); break; } await new Promise((x) => setTimeout(x, 300)); }
process.kill(JSON.parse(fs.readFileSync('out/live-data/engine.json')).pid, 'SIGKILL');
console.log('killed', (await 0, ''));
await client.close(); await new Promise((x) => setTimeout(x, 2000));
({ call, client } = await connect());
await call('flow_job_control', { action: 'resume' });
for (let i = 0; i < 60; i++) {
  const st = await call('flow_production_status', { production_id: I, detail: 'full' });
  const a = st.items.find((x) => x.item === 'ANI_03');
  if (a.state !== 'regenerating' && a.state !== 'generating') { console.log(st.status, a.state, short(a.takes.at(-1), 500), short(st.credits)); break; }
  await new Promise((x) => setTimeout(x, 5000));
}
await client.close(); process.exit(0);
