import { logger } from '../utils/logger.js';
import { getPage, isBrowserConnected } from '../browser/connect.js';
import { readAccountStatus } from '../browser/account-check.js';
import { isFlowHost } from '../browser/host.js';
import { jobQueue } from '../queue/job-queue.js';
import { get } from '../utils/config.js';
import { takeScreenshot } from '../utils/screenshots.js';

export async function handleFlowStatus(args = {}) {
  const status = {
    browser: isBrowserConnected(),
    account: null,
    accountStatus: 'unverified',
    flowAccessible: false,
    oauthRequired: false,
    currentUrl: null,
    pageTitle: null,
    queue: jobQueue.getStatus(),
  };

  if (isBrowserConnected()) {
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
      if (args.full) status.screenshot = await takeScreenshot(page, 'flow-status');
    } catch (err) {
      status.browserError = err.message;
    }
  }

  status.expectedAccount = get('expectedAccount', '');

  logger.info('Status check', status);
  return status;
}
