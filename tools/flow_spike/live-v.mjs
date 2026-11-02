// Live acceptance: one video job through the real MCP. argv[2] is the job JSON.
import { connect, PROJECT } from './mcp.mjs';
const { call, wait, client } = await connect();
await call('flow_job_control', { action: 'resume' });
const spec = JSON.parse(process.argv[2]);
const b = await call('flow_status');
const j = await call('flow_generate_video', { project_url: PROJECT, auto_confirm: true, ...spec });
console.log(JSON.stringify(j).slice(0, 300));
if (j.job_id) {
  const s = await wait(j.job_id);
  const f = await call('flow_job_status', { job_id: j.job_id });
  console.log(s.state, 'attempt', f.attempt, JSON.stringify(f.error ?? '').slice(0, 500));
  for (const o of f.outputs ?? []) console.log(JSON.stringify({ ...o, prompt: undefined, request: undefined }).slice(0, 700));
}
const a = await call('flow_status');
console.log('balance', b.balance, '->', a.balance);
await client.close();
process.exit(0);
