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

export const DRAFT_READY_POLL_INITIAL_DELAY_MS = 5_000;
export const DRAFT_READY_POLL_MAX_INTERVAL_MS = 60_000;
export const DRAFT_READY_POLL_MAX_WAIT_MS = 240_000;

export function getNextDraftReadyPollDelay(currentDelayMs: number): number {
  return Math.min(currentDelayMs * 2, DRAFT_READY_POLL_MAX_INTERVAL_MS);
}

export function getRemainingDraftReadyPollWait(startedAtMs: number, nowMs: number): number {
  return Math.max(0, DRAFT_READY_POLL_MAX_WAIT_MS - (nowMs - startedAtMs));
}
