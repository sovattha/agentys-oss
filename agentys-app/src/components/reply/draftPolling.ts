export const DRAFT_READY_POLL_INITIAL_DELAY_MS = 5_000;
export const DRAFT_READY_POLL_MAX_INTERVAL_MS = 60_000;
export const DRAFT_READY_POLL_MAX_WAIT_MS = 240_000;

export function getNextDraftReadyPollDelay(currentDelayMs: number): number {
  return Math.min(currentDelayMs * 2, DRAFT_READY_POLL_MAX_INTERVAL_MS);
}

export function getRemainingDraftReadyPollWait(startedAtMs: number, nowMs: number): number {
  return Math.max(0, DRAFT_READY_POLL_MAX_WAIT_MS - (nowMs - startedAtMs));
}
