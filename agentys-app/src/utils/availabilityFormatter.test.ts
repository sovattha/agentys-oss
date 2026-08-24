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
import { formatAvailability, formatBookingLineOnly } from './availabilityFormatter';

// All tests pin "now" to Thursday May 7, 2026 at 09:00 in NY → produces
// deterministic "today (May 7)" / "Thu May 7" / "Fri May 8" output.
const NOW = new Date('2026-05-07T13:00:00Z'); // 09:00 EDT

const slot = (startIso: string, endIso: string) => ({
  start: new Date(startIso),
  end: new Date(endIso),
});

describe('formatAvailability', () => {
  describe('empty / edge cases', () => {
    it('returns empty string for empty slot list', () => {
      expect(formatAvailability([], {
        locale: 'en-US', timezone: 'America/New_York', now: NOW,
      })).toBe('');
    });
  });

  describe('single slot, today (en)', () => {
    it('produces an inline "today (May 7) at H:MM – H:MM." sentence', () => {
      const out = formatAvailability(
        [slot('2026-05-07T15:45:00Z', '2026-05-07T16:15:00Z')], // 11:45–12:15 EDT
        { locale: 'en-US', timezone: 'America/New_York', now: NOW },
      );
      expect(out).toBe("Here's when I'm free — today (May 7) at 11:45 – 12:15.");
    });

    it('appends the timezone abbreviation when includeTzAbbrev=true', () => {
      const out = formatAvailability(
        [slot('2026-05-07T15:45:00Z', '2026-05-07T16:15:00Z')],
        {
          locale: 'en-US', timezone: 'America/New_York', now: NOW,
          includeTzAbbrev: true,
        },
      );
      expect(out).toBe("Here's when I'm free — today (May 7) at 11:45 – 12:15 EDT.");
    });
  });

  describe('multiple same-day slots (en)', () => {
    it('renders a heading + bullet list when all slots fall on one day', () => {
      const out = formatAvailability(
        [
          slot('2026-05-07T15:45:00Z', '2026-05-07T16:15:00Z'), // 11:45–12:15
          slot('2026-05-07T16:30:00Z', '2026-05-07T18:15:00Z'), // 12:30–14:15
          slot('2026-05-07T19:00:00Z', '2026-05-07T19:30:00Z'), // 15:00–15:30
        ],
        { locale: 'en-US', timezone: 'America/New_York', now: NOW },
      );
      expect(out).toBe(
        "Here's when I'm free today (May 7):\n" +
        '• 11:45 – 12:15\n' +
        '• 12:30 – 14:15\n' +
        '• 15:00 – 15:30',
      );
    });

    it('uses 24h colon format for EN (no am/pm)', () => {
      const out = formatAvailability(
        [slot('2026-05-07T18:00:00Z', '2026-05-07T19:00:00Z')], // 14:00–15:00 EDT
        { locale: 'en-US', timezone: 'America/New_York', now: NOW },
      );
      expect(out).toBe("Here's when I'm free — today (May 7) at 14:00 – 15:00.");
      expect(out).not.toMatch(/am|pm/i);
    });

    it('keeps the same 24h format when crossing noon', () => {
      const out = formatAvailability(
        [slot('2026-05-07T15:30:00Z', '2026-05-07T16:30:00Z')], // 11:30–12:30
        { locale: 'en-US', timezone: 'America/New_York', now: NOW },
      );
      expect(out).toBe("Here's when I'm free — today (May 7) at 11:30 – 12:30.");
    });
  });

  describe('multi-day slots (en)', () => {
    it('renders one bullet per day with weekday names for non-today dates', () => {
      const out = formatAvailability(
        [
          slot('2026-05-07T15:45:00Z', '2026-05-07T16:15:00Z'), // today 11:45–12:15
          slot('2026-05-08T18:00:00Z', '2026-05-08T19:00:00Z'), // Fri 14:00–15:00
        ],
        { locale: 'en-US', timezone: 'America/New_York', now: NOW },
      );
      expect(out).toBe(
        "Here's when I'm free:\n" +
        '• today (May 7): 11:45 – 12:15\n' +
        '• Fri May 8th: 14:00 – 15:00',
      );
    });
  });

  describe('consecutive merging', () => {
    it('merges back-to-back slots into a single range', () => {
      const out = formatAvailability(
        [
          slot('2026-05-07T18:00:00Z', '2026-05-07T18:30:00Z'), // 14:00–14:30
          slot('2026-05-07T18:30:00Z', '2026-05-07T19:00:00Z'), // 14:30–15:00
        ],
        { locale: 'en-US', timezone: 'America/New_York', now: NOW },
      );
      expect(out).toBe("Here's when I'm free — today (May 7) at 14:00 – 15:00.");
    });

    it('merges slots within 5-min gap (boundary)', () => {
      const out = formatAvailability(
        [
          slot('2026-05-07T18:00:00Z', '2026-05-07T18:30:00Z'),
          slot('2026-05-07T18:34:00Z', '2026-05-07T19:00:00Z'),
        ],
        { locale: 'en-US', timezone: 'America/New_York', now: NOW },
      );
      // 4-min gap → merged into a single inline slot.
      expect(out).toContain('14:00 – 15:00');
    });

    it('does NOT merge slots > 5-min gap (renders bullet list)', () => {
      const out = formatAvailability(
        [
          slot('2026-05-07T18:00:00Z', '2026-05-07T18:30:00Z'),
          slot('2026-05-07T18:40:00Z', '2026-05-07T19:00:00Z'),
        ],
        { locale: 'en-US', timezone: 'America/New_York', now: NOW },
      );
      expect(out).toBe(
        "Here's when I'm free today (May 7):\n" +
        '• 14:00 – 14:30\n' +
        '• 14:40 – 15:00',
      );
    });
  });

  // Séparateur d'heure locale-aware (2026-06-23) : FR garde `h`, EN/ES en `:`.
  describe('locale-aware time separator (2026-06-23)', () => {
    const tenToEleven = [slot('2026-05-07T14:00:00Z', '2026-05-07T15:00:00Z')]; // 10:00–11:00 EDT

    it('English uses a colon (10:00 – 11:00)', () => {
      const out = formatAvailability(tenToEleven, { locale: 'en-US', timezone: 'America/New_York', now: NOW });
      expect(out).toContain('10:00 – 11:00');
      expect(out).not.toContain('10h00');
    });

    it('French keeps the h notation (10h00 – 11h00)', () => {
      const out = formatAvailability(tenToEleven, { locale: 'fr-FR', timezone: 'America/New_York', now: NOW });
      expect(out).toContain('10h00 – 11h00');
      expect(out).not.toContain('10:00');
    });

    it('Spanish uses a colon (10:00 – 11:00)', () => {
      const out = formatAvailability(tenToEleven, { locale: 'es-ES', timezone: 'America/New_York', now: NOW });
      expect(out).toContain('10:00 – 11:00');
      expect(out).not.toContain('10h00');
    });

    it('strips the leading zero for single-digit hours in both notations', () => {
      const morning = [slot('2026-05-07T13:15:00Z', '2026-05-07T14:15:00Z')]; // 9:15–10:15 EDT
      const en = formatAvailability(morning, { locale: 'en-US', timezone: 'America/New_York', now: NOW });
      const fr = formatAvailability(morning, { locale: 'fr-FR', timezone: 'America/New_York', now: NOW });
      expect(en).toContain('9:15 – 10:15');
      expect(fr).toContain('9h15 – 10h15');
    });
  });

  describe('locale: french', () => {
    it('uses the h notation and " à " between day and time', () => {
      const out = formatAvailability(
        [slot('2026-05-07T18:00:00Z', '2026-05-07T19:00:00Z')], // 14:00–15:00 EDT
        { locale: 'fr-FR', timezone: 'America/New_York', now: NOW },
      );
      expect(out).toMatch(/^Voici mes disponibilités — aujourd'hui \(\d+ mai\) à 14h00 – 15h00\.$/);
    });

    it('renders multiple same-day slots as a bulleted heading', () => {
      const out = formatAvailability(
        [
          slot('2026-05-07T18:00:00Z', '2026-05-07T18:30:00Z'),
          slot('2026-05-07T19:00:00Z', '2026-05-07T19:30:00Z'),
        ],
        { locale: 'fr-FR', timezone: 'America/New_York', now: NOW },
      );
      expect(out).toContain("Voici mes disponibilités le aujourd'hui");
      expect(out).toContain('• 14h00 – 14h30');
      expect(out).toContain('• 15h00 – 15h30');
    });
  });

  describe('locale: spanish', () => {
    it('uses "Aquí están", "a las" and a colon time', () => {
      const out = formatAvailability(
        [slot('2026-05-07T18:00:00Z', '2026-05-07T19:00:00Z')],
        { locale: 'es-ES', timezone: 'America/New_York', now: NOW },
      );
      expect(out).toMatch(/^Aquí están mis disponibilidades — hoy \(\d+ may\) a las 14:00 – 15:00\.$/);
    });
  });

  describe('booking URL', () => {
    it('appends a booking line on a new line when provided', () => {
      const out = formatAvailability(
        [slot('2026-05-07T15:45:00Z', '2026-05-07T16:15:00Z')],
        {
          locale: 'en-US',
          timezone: 'America/New_York',
          now: NOW,
          bookingUrl: 'https://calendar.app.google/abc123',
        },
      );
      expect(out).toContain('Or pick directly: https://calendar.app.google/abc123');
      expect(out.split('\n')).toHaveLength(2);
    });

    it('omits the booking line when no URL is given', () => {
      const out = formatAvailability(
        [slot('2026-05-07T15:45:00Z', '2026-05-07T16:15:00Z')],
        { locale: 'en-US', timezone: 'America/New_York', now: NOW },
      );
      expect(out).not.toContain('Or pick directly');
      expect(out.split('\n')).toHaveLength(1);
    });
  });

  describe('formatBookingLineOnly', () => {
    it('returns just the booking line for the given locale', () => {
      expect(formatBookingLineOnly('https://cal.com/me', 'en-US'))
        .toBe('Or pick directly: https://cal.com/me');
      expect(formatBookingLineOnly('https://cal.com/me', 'fr-FR'))
        .toBe('Ou choisissez directement : https://cal.com/me');
    });

    it('returns empty for empty URL', () => {
      expect(formatBookingLineOnly('', 'en-US')).toBe('');
    });
  });

  describe('timezone abbrev', () => {
    it('is OFF by default — no EDT/CEST suffix', () => {
      const out = formatAvailability(
        [slot('2026-05-07T18:00:00Z', '2026-05-07T19:00:00Z')],
        { locale: 'en-US', timezone: 'America/New_York', now: NOW },
      );
      expect(out).toBe("Here's when I'm free — today (May 7) at 14:00 – 15:00.");
      expect(out).not.toContain('EDT');
    });

    it('appends abbrev only when includeTzAbbrev=true is opted in', () => {
      const out = formatAvailability(
        [slot('2026-05-07T18:00:00Z', '2026-05-07T19:00:00Z')],
        {
          locale: 'en-US', timezone: 'America/New_York', now: NOW,
          includeTzAbbrev: true,
        },
      );
      expect(out).toContain('EDT');
    });
  });

  describe('sort robustness', () => {
    it('sorts unsorted input before formatting', () => {
      const a = slot('2026-05-08T18:00:00Z', '2026-05-08T19:00:00Z'); // Fri
      const b = slot('2026-05-07T15:45:00Z', '2026-05-07T16:15:00Z'); // today
      const out = formatAvailability(
        [a, b],
        { locale: 'en-US', timezone: 'America/New_York', now: NOW },
      );
      // Today should come first regardless of input order.
      const todayIdx = out.indexOf('today');
      const friIdx = out.indexOf('Fri May 8th');
      expect(todayIdx).toBeLessThan(friIdx);
    });
  });
});
