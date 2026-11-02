import fs from 'fs';
import path from 'path';

// Returns only once the line is fsynced; a failed write is rolled back so the file stays parseable.
export function appendLine(file, line) {
  const size = fs.existsSync(file) ? fs.statSync(file).size : 0;
  const fd = fs.openSync(file, 'a');
  try {
    fs.writeFileSync(fd, `${line}\n`);
    fs.fsyncSync(fd);
  } catch (err) {
    try { fs.truncateSync(file, size); } catch { /* the reader drops a torn tail anyway */ }
    throw err;
  } finally {
    fs.closeSync(fd);
  }
}

export function appendEvent(run, event) {
  const record = { seq: run.seq + 1, ts: new Date().toISOString(), ...event };
  appendLine(path.join(run.dir, 'events.jsonl'), JSON.stringify(record));
  run.seq = record.seq;
  return record;
}

// A line with no newline never finished, so its caller never went on: cut it off, or the
// next append would merge with it. Bad JSON elsewhere throws, since guessing a job's state
// from a damaged journal could spend credits twice.
export function readEvents(file) {
  const raw = fs.readFileSync(file);
  const end = raw.lastIndexOf('\n') + 1;
  if (end < raw.length) fs.truncateSync(file, end);
  return raw.toString('utf8', 0, end).split('\n').filter(Boolean).map((line, i) => {
    try {
      return JSON.parse(line);
    } catch {
      throw new Error(`Corrupt journal ${file} at line ${i + 1}`);
    }
  });
}
