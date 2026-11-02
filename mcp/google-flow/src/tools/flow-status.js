import { logger } from '../utils/logger.js';
import { getPage, isBrowserConnected } from '../browser/connect.js';
import { readAccountStatus } from '../browser/account-check.js';
import { isFlowHost } from '../browser/host.js';
import { locate } from '../flow/contract.js';
import { getCapabilities } from '../engine/capabilities.js';
import { allRuns } from '../engine/job-store.js';
import { monthTotal, todayQuota } from '../engine/ledger.js';
import { get } from '../utils/config.js';
import { takeScreenshot } from '../utils/screenshots.js';

const BALANCE_TIMEOUT_MS = 2000;
const BALANCE_MAX_AGE_MS = 60000; // opening the panel is visible to the owner, so not on every poll
const IDLE = ['queued', 'done', 'failed', 'cancelled', 'needs_user', 'paused'];

let lastBalance = null;
let lastBalanceAt = 0;

// Reads the account panel. null when it isn't there: status must not fail on this.
export async function getBalance(page, timeout = BALANCE_TIMEOUT_MS) {
  try {
    await locate(page, 'account.open').click({ timeout });
    const text = await locate(page, 'account.balance').first().innerText({ timeout });
    await locate(page, 'account.close').click({ timeout });
    const credits = Number(text.replace(/[^\d]/g, ''));
    return text && Number.isFinite(credits) ? credits : null;
  } catch (err) {
    logger.debug('Balance not read', { error: err.message });
    return null;
  }
}

function queueStatus() {
  const jobs = allRuns().flatMap((run) => run.jobs);
  const counts = {};
  for (const { state } of jobs) counts[state] = (counts[state] ?? 0) + 1;
  const active = jobs.find((job) => !IDLE.includes(job.state));
  return { active: active ? { job_id: active.id, run_id: active.run.id, state: active.state } : null, counts };
}

function ledgerStatus() {
  const { models } = getCapabilities().image;
  return { monthTotal: monthTotal(), todayQuota: Object.fromEntries(models.map((model) => [model, todayQuota(model)])) };
}

// busy: a job holds the tab, so report only what needs no page.
export async function handleFlowStatus(args = {}) {
  const status = {
    browser: isBrowserConnected(),
    account: null,
    accountStatus: 'unverified',
    flowAccessible: false,
    oauthRequired: false,
    currentUrl: null,
    pageTitle: null,
    queue: queueStatus(),
    ledger: ledgerStatus(),
    balance: lastBalance,
  };

  if (args.busy) {
    status.tabBusy = true;
  } else if (isBrowserConnected()) {
    try {
      const page = getPage();
      status.currentUrl = page.url();
      status.pageTitle = await page.title();
      status.flowAccessible = isFlowHost(status.currentUrl);
      status.oauthRequired = status.currentUrl?.includes('accounts.google.com') || false;

      if (status.flowAccessible && !status.oauthRequired) {
        const check = await readAccountStatus(page);
        status.account = check.account;
        status.accountStatus = check.status;
      }
      if (status.flowAccessible && !status.oauthRequired && Date.now() - lastBalanceAt > BALANCE_MAX_AGE_MS) {
        const balance = await getBalance(page);
        if (balance !== null) {
          lastBalance = balance;
          lastBalanceAt = Date.now();
          status.balance = balance;
        }
      }
      if (args.full) status.screenshot = await takeScreenshot(page, 'flow-status');
    } catch (err) {
      status.browserError = err.message;
    }
  }

  status.expectedAccount = get('expectedAccount', '');

  logger.info('Status check', status);
  return status;
}
