import { connect } from './mcp.mjs';
const { call, client } = await connect();
const s = (o) => JSON.stringify(o).slice(0, 500);
const R = '20261102-190449-t3-mvzaw0af';
console.log('voices', s(await call('audio_voice_list', {})).slice(0, 200));
console.log('voice', s(await call('audio_voice_generate', { run_id: R, text: 'Ana walks along the dock as the fog rolls in, and she waves slowly.' })));
console.log('sfx', s(await call('audio_stable_generate', { run_id: R, kind: 'sfx', prompt: 'door slam', duration: 10, auto_confirm: true })));
console.log('stitch', s(await call('stitch_video', { run_id: R, auto: true })));
await client.close(); process.exit(0);
