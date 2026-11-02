import { connect, PROJECT } from './mcp.mjs';
const { call, wait, client } = await connect();
await call('flow_job_control', { action: 'resume' });
const b = await call('flow_status'); console.log('before bal', JSON.stringify(b.balance), 'q', b.ledger?.todayQuota?.banana21?.used);
const j = await call('flow_generate_image', { project_url: PROJECT, auto_confirm: true, prompt: 'Red kite above a wheat field, photoreal' });
const s = await wait(j.job_id); const f = await call('flow_job_status', { job_id: j.job_id });
console.log(s.state, JSON.stringify(f.outputs?.[0]?.observed), f.outputs?.[0]?.file, JSON.stringify(f.error??'').slice(0,300));
const a = await call('flow_status'); console.log('after bal', JSON.stringify(a.balance), 'q', a.ledger?.todayQuota?.banana21?.used);
await client.close(); process.exit(0);
