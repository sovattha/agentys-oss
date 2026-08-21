import { describe, expect, it } from 'vitest';
import {
  EMAIL_SYNC_IN_PROGRESS_RETRY_DELAYS_MS,
  getEmailSyncInProgressDecision,
  getEmailSyncInProgressRetryDelay,
} from '../utils/emailSyncInProgress';

describe('EmailList sync-in-progress retry decisions', () => {
  it('keeps waiting across repeated empty syncing responses', () => {
    EMAIL_SYNC_IN_PROGRESS_RETRY_DELAYS_MS.forEach((delayMs, retryCount) => {
      expect(
        getEmailSyncInProgressDecision({
          syncInProgress: true,
          responseEmailCount: 0,
          visibleEmailCount: 0,
          retryCount,
        }),
      ).toEqual({
        action: 'wait',
        delayMs,
        preserveExisting: false,
      });
    });
  });

  it('settles to the empty response only after bounded retries when nothing is visible', () => {
    expect(getEmailSyncInProgressRetryDelay(EMAIL_SYNC_IN_PROGRESS_RETRY_DELAYS_MS.length)).toBeNull();
    expect(
      getEmailSyncInProgressDecision({
        syncInProgress: true,
        responseEmailCount: 0,
        visibleEmailCount: 0,
        retryCount: EMAIL_SYNC_IN_PROGRESS_RETRY_DELAYS_MS.length,
      }),
    ).toEqual({ action: 'apply_response' });
  });

  it('preserves visible rows instead of clearing the list while sync is still active', () => {
    expect(
      getEmailSyncInProgressDecision({
        syncInProgress: true,
        responseEmailCount: 0,
        visibleEmailCount: 12,
        retryCount: EMAIL_SYNC_IN_PROGRESS_RETRY_DELAYS_MS.length,
      }),
    ).toEqual({ action: 'preserve_existing' });
  });

  it('resets to normal response handling once rows arrive', () => {
    expect(
      getEmailSyncInProgressDecision({
        syncInProgress: true,
        responseEmailCount: 2,
        visibleEmailCount: 0,
        retryCount: 3,
      }),
    ).toEqual({ action: 'apply_response' });
  });
});
