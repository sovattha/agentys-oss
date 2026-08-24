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

import { describe, it, expect } from 'vitest'
import {
  normalizeHolidayTitle,
  holidayDayDiff,
  dedupHolidays,
  holidayTitlesWithin,
  type Holiday,
} from './holidayDedup'

const h = (id: string, title: string, date: string): Holiday => ({ id, title, date })

describe('normalizeHolidayTitle', () => {
  // A title with no HOLIDAY_ALIASES entry exercises the raw normalization
  // (strip trailing parenthetical → collapse whitespace → lowercase).
  it('strips a trailing parenthetical qualifier and lowercases (non-aliased title)', () => {
    expect(
      normalizeHolidayTitle('Journée des Patriotes (jour férié local)'),
    ).toBe('journée des patriotes')
  })

  it('collapses whitespace (non-aliased title)', () => {
    expect(normalizeHolidayTitle('  Spring   Festival  ')).toBe('spring festival')
  })

  // Session Z: cross-LANGUAGE canonicalization via HOLIDAY_ALIASES so the
  // EN and FR names of the same holiday collapse to one id.
  it('canonicalizes EN and FR names of the same holiday to one id', () => {
    expect(normalizeHolidayTitle('Victoria Day')).toBe('CA:victoria-day')
    expect(normalizeHolidayTitle('Fête de la Reine')).toBe('CA:victoria-day')
  })

  it('aliases after stripping a trailing parenthetical qualifier', () => {
    expect(normalizeHolidayTitle('Fête de la Reine (jour férié local)')).toBe(
      'CA:victoria-day',
    )
  })
})

describe('holidayDayDiff', () => {
  it('returns the signed whole-day difference', () => {
    expect(holidayDayDiff('2026-05-19', '2026-05-18')).toBe(1)
    expect(holidayDayDiff('2026-05-18', '2026-05-19')).toBe(-1)
    expect(holidayDayDiff('2026-05-18', '2026-05-18')).toBe(0)
  })

  it('returns +Infinity for an unparseable date so it never counts as adjacent', () => {
    expect(holidayDayDiff('not-a-date', '2026-05-18')).toBe(Number.POSITIVE_INFINITY)
  })
})

describe('dedupHolidays (BUG-Y002 / F-03)', () => {
  it('collapses exact duplicates (same date + title)', () => {
    const out = dedupHolidays([
      h('1', 'Fête de la Reine (jour férié local)', '2026-05-19'),
      h('2', 'Fête de la Reine (jour férié local)', '2026-05-19'),
    ])
    expect(out).toHaveLength(1)
  })

  it('collapses a wording variant on the same day', () => {
    const out = dedupHolidays([
      h('1', 'Fête de la Reine', '2026-05-19'),
      h('2', 'Fête de la Reine (jour férié local)', '2026-05-19'),
    ])
    expect(out).toHaveLength(1)
  })

  it('collapses the same holiday shifted by one day (tz drift), keeping the earliest', () => {
    const out = dedupHolidays([
      h('late', 'Fête de la Reine (jour férié local)', '2026-05-19'),
      h('early', 'Fête de la Reine', '2026-05-18'),
    ])
    expect(out).toHaveLength(1)
    expect(out[0].date).toBe('2026-05-18') // earliest wins
  })

  it('keeps distinct holidays on the same day', () => {
    const out = dedupHolidays([
      h('1', 'Victoria Day', '2026-05-18'),
      h('2', 'Journée nationale des patriotes', '2026-05-18'),
    ])
    expect(out).toHaveLength(2)
  })

  it('keeps a same-titled holiday more than one day apart (not a tz dup)', () => {
    const out = dedupHolidays([
      h('1', 'Festival', '2026-05-18'),
      h('2', 'Festival', '2026-05-22'),
    ])
    expect(out).toHaveLength(2)
  })
})

describe('holidayTitlesWithin', () => {
  // Titles come back canonicalized (Session Z) — 'Victoria Day' → 'CA:victoria-day'.
  const primary = [h('1', 'Victoria Day', '2026-05-18')]

  it('includes a primary title (canonicalized) on an adjacent day (±1)', () => {
    expect(holidayTitlesWithin(primary, '2026-05-19', 1).has('CA:victoria-day')).toBe(true)
  })

  it('excludes a primary title two days away', () => {
    expect(holidayTitlesWithin(primary, '2026-05-20', 1).has('CA:victoria-day')).toBe(false)
  })
})
