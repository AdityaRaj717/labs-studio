// Live Task 11 rest: video restart recovery, flow_download on image, video and extend, cancel during download.
import fs from 'node:fs';
import { connect, PROJECT } from './mcp.mjs';
const short = (o, n = 450) => JSON.stringify(o).slice(0, n);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let { call, wait, client } = await connect();
await call('flow_job_control', { action: 'resume' });
const tag = Date.now().toString(36);
const v = await call('flow_generate_video', { project_url: PROJECT, auto_confirm: true, prompt: `A red fox yawning at dawn, ${tag}`, model: 'omni', resolution: '360p', duration: 4, max_credits: 4 });
for (let i = 0; i < 100; i++) { const s = await call('flow_job_status', { job_id: v.job_id }); if (s.state === 'generating') break; await sleep(1000); }
await sleep(6000);
process.kill(JSON.parse(fs.readFileSync('out/live-data/engine.json')).pid, 'SIGKILL');
console.log('killed during video');
await client.close(); await sleep(3000);
({ call, wait, client } = await connect());
await call('flow_job_control', { action: 'resume' });
const after = await wait(v.job_id);
const full = await call('flow_job_status', { job_id: v.job_id });
console.log('video', after.state, short(full.error ?? ''), 'files', (full.outputs ?? []).map((o) => `${o.width}x${o.height} ${o.duration}s`));
const before = (await call('flow_status')).balance;
const runs = (await call('flow_list_runs', { limit: 10 })).runs;
const t3 = runs.find((r) => r.name?.startsWith('t3-'));
const assets = (await call('flow_list_assets', { run_id: t3.run_id })).assets;
console.log('download image', short(await call('flow_download', { job_id: assets[0].job_id })));
console.log('download video', short(await call('flow_download', { job_id: v.job_id })));
console.log('download latest image', short(await call('flow_download', { latest: true, project_url: PROJECT })));
// Cancel while downloading.
const c = await call('flow_batch_start', { name: `cancel-${tag}`, project: PROJECT, jobs: [{ prompt: `a blue teapot, ${tag}`, size: '2K' }, { prompt: `a green teapot, ${tag}` }, { prompt: `a pink teapot, ${tag}` }], defaults: { kind: 'image', model: 'banana21' }, max_credits: 0, auto_confirm: true });
let sent = false;
for (let i = 0; i < 200; i++) {
  const r = (await call('flow_list_runs', { limit: 5 })).runs.find((x) => x.run_id === c.run_id);
  if (!sent && r.counts.downloading) { console.log('cancel', short(await call('flow_job_control', { action: 'cancel', run_id: c.run_id }))); sent = true; }
  if (sent && !r.counts.downloading && !r.counts.verifying && !r.counts.generating && !r.counts.preparing) { console.log('cancel end', short(r)); break; }
  await sleep(500);
}
console.log('balance', before, (await call('flow_status')).balance);
await client.close(); process.exit(0);
