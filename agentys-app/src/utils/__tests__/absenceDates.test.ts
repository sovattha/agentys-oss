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
import { parseIsoDateLocal, formatAbsencePeriodParts } from '../absenceDates'

describe('parseIsoDateLocal', () => {
  it('parses a valid date in the local zone (no UTC day-shift)', () => {
    const d = parseIsoDateLocal('2026-03-25')
    expect(d).not.toBeNull()
    expect(d!.getFullYear()).toBe(2026)
    expect(d!.getMonth()).toBe(2) // March (0-indexed)
    expect(d!.getDate()).toBe(25)
  })

  it('returns null for empty or malformed input', () => {
    expect(parseIsoDateLocal('')).toBeNull()
    expect(parseIsoDateLocal('2026-3-5')).toBeNull()
    expect(parseIsoDateLocal('25/03/2026')).toBeNull()
    expect(parseIsoDateLocal('not-a-date')).toBeNull()
  })

  it('rejects impossible calendar dates instead of rolling them over', () => {
    expect(parseIsoDateLocal('2026-02-31')).toBeNull()
    expect(parseIsoDateLocal('2026-13-01')).toBeNull()
  })
})

describe('formatAbsencePeriodParts', () => {
  it('formats "day month" parts in French', () => {
    expect(formatAbsencePeriodParts('2026-03-25', '2026-03-29', 'fr')).toEqual({
      start: '25 mars',
      end: '29 mars',
    })
  })

  it('formats "day month" parts in English with ordinal days', () => {
    expect(formatAbsencePeriodParts('2026-03-25', '2026-03-29', 'en')).toEqual({
      start: 'March 25th',
      end: 'March 29th',
    })
  })

  it('uses the correct English ordinal suffix across edge cases', () => {
    const day = (iso: string) => formatAbsencePeriodParts(iso, iso, 'en')!.start
    expect(day('2026-03-01')).toBe('March 1st')
    expect(day('2026-03-02')).toBe('March 2nd')
    expect(day('2026-03-03')).toBe('March 3rd')
    expect(day('2026-03-04')).toBe('March 4th')
    // The 11/12/13 exceptions must be "th", not st/nd/rd.
    expect(day('2026-03-11')).toBe('March 11th')
    expect(day('2026-03-12')).toBe('March 12th')
    expect(day('2026-03-13')).toBe('March 13th')
    // …while 21/22/23 go back to st/nd/rd.
    expect(day('2026-03-21')).toBe('March 21st')
    expect(day('2026-03-22')).toBe('March 22nd')
    expect(day('2026-03-23')).toBe('March 23rd')
  })

  it('applies ordinals to regional English tags too (en-US)', () => {
    expect(formatAbsencePeriodParts('2026-03-25', '2026-03-29', 'en-US')).toEqual({
      start: 'March 25th',
      end: 'March 29th',
    })
  })

  it('formats "day month" parts in Spanish', () => {
    expect(formatAbsencePeriodParts('2026-03-25', '2026-03-29', 'es')).toEqual({
      start: '25 de marzo',
      end: '29 de marzo',
    })
  })

  it('returns null when either bound is missing or malformed', () => {
    expect(formatAbsencePeriodParts('', '2026-03-29', 'fr')).toBeNull()
    expect(formatAbsencePeriodParts('2026-03-25', '', 'fr')).toBeNull()
    expect(formatAbsencePeriodParts('garbage', '2026-03-29', 'fr')).toBeNull()
  })

  it('falls back to French formatting for an invalid locale tag', () => {
    const parts = formatAbsencePeriodParts('2026-03-25', '2026-03-29', '@@bad@@')
    expect(parts).toEqual({ start: '25 mars', end: '29 mars' })
  })
})
