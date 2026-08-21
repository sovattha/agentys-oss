import { describe, it, expect } from 'vitest'
import {
  DAY_MIN,
  parseHM,
  minutesToPct,
  slotGeometry,
  daylightGeometry,
  formatSlotTime,
  formatStartTime,
  durationLabel,
  nowMarkerPct,
  WORK_WINDOW_START_MIN,
  WORK_WINDOW_END_MIN,
} from './deepWorkTimeline'

describe('parseHM', () => {
  it('parses HH:MM into minutes since midnight', () => {
    expect(parseHM('00:00')).toBe(0)
    expect(parseHM('08:00')).toBe(480)
    expect(parseHM('16:30')).toBe(990)
    expect(parseHM('23:59')).toBe(1439)
  })
  it('tolerates malformed input without NaN', () => {
    expect(parseHM('')).toBe(0)
    expect(parseHM('garbage')).toBe(0)
    expect(parseHM('9')).toBe(540)
  })
})

describe('minutesToPct', () => {
  it('maps the day onto 0–100%', () => {
    expect(minutesToPct(0)).toBe(0)
    expect(minutesToPct(DAY_MIN)).toBe(100)
    expect(minutesToPct(DAY_MIN / 2)).toBe(50)
  })
  it('clamps out-of-range values', () => {
    expect(minutesToPct(-60)).toBe(0)
    expect(minutesToPct(DAY_MIN + 999)).toBe(100)
  })
})

describe('slotGeometry', () => {
  it('places a slot at the right offset and width', () => {
    const g = slotGeometry('08:00', 30)
    expect(g.leftPct).toBeCloseTo((480 / DAY_MIN) * 100)
    expect(g.widthPct).toBeCloseTo((30 / DAY_MIN) * 100)
  })
  it('clamps a slot that would overflow past midnight', () => {
    const g = slotGeometry('23:50', 60) // would run to 00:50 next day
    expect(g.leftPct).toBeCloseTo((1430 / DAY_MIN) * 100)
    // width capped at 10 min (to midnight), not 60
    expect(g.widthPct).toBeCloseTo((10 / DAY_MIN) * 100)
  })
})

describe('daylightGeometry', () => {
  it('spans the working window', () => {
    const g = daylightGeometry()
    expect(g.leftPct).toBeCloseTo((WORK_WINDOW_START_MIN / DAY_MIN) * 100)
    expect(g.widthPct).toBeCloseTo(
      ((WORK_WINDOW_END_MIN - WORK_WINDOW_START_MIN) / DAY_MIN) * 100,
    )
  })
})

describe('formatSlotTime (locale-aware clock-times)', () => {
  it('EN/ES → colon, no leading hour zero', () => {
    expect(formatSlotTime('08:00', 30, 'en')).toBe('8:00 — 8:30')
    expect(formatSlotTime('16:00', 30, 'es')).toBe('16:00 — 16:30')
  })
  it('FR → h notation', () => {
    expect(formatSlotTime('08:00', 30, 'fr')).toBe('8h00 — 8h30')
    expect(formatSlotTime('16:00', 30, 'fr')).toBe('16h00 — 16h30')
  })
  it('wraps cleanly past midnight in both notations', () => {
    expect(formatSlotTime('23:50', 30, 'en')).toBe('23:50 — 0:20')
    expect(formatSlotTime('23:50', 30, 'fr')).toBe('23h50 — 0h20')
  })
  it('defaults to FR "h" when no locale is given', () => {
    expect(formatSlotTime('08:00', 30)).toBe('8h00 — 8h30')
  })
})

describe('formatStartTime (locale-aware clock-times)', () => {
  it('drops the leading hour zero, keeps padded minutes, locale separator', () => {
    expect(formatStartTime('09:00', 'fr')).toBe('9h00')
    expect(formatStartTime('09:00', 'en')).toBe('9:00')
    expect(formatStartTime('08:05', 'fr')).toBe('8h05')
    expect(formatStartTime('16:30', 'en')).toBe('16:30')
    expect(formatStartTime('00:00', 'fr')).toBe('0h00')
  })
  it('defaults to FR "h" when no locale is given', () => {
    expect(formatStartTime('09:00')).toBe('9h00')
  })
})

describe('durationLabel', () => {
  it('formats sub-hour and hour durations', () => {
    expect(durationLabel(30)).toBe('30 min')
    expect(durationLabel(60)).toBe('1h')
    expect(durationLabel(90)).toBe('1h30')
    expect(durationLabel(120)).toBe('2h')
  })
})

describe('nowMarkerPct', () => {
  it('positions the marker at the clock time', () => {
    const noon = new Date(2026, 4, 21, 12, 0, 0)
    expect(nowMarkerPct(noon)).toBe(50)
    const quarter = new Date(2026, 4, 21, 6, 0, 0)
    expect(nowMarkerPct(quarter)).toBe(25)
  })
})
