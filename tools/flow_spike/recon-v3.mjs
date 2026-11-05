import * as y from './y0lib.mjs';
import { connect, PROJECT } from './mcp.mjs';
const { call, client } = await connect();
const { browser, page } = await y.attach();
await call('flow_job_control', { action: 'resume' });
const read = () => y.locate(page, 'project.tile').evaluateAll((els) => ({ n: els.length, top: els.slice(0, 3).map((el) => ({ l: el.getAttribute('aria-label')?.slice(0, 24), t: el.innerText.replace(/\s+/g, ' ').slice(0, 40), img: el.querySelector('img')?.getAttribute('src')?.slice(40, 62), alt: el.querySelector('img')?.alt?.slice(0, 12), v: el.querySelector('video')?.getAttribute('src')?.slice(40, 62), kid: el.firstElementChild?.tagName, tag: el.querySelector('flow-video-tile,[class*=progress],[class*=pending]')?.tagName })) }));
const j = await call('flow_generate_video', { project_url: PROJECT, auto_confirm: true, prompt: 'A blue umbrella spinning on wet cobblestones, slow camera', model: 'omni', resolution: '360p', duration: 4, max_credits: 5 });
let last = ''; const t0 = Date.now();
while (Date.now() - t0 < 80000) { let r; try { r = JSON.stringify(await read()); } catch (e) { r = 'ERR'; } if (r !== last) { console.log(Math.round((Date.now() - t0) / 1000), r); last = r; } await page.waitForTimeout(1500); }
const s = await call('flow_job_status', { job_id: j.job_id }); console.log(s.state, JSON.stringify(s.error ?? '').slice(0, 200));
await browser.close(); await client.close(); process.exit(0);
