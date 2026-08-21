export const EMAIL_SYNC_IN_PROGRESS_RETRY_DELAYS_MS = [3000, 7000, 12000, 20000, 30000] as const;

export function getEmailSyncInProgressRetryDelay(retryCount: number): number | null {
  if (!Number.isFinite(retryCount) || retryCount < 0) {
    return EMAIL_SYNC_IN_PROGRESS_RETRY_DELAYS_MS[0];
  }
  return EMAIL_SYNC_IN_PROGRESS_RETRY_DELAYS_MS[retryCount] ?? null;
}

export function getEmailSyncInProgressDecision({
  syncInProgress,
  syncFailed,
  responseEmailCount,
  visibleEmailCount,
  retryCount,
}: {
  syncInProgress: boolean;
  syncFailed?: boolean;
  responseEmailCount: number;
  visibleEmailCount: number;
  retryCount: number;
}) {
  // Terminal failure: the backend's background refresh for this folder
  // completed and failed (auth / provider unreachable). Re-reading would
  // return the same empty payload — showing it as an empty folder would
  // lie to the user, and waiting would re-enter the skeleton ladder.
  if (syncFailed && responseEmailCount === 0) {
    return visibleEmailCount > 0
      ? { action: 'preserve_existing' as const }
      : { action: 'error' as const };
  }

  if (!syncInProgress || responseEmailCount > 0) {
    return { action: 'apply_response' as const };
  }

  const delayMs = getEmailSyncInProgressRetryDelay(retryCount);
  if (delayMs !== null) {
    return {
      action: 'wait' as const,
      delayMs,
      preserveExisting: visibleEmailCount > 0,
    };
  }

  return visibleEmailCount > 0
    ? { action: 'preserve_existing' as const }
    : { action: 'apply_response' as const };
}
