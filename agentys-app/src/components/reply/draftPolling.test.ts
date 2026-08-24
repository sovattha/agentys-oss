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
  DRAFT_READY_POLL_MAX_INTERVAL_MS,
  DRAFT_READY_POLL_MAX_WAIT_MS,
  getNextDraftReadyPollDelay,
  getRemainingDraftReadyPollWait,
} from './draftPolling';

describe('draft ready polling', () => {
  it('keeps polling long enough for slow complex drafts', () => {
    expect(DRAFT_READY_POLL_MAX_WAIT_MS).toBeGreaterThanOrEqual(180_000);
  });

  it('caps exponential backoff interval', () => {
    expect(getNextDraftReadyPollDelay(40_000)).toBe(DRAFT_READY_POLL_MAX_INTERVAL_MS);
  });

  it('returns remaining wait without going negative', () => {
    expect(getRemainingDraftReadyPollWait(1_000, 241_000)).toBe(0);
  });
});
