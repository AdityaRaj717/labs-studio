import path from 'node:path';
import * as y from './y0lib.mjs';
import { connect, PROJECT } from './mcp.mjs';
const { call, wait, client } = await connect();
const { page } = await y.attach();
const job = (a) => call('flow_generate_image', { project_url: PROJECT, auto_confirm: true, ...a });
// 5: agent on and progress
await page.goto(PROJECT, { waitUntil: 'domcontentloaded' }); await y.locate(page, 'project.prompt').waitFor({ timeout: 30000 });
const ag = y.locate(page, 'project.agent'); if ((await ag.getAttribute('aria-pressed')) !== 'true') await ag.click();
console.log('agent before', await ag.getAttribute('aria-pressed'));
let j = await job({ prompt: 'A lighthouse at dusk in heavy rain, photoreal' });
const seen = [];
for (let i = 0; i < 40; i++) { const s = await call('flow_job_status', { job_id: j.job_id }); if (s.progress?.source === 'flow') seen.push(s.progress.progress); if (s.finished) { console.log('5/6', s.state, 'flow progress', seen.join(','), 'observed', JSON.stringify(s.outputs?.[0]?.observed)); break; } await new Promise((r) => setTimeout(r, 2000)); }
console.log('agent after', await y.locate(page, 'project.agent').getAttribute('aria-pressed'), 'chat turns', await page.getByRole('radiogroup', { name: 'Permission options' }).count());
// 9: reuse by filename
j = await job({ prompt: 'The man from the reference lights a candle', ingredients: [path.join(path.resolve('out/y0'), 'y0-sheet-md02.jpg')] });
let s = await wait(j.job_id); console.log('9', s.state, JSON.stringify(s.error ?? '').slice(0, 300));
// 10: navigate away
j = await job({ prompt: 'A snowy mountain road at night, photoreal' });
for (let i = 0; i < 40; i++) { const t = await call('flow_job_status', { job_id: j.job_id }); if (t.state === 'generating') break; await new Promise((r) => setTimeout(r, 1000)); }
await new Promise((r) => setTimeout(r, 4000));
await page.goto('https://flow.google.com/', { waitUntil: 'domcontentloaded' });
s = await wait(j.job_id); console.log('10', s.state, JSON.stringify(s.error ?? '').slice(0, 400), 'paused', s.paused);
const st = await call('flow_status'); console.log('8 balance', st.balance, 'quota', st.ledger?.todayQuota?.banana21?.used, 'queue', JSON.stringify(st.queue));
await page.goto(PROJECT, { waitUntil: 'domcontentloaded' }); await client.close(); process.exit(0);
