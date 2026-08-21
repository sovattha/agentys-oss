import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Mock le module d'accountId AVANT l'import du service — sinon `getCurrentAccountId`
// retourne null et les clés localStorage sont scopées `:__none`.
vi.mock('../lib/currentAccountId', () => ({
  getCurrentAccountId: () => 'test-account',
  subscribeCurrentAccountId: () => () => {},
  ensureCurrentAccountId: async () => 'test-account',
  isCurrentAccountLoaded: () => true,
}))

import {
  isWithinWorkHours,
  getWorkHoursSettings,
  getWorkHoursStorageKeys,
  parseTime,
  type WorkHoursSettings,
} from '../services/workHours'

const KEYS = getWorkHoursStorageKeys()

describe('parseTime', () => {
  it('parse "09:00" en { hours: 9, minutes: 0 }', () => {
    const result = parseTime('09:00')
    expect(result).toEqual({ hours: 9, minutes: 0 })
  })

  it('parse "18:30" en { hours: 18, minutes: 30 }', () => {
    const result = parseTime('18:30')
    expect(result).toEqual({ hours: 18, minutes: 30 })
  })

  it('parse "00:00" en { hours: 0, minutes: 0 }', () => {
    const result = parseTime('00:00')
    expect(result).toEqual({ hours: 0, minutes: 0 })
  })

  it('parse "23:59" en { hours: 23, minutes: 59 }', () => {
    const result = parseTime('23:59')
    expect(result).toEqual({ hours: 23, minutes: 59 })
  })
})

describe('isWithinWorkHours', () => {
  const mockGetCurrentDate = vi.fn<() => Date>()

  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  const defaultSettings: WorkHoursSettings = {
    enabled: true,
    startTime: '09:00',
    endTime: '18:00',
  }

  describe('quand le filtre est desactive', () => {
    it('retourne true meme en dehors des heures', () => {
      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T03:00:00'))
      const settings = { ...defaultSettings, enabled: false }

      const result = isWithinWorkHours(settings, mockGetCurrentDate)

      expect(result).toBe(true)
    })
  })

  describe('heures de travail normales (09:00 - 18:00)', () => {
    it('retourne true a 09:00 (debut exact)', () => {
      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T09:00:00'))

      const result = isWithinWorkHours(defaultSettings, mockGetCurrentDate)

      expect(result).toBe(true)
    })

    it('retourne true a 12:00 (milieu de journee)', () => {
      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T12:00:00'))

      const result = isWithinWorkHours(defaultSettings, mockGetCurrentDate)

      expect(result).toBe(true)
    })

    it('retourne true a 17:59 (juste avant la fin)', () => {
      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T17:59:00'))

      const result = isWithinWorkHours(defaultSettings, mockGetCurrentDate)

      expect(result).toBe(true)
    })

    it('retourne false a 18:00 (fin exacte)', () => {
      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T18:00:00'))

      const result = isWithinWorkHours(defaultSettings, mockGetCurrentDate)

      expect(result).toBe(false)
    })

    it('retourne false a 08:59 (juste avant le debut)', () => {
      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T08:59:00'))

      const result = isWithinWorkHours(defaultSettings, mockGetCurrentDate)

      expect(result).toBe(false)
    })

    it('retourne false a 23:00 (nuit)', () => {
      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T23:00:00'))

      const result = isWithinWorkHours(defaultSettings, mockGetCurrentDate)

      expect(result).toBe(false)
    })

    it('retourne false a 03:00 (nuit)', () => {
      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T03:00:00'))

      const result = isWithinWorkHours(defaultSettings, mockGetCurrentDate)

      expect(result).toBe(false)
    })
  })

  describe('horaires personnalises', () => {
    it('gere les horaires du matin tot (06:00 - 14:00)', () => {
      const settings: WorkHoursSettings = {
        enabled: true,
        startTime: '06:00',
        endTime: '14:00',
      }

      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T07:00:00'))
      expect(isWithinWorkHours(settings, mockGetCurrentDate)).toBe(true)

      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T15:00:00'))
      expect(isWithinWorkHours(settings, mockGetCurrentDate)).toBe(false)
    })

    it('gere les horaires du soir (14:00 - 22:00)', () => {
      const settings: WorkHoursSettings = {
        enabled: true,
        startTime: '14:00',
        endTime: '22:00',
      }

      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T20:00:00'))
      expect(isWithinWorkHours(settings, mockGetCurrentDate)).toBe(true)

      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T10:00:00'))
      expect(isWithinWorkHours(settings, mockGetCurrentDate)).toBe(false)
    })

    it('gere les horaires avec minutes (09:30 - 17:45)', () => {
      const settings: WorkHoursSettings = {
        enabled: true,
        startTime: '09:30',
        endTime: '17:45',
      }

      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T09:29:00'))
      expect(isWithinWorkHours(settings, mockGetCurrentDate)).toBe(false)

      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T09:30:00'))
      expect(isWithinWorkHours(settings, mockGetCurrentDate)).toBe(true)

      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T17:44:00'))
      expect(isWithinWorkHours(settings, mockGetCurrentDate)).toBe(true)

      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T17:45:00'))
      expect(isWithinWorkHours(settings, mockGetCurrentDate)).toBe(false)
    })
  })

  describe('horaires de nuit (traversant minuit)', () => {
    const nightSettings: WorkHoursSettings = {
      enabled: true,
      startTime: '22:00',
      endTime: '06:00',
    }

    it('retourne true a 23:00', () => {
      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T23:00:00'))

      const result = isWithinWorkHours(nightSettings, mockGetCurrentDate)

      expect(result).toBe(true)
    })

    it('retourne true a 02:00', () => {
      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T02:00:00'))

      const result = isWithinWorkHours(nightSettings, mockGetCurrentDate)

      expect(result).toBe(true)
    })

    it('retourne true a 22:00 (debut exact)', () => {
      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T22:00:00'))

      const result = isWithinWorkHours(nightSettings, mockGetCurrentDate)

      expect(result).toBe(true)
    })

    it('retourne false a 06:00 (fin exacte)', () => {
      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T06:00:00'))

      const result = isWithinWorkHours(nightSettings, mockGetCurrentDate)

      expect(result).toBe(false)
    })

    it('retourne false a 12:00', () => {
      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T12:00:00'))

      const result = isWithinWorkHours(nightSettings, mockGetCurrentDate)

      expect(result).toBe(false)
    })

    it('retourne false a 10:00', () => {
      mockGetCurrentDate.mockReturnValue(new Date('2026-01-05T10:00:00'))

      const result = isWithinWorkHours(nightSettings, mockGetCurrentDate)

      expect(result).toBe(false)
    })
  })
})

describe('getWorkHoursSettings', () => {
  const mockGetItem = vi.fn<(key: string) => string | null>()

  beforeEach(() => {
    vi.clearAllMocks()
    mockGetItem.mockReturnValue(null)
  })

  it('retourne les valeurs par defaut si rien en localStorage', () => {
    const result = getWorkHoursSettings(mockGetItem)

    expect(result).toEqual({
      enabled: false,
      startTime: '09:00',
      endTime: '18:00',
    })
  })

  it('retourne les valeurs stockees', () => {
    mockGetItem.mockImplementation((key) => {
      const values: Record<string, string> = {
        [KEYS.WORK_HOURS_ONLY]: 'true',
        [KEYS.WORK_HOURS_START]: '08:00',
        [KEYS.WORK_HOURS_END]: '17:00',
      }
      return values[key] ?? null
    })

    const result = getWorkHoursSettings(mockGetItem)

    expect(result).toEqual({
      enabled: true,
      startTime: '08:00',
      endTime: '17:00',
    })
  })

  it('gere les valeurs partielles', () => {
    mockGetItem.mockImplementation((key) => {
      if (key === KEYS.WORK_HOURS_ONLY) return 'true'
      return null
    })

    const result = getWorkHoursSettings(mockGetItem)

    expect(result).toEqual({
      enabled: true,
      startTime: '09:00',
      endTime: '18:00',
    })
  })
})
