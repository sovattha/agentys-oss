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

import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest';
import { detectDateFromBody } from '../components/FollowupDatePicker';

// detectDateFromBody compares to "now" — pin to a known date for reproducibility.
// 2026-04-15 ensures all "May 6", "6 mai" examples below are in the future.
beforeAll(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(2026, 3, 15, 10, 0, 0));
});

afterAll(() => {
  vi.useRealTimers();
});

describe('detectDateFromBody — commitment dates', () => {
  it('detects "pour le 6 mai"', () => {
    const r = detectDateFromBody('pour le 6 mai');
    expect(r).not.toBeNull();
    expect(r!.date.getMonth()).toBe(4); // mai = 4
    expect(r!.date.getDate()).toBe(6);
  });

  it('detects "May 6th"', () => {
    const r = detectDateFromBody('I will send the report on May 6th');
    expect(r).not.toBeNull();
    expect(r!.date.getMonth()).toBe(4);
    expect(r!.date.getDate()).toBe(6);
  });

  it('detects "8 juin" inside HTML', () => {
    const r = detectDateFromBody('<p>Je te confirme pour le <b>8 juin</b></p>');
    expect(r).not.toBeNull();
    expect(r!.date.getMonth()).toBe(5);
    expect(r!.date.getDate()).toBe(8);
  });
});

describe('detectDateFromBody — non-commitment phrases (vacation/OOO/etc.)', () => {
  it('skips vacation in French (the bug example)', () => {
    expect(
      detectDateFromBody('Je serai en vacances du 6 au 10 mai'),
    ).toBeNull();
  });

  it('skips "I will be on vacation on may 6th to may 10th"', () => {
    expect(
      detectDateFromBody('I will be on vacation on may 6th to may 10th'),
    ).toBeNull();
  });

  it('skips out of office', () => {
    expect(
      detectDateFromBody('I will be out of office until May 6'),
    ).toBeNull();
  });

  it('skips OOO acronym', () => {
    expect(detectDateFromBody('OOO May 6')).toBeNull();
  });

  it('skips "en congé"', () => {
    expect(detectDateFromBody('Je suis en congé le 8 juin')).toBeNull();
  });

  it('skips "férié"', () => {
    expect(detectDateFromBody('Bureau fermé, férié le 8 mai')).toBeNull();
  });

  it('skips "unavailable"', () => {
    expect(
      detectDateFromBody('I am unavailable on May 6'),
    ).toBeNull();
  });

  it('skips "won\'t be there"', () => {
    expect(
      detectDateFromBody("I won't be there on May 6"),
    ).toBeNull();
  });
});

describe('detectDateFromBody — preserves false-positive guards', () => {
  it('returns null for empty body', () => {
    expect(detectDateFromBody('')).toBeNull();
    expect(detectDateFromBody(undefined)).toBeNull();
  });

  it('does not match "off" inside "office" or "offer"', () => {
    // "office" contains "off" but the \b boundary in the regex prevents the match.
    // The body has a date but no real unavailability phrase.
    const r = detectDateFromBody('Drop by my office on May 6');
    expect(r).not.toBeNull();
  });
});
