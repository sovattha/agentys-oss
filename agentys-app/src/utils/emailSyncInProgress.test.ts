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

import { describe, it, expect } from 'vitest';
import {
  EMAIL_SYNC_IN_PROGRESS_RETRY_DELAYS_MS,
  getEmailSyncInProgressDecision,
  getEmailSyncInProgressRetryDelay,
} from './emailSyncInProgress';

describe('getEmailSyncInProgressRetryDelay', () => {
  it('escalates through the ladder then returns null', () => {
    EMAIL_SYNC_IN_PROGRESS_RETRY_DELAYS_MS.forEach((delay, i) => {
      expect(getEmailSyncInProgressRetryDelay(i)).toBe(delay);
    });
    expect(getEmailSyncInProgressRetryDelay(EMAIL_SYNC_IN_PROGRESS_RETRY_DELAYS_MS.length)).toBeNull();
  });
});

describe('getEmailSyncInProgressDecision', () => {
  it('applies the response when no sync is in progress', () => {
    expect(getEmailSyncInProgressDecision({
      syncInProgress: false, responseEmailCount: 0, visibleEmailCount: 0, retryCount: 0,
    })).toEqual({ action: 'apply_response' });
  });

  it('waits while a sync is in progress and the response is empty', () => {
    expect(getEmailSyncInProgressDecision({
      syncInProgress: true, responseEmailCount: 0, visibleEmailCount: 0, retryCount: 0,
    })).toEqual({ action: 'wait', delayMs: 3000, preserveExisting: false });
  });

  it('gives up to apply_response after the ladder is exhausted', () => {
    expect(getEmailSyncInProgressDecision({
      syncInProgress: true, responseEmailCount: 0, visibleEmailCount: 0, retryCount: 5,
    })).toEqual({ action: 'apply_response' });
  });

  // Bug "les onglets Corbeille/Indésirables ne s'ouvrent pas" (2026-06-09) :
  // un refresh dossier en échec terminal côté backend (sync_failed) doit
  // afficher une erreur immédiatement, pas re-dérouler ~72 s de skeleton ni
  // prétendre que le dossier est vide.
  describe('terminal sync failure (sync_failed)', () => {
    it('returns error when nothing is visible', () => {
      expect(getEmailSyncInProgressDecision({
        syncInProgress: false, syncFailed: true, responseEmailCount: 0, visibleEmailCount: 0, retryCount: 0,
      })).toEqual({ action: 'error' });
    });

    it('keeps existing rows visible instead of erroring', () => {
      expect(getEmailSyncInProgressDecision({
        syncInProgress: false, syncFailed: true, responseEmailCount: 0, visibleEmailCount: 12, retryCount: 0,
      })).toEqual({ action: 'preserve_existing' });
    });

    it('wins over a concurrent syncInProgress flag (no retry ladder on terminal failure)', () => {
      expect(getEmailSyncInProgressDecision({
        syncInProgress: true, syncFailed: true, responseEmailCount: 0, visibleEmailCount: 0, retryCount: 0,
      })).toEqual({ action: 'error' });
    });

    it('ignores syncFailed when the response actually has emails', () => {
      expect(getEmailSyncInProgressDecision({
        syncInProgress: false, syncFailed: true, responseEmailCount: 3, visibleEmailCount: 0, retryCount: 0,
      })).toEqual({ action: 'apply_response' });
    });
  });
});
