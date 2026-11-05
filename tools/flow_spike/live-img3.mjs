import * as y from './y0lib.mjs';
import { connect, PROJECT } from './mcp.mjs';
const { call, client } = await connect();
const { page } = await y.attach();
await page.goto(PROJECT, { waitUntil: 'domcontentloaded' }); await y.locate(page, 'project.prompt').waitFor({ timeout: 30000 }); await page.waitForTimeout(1500);
const ag = y.locate(page, 'project.agent');
const dump = async (w) => console.log(w, await ag.evaluate((e) => ({ pressed: e.getAttribute('aria-pressed'), cls: e.className.slice(-60), attrs: e.getAttributeNames().join(',') })), (await y.snap(page, 'agent')).split('\n').filter((l) => /button "Agent"/.test(l)).join());
await dump('start'); await ag.click(); await page.waitForTimeout(800); await dump('clicked');
console.log(await call('flow_job_control', { action: 'resume' }).then((r) => JSON.stringify(r).slice(0, 200)));
const j = await call('flow_generate_image', { project_url: PROJECT, auto_confirm: true, prompt: 'A lighthouse at dawn over calm sea, photoreal' });
const seen = new Set(); let s;
for (let i = 0; i < 60; i++) { s = await call('flow_job_status', { job_id: j.job_id }); if (s.progress?.source === 'flow') seen.add(s.progress.progress); if (['done', 'failed', 'paused'].includes(s.state)) break; await new Promise((r) => setTimeout(r, 2000)); }
console.log('result', s.state, 'flow%', [...seen].join(','), 'observed', JSON.stringify(s.outputs?.[0]?.observed), JSON.stringify(s.error ?? '').slice(0, 300));
await dump('after'); console.log('permission radios', await page.getByRole('radiogroup', { name: 'Permission options' }).count());
await client.close(); process.exit(0);
