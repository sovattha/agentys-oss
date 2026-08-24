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

// BUG-Y002 / F-03 (audit 2026-05-19): holiday rows duplicated on the calendar.
// Cross-LANGUAGE duplicates ("Victoria Day" EN vs "Fete de la Reine" FR for
// the same Canadian holiday) are canonicalized in JS via the alias table below.
// Session Z (2026-05-20).

export interface Holiday {
  id: string
  title: string
  date: string // YYYY-MM-DD
}

const HOLIDAY_ALIASES: Record<string, string> = {
  'victoria day': 'CA:victoria-day',
  'fête de la reine': 'CA:victoria-day',
  'fete de la reine': 'CA:victoria-day',
  'canada day': 'CA:canada-day',
  'fête du canada': 'CA:canada-day',
  'fete du canada': 'CA:canada-day',
  'labour day': 'CA:labour-day',
  'labor day': 'CA:labour-day',
  'fête du travail': 'CA:labour-day',
  'fete du travail': 'CA:labour-day',
  'thanksgiving': 'CA:thanksgiving',
  'thanksgiving day': 'CA:thanksgiving',
  'action de grâce': 'CA:thanksgiving',
  'action de grace': 'CA:thanksgiving',
  'action de grâces': 'CA:thanksgiving',
  'remembrance day': 'CA:remembrance-day',
  'jour du souvenir': 'CA:remembrance-day',
  'christmas day': 'christmas',
  'christmas': 'christmas',
  'noël': 'christmas',
  'noel': 'christmas',
  "new year's day": 'new-year',
  'new years day': 'new-year',
  "jour de l'an": 'new-year',
  'jour de lan': 'new-year',
}

export function normalizeHolidayTitle(title: string): string {
  const stripped = title
    .replace(/\s*\([^)]*\)\s*$/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase()
  return HOLIDAY_ALIASES[stripped] ?? stripped
}

export function holidayDayDiff(a: string, b: string): number {
  const da = Date.parse(a + 'T00:00:00Z')
  const db = Date.parse(b + 'T00:00:00Z')
  if (Number.isNaN(da) || Number.isNaN(db)) return Number.POSITIVE_INFINITY
  return Math.round((da - db) / 86400000)
}

export function dedupHolidays(list: Holiday[]): Holiday[] {
  const sorted = [...list].sort((a, b) =>
    a.date < b.date ? -1 : a.date > b.date ? 1 : 0,
  )
  const kept: Holiday[] = []
  for (const h of sorted) {
    const n = normalizeHolidayTitle(h.title)
    const isDup = kept.some(
      (k) =>
        normalizeHolidayTitle(k.title) === n
        && Math.abs(holidayDayDiff(k.date, h.date)) <= 1,
    )
    if (!isDup) kept.push(h)
  }
  return kept
}

export function holidayTitlesWithin(
  list: Holiday[],
  targetDate: string,
  windowDays = 1,
): Set<string> {
  const out = new Set<string>()
  for (const h of list) {
    if (Math.abs(holidayDayDiff(h.date, targetDate)) <= windowDays) {
      out.add(normalizeHolidayTitle(h.title))
    }
  }
  return out
}
