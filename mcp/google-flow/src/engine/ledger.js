import fs from 'fs';
import path from 'path';
import { getDataDir } from '../utils/config.js';
import { createError, ErrorCodes } from '../utils/errors.js';
import { getCapabilities } from './capabilities.js';
import { readStateFile, writeFileAtomic } from './run-folder.js';

const ledgerFile = () => path.join(getDataDir(), 'ledger.json');
const today = () => new Date().toLocaleDateString('sv'); // local YYYY-MM-DD

function spends() {
  const saved = readStateFile(ledgerFile());
  if (saved === null) return {};
  if (typeof saved.spends !== 'object' || saved.spends === null) {
    throw createError(ErrorCodes.INTERNAL_ERROR, `Corrupt state file: ${ledgerFile()}`, {
      next_action: `Restore or repair ${ledgerFile()}; deleting it forgets what it recorded.`,
    });
  }
  return saved.spends;
}

// Keyed by job, so recording twice after a crash or retry never double-counts: the first record stands.
export function recordSpend(job, credits) {
  if (!job?.id) throw createError(ErrorCodes.INVALID_PARAMS, 'recordSpend needs a job with an id');
  if (!Number.isFinite(credits) || credits < 0) {
    throw createError(ErrorCodes.INVALID_PARAMS, `credits must be a number, 0 or more: ${credits}`);
  }
  const all = spends();
  if (all[job.id]) return all[job.id];
  const { kind, model, count } = job.spec ?? {};
  all[job.id] = { credits, model, images: kind === 'image' ? count : 0, day: today() };
  fs.mkdirSync(getDataDir(), { recursive: true });
  writeFileAtomic(ledgerFile(), JSON.stringify({ spends: all }));
  return all[job.id];
}

export function monthTotal() {
  const month = today().slice(0, 7);
  return Object.values(spends())
    .filter((spend) => spend.day.startsWith(month))
    .reduce((sum, spend) => sum + spend.credits, 0);
}

export function todayQuota(model) {
  const group = getCapabilities().limits.imageDaily.find(({ models }) => models.includes(model));
  const models = group?.models ?? [model];
  const used = Object.values(spends())
    .filter((spend) => spend.day === today() && models.includes(spend.model))
    .reduce((sum, spend) => sum + spend.images, 0);
  const limit = group?.limit ?? null;
  return { model, used, limit, remaining: limit === null ? null : Math.max(0, limit - used) };
}
