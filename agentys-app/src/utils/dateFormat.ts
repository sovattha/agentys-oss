/**
 * Shared date formatting utilities — language-aware.
 * English: ordinal suffix  → "March 2nd", "Mar 2nd"
 * Other languages: day-first → "2 mars", "2 März"
 *
 * Long dates use compact format: "2026-03-22 9h24" (FR) / "2026-03-22 13:24" (EN/ES).
 */

/**
 * Locale-aware "H:MM" formatter for inline timestamps. The hour is never
 * zero-padded (consistent across locales); minutes are always 2 digits.
 * - French → "9h05", "17h00" (legacy "h" convention used throughout the app)
 * - English / Spanish / others → "9:05", "17:00" (24h with colon)
 *
 * QA 2026-05-19 — Bug #5: the app rendered times as "${h}h${mm}" regardless
 * of locale, which collided with English date formatting like "May 14th" and
 * produced rows like "Alexandre Simon — Re: Test666 — 13h53" in an
 * English UI. Centralise here so every call site stays in sync.
 */
export function formatHourMinute(date: Date, lang?: string): string {
  const h = date.getHours();
  const mm = String(date.getMinutes()).padStart(2, '0');
  // Default to the French "h" form when no locale is supplied so existing
  // callers that don't pass `lang` keep their historical output.
  const useColon = typeof lang === 'string' && !lang.startsWith('fr');
  if (useColon) {
    return `${h}:${mm}`;
  }
  return `${h}h${mm}`;
}

/** Compact date+time: "2026-03-22 9h24" (FR) / "2026-03-22 13:24" (EN/ES) */
export function formatCompactDateTime(date: Date, lang?: string): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d} ${formatHourMinute(date, lang)}`;
}

/** Compact date only: "2026-03-22" */
export function formatCompactDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

export function getOrdinalSuffix(n: number): string {
  const v = n % 100;
  if (v >= 11 && v <= 13) return `${n}th`;
  switch (n % 10) {
    case 1: return `${n}st`;
    case 2: return `${n}nd`;
    case 3: return `${n}rd`;
    default: return `${n}th`;
  }
}

/** "March 2nd" (EN) · "2 mars" (FR/DE/ES) */
export function formatDayMonth(day: number, monthName: string, lang: string): string {
  if (lang.startsWith('en')) return `${monthName} ${getOrdinalSuffix(day)}`;
  return `${day} ${monthName}`;
}

/**
 * Parse a date string for displaying its calendar day. A bare 'YYYY-MM-DD' is
 * parsed as UTC midnight by ECMAScript, so getDate() returns the previous day in
 * UTC-X timezones (CP-10, e.g. the Americas). Treat date-only strings as local
 * midnight; pass full ISO timestamps through unchanged.
 */
function parseLocalDate(dateString: string): Date {
  return new Date(/^\d{4}-\d{2}-\d{2}$/.test(dateString) ? `${dateString}T00:00:00` : dateString);
}

/** Short date for inline rows: "Mar 2nd" (EN) · "2 mars" (FR) */
export function formatShortDate(dateString: string, lang: string): string {
  const date = parseLocalDate(dateString);
  if (isNaN(date.getTime())) return '—';
  const day = date.getDate();
  const monthName = date.toLocaleString(lang, { month: 'short' });
  return formatDayMonth(day, monthName, lang);
}

/** Short date without parsing: day + short month from a Date object */
export function formatShortDateFromDate(date: Date, lang: string): string {
  const day = date.getDate();
  const monthName = date.toLocaleString(lang, { month: 'short' });
  return formatDayMonth(day, monthName, lang);
}

/** Long-month variant of formatShortDateFromDate: "May 27th" (EN) · "27 mai" (FR). */
export function formatLongDateFromDate(date: Date, lang: string): string {
  const day = date.getDate();
  const monthName = date.toLocaleString(lang, { month: 'long' });
  return formatDayMonth(day, monthName, lang);
}

/**
 * Day + month + year — no weekday, no time:
 * "May 27th 2026" (EN) · "27 mai 2026" (FR/DE/ES).
 * `width` selects the month-name length (short by default). Mirrors the date
 * portion of formatGmailDateTime so every "DD Month YYYY" surface shares the
 * same English ordinal / day-first house style (no comma before the year).
 */
export function formatDayMonthYear(date: Date, lang: string, width: 'short' | 'long' = 'short'): string {
  const day = date.getDate();
  const monthName = date.toLocaleString(lang, { month: width });
  return `${formatDayMonth(day, monthName, lang)} ${date.getFullYear()}`;
}

/** Long date: "March 2nd" (EN) · "2 mars" (FR) */
export function formatLongDate(dateString: string, lang: string): string {
  const date = parseLocalDate(dateString);
  if (isNaN(date.getTime())) return '—';
  const day = date.getDate();
  const monthName = date.toLocaleString(lang, { month: 'long' });
  return formatDayMonth(day, monthName, lang);
}

/**
 * Nettoie la description d'un événement ICS.
 * Supprime le corps des emails d'invitation Google Calendar / Outlook (boilerplate ICS)
 * et tronque à une longueur raisonnable.
 */
export function sanitizeEventDescription(raw: string): string {
  if (!raw) return '';

  // Supprime tout après les délimiteurs MIME ICS ou les marqueurs de boilerplate Google/Outlook
  const boilerplateMarkers = [
    /\n-{2,}/,                          // "-- " MIME boundary
    /\nChanged:/i,                        // Google: "Changed: time"
    /\nYou have been invited/i,           // Google invitation header
    /\nInvitation from Google Calendar/i, // Google footer
    /\nView all guest info/i,             // Google
    /\nReply for \S+@\S+/i,              // Google reply link
    /\nMicrosoft Teams meeting/i,         // Teams
    /\nJoin Microsoft Teams Meeting/i,    // Teams
    /\n_{10,}/,                          // Outlook separator "___..."
  ];

  let cleaned = raw;
  for (const marker of boilerplateMarkers) {
    const match = cleaned.search(marker);
    if (match > 0) {
      cleaned = cleaned.slice(0, match).trim();
    }
  }

  // Tronquer à 500 caractères max avec ellipsis si nécessaire
  const MAX_LEN = 500;
  if (cleaned.length > MAX_LEN) {
    cleaned = cleaned.slice(0, MAX_LEN).trim() + '…';
  }

  return cleaned.trim();
}

/**
 * Localized date for calendar event detail card: "7 avril 2026" (FR) · "April 7, 2026" (EN)
 * Utilise toLocaleDateString avec le format long pour un affichage lisible.
 */
export function formatEventDetailDate(date: Date, lang: string): string {
  try {
    return date.toLocaleDateString(lang, { day: 'numeric', month: 'long', year: 'numeric' });
  } catch {
    return formatCompactDate(date);
  }
}

/**
 * Localized date+time for calendar event detail card: "7 avril 2026, 10h45" (FR)
 * · "April 7, 2026, 10:45" (EN/ES). Bug #5 (2026-05-19).
 */
export function formatEventDetailDateTime(date: Date, lang: string): string {
  const datePart = formatEventDetailDate(date, lang);
  return `${datePart}, ${formatHourMinute(date, lang)}`;
}

/**
 * Email header date: day + month + year + time (no weekday).
 * "31 mai 2026, 17h07" (FR/DE/ES) · "May 31st 2026, 17:07" (EN).
 *
 * The date portion reuses formatDayMonth so English gets an ordinal day
 * ("May 31st") while other locales stay day-first ("31 mai"); the time portion
 * reuses formatHourMinute so French keeps the app's "17h07" convention while
 * English/Spanish use "17:07" (Bug #5 — "h" times collide with English ordinals,
 * the very format this header now produces).
 */
export function formatGmailDateTime(dateString: string, lang: string): string {
  const date = parseLocalDate(dateString);
  if (isNaN(date.getTime())) return '—';
  let datePart: string;
  try {
    const monthName = date.toLocaleString(lang, { month: 'short' });
    datePart = `${formatDayMonth(date.getDate(), monthName, lang)} ${date.getFullYear()}`;
  } catch {
    datePart = formatCompactDate(date);
  }
  return `${datePart}, ${formatHourMinute(date, lang)}`;
}

/**
 * Full date with time — compact: "2026-03-22 9h24" (FR) / "2026-03-22 13:24" (EN/ES).
 * Bug #5 (2026-05-19): now respects the active language.
 */
export function formatFullDateWithTime(dateString: string, lang: string): string {
  const date = parseLocalDate(dateString);
  if (isNaN(date.getTime())) return '—';
  return formatCompactDateTime(date, lang);
}

/**
 * Full date with time (email headers, detail view) — compact: "2026-03-22 9h24" (FR)
 * / "2026-03-22 13:24" (EN/ES). Bug #5 (2026-05-19).
 */
export function formatFullDateLong(dateString: string, lang: string): string {
  const date = parseLocalDate(dateString);
  if (isNaN(date.getTime())) return '—';
  return formatCompactDateTime(date, lang);
}
