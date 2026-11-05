import path from 'path';
import { appendEvent, readEvents } from '../engine/journal.js';
import { readStateFile, writeFileAtomic } from '../engine/run-folder.js';
import { logger } from '../utils/logger.js';
import { applyEvent } from './state.js';

const fileOf = (run) => path.join(run.dir, 'production.json');
const EVENT = 'production.event';

function write(run, production) {
  writeFileAtomic(fileOf(run), JSON.stringify(production, null, 2));
}

export function saveNew(run, production) {
  const saved = { ...production, last_seq: run.seq };
  write(run, saved);
  return saved;
}

// null: this Run is not a Production. Events past last_seq were journaled before a crash stopped the rewrite.
export function loadProduction(run) {
  const saved = readStateFile(fileOf(run));
  if (!saved) return null;
  const events = readEvents(path.join(run.dir, 'events.jsonl')).filter(({ seq, type }) => type === EVENT && seq > saved.last_seq);
  return events.reduce((production, { seq, event }) => ({ ...applyEvent(production, event), last_seq: seq }), saved);
}

// A refused event throws before anything is written. On return the event is fsynced, so a verdict holds through a crash.
export function commit(run, production, event) {
  const next = applyEvent(production, event);
  next.last_seq = appendEvent(run, { type: EVENT, event }).seq;
  try {
    write(run, next);
  } catch (err) {
    logger.warn('production.json write failed; the journal holds the change', { run: run.id, error: err.message });
  }
  return next;
}
