export const ErrorCodes = {
  WRONG_GOOGLE_ACCOUNT: 'WRONG_GOOGLE_ACCOUNT',
  NOT_LOGGED_IN: 'NOT_LOGGED_IN',
  FLOW_PAGE_NOT_FOUND: 'FLOW_PAGE_NOT_FOUND',
  MODEL_NOT_AVAILABLE: 'MODEL_NOT_AVAILABLE',
  RATIO_NOT_AVAILABLE: 'RATIO_NOT_AVAILABLE',
  GENERATION_BUTTON_DISABLED: 'GENERATION_BUTTON_DISABLED',
  GENERATION_TIMEOUT: 'GENERATION_TIMEOUT',
  DOWNLOAD_FAILED: 'DOWNLOAD_FAILED',
  MANUAL_VERIFICATION_REQUIRED: 'MANUAL_VERIFICATION_REQUIRED',
  GOOGLE_LIMIT_REACHED: 'GOOGLE_LIMIT_REACHED',
  UNKNOWN_UI_CHANGE: 'UNKNOWN_UI_CHANGE',
  PLAYWRIGHT_ERROR: 'PLAYWRIGHT_ERROR',
  BROWSER_NOT_CONNECTED: 'BROWSER_NOT_CONNECTED',
  JOB_IN_PROGRESS: 'JOB_IN_PROGRESS',
  INVALID_PARAMS: 'INVALID_PARAMS',
  GENERATION_REFUSED: 'GENERATION_REFUSED',
  PROJECT_NOT_FOUND: 'PROJECT_NOT_FOUND',
  COMBINATION_NOT_SUPPORTED: 'COMBINATION_NOT_SUPPORTED',
  BUDGET_EXCEEDED: 'BUDGET_EXCEEDED',
  WAF_BLOCK: 'WAF_BLOCK',
  FLOW_ACTIVITY_FLAG: 'FLOW_ACTIVITY_FLAG',
  DAILY_MODEL_LIMIT: 'DAILY_MODEL_LIMIT',
  DAILY_CAP_REACHED: 'DAILY_CAP_REACHED',
  AUDIO_NO_CREDIT: 'AUDIO_NO_CREDIT',
  SAFETY_BLOCKED: 'SAFETY_BLOCKED',
  AGENT_NEEDS_CLARIFICATION: 'AGENT_NEEDS_CLARIFICATION',
  RESULT_MISMATCH: 'RESULT_MISMATCH',
  UPLOAD_STALLED: 'UPLOAD_STALLED',
  NAVIGATION_TIMEOUT: 'NAVIGATION_TIMEOUT',
  AUDIO_RATE_LIMITED: 'AUDIO_RATE_LIMITED',
  AUDIO_UNAVAILABLE: 'AUDIO_UNAVAILABLE',
  FLOW_GENERATION_FAILED: 'FLOW_GENERATION_FAILED',
  MISSING_API_KEY: 'MISSING_API_KEY',
  FFMPEG_NOT_FOUND: 'FFMPEG_NOT_FOUND',
  JOB_NOT_FOUND: 'JOB_NOT_FOUND',
  INTERNAL_ERROR: 'INTERNAL_ERROR',
  JOURNAL_CORRUPT: 'JOURNAL_CORRUPT',
  NOT_IMPLEMENTED: 'NOT_IMPLEMENTED',
  PROMPT_FILE_INVALID: 'PROMPT_FILE_INVALID',
  ANALYSIS_REQUIRED: 'ANALYSIS_REQUIRED',
  PLAN_CHANGED: 'PLAN_CHANGED',
  PRODUCTION_NOT_FOUND: 'PRODUCTION_NOT_FOUND',
  ITEM_NOT_FOUND: 'ITEM_NOT_FOUND',
  REVIEW_CONFLICT: 'REVIEW_CONFLICT',
};

const inClass = (cls) => (next_action) => ({ class: cls, next_action });
const owner = inClass('owner');
const stopRun = inClass('stop_run');
const job = inClass('job');
const retry = inClass('retry');
const retryWithSpend = inClass('retry_with_spend');
const caller = inClass('caller');

// Spec 6.5. The last group predates the spec and is classed by what a failure there can cost.
export const ERROR_CLASSES = {
  NOT_LOGGED_IN: owner('Sign in to Google in the Flow Chrome window, then call resume.'),
  WRONG_GOOGLE_ACCOUNT: owner('Switch to the expected Google account in the Flow Chrome window, then call resume.'),
  MANUAL_VERIFICATION_REQUIRED: owner('Complete the verification yourself in the Flow Chrome window, then call resume.'),
  FLOW_ACTIVITY_FLAG: owner('Flow flagged this generation as unusual activity. Check the Chrome window yourself, delete the failed tile, then call resume.'),
  WAF_BLOCK: owner('Stop using Flow for now, check the Chrome window yourself, then call resume once it loads normally.'),

  GOOGLE_LIMIT_REACHED: stopRun('Wait for the Google limit to reset, then call resume.'),
  DAILY_MODEL_LIMIT: stopRun('Wait for the daily reset or pick another model, then call resume.'),
  DAILY_CAP_REACHED: stopRun('Wait for tomorrow or raise the daily cap setting, then call resume.'),
  BUDGET_EXCEEDED: stopRun('Raise max_credits or request fewer or cheaper videos.'),
  UNKNOWN_UI_CHANGE: stopRun('Run flow_doctor and update config/ui-contract.json.'),
  AUDIO_NO_CREDIT: stopRun('Top up the audio account, then call resume.'),

  GENERATION_REFUSED: job('Reword the prompt and submit it as a new job.'),
  SAFETY_BLOCKED: job('Reword the prompt and submit it as a new job. Video credits return within an hour.'),
  AGENT_NEEDS_CLARIFICATION: job('Make the prompt more specific and submit it as a new job.'),
  RESULT_MISMATCH: job('Review the kept files, then decide whether to retry the job.'),

  UPLOAD_STALLED: retry('Retry the job; the upload repeats no spend.'),
  DOWNLOAD_FAILED: retry('Retry the download; the generation is not repeated.'),
  NAVIGATION_TIMEOUT: retry('Retry the call.'),
  BROWSER_NOT_CONNECTED: retry('Check that the Flow Chrome window is open, then retry.'),
  AUDIO_RATE_LIMITED: retry('Retry after a short wait.'),
  AUDIO_UNAVAILABLE: retry('Retry after a short wait.'),

  FLOW_GENERATION_FAILED: retryWithSpend('Retry only with an explicit retry call or max_generation_retries, since a retry spends again.'),

  INVALID_PARAMS: caller('Fix the listed parameter and call again.'),
  MODEL_NOT_AVAILABLE: caller('Pick a model from flow_capabilities.'),
  RATIO_NOT_AVAILABLE: caller('Pick a ratio from flow_capabilities.'),
  COMBINATION_NOT_SUPPORTED: caller('Pick a combination listed in flow_capabilities.'),
  PROJECT_NOT_FOUND: caller('Check the project id or create the project.'),
  MISSING_API_KEY: caller('Set the API key in the app settings.'),
  FFMPEG_NOT_FOUND: caller('Set the ffmpegPath setting or the FFMPEG_PATH environment variable.'),
  JOB_NOT_FOUND: caller('Check the job id against flow_status.'),
  PROMPT_FILE_INVALID: caller('Fix the named file and line, or pass the whole plan as JSON, then call flow_production_plan again.'),
  ANALYSIS_REQUIRED: caller('Read both files, answer analysis_needed through overrides, and call flow_production_plan again.'),
  PLAN_CHANGED: caller('Call flow_production_plan again and start with its new plan_id.'),
  PRODUCTION_NOT_FOUND: caller('Check the id against flow_production_status or flow_list_runs.'),
  ITEM_NOT_FOUND: caller('Check the item id against flow_production_status.'),
  REVIEW_CONFLICT: caller('Read the current state with flow_production_status, then decide again.'),

  FLOW_PAGE_NOT_FOUND: retry('Open the Flow home page in the Chrome window and retry.'),
  GENERATION_BUTTON_DISABLED: job('Check the prompt and settings in the Flow tab, then submit a new job.'),
  GENERATION_TIMEOUT: job('Check the project in Flow for the result before spending on a retry.'),
  PLAYWRIGHT_ERROR: stopRun('Check the Flow Chrome window, then call resume.'),
  JOB_IN_PROGRESS: caller('Wait for the current job with flow_wait, then call again.'),
  JOURNAL_CORRUPT: stopRun('Repair or remove the named journal file, then start the engine again. Guessing could spend credits twice.'),
  NOT_IMPLEMENTED: caller('This tool is not built yet. Check flow://guide for what works now.'),
  INTERNAL_ERROR: stopRun('Read the engine log and fix the cause in details, then call resume.'),
};

export class FlowError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = 'FlowError';
    this.code = code;
    this.details = details;
  }

  toJSON() {
    return {
      error: this.code,
      message: this.message,
      details: this.details,
    };
  }
}

export function createError(code, message, details = {}) {
  return new FlowError(code, message, details);
}

export function toErrorPayload(err) {
  const known = err instanceof FlowError && ERROR_CLASSES[err.code];
  const error_code = known ? err.code : ErrorCodes.INTERNAL_ERROR;
  const { next_action, credits_at_risk, screenshot, ...details } = known ? err.details : { code: err?.code };
  return {
    ok: false,
    error_code,
    message: err?.message ?? String(err),
    retryable: ERROR_CLASSES[error_code].class === 'retry',
    credits_at_risk: credits_at_risk ?? false,
    next_action: next_action ?? ERROR_CLASSES[error_code].next_action,
    details,
    screenshot: screenshot ?? null,
  };
}
