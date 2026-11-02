import { createError, ErrorCodes } from '../utils/errors.js';
import { getCapabilities } from './capabilities.js';

const DEFAULT_MAX_CREDITS = 30;

// Takes jobs from validateImage and validateVideo. Flow's live quote decides at Start; this is the preview.
export function estimate(jobSpecs) {
  const { video, limits } = getCapabilities();
  const result = { credits: 0, imageQuota: {}, warnings: [] };
  for (const job of jobSpecs) {
    if (job.kind === 'image') {
      result.imageQuota[job.model] = (result.imageQuota[job.model] ?? 0) + job.count;
    } else {
      const caps = video.models[job.model];
      const each = job.mode === 'edit' ? caps.editCredits : caps.credits[job.resolution][job.duration];
      result.credits += each * job.count;
    }
  }
  for (const { models, limit } of limits.imageDaily) {
    const used = models.reduce((sum, model) => sum + (result.imageQuota[model] ?? 0), 0);
    if (used > limit) result.warnings.push(`${used} images exceed the daily limit for ${models.join(' + ')}: ${limit}`);
  }
  return result;
}

export function checkBudget(estimated, maxCredits = DEFAULT_MAX_CREDITS, ledger) {
  if (!Number.isFinite(maxCredits) || maxCredits < 0) {
    throw createError(ErrorCodes.INVALID_PARAMS, `max_credits must be a number, 0 or more: ${maxCredits}`, {
      next_action: 'Pass max_credits as a number.',
    });
  }
  const { credits } = estimated;
  if (credits > maxCredits) {
    throw createError(ErrorCodes.BUDGET_EXCEEDED, `${credits} credits is above max_credits ${maxCredits}`, {
      credits,
      maxCredits,
      next_action: 'Raise max_credits or request fewer or cheaper videos.',
    });
  }
  const { monthlyCredits } = getCapabilities().limits;
  const monthTotal = ledger.monthTotal();
  if (monthTotal + credits > monthlyCredits) {
    throw createError(ErrorCodes.BUDGET_EXCEEDED, `${credits} credits would pass the monthly allowance: ${monthTotal} of ${monthlyCredits} used`, {
      credits,
      monthTotal,
      monthlyCredits,
      next_action: 'Wait for the monthly reset or request cheaper videos.',
    });
  }
}
