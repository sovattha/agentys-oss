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
 * Idempotency store for meeting reminders.
 *
 * Keyed by `${eventId}:${tier}` where tier is one of `lead` (T-leadMinutes),
 * `imminent` (T-1min). Entries auto-expire after 24h to avoid unbounded
 * growth and to allow re-firing if the same event id reappears next week
 * (e.g. weekly recurring meeting).
 */

const STORAGE_KEY = 'agentys_meeting_reminders_fired_v1'
const TTL_MS = 24 * 60 * 60 * 1000

export type ReminderTier = 'lead' | 'imminent' | 'buzzer'

interface FiredMap {
  [key: string]: number // firedAt epoch ms
}

function readMap(): FiredMap {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as FiredMap
    return typeof parsed === 'object' && parsed !== null ? parsed : {}
  } catch {
    return {}
  }
}

function writeMap(map: FiredMap): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(map))
  } catch {
    // localStorage full or disabled — accept duplicate notifications rather than crash
  }
}

function pruneExpired(map: FiredMap): FiredMap {
  const now = Date.now()
  const result: FiredMap = {}
  for (const [k, v] of Object.entries(map)) {
    if (now - v < TTL_MS) result[k] = v
  }
  return result
}

function makeKey(eventId: string, tier: ReminderTier): string {
  return `${eventId}:${tier}`
}

export function hasFired(eventId: string, tier: ReminderTier): boolean {
  const map = readMap()
  return makeKey(eventId, tier) in map
}

export function markFired(eventId: string, tier: ReminderTier): void {
  const map = pruneExpired(readMap())
  map[makeKey(eventId, tier)] = Date.now()
  writeMap(map)
}

/** Test helper — clears all fired markers. */
export function _resetFiredStore(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // ignore
  }
}
