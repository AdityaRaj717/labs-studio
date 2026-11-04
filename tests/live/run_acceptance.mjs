// Live acceptance run of docs/agent_control_testing_guide.md against the real shim over MCP stdio.
// node run_acceptance.mjs <results.jsonl> [--only 1,2,7]
// Env: FLOW_DATA_DIR (passed through), FLOW_TEST_PROJECT (default below), FISH_API_KEY for section 12; FLOW_ACC_VIDEO_RUN and FLOW_ACC_VIDEO_JOB reuse a clip for section 19 alone.
// Budget: images use free banana21 (bananaPro and banana2Lite once each); at most 3 video clips (this run uses 1,
// Omni 360p 4s silent, about 4 credits); audio_stable_generate is only ever an estimate. The run stops when the balance
// has dropped 60 from its start. A project is deleted only when this script created it.
import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '../../mcp/google-flow');
const require = createRequire(path.join(root, 'package.json'));
const { Client } = require('@modelcontextprotocol/sdk/client/index.js');
const { StdioClientTransport } = require('@modelcontextprotocol/sdk/client/stdio.js');

const PROJECT = process.env.FLOW_TEST_PROJECT ?? 'https://flow.google.com/project/065acc3b-852c-4cf2-84c6-80359d0543bd';
const MAX_DROP = 60;
const MAX_CLIPS = 3;
const args = process.argv.slice(2);
let only = null;
const oi = args.indexOf('--only');
if (oi >= 0) { only = new Set(args[oi + 1].split(/[ ,]+/).filter(Boolean).map(Number)); args.splice(oi, 2); }
const outFile = path.resolve(args[0] ?? 'acceptance-results.jsonl');
fs.mkdirSync(path.dirname(outFile), { recursive: true });

const client = new Client({ name: 'live-acceptance', version: '1' });
await client.connect(new StdioClientTransport({ command: process.execPath, args: [path.join(root, 'src/index.js')], cwd: root, stderr: 'ignore', env: process.env }));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function call(name, a = {}) {
  const r = await client.callTool({ name, arguments: a }, undefined, { timeout: 300000 });
  const t = r.content?.[0]?.text ?? '';
  let data; try { data = JSON.parse(t); } catch { data = t; }
  return { isError: Boolean(r.isError), data, code: data?.error_code ?? data?.error?.error_code };
}
const ok = async (name, a) => { const r = await call(name, a); if (r.isError) throw new Error(`${name} failed: ${r.code ?? JSON.stringify(r.data).slice(0, 200)} ${JSON.stringify(r?.data ?? r?.message ?? "").slice(0,300)}`); return r.data; };

// ---- file checks
function kindOf(buf) {
  if (buf.length >= 3 && buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff) return 'jpeg';
  if (buf.length >= 4 && buf.readUInt32BE(0) === 0x89504e47) return 'png';
  if (buf.length >= 12 && buf.toString('latin1', 4, 8) === 'ftyp') return 'mp4';
  if (buf.length >= 12 && buf.toString('latin1', 0, 4) === 'RIFF' && buf.toString('latin1', 8, 12) === 'WAVE') return 'wav';
  if (buf.length >= 3 && (buf.toString('latin1', 0, 3) === 'ID3' || (buf[0] === 0xff && (buf[1] & 0xe0) === 0xe0))) return 'mp3';
  return 'unknown';
}
function checkFile(file, allowed) {
  if (typeof file !== 'string' || !fs.existsSync(file)) throw new Error(`missing file: ${file}`);
  const size = fs.statSync(file).size;
  if (size <= 0) throw new Error(`empty file: ${file}`);
  const fd = fs.openSync(file, 'r'); const buf = Buffer.alloc(16); fs.readSync(fd, buf, 0, 16, 0); fs.closeSync(fd);
  const kind = kindOf(buf);
  if (!allowed.includes(kind)) throw new Error(`${file}: magic says ${kind}, wanted ${allowed.join('/')}`);
  return `${path.basename(file)} ${kind} ${size}B`;
}
const IMG = ['jpeg', 'png'];
const files = (outs) => (outs ?? []).map((o) => o.file ?? o);
const expectCode = (r, code) => { if (!r.isError || r.code !== code) throw new Error(`wanted ${code}, got ${r.isError ? r.code : 'success'}: ${JSON.stringify(r.data).slice(0, 160)}`); return `error_code ${code}`; };
const must = (cond, msg) => { if (!cond) throw new Error(msg); };

// ---- state shared between tests
const st = { image: null, runIds: [], char: null, scene: null, clips: 0, videoJob: process.env.FLOW_ACC_VIDEO_JOB ?? null, videoRun: process.env.FLOW_ACC_VIDEO_RUN ?? null, tmp: new Set(), startBalance: null };

async function balance() {
  try { const b = (await call('flow_status')).data?.balance; return typeof b === 'number' ? b : null; } catch { return null; }
}
async function finish(started, minutes = 15) {
  must(started?.job_id, `not queued: ${JSON.stringify(started).slice(0, 200)}`);
  const end = Date.now() + minutes * 60000;
  while (Date.now() < end) {
    const s = (await call('flow_wait', { job_id: started.job_id, wait_ms: 50000 })).data;
    if (s?.finished) return s;
    if (s?.paused) throw new Error(`queue paused: ${JSON.stringify(s.paused).slice(0, 150)}`);
  }
  throw new Error('job did not finish in time');
}
async function genImage(extra = {}) {
  const started = await ok('flow_generate_image', { prompt: 'a small red paper boat on calm water, soft light', project_url: PROJECT, auto_confirm: true, max_credits: 1, ...extra });
  const s = await finish(started);
  must(s.state === 'done', `job ${s.state}: ${s.error?.error_code ?? ''} ${s.error?.message ?? ''}`);
  const list = files(s.outputs); must(list.length > 0, 'no outputs');
  const evidence = list.map((f) => checkFile(f, IMG)).join('; ');
  st.image = list[0]; st.runIds.push(s.run_id);
  return { evidence, list, s };
}
const ensureImage = async () => { if (!st.image || !fs.existsSync(st.image)) await genImage(); return st.image; };
const stamp = Date.now().toString(36);

// ---- tests: [id, section, credits, fn]
const tests = [];
const T = (id, section, credits, fn) => tests.push({ id, section, credits, fn });

// 1 Connection
T('1.1', 1, 0, async () => { const d = await ok('flow_connect', {}); must(d.status === 'connected', `status ${d.status}`); return { evidence: `connected ${d.account}` }; });
T('1.2', 1, 0, async () => { const d = await ok('flow_status', {}); must(d.browser === true, 'browser not attached'); return { evidence: `balance ${d.balance}, ${d.currentUrl}` }; });
T('1.3', 1, 0, async () => { const d = await ok('flow_status', { full: true }); return { evidence: checkFile(d.screenshot, ['png', 'jpeg']) }; });
T('1.4', 1, 0, async () => { const d = await ok('flow_status', {}); must(d.account, "no account"); return { evidence: `${d.account} ${d.accountStatus}` }; });
T('1.5', 1, 0, async () => { await ok('flow_disconnect', {}); const d = await ok('flow_connect', {}); must(d.status === 'connected', d.status); return { evidence: 'reconnected' }; });

// 2 Simple image generation
T('2.1', 2, 0, async () => { const d = await ok('flow_generate_image', { prompt: 'blue butterfly', project_url: PROJECT }); must(d.status === 'ready_for_confirmation' && !d.job_id, JSON.stringify(d).slice(0, 150)); return { evidence: `dry run, estimate ${JSON.stringify(d.estimate)}` }; });
T('2.2', 2, 0, async () => { const g = await genImage(); return { evidence: g.evidence }; });
T('2.3', 2, 0, async () => { const g = await genImage({ prompt: 'chaos' }); return { evidence: g.evidence }; });
T('2.4', 2, 0, async () => { const d = await ok('flow_generate_image', { prompt: 'a lantern [1+1=2] "quoted" 猫と傘 <b>', project_url: PROJECT }); must(d.status === 'ready_for_confirmation', 'not accepted'); return { evidence: 'special characters accepted in dry run' }; });

// 3 Models
T('3.1', 3, 0, async () => { const g = await genImage({ model: 'banana21' }); return { evidence: g.evidence }; });
T('3.2', 3, 0, async () => { const g = await genImage({ model: 'bananaPro' }); return { evidence: g.evidence }; });
T('3.3', 3, 0, async () => { const g = await genImage({ model: 'banana2Lite' }); return { evidence: g.evidence }; });

// 4 Ratios
T('4.1', 4, 0, async () => { const g = await genImage({ ratio: '9:16' }); return { evidence: g.evidence }; });
T('4.2', 4, 0, async () => {
  const seen = [];
  for (const ratio of ['16:9', '4:3', '1:1', '3:4', '9:16']) { const d = await ok('flow_generate_image', { prompt: 'ratio check', ratio }); must(d.status === 'ready_for_confirmation' && d.request.ratio === ratio, ratio); seen.push(ratio); }
  return { evidence: `dry runs ok: ${seen.join(' ')}` };
});

// 5 Size and count
T('5.1', 5, 0, async () => { const g = await genImage({ size: '2K' }); return { evidence: g.evidence }; });
T('5.2', 5, 0, async () => { const g = await genImage({ count: 2 }); must(g.list.length === 2, `got ${g.list.length} files`); return { evidence: g.evidence }; });
T('5.3', 5, 0, async () => { const d = await ok('flow_generate_image', { prompt: 'count check', count: 4, size: '2K' }); must(d.status === 'ready_for_confirmation', 'no dry run'); return { evidence: `estimate ${JSON.stringify(d.estimate)}` }; });

// 6 Reference images
T('6.1', 6, 0, async () => {
  const ref = await ensureImage(); const before = checkFile(ref, IMG);
  const g = await genImage({ prompt: 'the same boat at sunset', ingredients: [ref] });
  return { evidence: `ref ${before}; out ${g.evidence}` };
});

// 7 Projects
T('7.1', 7, 0, async () => { const d = await ok('flow_list_projects', {}); const id = PROJECT.split('/').pop(); must(JSON.stringify(d).includes(id), 'target project not listed'); return { evidence: 'target project listed' }; });
T('7.2', 7, 0, async () => { const d = await ok('flow_open_project', { url: PROJECT, create_if_missing: false }); return { evidence: `opened ${d.url ?? d.project_url}` }; });
let tmpUrl = null;
T('7.3', 7, 0, async () => {
  const d = await ok('flow_open_project', { name: `acceptance-${stamp}`, create_if_missing: true });
  tmpUrl = d.url ?? d.project_url; must(tmpUrl && tmpUrl !== PROJECT, `url ${tmpUrl}`); st.tmp.add(tmpUrl);
  const list = await ok('flow_list_projects', { query: `acceptance-${stamp}` }); must(JSON.stringify(list).includes(tmpUrl.split('/').pop()), 'created project not listed');
  return { evidence: `created ${tmpUrl}` };
});
T('7.4', 7, 0, async () => { must(tmpUrl, 'no created project'); await ok('flow_rename_project', { url: tmpUrl, name: `acceptance-${stamp}-renamed` }); const list = await ok('flow_list_projects', { query: `acceptance-${stamp}-renamed` }); must(JSON.stringify(list).includes(`${stamp}-renamed`), 'rename not listed'); return { evidence: 'renamed and listed' }; });
T('7.5', 7, 0, async () => { const r = await call('flow_delete_project', { url: tmpUrl ?? PROJECT }); return { evidence: expectCode(r, 'INVALID_PARAMS') }; });
T('7.6', 7, 0, async () => {
  must(tmpUrl && st.tmp.has(tmpUrl), 'refusing: not a project this script created');
  await ok('flow_delete_project', { url: tmpUrl, confirm: true }); st.tmp.delete(tmpUrl);
  const list = await ok('flow_list_projects', { query: `acceptance-${stamp}` }); must(!JSON.stringify(list).includes(tmpUrl.split('/').pop()), 'still listed');
  return { evidence: 'deleted and gone from list' };
});

// 8 Characters
T('8.1', 8, 0, async () => {
  const img = await ensureImage(); const ev = checkFile(img, IMG); st.char = `accchar${stamp}`;
  await ok('flow_create_character', { project_url: PROJECT, name: st.char, images: [img], auto_confirm: true });
  return { evidence: `source ${ev}` };
});
T('8.2', 8, 0, async () => { must(st.char, 'no character'); const d = await ok('flow_list_characters', { project_url: PROJECT, details: true }); must(JSON.stringify(d).includes(st.char), 'character not listed'); return { evidence: `${st.char} listed` }; });
T('8.3', 8, 0, async () => {
  const name = `accnoprompt${stamp}`; const r = await call('flow_create_character', { project_url: PROJECT, name, prompt: 'a tall sailor', auto_confirm: false });
  const d = await ok('flow_list_characters', { project_url: PROJECT }); must(!JSON.stringify(d).includes(name), 'a prompt-only character was created without auto_confirm');
  return { evidence: `no spend without auto_confirm (${r.isError ? r.code : r.data?.status ?? 'ok'})` };
});

// 9 Scenes
T('9.1', 9, 0, async () => { const img = await ensureImage(); const ev = checkFile(img, IMG); st.scene = `accscene${stamp}`; await ok('flow_create_scene', { project_url: PROJECT, name: st.scene, images: [img], auto_confirm: false }); return { evidence: `source ${ev}` }; });
T('9.2', 9, 0, async () => { must(st.scene, 'no scene'); const d = await ok('flow_list_scenes', { project_url: PROJECT }); must(JSON.stringify(d).includes(st.scene), 'scene not listed'); return { evidence: `${st.scene} listed` }; });

// 10 Characters and scenes in generation
T('10.1', 10, 0, async () => { must(st.char && st.scene, 'needs sections 8 and 9'); const g = await genImage({ prompt: 'the character stands in the scene', ingredients: [{ character: st.char }, { scene: st.scene }] }); return { evidence: g.evidence }; });

// 11 Video: one clip, Omni 360p 4s silent
T('11.1', 11, 4, async () => {
  const d = await ok('flow_generate_video', { prompt: 'a paper boat drifting on still water', model: 'omni', resolution: '360p', duration: 4, silent: true, project_url: PROJECT });
  must(d.status === 'ready_for_confirmation' && !d.job_id, 'not a dry run'); return { evidence: `estimate ${JSON.stringify(d.estimate)}` };
});
T('11.2', 11, 4, async () => {
  must(st.clips < MAX_CLIPS, 'clip cap reached'); st.clips++;
  const started = await ok('flow_generate_video', { prompt: 'a paper boat drifting on still water', model: 'omni', resolution: '360p', duration: 4, silent: true, project_url: PROJECT, auto_confirm: true, max_credits: 5 });
  const s = await finish(started, 25); must(s.state === 'done', `job ${s.state}: ${s.error?.error_code ?? ''}`);
  const list = files(s.outputs); must(list.length === 1, `${list.length} outputs`);
  st.videoJob = s.job_id; st.videoRun = s.run_id;
  return { evidence: list.map((f) => checkFile(f, ['mp4'])).join('; ') };
});

// 12 Audio
T('12.1', 12, 0, async () => { const d = await ok('audio_voice_list', { limit: 3 }); must(Array.isArray(d.voices) && d.voices.length > 0, 'no voices'); return { evidence: `${d.voices.length} voices` }; });
T('12.2', 12, 0, async () => { const d = await ok('audio_voice_generate', { text: 'Acceptance check, one two three.', model: 's2.1-pro-free', format: 'mp3', name: `acc-${stamp}` }); return { evidence: checkFile(d.file, ['mp3']) }; });
T('12.3', 12, 0, async () => { const d = await ok('audio_stable_generate', { kind: 'sfx', prompt: 'a short door knock', duration: 2 }); must(!d.file, 'a file was produced without auto_confirm'); return { evidence: `estimate only: ${JSON.stringify(d).slice(0, 120)}` }; });

// 13 Batch
T('13.1', 13, 0, async () => {
  const d = await ok('flow_batch_start', { name: `acc-batch-${stamp}`, project: PROJECT, jobs: [{ prompt: 'batch one, a lighthouse' }, { prompt: 'batch two, a windmill' }, { prompt: 'batch three, a bridge' }] });
  must(!d.run_id, 'queued without auto_confirm'); return { evidence: `estimate ${JSON.stringify(d.estimate ?? d).slice(0, 120)}` };
});
T('13.2', 13, 0, async () => {
  const d = await ok('flow_batch_start', { name: `acc-batch-${stamp}`, project: PROJECT, auto_confirm: true, max_credits: 1, jobs: [{ prompt: 'batch one, a lighthouse' }, { prompt: 'batch two, a windmill' }] });
  must(d.run_id, `no run: ${JSON.stringify(d).slice(0, 150)}`);
  const end = Date.now() + 25 * 60000; let s;
  while (Date.now() < end) { s = (await call('flow_wait', { run_id: d.run_id, wait_ms: 50000 })).data; if (s.finished) break; if (s.paused) throw new Error('queue paused'); }
  must(s?.finished, 'batch did not finish');
  const full = (await call('flow_job_status', { run_id: d.run_id, detail: 'full' })).data;
  const outs = (full.jobs ?? []).flatMap((j) => files(j.outputs)); must(outs.length === 2, `${outs.length} files`);
  st.runIds.push(d.run_id); return { evidence: outs.map((f) => checkFile(f, IMG)).join('; ') };
});

// 14 Cross-project
T('14.1', 14, 0, async () => {
  must(st.char, 'needs section 8'); const d = await ok('flow_open_project', { name: `acceptance-x-${stamp}`, create_if_missing: true });
  const url = d.url ?? d.project_url; must(url && url !== PROJECT, 'no new project'); st.tmp.add(url);
  await ok('flow_import_character', { project_url: url, from_project_url: PROJECT, name: st.char });
  const list = await ok('flow_list_characters', { project_url: url }); must(JSON.stringify(list).includes(st.char), 'imported character not listed');
  must(st.tmp.has(url), 'refusing to delete a project not created here'); await ok('flow_delete_project', { url, confirm: true }); st.tmp.delete(url);
  return { evidence: 'imported, listed, temp project deleted' };
});

// 15 Diagnostics
T('15.1', 15, 0, async () => { const d = await ok('flow_doctor', {}); must(d.ok === true, `missing ${JSON.stringify(d.missing)}`); return { evidence: 'doctor ok' }; });
T('15.2', 15, 0, async () => { const d = await ok('flow_capabilities', {}); must(d.image?.models?.includes('banana21') && d.video?.models?.omni, 'models missing'); return { evidence: `verifiedAt ${d.verifiedAt}` }; });
T('15.3', 15, 0, async () => { const d = await ok('flow_screenshot', { name: 'acceptance' }); const f = d.path ?? d.file ?? d.screenshot; return { evidence: checkFile(f, ['png', 'jpeg']) }; });
T('15.4', 15, 0, async () => {
  must(st.runIds.length, 'no run yet'); const d = await ok('flow_list_assets', { run_id: st.runIds[0] }); must(d.assets?.length > 0, 'no assets');
  return { evidence: d.assets.map((a) => checkFile(a.file, IMG)).join('; ') };
});
T('15.5', 15, 0, async () => { const d = await ok('flow_list_runs', { limit: 5 }); must(d.runs?.length > 0, 'no runs'); return { evidence: `${d.runs.length} runs` }; });

// 16 Errors
T('16.1', 16, 0, async () => ({ evidence: expectCode(await call('flow_generate_image', { prompt: '   ' }), 'INVALID_PARAMS') }));
T('16.2', 16, 0, async () => ({ evidence: expectCode(await call('flow_generate_image', { prompt: 'x', model: 'nope' }), 'MODEL_NOT_AVAILABLE') }));
T('16.3', 16, 0, async () => ({ evidence: expectCode(await call('flow_generate_image', { prompt: 'x', ratio: '7:5' }), 'RATIO_NOT_AVAILABLE') }));
T('16.4', 16, 0, async () => ({ evidence: expectCode(await call('flow_open_project', { url: 'https://flow.google.com/project/00000000-0000-0000-0000-000000000000', create_if_missing: false }), 'PROJECT_NOT_FOUND') }));
T('16.5', 16, 0, async () => ({ evidence: expectCode(await call('flow_generate_image', { prompt: 'x', ingredients: ['Z:\\no\\such\\file.png'] }), 'INVALID_PARAMS') }));
T('16.6', 16, 0, async () => ({ evidence: expectCode(await call('flow_generate_image', { prompt: 'x', count: 5 }), 'INVALID_PARAMS') }));
T('16.7', 16, 0, async () => ({ evidence: expectCode(await call('flow_generate_video', { prompt: 'x', auto_confirm: true, max_credits: 1 }), 'BUDGET_EXCEEDED') }));
T('16.8', 16, 0, async () => ({ evidence: expectCode(await call('flow_job_status', { job_id: 'job_does_not_exist' }), 'JOB_NOT_FOUND') }));
T('16.9', 16, 0, async () => ({ evidence: expectCode(await call('flow_delete_project', { url: PROJECT }), 'INVALID_PARAMS') }));

// 18 Stress and boundary
T('18.1', 18, 0, async () => {
  const jobs = Array.from({ length: 20 }, (_, i) => ({ prompt: `estimate ${i}`, kind: i % 2 ? 'video' : 'image', ...(i % 2 ? { model: 'omni', duration: 4, resolution: '360p' } : {}) }));
  const d = await ok('flow_estimate', { jobs }); return { evidence: `estimate ${JSON.stringify(d).slice(0, 140)}` };
});
T('18.2', 18, 0, async () => {
  const key = `acc-${stamp}`;
  const a = await ok('flow_generate_image', { prompt: 'idempotency boat', project_url: PROJECT, auto_confirm: true, max_credits: 1, idempotency_key: key });
  const b = await ok('flow_generate_image', { prompt: 'idempotency boat', project_url: PROJECT, auto_confirm: true, max_credits: 1, idempotency_key: key });
  must(b.repeated === true && b.job_id === a.job_id, 'repeat did not return the first job');
  const mid = await call('flow_status'); must(!mid.isError, 'flow_status failed while a job ran');
  const s = await finish(a); must(s.state === 'done', `job ${s.state}`);
  return { evidence: files(s.outputs).map((f) => checkFile(f, IMG)).join('; ') };
});

// 19 Last frame and stitch (uses the section 11 clip)
T('19.1', 19, 0, async () => { must(st.videoJob, 'no clip'); const d = await ok('last_frame', { run_id: st.videoRun, asset_id: st.videoJob }); return { evidence: checkFile(d.file, ['png', 'jpeg']) }; });
// S5-3: stitch_video returns a stitch_id at once; flow_wait on it until finished, then read file or error.
T('19.2', 19, 0, async () => {
  must(st.videoRun, 'no clip');
  const d = await ok('stitch_video', { run_id: st.videoRun, auto: true, name: `acc-${stamp}` });
  must(d.stitch_id, `no stitch_id: ${JSON.stringify(d).slice(0, 200)}`);
  let s = d; const end = Date.now() + 600000;
  while (!s.finished && Date.now() < end) s = await ok('flow_wait', { stitch_id: d.stitch_id, wait_ms: 50000 });
  must(s.finished && s.state === 'done', `stitch ${s.state}: ${s.error ?? ''}`);
  return { evidence: checkFile(s.file, ['mp4']) };
});

// ---- runner
const append = (o) => fs.appendFileSync(outFile, `${JSON.stringify(o)}\n`);
st.startBalance = await balance();
append({ id: 'start', section: 0, pass: true, evidence: `project ${PROJECT}`, credits_balance_before: st.startBalance, after: st.startBalance, detail: only ? `only ${[...only].join(',')}` : 'all' });
let stopped = false;
for (const t of tests) {
  if (only && !only.has(t.section)) continue;
  const before = await balance();
  let r;
  try { r = await t.fn(); r = { pass: true, ...r }; } catch (e) { r = { pass: false, evidence: null, detail: String(e.message).slice(0, 500) }; }
  const after = await balance();
  append({ id: t.id, section: t.section, pass: r.pass, evidence: r.evidence ?? null, credits_balance_before: before, after, detail: r.detail ?? `credits budgeted ${t.credits}` });
  console.log(`${r.pass ? 'PASS' : 'FAIL'} ${t.id} ${r.evidence ?? r.detail}`);
  if (st.startBalance != null && after != null && st.startBalance - after >= MAX_DROP) {
    append({ id: 'stop', section: 0, pass: false, evidence: null, credits_balance_before: st.startBalance, after, detail: `balance dropped ${st.startBalance - after}, stopping` });
    stopped = true; break;
  }
}
// Cleanup: only projects this script created.
for (const url of st.tmp) { try { await call('flow_delete_project', { url, confirm: true }); } catch { /* left for the owner */ } }
await client.close();
console.log(stopped ? 'stopped on budget' : 'done');
process.exit(0);
