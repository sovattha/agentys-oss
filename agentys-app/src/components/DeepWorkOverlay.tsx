import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { apiClient, type CalendarEvent } from '../services/api'
import { extractVideoLink } from '../utils/meetingVideoLink'
import { formatHourMinute } from '../utils/dateFormat'
import i18n from '../i18n'
import './DeepWorkOverlay.css'

interface DeepWorkOverlayProps {
  slotLabel: string
  nextCheckLabel: string
  progress?: number   // 0–100, from slotProgress
  focusMinutes?: number
  onBypass: () => void
  onSnoozeDay?: () => void
  /** Account ID used to scope the agenda fetch. Undefined → primary account. */
  accountId?: string
}

const AGENDA_POLL_MS = 60_000
const AGENDA_MAX_ITEMS = 4

/** Locale-aware clock time (FR "9h45", EN/ES "09:45"). */
function fmtAgendaTime(iso: string): string {
  try {
    return formatHourMinute(new Date(iso), i18n.language)
  } catch {
    return ''
  }
}

const ARC_R = 80
const ARC_C = 2 * Math.PI * ARC_R  // ~502.65

function parseEndTime(label: string): Date | null {
  const m = label.match(/(\d{1,2})h(\d{2})/)
  if (!m) return null
  const d = new Date()
  d.setHours(parseInt(m[1]), parseInt(m[2]), 0, 0)
  if (d < new Date()) d.setDate(d.getDate() + 1)
  return d
}

/** Splits "5h 25min" → two-line premium display.
 * Minutes are zero-padded upstream (e.g. "3h 05min") to match the app's
 * `15h00`-style time convention; preserve the pad when rendering. */
function DurationDisplay({ duration }: { duration: string }) {
  const m = duration.match(/^(\d+)h\s*(\d{1,2})min$/)
  if (m) {
    return (
      <div className="dw-arc-duration-split">
        <span className="dw-arc-dur-h">{m[1]}<em>h</em></span>
        <span className="dw-arc-dur-m">{m[2].padStart(2, '0')}<em>min</em></span>
      </div>
    )
  }
  // Only minutes: "25min"
  const mOnly = duration.match(/^(\d+)min$/)
  if (mOnly) {
    return (
      <div className="dw-arc-duration-split dw-arc-duration-split--min-only">
        <span className="dw-arc-dur-h">{mOnly[1]}<em>min</em></span>
      </div>
    )
  }
  return <span className="dw-arc-duration">{duration}</span>
}

export function DeepWorkOverlay({ slotLabel, nextCheckLabel, progress, focusMinutes, onBypass, onSnoozeDay, accountId }: DeepWorkOverlayProps) {
  const { t } = useTranslation('deepfocus')
  const [countdown, setCountdown] = useState('')
  const [duration, setDuration] = useState('')
  const [isElapsed, setIsElapsed] = useState(false)
  const [agendaEvents, setAgendaEvents] = useState<CalendarEvent[]>([])

  // Fetch today's events so the user can glance at upcoming meetings while
  // in focus mode. Independent from useMeetingReminders — that hook is gated
  // on notification settings, but the panel should show regardless.
  useEffect(() => {
    let cancelled = false
    async function fetchAgenda() {
      try {
        const resp = await apiClient.getTodayEvents(accountId)
        if (cancelled) return
        setAgendaEvents(resp.events || [])
      } catch {
        // Silent: no calendar account connected, or transient fetch error.
      }
    }
    fetchAgenda()
    const id = setInterval(fetchAgenda, AGENDA_POLL_MS)
    return () => { cancelled = true; clearInterval(id) }
  }, [accountId])

  // Tick every 30s so the "upcoming" filter and minute display stay fresh
  // even when no new fetch happened.
  const [agendaTick, setAgendaTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setAgendaTick(n => n + 1), 30_000)
    return () => clearInterval(id)
  }, [])

  // Esc = bypass — overlay covers the whole inbox so the user has no other
  // keyboard exit. Registered as a window listener (not on the overlay node)
  // because focus may not yet be inside the overlay when it auto-mounts.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onBypass()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onBypass])

  const upcomingToday = useMemo(() => {
    const cutoff = Date.now() - 60_000 // include events that just started
    return agendaEvents
      .filter(ev =>
        ev.status !== 'cancelled' &&
        !ev.isAllDay &&
        ev.start &&
        new Date(ev.start).getTime() > cutoff
      )
      .sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime())
      .slice(0, AGENDA_MAX_ITEMS)
    // agendaTick forces recompute every 30s so events scroll off the list
    // as time passes.

  }, [agendaEvents, agendaTick])

  // ESC to exit focus mode
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onBypass()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onBypass])

  // Live countdown
  useEffect(() => {
    const endDate = parseEndTime(slotLabel)
    if (!endDate) {
      // Try to parse next check label for countdown (e.g. "Emails · 08h00 → 08h30")
      const nextMatch = nextCheckLabel?.match(/(\d{1,2})h(\d{2})/)
      if (nextMatch) {
        const targetDate = new Date()
        targetDate.setHours(parseInt(nextMatch[1]), parseInt(nextMatch[2]), 0, 0)
        if (targetDate <= new Date()) targetDate.setDate(targetDate.getDate() + 1)
        const update = () => {
          const diff = targetDate.getTime() - Date.now()
          if (diff <= 0) { setCountdown(''); setDuration(''); return }
          const h = Math.floor(diff / 3600000)
          const m = Math.floor((diff % 3600000) / 60000)
          const dur = h > 0 ? `${h}h ${String(m).padStart(2, '0')}min` : `${m}min`
          setDuration(dur)
          setIsElapsed(false)
          setCountdown(t('concentration_time_label', { duration: dur }))
        }
        update()
        const timer = setInterval(update, 60000)
        return () => clearInterval(timer)
      }
      // No parseable time anywhere — show nothing
      return
    }
    setIsElapsed(false)
    const update = () => {
      const diff = endDate.getTime() - Date.now()
      if (diff <= 0) { setCountdown(''); return }
      const h = Math.floor(diff / 3600000)
      const m = Math.floor((diff % 3600000) / 60000)
      const dur = h > 0 ? `${h}h ${String(m).padStart(2, '0')}min` : `${m}min`
      setDuration(dur)
      setCountdown(t('concentration_time_label', { duration: dur }))
    }
    update()
    const timer = setInterval(update, 60000)
    return () => clearInterval(timer)
  }, [slotLabel, focusMinutes, nextCheckLabel])

  return (
    <div className="deep-work-overlay" data-testid="deep-work-overlay">
      {upcomingToday.length > 0 && (
        <div className="dw-agenda" data-testid="dw-agenda">
          <div className="dw-agenda-title">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="3" y="4" width="18" height="18" rx="2" />
              <line x1="16" y1="2" x2="16" y2="6" />
              <line x1="8" y1="2" x2="8" y2="6" />
              <line x1="3" y1="10" x2="21" y2="10" />
            </svg>
            <span>{t('dw_next_up')}</span>
          </div>
          <ul className="dw-agenda-list">
            {upcomingToday.map(ev => {
              const videoLink = extractVideoLink(ev)
              return (
                <li key={ev.id} className="dw-agenda-item" data-testid="dw-agenda-item">
                  <span className="dw-agenda-time">{fmtAgendaTime(ev.start)}</span>
                  <span className="dw-agenda-event-title">{ev.title || t('dw_untitled_event')}</span>
                  {videoLink && (
                    <svg className="dw-agenda-video" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-label="video link">
                      <polygon points="23 7 16 12 23 17 23 7" />
                      <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
                    </svg>
                  )}
                </li>
              )
            })}
          </ul>
        </div>
      )}

      <span className="dw-mode-title">{t('title')}</span>

      {/* Progress arc */}
      <div className="dw-arc-container">
        <svg className="dw-arc-svg" viewBox="0 0 200 200" width="200" height="200" role="presentation" aria-hidden="true">
          <defs>
            <filter id="dw-glow-filter" x="-30%" y="-30%" width="160%" height="160%">
              <feGaussianBlur stdDeviation="4" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>
          <circle className="dw-arc-track" cx="100" cy="100" r={ARC_R} />
          {(progress ?? 0) > 0 && (() => {
            const p = (progress ?? 0) / 100
            // Arc starts at 3-o'clock in SVG coords (CSS rotates -90deg → visual top)
            const angle = 2 * Math.PI * p
            const dotX = 100 + ARC_R * Math.cos(angle)
            const dotY = 100 + ARC_R * Math.sin(angle)
            return (
              <>
                <circle
                  className="dw-arc-progress"
                  cx="100" cy="100" r={ARC_R}
                  style={{
                    strokeDasharray: ARC_C,
                    strokeDashoffset: ARC_C * (1 - p),
                  }}
                />
                <circle className="dw-arc-dot" cx={dotX} cy={dotY} r={4} />
              </>
            )
          })()}

        </svg>
        {duration ? (
          <div className="dw-arc-inner" aria-label={countdown}>
            <span className="dw-arc-encore">{isElapsed ? t('dw_already') : t('dw_encore')}</span>
            <DurationDisplay duration={duration} />
          </div>
        ) : (
          // No parseable time in either label → user has burned through every
          // check slot for the day. Fall back to a "done for today" inner so
          // the arc reads as a clear end-of-day state instead of an empty ring.
          <div className="dw-arc-inner dw-arc-inner--done" aria-label={slotLabel}>
            <svg
              className="dw-arc-done-check"
              width="32" height="32" viewBox="0 0 24 24"
              fill="none" stroke="currentColor" strokeWidth="2.5"
              strokeLinecap="round" strokeLinejoin="round"
              aria-hidden="true"
            >
              <polyline points="20 6 9 17 4 12" />
            </svg>
            {slotLabel && <span className="dw-arc-done-label">{slotLabel}</span>}
          </div>
        )}
      </div>


      <div className="dw-separator" aria-hidden="true" />

      {nextCheckLabel && (
        <p className="dw-next-check">{nextCheckLabel}</p>
      )}

      <button
        className="dw-bypass-btn"
        onClick={onBypass}
        data-testid="deep-work-bypass"
        aria-keyshortcuts="Escape"
        title={t('dw_bypass_hint', 'Esc')}
      >
        {t('dw_bypass')}
      </button>

      {onSnoozeDay && (
        <button className="dw-snooze-day-btn" onClick={onSnoozeDay} data-testid="deep-work-snooze-day">
          {t('dw_snooze_day')}
        </button>
      )}
    </div>
  )
}
