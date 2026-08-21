/**
 * Work Hours Filter for Agentys Notifications
 *
 * Filters notifications based on configurable work hours.
 * Supports overnight schedules (e.g., 22:00 - 06:00).
 *
 * Clés scopées par compte actif (`agentys_work_hours_*:<accountId>`) pour éviter
 * qu'un compte hérite des horaires de travail d'un autre.
 */

import { getCurrentAccountId } from '../lib/currentAccountId'

export interface WorkHoursSettings {
  enabled: boolean
  startTime: string // Format: "HH:MM"
  endTime: string // Format: "HH:MM"
}

export interface ParsedTime {
  hours: number
  minutes: number
}

const STORAGE_KEY_BASES = {
  WORK_HOURS_ONLY: 'agentys_work_hours_only',
  WORK_HOURS_START: 'agentys_work_hours_start',
  WORK_HOURS_END: 'agentys_work_hours_end',
} as const

function scopedKey(base: string): string {
  const accountId = getCurrentAccountId()
  return `${base}:${accountId ?? '__none'}`
}

/** Exposé pour les tests : retourne les clés effectives pour le compte actif. */
export function getWorkHoursStorageKeys() {
  return {
    WORK_HOURS_ONLY: scopedKey(STORAGE_KEY_BASES.WORK_HOURS_ONLY),
    WORK_HOURS_START: scopedKey(STORAGE_KEY_BASES.WORK_HOURS_START),
    WORK_HOURS_END: scopedKey(STORAGE_KEY_BASES.WORK_HOURS_END),
  } as const
}

const DEFAULT_VALUES = {
  ENABLED: false,
  START_TIME: '09:00',
  END_TIME: '18:00',
} as const

export function parseTime(timeStr: string): ParsedTime {
  const [hours, minutes] = timeStr.split(':').map(Number)
  return { hours, minutes }
}

function timeToMinutes(time: ParsedTime): number {
  return time.hours * 60 + time.minutes
}

function currentTimeToMinutes(date: Date): number {
  return date.getHours() * 60 + date.getMinutes()
}

export function isWithinWorkHours(
  settings: WorkHoursSettings,
  getCurrentDate: () => Date = () => new Date()
): boolean {
  if (!settings.enabled) {
    return true
  }

  const start = parseTime(settings.startTime)
  const end = parseTime(settings.endTime)
  const startMinutes = timeToMinutes(start)
  const endMinutes = timeToMinutes(end)
  const currentMinutes = currentTimeToMinutes(getCurrentDate())

  if (startMinutes < endMinutes) {
    return currentMinutes >= startMinutes && currentMinutes < endMinutes
  }

  return currentMinutes >= startMinutes || currentMinutes < endMinutes
}

export function getWorkHoursSettings(
  getItem: (key: string) => string | null = (key) => localStorage.getItem(key)
): WorkHoursSettings {
  const keys = getWorkHoursStorageKeys()
  const enabled = getItem(keys.WORK_HOURS_ONLY) === 'true'
  const startTime = getItem(keys.WORK_HOURS_START) ?? DEFAULT_VALUES.START_TIME
  const endTime = getItem(keys.WORK_HOURS_END) ?? DEFAULT_VALUES.END_TIME

  return { enabled, startTime, endTime }
}

export function shouldNotify(
  getCurrentDate: () => Date = () => new Date(),
  getItem: (key: string) => string | null = (key) => localStorage.getItem(key)
): boolean {
  const settings = getWorkHoursSettings(getItem)
  return isWithinWorkHours(settings, getCurrentDate)
}
