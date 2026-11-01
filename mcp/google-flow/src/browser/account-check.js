import { logger } from '../utils/logger.js';
import { get } from '../utils/config.js';
import { FlowError, ErrorCodes } from '../utils/errors.js';
import { takeScreenshot } from '../utils/screenshots.js';
import { locate } from '../flow/contract.js';
import { getPage } from './connect.js';

// The name is 'Google Account: <name> (<email>), Google membership'.
const EMAIL_IN_NAME = /Google Account: .*\(([^()\s]+@[^()\s]+)\)/;

// status: ok (matches), mismatch (differs), unverified (nothing expected, or no account shown).
export async function readAccountStatus(page, expected = get('expectedAccount', '')) {
  const snapshot = await locate(page, 'account.identity').first().ariaSnapshot({ timeout: 5000 }).catch(() => '');
  const account = snapshot.match(EMAIL_IN_NAME)?.[1] ?? null;
  if (!expected || !account) return { status: 'unverified', verified: false, account, expected };
  const same = account.toLowerCase() === expected.toLowerCase();
  return { status: same ? 'ok' : 'mismatch', verified: same, account, expected };
}

export async function verifyAccount(page = getPage(), expected = get('expectedAccount', '')) {
  const result = await readAccountStatus(page, expected);
  logger.info('Account check', { status: result.status });
  if (result.status === 'mismatch') {
    await takeScreenshot(page, 'wrong-account');
    throw new FlowError(ErrorCodes.WRONG_GOOGLE_ACCOUNT,
      `Wrong Google account detected. Expected ${expected}, found ${result.account}`);
  }
  return result;
}
