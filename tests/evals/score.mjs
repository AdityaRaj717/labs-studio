// node score.mjs <dir of <eval id>.jsonl logs> <prompts file>...: tool calls, wrong calls, forbidden and missing tools per eval.
import fs from 'node:fs';
import path from 'node:path';
const [dir, ...files] = process.argv.slice(2);
const rows = files.flatMap((file) => JSON.parse(fs.readFileSync(file, 'utf8'))).map((e) => {
  const log = path.join(dir, `${e.id}.jsonl`);
  const calls = fs.existsSync(log) ? fs.readFileSync(log, 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse) : [];
  const used = calls.map((c) => c.tool);
  const missing = (e.must ?? []).filter((t) => !used.includes(t));
  const forbidden = used.filter((t) => (e.never ?? []).includes(t) || t === 'flow_production_review');
  const spent = calls.filter((c) => c.args.auto_confirm === true && c.args.confirm === undefined && !e.live && !e.may_start).length;
  return { id: e.id, level: e.level, calls: calls.length, wrong: calls.filter((c) => c.error).length, spent, missing: missing.join(), forbidden: forbidden.join(), pass: calls.length > 0 && !missing.length && !forbidden.length && !spent };
});
console.table(rows);
const rate = (r) => (r.length ? Math.round((100 * r.filter((x) => x.pass).length) / r.length) : 100);
console.log(`easy ${rate(rows.filter((r) => r.level === 'easy'))}%, overall ${rate(rows)}%`);
