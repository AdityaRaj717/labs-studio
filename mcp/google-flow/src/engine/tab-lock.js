import { logger } from '../utils/logger.js';

let tail = Promise.resolve();

// First come, first served. shortcut: calling withTab inside fn deadlocks, keep the lock at the outer call.
export function withTab(label, fn) {
  const run = tail.then(() => {
    logger.debug(`Tab lock: ${label}`);
    return fn();
  });
  tail = run.catch(() => {}); // the caller gets the failure; the next holder must still run
  return run;
}
