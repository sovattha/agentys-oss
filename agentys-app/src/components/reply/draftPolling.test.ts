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
