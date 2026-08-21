/**
 * Meeting reminder scheduler.
 *
 * Polls upcoming events every 60s, then on a 30s heartbeat:
 *  - Fires an OS notification at T-leadMinutes (idempotent per event id).
 *  - Surfaces an imminent banner state at T-1min (when enabled).
 *  - Exposes the next upcoming event + minutes-until for passive UI
 *    (sidebar badge, calendar card highlight).
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { apiClient, type CalendarEvent } from '../services/api'
import { getNotificationService } from './../services/notifications'
import { hasFired, markFired } from '../services/meetingReminderStore'
import { extractVideoLink } from '../utils/meetingVideoLink'
import { useMeetingReminderSettings } from './useMeetingReminderSettings'
import { formatHourMinute } from '../utils/dateFormat'
import i18n from '../i18n'

const POLL_INTERVAL_MS = 60_000
const TICK_INTERVAL_MS = 30_000
const LOOKAHEAD_HOURS = 6
const FETCH_LIMIT = 50

/** T-leadMinutes notification window: fire once when minutesUntil ∈ (lead-2, lead]. */
const LEAD_WINDOW_BACKLOG_MIN = 2
/** Imminent banner window: visible when minutesUntil ∈ [-5, 5] (5 min avant à 5 min après le start). */
const IMMINENT_WINDOW_AHEAD_MIN = 5
const IMMINENT_WINDOW_BACK_MIN = 5
/** Buzzer sonore: fenêtre de tir T-1min (fire once when minutesUntil ∈ (-1, 1]). */
const BUZZER_LEAD_MIN = 1
const BUZZER_BACKLOG_MIN = 2

/**
 * Joue un buzzer court via Web Audio API. Pas de fichier audio à charger.
 * Deux notes courtes (A5 → E5) pour un effet "ding-dong" reconnaissable.
 * Silencieux si le navigateur n'autorise pas encore l'audio (avant 1ʳᵉ interaction).
 */
function playMeetingBuzzer(): void {
  try {
    const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Ctx) return
    const ctx = new Ctx()
    const tones: Array<{ freq: number; start: number; duration: number }> = [
      { freq: 880, start: 0,    duration: 0.18 },  // A5
      { freq: 660, start: 0.22, duration: 0.30 },  // E5
    ]
    for (const t of tones) {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = 'sine'
      osc.frequency.value = t.freq
      gain.gain.setValueAtTime(0.0001, ctx.currentTime + t.start)
      gain.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + t.start + 0.02)
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + t.start + t.duration)
      osc.connect(gain)
      gain.connect(ctx.destination)
      osc.start(ctx.currentTime + t.start)
      osc.stop(ctx.currentTime + t.start + t.duration + 0.05)
    }
    setTimeout(() => { void ctx.close() }, 1000)
  } catch {
    // ignore — autoplay policy or unavailable AudioContext
  }
}

interface UseMeetingRemindersResult {
  /** Next upcoming non-cancelled meeting, or null. */
  nextEvent: CalendarEvent | null
  /** Minutes until nextEvent.start (rounded), or null. */
  minutesUntilNext: number | null
  /** Event currently in the imminent window (for the banner). */
  imminentEvent: CalendarEvent | null
  /** Set of event ids whose card should display the "imminent" highlight (T-30min). */
  imminentEventIds: Set<string>
  /** Hide the banner for the rest of this session. */
  dismissImminent: () => void
  /** Snooze the imminent banner — re-shows in `minutes` minutes. */
  snoozeImminent: (minutes: number) => void
}

function formatStartTime(iso: string): string {
  try {
    return formatHourMinute(new Date(iso), i18n.language)
  } catch {
    return ''
  }
}

export function useMeetingReminders(accountId?: string, enabled: boolean = true): UseMeetingRemindersResult {
  const { settings } = useMeetingReminderSettings()
  const [nextEvent, setNextEvent] = useState<CalendarEvent | null>(null)
  const [minutesUntilNext, setMinutesUntilNext] = useState<number | null>(null)
  const [imminentEvent, setImminentEvent] = useState<CalendarEvent | null>(null)
  const [imminentEventIds, setImminentEventIds] = useState<Set<string>>(new Set())

  const eventsRef = useRef<CalendarEvent[]>([])
  const dismissedRef = useRef<Set<string>>(new Set())
  const snoozeUntilRef = useRef<Map<string, number>>(new Map())

  // Polling activé si AU MOINS UNE des 3 surfaces est on (OS notif, banner, buzzer).
  // Plus de master toggle "enabled" séparé — c'est dérivé pour éviter une UX
  // redondante (cf. retour utilisateur 2026-05-06).
  // `enabled` (app-level auth) is ANDed in so /api/calendar/upcoming doesn't
  // 401 on the login page (QA 2026-05-19).
  const anyEnabled = enabled && (settings.imminentBanner || settings.soundBuzzer || settings.leadMinutes > 0)

  // Poll the backend for upcoming events
  useEffect(() => {
    if (!anyEnabled) {
      eventsRef.current = []
      setNextEvent(null)
      setMinutesUntilNext(null)
      setImminentEvent(null)
      setImminentEventIds(new Set())
      return
    }

    let cancelled = false

    async function poll() {
      try {
        const resp = await apiClient.getUpcomingEvents(LOOKAHEAD_HOURS, FETCH_LIMIT, accountId)
        if (cancelled) return
        const events = (resp.events || []).filter(
          ev => ev.status !== 'cancelled' && !ev.isAllDay && ev.start
        )
        eventsRef.current = events
      } catch {
        // Silent: getUpcomingEvents can fail when no calendar account is connected
      }
    }

    poll()
    const id = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [anyEnabled, accountId])

  // Tick: evaluate firing windows + derived state
  useEffect(() => {
    if (!anyEnabled) return

    function tick() {
      const now = Date.now()
      const events = eventsRef.current

      let upcoming: CalendarEvent | null = null
      let upcomingMin = Number.POSITIVE_INFINITY
      const imminentIds = new Set<string>()
      let bannerCandidate: CalendarEvent | null = null

      for (const ev of events) {
        const startMs = new Date(ev.start).getTime()
        if (Number.isNaN(startMs)) continue
        const minutesUntil = (startMs - now) / 60_000

        // Track next upcoming for sidebar badge
        if (minutesUntil > 0 && minutesUntil < upcomingMin) {
          upcoming = ev
          upcomingMin = minutesUntil
        }

        // Highlight set: events within next 30 min that haven't started
        if (minutesUntil > 0 && minutesUntil <= 30) {
          imminentIds.add(ev.id)
        }

        // Lead-time OS notification — skip si lead=0 (utilisateur a choisi "Off"
        // dans le dropdown OS notification).
        const lead = settings.leadMinutes
        if (
          lead > 0 &&
          minutesUntil <= lead &&
          minutesUntil > lead - LEAD_WINDOW_BACKLOG_MIN &&
          !hasFired(ev.id, 'lead')
        ) {
          markFired(ev.id, 'lead')
          const videoLink = extractVideoLink(ev) ?? undefined
          void getNotificationService().notifyMeetingReminder({
            eventId: ev.id,
            title: ev.title || '',
            minutesUntilStart: Math.max(1, Math.round(minutesUntil)),
            startTimeLabel: formatStartTime(ev.start),
            videoLink,
          })
        }

        // Buzzer sonore à T-1min — tier 'buzzer', tire une seule fois.
        // Indépendant du bannière visuel : peut sonner même si imminentBanner=off.
        if (
          settings.soundBuzzer &&
          minutesUntil <= BUZZER_LEAD_MIN &&
          minutesUntil > BUZZER_LEAD_MIN - BUZZER_BACKLOG_MIN &&
          !hasFired(ev.id, 'buzzer')
        ) {
          markFired(ev.id, 'buzzer')
          playMeetingBuzzer()
        }

        // Imminent banner candidate (and optional T-1min OS notif)
        if (
          settings.imminentBanner &&
          minutesUntil <= IMMINENT_WINDOW_AHEAD_MIN &&
          minutesUntil > -IMMINENT_WINDOW_BACK_MIN &&
          !dismissedRef.current.has(ev.id)
        ) {
          const snoozeUntil = snoozeUntilRef.current.get(ev.id)
          if (snoozeUntil && now < snoozeUntil) {
            // skipped while snoozed
          } else {
            // Pick the event closest to start time as the banner candidate
            if (
              !bannerCandidate ||
              Math.abs(minutesUntil) <
                Math.abs((new Date(bannerCandidate.start).getTime() - now) / 60_000)
            ) {
              bannerCandidate = ev
            }
            // Fire imminent OS notif once per event
            if (
              minutesUntil > 0 &&
              minutesUntil <= IMMINENT_WINDOW_AHEAD_MIN &&
              !hasFired(ev.id, 'imminent')
            ) {
              markFired(ev.id, 'imminent')
              void getNotificationService().notifyMeetingReminder({
                eventId: ev.id,
                title: ev.title || '',
                minutesUntilStart: 1,
                startTimeLabel: formatStartTime(ev.start),
                videoLink: extractVideoLink(ev) ?? undefined,
              })
            }
          }
        }
      }

      setNextEvent(upcoming)
      setMinutesUntilNext(upcomingMin === Number.POSITIVE_INFINITY ? null : Math.round(upcomingMin))
      setImminentEventIds(prev => (setsEqual(prev, imminentIds) ? prev : imminentIds))
      setImminentEvent(prev => {
        if (bannerCandidate && (!prev || prev.id !== bannerCandidate.id)) return bannerCandidate
        if (!bannerCandidate && prev) return null
        return prev
      })
    }

    tick()
    const id = setInterval(tick, TICK_INTERVAL_MS)
    return () => clearInterval(id)
  }, [anyEnabled, settings.leadMinutes, settings.imminentBanner, settings.soundBuzzer])

  const dismissImminent = useCallback(() => {
    setImminentEvent(prev => {
      if (prev) dismissedRef.current.add(prev.id)
      return null
    })
  }, [])

  const snoozeImminent = useCallback((minutes: number) => {
    setImminentEvent(prev => {
      if (prev) {
        snoozeUntilRef.current.set(prev.id, Date.now() + minutes * 60_000)
      }
      return null
    })
  }, [])

  return {
    nextEvent,
    minutesUntilNext,
    imminentEvent,
    imminentEventIds,
    dismissImminent,
    snoozeImminent,
  }
}

function setsEqual<T>(a: Set<T>, b: Set<T>): boolean {
  if (a.size !== b.size) return false
  for (const v of a) if (!b.has(v)) return false
  return true
}
