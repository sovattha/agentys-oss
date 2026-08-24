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
