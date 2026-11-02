import fs from 'node:fs';
try { const j = JSON.parse(fs.readFileSync('out/live-data/engine.json')); const r = await fetch(`http://127.0.0.1:${j.port}/shutdown`, { method: 'POST', headers: { authorization: `Bearer ${j.token}` } }); console.log('shutdown', r.status); } catch (e) { console.log('no engine', e.message); }
