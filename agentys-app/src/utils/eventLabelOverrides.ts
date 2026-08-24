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

/**
 * Manual calendar event-label overrides — a local-only (localStorage) map of
 * eventId → { name, color } applied via the event-detail "Label" picker.
 * Keyed by the event id, which is volatile for freshly-created events: the
 * optimistic event starts with a `temp-…` id and is swapped for the real
 * provider id once the create call resolves. This helper keeps the override
 * attached across that id swap so a labelled meeting doesn't lose its colour.
 */
export type EventLabelOverride = { name: string; color: string };
export type EventLabelOverrides = Record<string, EventLabelOverride>;

/**
 * Move (or drop) the override stored under `fromId`.
 *
 * - `toId` is a string → re-key the override from `fromId` to `toId`
 *   (temp id → real id after create resolves).
 * - `toId` is `null` → delete the override for `fromId`
 *   (the optimistic event was rolled back because create failed).
 *
 * Returns the *same* object reference when there is nothing to do (no entry for
 * `fromId`, or `toId === fromId`) so callers can skip a needless state update.
 * Never mutates the input.
 */
export function remapEventLabelOverride(
  overrides: EventLabelOverrides,
  fromId: string,
  toId: string | null,
): EventLabelOverrides {
  if (!(fromId in overrides)) return overrides;
  if (toId === fromId) return overrides;
  const next = { ...overrides };
  const value = next[fromId];
  delete next[fromId];
  if (toId) next[toId] = value;
  return next;
}
