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

import { describe, it, expect } from 'vitest';
import {
  formatGmailDateTime,
  getOrdinalSuffix,
  formatHourMinute,
  formatLongDateFromDate,
  formatDayMonthYear,
} from './dateFormat';

// Date-time strings WITHOUT a timezone suffix are parsed as LOCAL time per the
// ECMAScript spec, so getHours()/getDate() stay deterministic across CI zones.
const MAY_31 = '2026-05-31T17:07:00';

describe('formatGmailDateTime', () => {
  it('drops the weekday in every locale', () => {
    for (const lang of ['en', 'fr', 'es', 'de']) {
      const out = formatGmailDateTime(MAY_31, lang);
      // No leading weekday token (e.g. "Sun,", "dim.", "Mo,").
      expect(out).not.toMatch(/^[A-Za-zÀ-ÿ]{2,3}[.,]/);
    }
  });

  it('English: ordinal day, no comma before year, colon time', () => {
    expect(formatGmailDateTime(MAY_31, 'en')).toBe('May 31st 2026, 17:07');
    // en-US (the real i18n.language value) must behave identically.
    expect(formatGmailDateTime(MAY_31, 'en-US')).toBe('May 31st 2026, 17:07');
  });

  it('French: day-first, "h" time separator', () => {
    expect(formatGmailDateTime(MAY_31, 'fr')).toBe('31 mai 2026, 17h07');
  });

  it('Spanish: day-first, colon time (no "h")', () => {
    expect(formatGmailDateTime(MAY_31, 'es')).toBe('31 may 2026, 17:07');
  });

  it('English ordinal suffix is correct across edge cases', () => {
    expect(formatGmailDateTime('2026-05-01T09:05:00', 'en')).toBe('May 1st 2026, 9:05');
    expect(formatGmailDateTime('2026-05-22T09:05:00', 'en')).toBe('May 22nd 2026, 9:05');
    expect(formatGmailDateTime('2026-05-23T09:05:00', 'en')).toBe('May 23rd 2026, 9:05');
    // 11/12/13 are the classic "th" exception.
    expect(formatGmailDateTime('2026-05-11T09:05:00', 'en')).toBe('May 11th 2026, 9:05');
    expect(getOrdinalSuffix(13)).toBe('13th');
    expect(getOrdinalSuffix(21)).toBe('21st');
  });

  it('returns an em-dash for an unparseable date', () => {
    expect(formatGmailDateTime('not-a-date', 'en')).toBe('—');
  });
});

// The app-wide clock-time contract: every UI surface (calendar, snooze badges,
// draft/list timestamps, meeting banners, deep-work labels, availability grid)
// routes through this. FR keeps the "h" convention; EN/ES use a colon — so "h"
// no longer collides with English ordinal dates (Bug #5). Locked here so the
// unified surfaces can't silently drift back to a hardcoded format.
describe('formatHourMinute (UI clock-time contract)', () => {
  const at = (h: number, m: number) => new Date(2000, 0, 1, h, m);

  it('French → "h" separator, no hour padding', () => {
    expect(formatHourMinute(at(9, 5), 'fr')).toBe('9h05');
    expect(formatHourMinute(at(17, 0), 'fr')).toBe('17h00');
    expect(formatHourMinute(at(17, 0), 'fr-CA')).toBe('17h00');
  });

  it('English / Spanish → colon, numeric hour (no leading zero)', () => {
    expect(formatHourMinute(at(9, 5), 'en')).toBe('9:05');
    expect(formatHourMinute(at(17, 0), 'en-US')).toBe('17:00');
    expect(formatHourMinute(at(9, 5), 'es')).toBe('9:05');
  });

  it('defaults to the French "h" form when lang is omitted (legacy callers)', () => {
    expect(formatHourMinute(at(8, 30))).toBe('8h30');
  });
});

// "May 27th style" — the app-wide ordinal contract for any surface that shows a
// day-of-month (followup labels, snooze sections, scheduled list, context panels,
// {date} snippet token, meeting card, calendar pickers). English ordinalises the
// day; French/Spanish stay day-first with no ordinal. Locked so the ~14 call sites
// routed through these helpers can't drift back to "May 27" / "27 de mayo".
describe('formatLongDateFromDate / formatDayMonthYear (ordinal date contract)', () => {
  // Local-time construction so getDate() is deterministic across CI zones.
  const mar2 = new Date(2026, 2, 2);   // March 2nd — short ("Mar") ≠ long ("March")
  const may1 = new Date(2026, 4, 1);   // May 1st — ordinal "st" edge
  const may22 = new Date(2026, 4, 22); // May 22nd — ordinal "nd" edge

  it('formatLongDateFromDate: English ordinal, others day-first (long month)', () => {
    expect(formatLongDateFromDate(mar2, 'en')).toBe('March 2nd');
    expect(formatLongDateFromDate(mar2, 'en-US')).toBe('March 2nd');
    expect(formatLongDateFromDate(mar2, 'fr')).toBe('2 mars');
    expect(formatLongDateFromDate(mar2, 'es')).toBe('2 marzo');
  });

  it('formatDayMonthYear: "May 27th 2026" house style — no comma before the year', () => {
    expect(formatDayMonthYear(may1, 'en')).toBe('May 1st 2026');
    expect(formatDayMonthYear(may22, 'en')).toBe('May 22nd 2026');
    expect(formatDayMonthYear(mar2, 'en')).toBe('Mar 2nd 2026');          // short month default
    expect(formatDayMonthYear(mar2, 'en', 'long')).toBe('March 2nd 2026'); // long month
    expect(formatDayMonthYear(mar2, 'fr')).toBe('2 mars 2026');
    expect(formatDayMonthYear(mar2, 'fr', 'long')).toBe('2 mars 2026');
  });
});
