/**
 * Persisted settings for meeting reminders (localStorage).
 * Three knobs: master on/off, lead time before fire, optional T-1min imminent banner.
 */
import { useCallback, useEffect, useState } from 'react'

const STORAGE_KEYS = {
  ENABLED: 'agentys_meeting_reminders_enabled',
  LEAD_MINUTES: 'agentys_meeting_reminders_lead_minutes',
  IMMINENT_BANNER: 'agentys_meeting_reminders_imminent_banner',
  SOUND_BUZZER: 'agentys_meeting_reminders_sound_buzzer',
} as const

/** 0 = OS notification désactivée. Les autres valeurs = délai en minutes avant l'event. */
export const LEAD_TIME_OPTIONS = [0, 1, 5, 10, 15, 30, 60] as const
export type LeadTimeMinutes = (typeof LEAD_TIME_OPTIONS)[number]

export interface MeetingReminderSettings {
  enabled: boolean
  leadMinutes: LeadTimeMinutes
  imminentBanner: boolean
  /** Joue un buzzer sonore à T-1 min en plus du bannière visuel. */
  soundBuzzer: boolean
}

const DEFAULTS: MeetingReminderSettings = {
  enabled: true,
  leadMinutes: 0,
  imminentBanner: true,
  soundBuzzer: false,
}

function readBool(key: string, fallback: boolean): boolean {
  try {
    const v = localStorage.getItem(key)
    if (v === null) return fallback
    return v === 'true'
  } catch {
    return fallback
  }
}

function readLeadMinutes(): LeadTimeMinutes {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.LEAD_MINUTES)
    const n = raw === null ? NaN : parseInt(raw, 10)
    if (LEAD_TIME_OPTIONS.includes(n as LeadTimeMinutes)) {
      return n as LeadTimeMinutes
    }
  } catch {
    // ignore
  }
  return DEFAULTS.leadMinutes
}

export function loadMeetingReminderSettings(): MeetingReminderSettings {
  return {
    enabled: readBool(STORAGE_KEYS.ENABLED, DEFAULTS.enabled),
    leadMinutes: readLeadMinutes(),
    imminentBanner: readBool(STORAGE_KEYS.IMMINENT_BANNER, DEFAULTS.imminentBanner),
    soundBuzzer: readBool(STORAGE_KEYS.SOUND_BUZZER, DEFAULTS.soundBuzzer),
  }
}

const SETTINGS_EVENT = 'agentys-meeting-reminders-settings'

export function useMeetingReminderSettings() {
  const [settings, setSettings] = useState<MeetingReminderSettings>(() => loadMeetingReminderSettings())

  useEffect(() => {
    const handler = () => setSettings(loadMeetingReminderSettings())
    window.addEventListener(SETTINGS_EVENT, handler)
    window.addEventListener('storage', handler)
    return () => {
      window.removeEventListener(SETTINGS_EVENT, handler)
      window.removeEventListener('storage', handler)
    }
  }, [])

  const update = useCallback((patch: Partial<MeetingReminderSettings>) => {
    setSettings(prev => {
      const next = { ...prev, ...patch }
      try {
        localStorage.setItem(STORAGE_KEYS.ENABLED, String(next.enabled))
        localStorage.setItem(STORAGE_KEYS.LEAD_MINUTES, String(next.leadMinutes))
        localStorage.setItem(STORAGE_KEYS.IMMINENT_BANNER, String(next.imminentBanner))
        localStorage.setItem(STORAGE_KEYS.SOUND_BUZZER, String(next.soundBuzzer))
        window.dispatchEvent(new Event(SETTINGS_EVENT))
      } catch {
        // ignore
      }
      return next
    })
  }, [])

  return {
    settings,
    setEnabled: (v: boolean) => update({ enabled: v }),
    setLeadMinutes: (v: LeadTimeMinutes) => update({ leadMinutes: v }),
    setImminentBanner: (v: boolean) => update({ imminentBanner: v }),
    setSoundBuzzer: (v: boolean) => update({ soundBuzzer: v }),
  }
}
