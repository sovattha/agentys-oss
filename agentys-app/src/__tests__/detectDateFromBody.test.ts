import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { detectDateFromBody } from '../components/FollowupDatePicker'

// Freeze "now" at 2026-05-04 (a Monday) for predictable computation.
const FIXED_NOW = new Date(2026, 4, 4, 10, 0, 0, 0) // May 4, 2026, 10:00

describe('detectDateFromBody', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(FIXED_NOW)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('empty / null', () => {
    it('returns null for undefined', () => {
      expect(detectDateFromBody(undefined)).toBeNull()
    })
    it('returns null for empty string', () => {
      expect(detectDateFromBody('')).toBeNull()
    })
    it('returns null when no date hint present', () => {
      expect(detectDateFromBody('Hello, how are you?')).toBeNull()
    })
  })

  describe('English month + day (the bug from the screenshot)', () => {
    it('detects "May 5th"', () => {
      const r = detectDateFromBody('i will come back on May 5th')
      expect(r).not.toBeNull()
      expect(r!.date.getMonth()).toBe(4)
      expect(r!.date.getDate()).toBe(5)
      expect(r!.date.getFullYear()).toBe(2026)
    })

    it('detects "May 5" (no ordinal)', () => {
      const r = detectDateFromBody('see you May 5')
      expect(r!.date.getMonth()).toBe(4)
      expect(r!.date.getDate()).toBe(5)
    })

    it('detects "March 1st"', () => {
      const r = detectDateFromBody('let us meet March 1st')
      expect(r!.date.getMonth()).toBe(2)
      expect(r!.date.getDate()).toBe(1)
      // March is past in May → next year
      expect(r!.date.getFullYear()).toBe(2027)
    })

    it('detects abbreviated month "Sep 12"', () => {
      const r = detectDateFromBody('flight on Sep 12')
      expect(r!.date.getMonth()).toBe(8)
      expect(r!.date.getDate()).toBe(12)
    })

    it('detects "Sept" (4-letter abbr) without partial-matching "Sep"', () => {
      const r = detectDateFromBody('Sept 30 deadline')
      expect(r!.date.getMonth()).toBe(8)
      expect(r!.date.getDate()).toBe(30)
    })

    it('detects ordinal "21st"', () => {
      const r = detectDateFromBody('June 21st')
      expect(r!.date.getMonth()).toBe(5)
      expect(r!.date.getDate()).toBe(21)
    })

    it('detects ordinal "22nd"', () => {
      const r = detectDateFromBody('I am free on August 22nd')
      expect(r!.date.getMonth()).toBe(7)
      expect(r!.date.getDate()).toBe(22)
    })

    it('detects ordinal "3rd"', () => {
      const r = detectDateFromBody('December 3rd works')
      expect(r!.date.getMonth()).toBe(11)
      expect(r!.date.getDate()).toBe(3)
    })
  })

  describe('English day + month order', () => {
    it('detects "5 May"', () => {
      const r = detectDateFromBody('back on 5 May')
      expect(r!.date.getMonth()).toBe(4)
      expect(r!.date.getDate()).toBe(5)
    })
    it('detects "5th of May"', () => {
      const r = detectDateFromBody('the 5th of May')
      expect(r!.date.getMonth()).toBe(4)
      expect(r!.date.getDate()).toBe(5)
    })
    it('detects "21st of June"', () => {
      const r = detectDateFromBody('returning 21st of June')
      expect(r!.date.getMonth()).toBe(5)
      expect(r!.date.getDate()).toBe(21)
    })
  })

  describe('French (existing behavior preserved)', () => {
    it('detects "5 mai"', () => {
      const r = detectDateFromBody('je reviens le 5 mai')
      expect(r!.date.getMonth()).toBe(4)
      expect(r!.date.getDate()).toBe(5)
    })
    it('detects "1 mars" (past month → next year)', () => {
      const r = detectDateFromBody('le 1 mars')
      expect(r!.date.getMonth()).toBe(2)
      expect(r!.date.getDate()).toBe(1)
      expect(r!.date.getFullYear()).toBe(2027)
    })
    it('detects "15 février" with accents', () => {
      const r = detectDateFromBody('rendez-vous le 15 février')
      expect(r!.date.getMonth()).toBe(1)
      expect(r!.date.getDate()).toBe(15)
    })
    it('detects "15 fevrier" without accents', () => {
      const r = detectDateFromBody('rendez-vous le 15 fevrier')
      expect(r!.date.getMonth()).toBe(1)
      expect(r!.date.getDate()).toBe(15)
    })
    it('detects "août" with circumflex', () => {
      // Avant : "vacances 10 août" — désormais filtré comme non-commitment.
      // On garde la couverture du circonflexe avec une phrase d'engagement.
      const r = detectDateFromBody('rendez-vous le 10 août')
      expect(r!.date.getMonth()).toBe(7)
      expect(r!.date.getDate()).toBe(10)
    })
  })

  describe('Mixed languages (the user’s actual input)', () => {
    it('detects "mai 5th" — French month + English ordinal/order', () => {
      const r = detectDateFromBody('i will come back on mai 5th')
      expect(r).not.toBeNull()
      expect(r!.date.getMonth()).toBe(4)
      expect(r!.date.getDate()).toBe(5)
      expect(r!.date.getFullYear()).toBe(2026)
    })
    it('detects "may 5" — English month, no ordinal', () => {
      const r = detectDateFromBody('back on may 5')
      expect(r!.date.getMonth()).toBe(4)
      expect(r!.date.getDate()).toBe(5)
    })
  })

  describe('Day-of-week fallback', () => {
    // FIXED_NOW = Monday May 4, 2026
    it('detects English "saturday" → next Saturday', () => {
      const r = detectDateFromBody('see you saturday')
      expect(r!.date.getDay()).toBe(6)
      expect(r!.date.getDate()).toBe(9) // Sat May 9
    })
    it('detects French "samedi"', () => {
      const r = detectDateFromBody('on se voit samedi')
      expect(r!.date.getDay()).toBe(6)
      expect(r!.date.getDate()).toBe(9)
    })
    it('detects "monday" → next Monday (today doesn’t count)', () => {
      const r = detectDateFromBody('let us sync monday')
      expect(r!.date.getDay()).toBe(1)
      expect(r!.date.getDate()).toBe(11) // next week, not today
    })
  })

  describe('HTML stripping', () => {
    it('strips tags and decodes entities', () => {
      const r = detectDateFromBody('<p>back on <strong>May&nbsp;5th</strong></p>')
      expect(r!.date.getMonth()).toBe(4)
      expect(r!.date.getDate()).toBe(5)
    })
  })

  describe('Priority: explicit date wins over day name', () => {
    it('prefers "May 5th" over "monday"', () => {
      const r = detectDateFromBody('on monday or May 5th')
      expect(r!.date.getMonth()).toBe(4)
      expect(r!.date.getDate()).toBe(5)
    })
  })

  describe('Edge cases / no false positives', () => {
    it('does not match "may" alone (no number)', () => {
      expect(detectDateFromBody('I may come back later')).toBeNull()
    })
    it('does not match invalid day "May 32"', () => {
      // Day > 31 should not produce a valid date
      const r = detectDateFromBody('May 32')
      // Either null OR clamped — accept null only
      expect(r).toBeNull()
    })
    it('does not match number embedded in word', () => {
      expect(detectDateFromBody('item5may')).toBeNull()
    })
  })
})
