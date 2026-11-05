import { connect } from './mcp.mjs';
const { call, client } = await connect();
for (const r of (await call('flow_list_runs', { limit: 20 })).runs) if (Object.keys(r.counts).some((k) => !['done', 'failed', 'cancelled'].includes(k))) console.log(r.run_id, JSON.stringify(await call('flow_job_control', { action: 'cancel', run_id: r.run_id })).slice(0, 150));
await client.close(); process.exit(0);
