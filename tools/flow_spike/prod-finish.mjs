import fs from 'node:fs';
import { connect } from './mcp.mjs';
const { call, client } = await connect();
const prev = JSON.parse(fs.readFileSync('out/prod-status.json'));
const I = prev.production_id;
let st;
for (let i = 0; i < 40; i++) {
  st = await call('flow_production_status', { production_id: I, detail: 'full' });
  const ani = st.items.find((x) => x.item === 'ANI_03');
  if (ani.state === 'pending_review') { console.log(JSON.stringify(await call('flow_production_review', { production_id: I, items: [{ id: 'ANI_03', take: 1 }], action: 'approve', actor: 'agent' })).slice(0, 300)); st = await call('flow_production_status', { production_id: I, detail: 'full' }); break; }
  await new Promise((r) => setTimeout(r, 10000));
}
console.log(st.status, JSON.stringify(st.credits), 'stale', JSON.stringify(st.stale), st.run_id);
for (const x of st.items) console.log(x.item, x.state, 'refs', (x.takes.at(-1)?.refs_used ?? []).length, 'start', JSON.stringify(x.takes.at(-1)?.start_used)?.slice(-70), 'audio', x.takes.at(-1)?.audio_streams);
console.log('balance', (await call('flow_status')).balance);
fs.writeFileSync('out/run-id.txt', st.run_id);
await client.close(); process.exit(0);
