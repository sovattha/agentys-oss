/*
 * Agentys — voice-first email assistant.
 * Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version. See the LICENSE file for details.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

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
