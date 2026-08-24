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

﻿/**
 * Convert selected availability slots into prose suitable for pasting
 * into an email reply. Locale-aware (en/fr/es), timezone-aware, and
 * smart enough to collapse consecutive slots into ranges and group same-
 * day slots together.
 *
 * Examples (en-US, America/New_York → "EDT"):
 *
 *   single slot, today:
 *     "I can do today (May 7) at 11:45 am – 12:15 pm EDT."
 *
 *   multiple same-day:
 *     "I can do Thu May 7 at 11:45 am – 12:15 pm, 12:30 – 2:15 pm,
 *      or 3:00 – 3:30 pm EDT."
 *
 *   multi-day:
 *     "I can do Thu May 7 at 11:45 am – 12:15 pm, or Fri May 8 at
 *      2:00 – 3:00 pm EDT."
 *
 * The function intentionally does NOT include any HTML — it returns
 * plain text suitable for `editor.insertText()`. Compose surfaces are
 * responsible for trailing newlines / surrounding whitespace.
 */

export interface AvailabilitySlot {
  /** ISO 8601 string OR a Date — both supported. */
  start: Date | string;
  end: Date | string;
}

export interface FormatOptions {
  /** BCP-47 locale like 'en-US', 'fr-FR', 'es-ES'. */
  locale: string;
  /** IANA timezone like 'America/New_York', 'Europe/Paris'. */
  timezone: string;
  /** Append a short timezone abbreviation (e.g. "EDT", "CEST"). Default true. */
  includeTzAbbrev?: boolean;
  /** Append a booking-page URL on a new line. Optional. */
  bookingUrl?: string;
  /**
   * "today's date" anchor. Tests inject a fixed value so output is
   * deterministic; production callers leave it undefined and we use Date.now().
   */
  now?: Date;
  /**
   * Output shape:
   *  - 'text' (default): plain text with `• ` bullets and `\n` newlines.
   *  - 'html': proper `<p>` and `<ul><li>…</li></ul>` markup so a
   *    rich-text editor (TipTap, Outlook, Gmail) renders a real list
   *    rather than literal bullet characters.
   */
  output?: 'text' | 'html';
}

// ---------------------------------------------------------------------------
// Per-locale phrasing. Kept in this file (not i18n keys) because the formatter
// is pure logic and the phrases are tightly coupled to its grammar.
// ---------------------------------------------------------------------------

interface Phrasing {
  /** Sentence prefix, e.g. "Here are my availabilities" / "Voici mes disponibilités". */
  leadIn: string;
  /** Connector in single-slot inline form: leadIn + sep + day + dayTimeSep + range. */
  inlineSep: string;
  /** Connector between day and time in single-slot inline form (" at " / " à "). */
  inlineDayTimeSep: string;
  /** Connector for same-day-multi heading: leadIn + forDay + day + ":" */
  forDay: string;
  /** Colon prefix before bullets ":" in EN, " :" in FR (with non-breaking space). */
  colon: string;
  /** Joins multiple times under the same day, e.g. ", ". */
  timesJoin: string;
  /** "today (May 7)" — full day phrase when same as `now`. */
  todayWithDate: (monthDay: string) => string;
  /** "Thu May 7" — relative day name + date. */
  weekdayWithDate: (weekday: string, monthDay: string) => string;
  /** Joins a day phrase with the time list inside multi-day bullets ("Mon May 11: 14h30 …"). */
  bulletDayTimeSep: string;
  /** Final period + space before optional booking line. */
  bookingLinePrefix: string;
}

const PHRASINGS: Record<string, Phrasing> = {
  en: {
    // House-style: terser lead-in than "Here are my availabilities".
    leadIn: "Here's when I'm free",
    inlineSep: ' — ',
    inlineDayTimeSep: ' at ',
    // Just a space — reads naturally for both "today (May 7)" and
    // "Wed May 13th": "Here's when I'm free today (May 7):" /
    // "Here's when I'm free Wed May 13th:".
    forDay: ' ',
    colon: ':',
    timesJoin: ', ',
    todayWithDate: (md) => `today (${md})`,
    // House-style: ordinal suffix on the day-of-month — "Wed May 13th"
    // not "Wed May 13". `md` is "May 13" so we append the suffix to the
    // trailing number.
    weekdayWithDate: (wd, md) => `${wd} ${withOrdinalSuffix(md)}`,
    bulletDayTimeSep: ': ',
    bookingLinePrefix: 'Or pick directly: ',
  },
  fr: {
    leadIn: 'Voici mes disponibilités',
    inlineSep: ' — ',
    inlineDayTimeSep: ' à ',
    forDay: ' le ',
    colon: ' :',
    timesJoin: ', ',
    todayWithDate: (md) => `aujourd'hui (${md})`,
    weekdayWithDate: (wd, md) => `${wd} ${md}`,
    bulletDayTimeSep: ' : ',
    bookingLinePrefix: 'Ou choisissez directement : ',
  },
  es: {
    leadIn: 'Aquí están mis disponibilidades',
    inlineSep: ' — ',
    inlineDayTimeSep: ' a las ',
    forDay: ' para ',
    colon: ':',
    timesJoin: ', ',
    todayWithDate: (md) => `hoy (${md})`,
    weekdayWithDate: (wd, md) => `${wd} ${md}`,
    bulletDayTimeSep: ': ',
    bookingLinePrefix: 'O elige directamente: ',
  },
};

function pickPhrasing(locale: string): Phrasing {
  const tag = (locale || 'en').split('-')[0].toLowerCase();
  return PHRASINGS[tag] || PHRASINGS.en;
}

/**
 * Append an English ordinal suffix to the trailing number of a string —
 * "May 13" → "May 13th", "May 1" → "May 1st", "May 22" → "May 22nd".
 *
 * Used by the EN phrasing only; other locales don't use ordinals.
 * Handles the standard 11/12/13 → "th" exception.
 */
function withOrdinalSuffix(monthDay: string): string {
  return monthDay.replace(/(\d+)$/, (_, num: string) => {
    const n = parseInt(num, 10);
    const mod100 = n % 100;
    if (mod100 >= 11 && mod100 <= 13) return `${n}th`;
    switch (n % 10) {
      case 1: return `${n}st`;
      case 2: return `${n}nd`;
      case 3: return `${n}rd`;
      default: return `${n}th`;
    }
  });
}

// ---------------------------------------------------------------------------
// Date / time helpers — all timezone-aware via Intl.DateTimeFormat.
// ---------------------------------------------------------------------------

function asDate(d: Date | string): Date {
  return d instanceof Date ? d : new Date(d);
}

/** "May 7" / "7 mai" — month+day in the user's locale. */
export function fmtMonthDay(d: Date, locale: string, timezone: string): string {
  return new Intl.DateTimeFormat(locale, {
    month: 'short', day: 'numeric', timeZone: timezone,
  }).format(d);
}

/** "Thu" / "jeu." — short weekday. */
export function fmtWeekdayShort(d: Date, locale: string, timezone: string): string {
  const out = new Intl.DateTimeFormat(locale, {
    weekday: 'short', timeZone: timezone,
  }).format(d);
  // Capitalize first letter — some locales (es) lowercase weekdays.
  return out.charAt(0).toUpperCase() + out.slice(1);
}

/**
 * Clock time, 24-hour, leading zero stripped. Le s\u00e9parateur est LOCALE-AWARE
 * (choix utilisateur 2026-06-23) :
 *   - fr            \u2192 notation `h` : 8h00 / 14h30 (convention fran\u00e7aise)
 *   - en / es / \u2026 \u2192 `:`          : 8:00 / 14:30 (convention anglo / hispano)
 * Avant le 2026-06-23 c'\u00e9tait `h` pour TOUTES les langues ; un email anglais
 * affichant \u00ab 10h00 \u00bb paraissait franco-centr\u00e9 \u00e0 c\u00f4t\u00e9 du reste d\u00e9j\u00e0 localis\u00e9
 * (\u00ab Here's when I'm free \u00bb, \u00ab Wed Jun 24th \u00bb). On garde TOUJOURS les minutes
 * (jamais \u00ab 10h \u00bb / \u00ab 10 \u00bb seul).
 */
export function fmtClockTime(d: Date, locale: string, timezone: string): string {
  const sep = (locale || 'en').split('-')[0].toLowerCase() === 'fr' ? 'h' : ':';
  // 'en-GB' gives a deterministic "08:00" 24h base; strip the leading zero from
  // the hour, then apply the locale separator.
  const out = new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: timezone,
  }).format(d);
  const m = out.match(/^0?(\d{1,2}):(\d{2})$/);
  if (m) return `${parseInt(m[1], 10)}${sep}${m[2]}`;
  return out.replace(':', sep);
}

/**
 * "EDT" / "CEST" — short timezone abbreviation.
 *
 * We deliberately format with locale='en' regardless of the user's locale.
 * Node/ICU emits "UTC−4" instead of "EDT" for non-English locales, and the
 * 3-letter abbrev is universally recognized in email — a French recipient
 * still wants to see "EDT" rather than "UTC−4". Superhuman / Calendly /
 * Cal.com all do the same.
 */
function fmtTzAbbrev(d: Date, _locale: string, timezone: string): string {
  try {
    const parts = new Intl.DateTimeFormat('en', {
      timeZone: timezone,
      timeZoneName: 'short',
    }).formatToParts(d);
    const tz = parts.find(p => p.type === 'timeZoneName');
    const value = tz?.value ?? '';
    // Some runtimes still fall back to "GMT+2" / "UTC-4" — those are fine,
    // they're more informative than nothing.
    return value;
  } catch {
    return '';
  }
}

/** YYYY-MM-DD key for the slot's calendar date in the target timezone — used for grouping. */
export function dayKey(d: Date, timezone: string): string {
  // en-CA gives ISO-style YYYY-MM-DD; safest cross-browser approach.
  return new Intl.DateTimeFormat('en-CA', {
    year: 'numeric', month: '2-digit', day: '2-digit', timeZone: timezone,
  }).format(d);
}

/** True if same calendar date in the target timezone. */
export function isSameDay(a: Date, b: Date, timezone: string): boolean {
  return dayKey(a, timezone) === dayKey(b, timezone);
}

// ---------------------------------------------------------------------------
// Slot grouping & range-collapsing.
// ---------------------------------------------------------------------------

/** Two slots are "consecutive" if the second starts within 5 min of the first ending. */
function isConsecutive(a: AvailabilitySlot, b: AvailabilitySlot): boolean {
  const aEnd = asDate(a.end).getTime();
  const bStart = asDate(b.start).getTime();
  const gapMs = bStart - aEnd;
  return gapMs >= 0 && gapMs <= 5 * 60 * 1000;
}

/**
 * Merge consecutive slots so [11:45–12:15, 12:15–1:00] becomes [11:45–1:00].
 * Caller has already sorted ascending.
 */
function mergeConsecutive(slots: AvailabilitySlot[]): AvailabilitySlot[] {
  if (slots.length < 2) return slots;
  const out: AvailabilitySlot[] = [{ ...slots[0] }];
  for (let i = 1; i < slots.length; i++) {
    const prev = out[out.length - 1];
    const curr = slots[i];
    if (isConsecutive(prev, curr)) {
      prev.end = curr.end;
    } else {
      out.push({ ...curr });
    }
  }
  return out;
}

/** Group sorted slots by their day in the target timezone. */
export function groupByDay(
  slots: AvailabilitySlot[],
  timezone: string,
): Array<{ day: Date; slots: AvailabilitySlot[] }> {
  const groups: Array<{ day: Date; slots: AvailabilitySlot[] }> = [];
  for (const s of slots) {
    const start = asDate(s.start);
    const last = groups[groups.length - 1];
    if (last && isSameDay(asDate(last.slots[0].start), start, timezone)) {
      last.slots.push(s);
    } else {
      groups.push({ day: start, slots: [s] });
    }
  }
  return groups;
}

// ---------------------------------------------------------------------------
// Time-range rendering. The trick: when both ends share am/pm in EN, omit
// the first one ("11:45 – 12:15 pm" instead of "11:45 am – 12:15 pm" when
// both are pm). Saves a lot of visual noise.
// ---------------------------------------------------------------------------

function fmtRange(
  start: Date,
  end: Date,
  locale: string,
  timezone: string,
): string {
  // 24-hour `HhMM` is locale-neutral and self-contained — no am/pm
  // collapse logic needed any more.
  const startStr = fmtClockTime(start, locale, timezone);
  const endStr = fmtClockTime(end, locale, timezone);
  return `${startStr} – ${endStr}`;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Format selected availability slots into prose ready to paste into an
 * email reply. Returns an empty string if `slots` is empty.
 *
 * Output shapes (EN / FR examples):
 *
 *   Séparateur d'heure locale-aware (2026-06-23) : EN/ES en `:`, FR en `h`.
 *
 *   1 slot:
 *     "Here's when I'm free — Mon May 11th at 14:30 – 15:15."
 *     "Voici mes disponibilités — lundi 11 mai à 14h30 – 15h15."
 *
 *   N slots, same day:
 *     "Here's when I'm free Mon May 11th:
 *      • 14:30 – 15:15
 *      • 16:00 – 17:00"
 *     "Voici mes disponibilités le lundi 11 mai :
 *      • 14h30 – 15h15
 *      • 16h00 – 17h00"
 *
 *   N slots, multiple days → ONE bullet per day, times comma-joined:
 *     "Here's when I'm free:
 *      • Mon May 11th: 14:30 – 15:15
 *      • Tue May 12th: 11:15 – 12:00, 14:15 – 15:30
 *      • Wed May 13th: 11:00 – 12:00"
 *     "Voici mes disponibilités :
 *      • lundi 11 mai : 14h30 – 15h15
 *      • mardi 12 mai : 11h15 – 12h00, 14h15 – 15h30"
 *
 * The timezone abbreviation is OFF by default (recipients usually share
 * the user's TZ; the suffix adds visual noise in the email body). Pass
 * `includeTzAbbrev: true` to opt back in.
 */
export function formatAvailability(
  slots: AvailabilitySlot[],
  options: FormatOptions,
): string {
  if (!slots || slots.length === 0) return '';
  const phrasing = pickPhrasing(options.locale);
  const tz = options.timezone || 'UTC';
  const includeTz = options.includeTzAbbrev === true; // opt-in
  const now = options.now ?? new Date();

  const sorted = [...slots].sort(
    (a, b) => asDate(a.start).getTime() - asDate(b.start).getTime(),
  );
  const merged = mergeConsecutive(sorted);
  const groups = groupByDay(merged, tz);

  const labelForDay = (day: Date): string => {
    const monthDay = fmtMonthDay(day, options.locale, tz);
    return isSameDay(now, day, tz)
      ? phrasing.todayWithDate(monthDay)
      : phrasing.weekdayWithDate(fmtWeekdayShort(day, options.locale, tz), monthDay);
  };

  const tzAbbrev = includeTz
    ? fmtTzAbbrev(asDate(merged[merged.length - 1].start), options.locale, tz)
    : '';
  const tzSuffix = tzAbbrev ? ` ${tzAbbrev}` : '';

  const html = options.output === 'html';

  let sentence: string;

  // Case 1: a single slot → inline sentence, no bullets.
  if (merged.length === 1) {
    const slot = merged[0];
    const range = fmtRange(asDate(slot.start), asDate(slot.end), options.locale, tz);
    const inline = `${phrasing.leadIn}${phrasing.inlineSep}${labelForDay(asDate(slot.start))}${phrasing.inlineDayTimeSep}${range}${tzSuffix}.`;
    sentence = html ? `<p>${escHtml(inline)}</p>` : inline;
  }
  // Case 2: multiple slots, all on the same day → heading + bulleted times.
  else if (groups.length === 1) {
    const { day, slots: daySlots } = groups[0];
    const ranges = daySlots.map(s =>
      fmtRange(asDate(s.start), asDate(s.end), options.locale, tz),
    );
    const heading = `${phrasing.leadIn}${phrasing.forDay}${labelForDay(day)}${phrasing.colon}`;
    if (html) {
      const items = ranges.map(r => `<li>${escHtml(`${r}${tzSuffix}`)}</li>`).join('');
      sentence = `<p>${escHtml(heading)}</p><ul>${items}</ul>`;
    } else {
      const bullets = ranges.map(r => `• ${r}${tzSuffix}`).join('\n');
      sentence = `${heading}\n${bullets}`;
    }
  }
  // Case 3: multiple days → ONE bullet per day, times for that day comma-joined.
  else {
    const lines: string[] = [];
    for (const { day, slots: daySlots } of groups) {
      const dayLabel = labelForDay(day);
      const ranges = daySlots.map(s =>
        fmtRange(asDate(s.start), asDate(s.end), options.locale, tz),
      );
      const tzPart = tzSuffix ? `${tzSuffix}` : '';
      lines.push(`${dayLabel}${phrasing.bulletDayTimeSep}${ranges.join(phrasing.timesJoin)}${tzPart}`);
    }
    if (html) {
      const items = lines.map(l => `<li>${escHtml(l)}</li>`).join('');
      sentence = `<p>${escHtml(`${phrasing.leadIn}${phrasing.colon}`)}</p><ul>${items}</ul>`;
    } else {
      sentence = `${phrasing.leadIn}${phrasing.colon}\n${lines.map(l => `• ${l}`).join('\n')}`;
    }
  }

  if (options.bookingUrl) {
    if (html) {
      const url = escHtml(options.bookingUrl);
      sentence += `<p>${escHtml(phrasing.bookingLinePrefix)}<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a></p>`;
    } else {
      sentence += `\n${phrasing.bookingLinePrefix}${options.bookingUrl}`;
    }
  }

  // Wrap HTML output in a tagged container so downstream scanners
  // (e.g. detectDateFromBody → followup auto-reminder) can identify and
  // skip the block. Availability dates are dates we're OFFERING to the
  // recipient, not commitments we're making to ourselves — they must
  // not trigger an auto-followup reminder.
  if (html) {
    return `<div class="agentys-availability">${sentence}</div>`;
  }
  return sentence;
}

/** HTML escape — keep insertions safe even though the booking URL is the
 *  only user-controlled field (text from the formatter is never user input). */
function escHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => {
    switch (c) {
      case '&': return '&amp;';
      case '<': return '&lt;';
      case '>': return '&gt;';
      case '"': return '&quot;';
      case "'": return '&#39;';
      default: return c;
    }
  });
}

/**
 * Convenience: format just a booking URL line (used by the "Insert booking
 * link only" mode that skips the calendar picker).
 */
export function formatBookingLineOnly(
  bookingUrl: string,
  locale: string,
  output: 'text' | 'html' = 'text',
): string {
  if (!bookingUrl) return '';
  const phrasing = pickPhrasing(locale);
  if (output === 'html') {
    const url = escHtml(bookingUrl);
    // Same `agentys-availability` wrapper as formatAvailability — so the
    // booking line alone also opts out of follow-up date auto-detection.
    return `<div class="agentys-availability"><p>${escHtml(phrasing.bookingLinePrefix)}<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a></p></div>`;
  }
  return `${phrasing.bookingLinePrefix}${bookingUrl}`;
}
