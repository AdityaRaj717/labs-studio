// Live Y5 T3 and Animation proof: mixed fixture through the real MCP, approving each Item as it reaches review.
import fs from 'node:fs';
import path from 'node:path';
import { connect } from './mcp.mjs';
const short = (o, n = 500) => JSON.stringify(o)?.slice(0, n);
const { call, client } = await connect();
const src = path.resolve('../../mcp/google-flow/test/fixtures/productions/mixed');
const dir = path.resolve('out/prod-mixed');
fs.rmSync(dir, { recursive: true, force: true }); fs.cpSync(src, dir, { recursive: true });
const defaults = { resolution: '360p', duration: 4 };
const plan = await call('flow_production_plan', { folder: dir, name: `t3-${Date.now().toString(36)}`, defaults });
console.log('plan', short(plan, 900));
const P = plan.plan_id;
const base = { plan_id: P, cast_confirmed: true, auto_confirm: true };
console.log('no cast', short(await call('flow_production_start', { plan_id: P, auto_confirm: true }), 200));
console.log('no max', short(await call('flow_production_start', base), 200));
console.log('max 1', short(await call('flow_production_start', { ...base, max_credits: 1 }), 200));
const max = (plan.estimate?.credits ?? plan.credits ?? 30) + 20;
// Edited file refused.
const f = path.join(dir, 'animations.md'); const text = fs.readFileSync(f);
fs.appendFileSync(f, '\n');
console.log('edited', short(await call('flow_production_start', { ...base, max_credits: max }), 200));
fs.writeFileSync(f, text);
const s = await call('flow_production_start', { ...base, max_credits: max });
console.log('start', short(s));
if (!s.production_id) { await client.close(); process.exit(1); }
const again = await call('flow_production_start', { ...base, max_credits: max });
console.log('repeat', short(again, 200));
const I = s.production_id; const R = s.run_id;
let regen = false; let first = true;
for (let i = 0; i < 200; i++) {
  await call('flow_wait', { run_id: R, wait_ms: 20000 });
  const st = await call('flow_production_status', { production_id: I, detail: 'full' });
  if (first) { console.log('status', short(st, 1200)); first = false; }
  const items = st.items ?? [];
  console.log(i, st.status, items.map((x) => `${x.item}:${x.state}`).join(' '), st.paused ? short(st.paused, 250) : '', short(st.credits, 80));
  const ready = items.filter((x) => x.state === "pending_review");
  for (const it of ready) {
    const take = it.takes?.length ?? 1;
    const r = await call('flow_production_review', { production_id: I, items: [{ id: it.item, take }], action: 'approve', actor: 'agent' });
    console.log(' approve', it.item, take, short(r, 200));
  }
  if (!regen && items.find((x) => x.item === 'IMG_01' && x.state === 'approved')) {
    regen = true;
    const a = { production_id: I, item: 'IMG_01', prompt: 'Ana on the dock at dusk, darker', expected_take: 1 };
    console.log(' regen', short(await call('flow_production_regenerate', a), 250));
    console.log(' regen2', short(await call('flow_production_regenerate', a), 250));
  }
  if (['done', 'complete', 'completed', 'failed', 'cancelled'].includes(st.status) || (st.status === 'paused' && i > 2)) { fs.writeFileSync('out/prod-status.json', JSON.stringify(st, null, 1)); break; }
  fs.writeFileSync('out/prod-status.json', JSON.stringify(st, null, 1));
}
console.log('balance', (await call('flow_status')).balance);
await client.close(); process.exit(0);
