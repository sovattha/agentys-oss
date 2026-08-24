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

// Pure, dependency-free formatting for the auto-reply "absence period"
// placeholder. Kept out of the component so it can be unit-tested in isolation
// and reused if another surface ever needs the same date-range wording.

/**
 * Parse a `YYYY-MM-DD` string as a *local* date (no timezone shift).
 *
 * `new Date('2026-03-25')` parses as UTC midnight and can roll back a day in
 * negative-offset zones — splitting the parts and using the multi-arg `Date`
 * constructor keeps the date in the user's local zone, which is what the
 * date pickers above the message edit.
 *
 * Returns `null` for empty or malformed input (including impossible calendar
 * dates like `2026-02-31` that JS would otherwise silently roll over).
 */
export function parseIsoDateLocal(iso: string): Date | null {
  if (!iso) return null
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso.trim())
  if (!m) return null
  const year = Number(m[1])
  const month = Number(m[2])
  const day = Number(m[3])
  const d = new Date(year, month - 1, day)
  if (d.getFullYear() !== year || d.getMonth() !== month - 1 || d.getDate() !== day) {
    return null
  }
  return d
}

// English reads day-of-month as an ordinal ("March 25th", not "March 25").
// `Intl.PluralRules` with `type: 'ordinal'` returns the right category
// including the 11th/12th/13th exceptions, so we don't hand-roll the rules.
const EN_ORDINAL_SUFFIX: Record<Intl.LDMLPluralRule, string> = {
  one: 'st',
  two: 'nd',
  few: 'rd',
  other: 'th',
  zero: 'th',
  many: 'th',
}

function englishOrdinalSuffix(day: number): string {
  return EN_ORDINAL_SUFFIX[new Intl.PluralRules('en', { type: 'ordinal' }).select(day)] ?? 'th'
}

/**
 * Format the start/end of an absence window into locale-aware "day month"
 * parts (no year), matching the auto-reply message style:
 *   fr → "25 mars" / "29 mars"
 *   en → "March 25th" / "March 29th"
 *   es → "25 de marzo" / "29 de marzo"
 *
 * The caller composes these into the final phrase via the `auto_reply_period_range`
 * i18n template ("du {{start}} au {{end}}"), so the connector words stay
 * translatable while the dates stay locale-formatted.
 *
 * Returns `null` if either date is missing/malformed so the caller can fall
 * back to a generic label.
 */
export function formatAbsencePeriodParts(
  startISO: string,
  endISO: string,
  locale: string,
): { start: string; end: string } | null {
  const start = parseIsoDateLocal(startISO)
  const end = parseIsoDateLocal(endISO)
  if (!start || !end) return null
  let fmt: Intl.DateTimeFormat
  try {
    fmt = new Intl.DateTimeFormat(locale || 'fr', { day: 'numeric', month: 'long' })
  } catch {
    // Bad/unsupported locale tag → fall back to French (the app default).
    fmt = new Intl.DateTimeFormat('fr', { day: 'numeric', month: 'long' })
  }
  // Use the formatter's RESOLVED locale (not the raw tag) so an invalid tag
  // that fell back to French isn't mistaken for English.
  const isEnglish = fmt.resolvedOptions().locale.toLowerCase().startsWith('en')
  const fmtOne = (d: Date): string => {
    if (!isEnglish) return fmt.format(d)
    // Append the ordinal to the day token via formatToParts so it stays
    // position-safe regardless of where the locale places the day.
    return fmt
      .formatToParts(d)
      .map((p) => (p.type === 'day' ? p.value + englishOrdinalSuffix(Number(p.value)) : p.value))
      .join('')
  }
  return { start: fmtOne(start), end: fmtOne(end) }
}
