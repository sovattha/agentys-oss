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
 * Pure geometry + formatting helpers for the Deep Work day-timeline.
 *
 * Extracted from DeepWorkPanel so the math (slot placement, the "now" marker,
 * time-range formatting) is unit-testable without mounting the modal. Everything
 * here is a pure function of its inputs — no React, no DOM, no clock except the
 * `now` argument that callers pass explicitly.
 */

import { formatHourMinute } from '../utils/dateFormat'

/** Minutes in a full day — the timeline maps [0, DAY_MIN] onto [0%, 100%]. */
export const DAY_MIN = 24 * 60

/**
 * Default "working day" window painted as a lit band behind the slots. Purely
 * cosmetic context so an empty bar still reads like a real day instead of a
 * flat strip. Not user-configurable (yet) — a sane 07:00–19:00 default.
 */
export const WORK_WINDOW_START_MIN = 7 * 60
export const WORK_WINDOW_END_MIN = 19 * 60

/** "HH:MM" → minutes since midnight. Tolerant of malformed input (→ 0). */
export function parseHM(hhmm: string): number {
  const [h, m] = (hhmm || '').split(':').map(Number)
  return (Number.isFinite(h) ? h : 0) * 60 + (Number.isFinite(m) ? m : 0)
}

/** Minutes since midnight → percentage across the 24h bar, clamped to [0, 100]. */
export function minutesToPct(min: number): number {
  const clamped = Math.min(Math.max(min, 0), DAY_MIN)
  return (clamped / DAY_MIN) * 100
}

export interface SlotGeometry {
  leftPct: number
  widthPct: number
}

/**
 * Where a slot sits on the bar. Width is clamped so a slot that would run past
 * midnight stops at the right edge rather than overflowing the rounded track.
 * The minimum *visible* width is enforced in CSS (`min-width`) so short checks
 * (15–30 min ≈ 1–2% of the day) still render as a tappable pill.
 */
export function slotGeometry(start: string, duration: number): SlotGeometry {
  const startMin = parseHM(start)
  const widthMin = Math.min(Math.max(duration, 0), DAY_MIN - startMin)
  return {
    leftPct: minutesToPct(startMin),
    widthPct: (widthMin / DAY_MIN) * 100,
  }
}

/** Daylight band geometry (left + width %) for the working-hours backdrop. */
export function daylightGeometry(): SlotGeometry {
  const leftPct = minutesToPct(WORK_WINDOW_START_MIN)
  return { leftPct, widthPct: minutesToPct(WORK_WINDOW_END_MIN) - leftPct }
}

// Clock-time labels are LOCALE-AWARE (FR "9h00" / EN-ES "9:00") via the canonical
// formatHourMinute — Deep Work slots are clock-times, not durations. (`locale`
// optional → defaults to FR "h", matching formatHourMinute's own default.)
// NB: `durationLabel` below stays "h" — a duration unit, correct in every language.

/** Minutes since midnight → "9h00" (FR) / "9:00" (EN/ES) — plain hour, padded minutes. */
function minutesToHM(min: number, locale?: string): string {
  return formatHourMinute(new Date(2000, 0, 1, Math.floor(min / 60), min % 60), locale)
}

/** "09:00" → "9h00" (FR) / "9:00" (EN/ES) — house style: no leading zero on the hour. */
export function formatStartTime(hhmm: string, locale?: string): string {
  return minutesToHM(parseHM(hhmm), locale)
}

/** "8h00 — 8h30" (FR) / "8:00 — 8:30" (EN/ES). */
export function formatSlotTime(start: string, duration: number, locale?: string): string {
  const startMin = parseHM(start)
  const endMin = (startMin + duration) % DAY_MIN
  return `${minutesToHM(startMin, locale)} — ${minutesToHM(endMin, locale)}`
}

/** Compact duration label: "30 min", "1h", "1h30". */
export function durationLabel(d: number): string {
  if (d < 60) return `${d} min`
  const h = Math.floor(d / 60)
  const m = d % 60
  return m > 0 ? `${h}h${String(m).padStart(2, '0')}` : `${h}h`
}

/** Horizontal position (%) of the "now" marker for the given clock time. */
export function nowMarkerPct(now: Date = new Date()): number {
  return minutesToPct(now.getHours() * 60 + now.getMinutes())
}
