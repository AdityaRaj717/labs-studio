// Live T3: 10-image batch with a Character, hard-kill the engine mid-generation, restart, confirm no duplicate. Also the cheap Task 11 checks.
import fs from 'node:fs';
import { connect, PROJECT } from './mcp.mjs';
const short = (o) => JSON.stringify(o).slice(0, 500);
let { call, client } = await connect();
await call('flow_job_control', { action: 'resume' });
const tag = Date.now().toString(36);
const subjects = ['a copper kettle', 'a glass marble', 'a wooden spoon', 'a tin robot', 'a paper crane', 'a brass bell', 'a felt hat', 'a clay pot', 'a stone owl'];
const jobs = subjects.map((s) => ({ prompt: `${s} on a plain table, ${tag}` }));
jobs.splice(3, 0, { prompt: `The narrator reading by a window, ${tag}`, ingredients: [{ character: 'y0 narrator' }] });
const b = await call('flow_batch_start', { name: `t3-${tag}`, project: PROJECT, jobs, defaults: { kind: 'image', model: 'banana21' }, max_credits: 0, auto_confirm: true });
console.log('start', short(b));
const run = b.run_id;
const view = async () => (await call('flow_list_runs', { limit: 5 })).runs.find((r) => r.id === run || r.run_id === run);
let killed = false;
for (let i = 0; i < 300 && !killed; i++) {
  const v = await view();
  if (JSON.stringify(v).includes('"generating"')) {
    await new Promise((r) => setTimeout(r, 4000));
    const { pid } = JSON.parse(fs.readFileSync('out/live-data/engine.json'));
    process.kill(pid, 'SIGKILL');
    killed = true;
    console.log('killed engine', pid, short(v));
  } else await new Promise((r) => setTimeout(r, 1500));
}
await client.close();
await new Promise((r) => setTimeout(r, 3000));
({ call, client } = await connect());
await call('flow_job_control', { action: 'resume' });
for (let i = 0; i < 240; i++) {
  const v = await view();
  const s = JSON.stringify(v);
  if (i % 8 === 0) console.log(short(v));
  if (!/queued|preparing|submitted|generating|downloading|verifying/.test(s)) { console.log('end', s.slice(0, 1500)); break; }
  await new Promise((r) => setTimeout(r, 5000));
}
const dir = (await call('flow_list_assets', { run_id: run }));
console.log('assets', short(dir), Array.isArray(dir.assets) ? dir.assets.length : '');
console.log('project assets', short(await call('flow_list_assets', { project_url: PROJECT })));
const missing = await call('flow_generate_image', { project_url: PROJECT, prompt: 'x', auto_confirm: true, ingredients: [{ character: 'Nope' }] });
console.log('missing char submit', short(missing));
if (missing.job_id) { for (let i = 0; i < 20; i++) { const s = await call('flow_job_status', { job_id: missing.job_id }); if (s.error || s.state === 'done') { console.log(short(s.error ?? s)); break; } await new Promise((r) => setTimeout(r, 2000)); } }
await client.close();
process.exit(0);
