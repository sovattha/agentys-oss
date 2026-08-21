import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import type { CalendarEvent } from '../services/api'
import { extractVideoLink } from '../utils/meetingVideoLink'
import { CloseIcon } from './icons/ActionIcons'
import { formatHourMinute } from '../utils/dateFormat'
import i18n from '../i18n'
import './MeetingImminentBanner.css'

/** Locale-aware clock time (FR "9h45", EN/ES "09:45"). */
function fmtTime(iso: string): string {
  try {
    return formatHourMinute(new Date(iso), i18n.language)
  } catch {
    return ''
  }
}

interface MeetingImminentBannerProps {
  event: CalendarEvent
  onDismiss: () => void
  onSnooze: (minutes: number) => void
  /** Auto-dismiss after this many ms (default 60s). Pass 0 to disable. */
  autoDismissMs?: number
}

export function MeetingImminentBanner({
  event,
  onDismiss,
  onSnooze,
  autoDismissMs = 60_000,
}: MeetingImminentBannerProps) {
  const { t } = useTranslation('calendar')
  const videoLink = extractVideoLink(event)

  useEffect(() => {
    if (autoDismissMs <= 0) return
    const id = setTimeout(onDismiss, autoDismissMs)
    return () => clearTimeout(id)
  }, [event.id, autoDismissMs, onDismiss])

  function handleJoin() {
    if (!videoLink) return
    window.open(videoLink, '_blank', 'noopener,noreferrer')
    onDismiss()
  }

  return (
    <div
      className="meeting-imminent-banner"
      role="alert"
      aria-live="assertive"
      data-testid="meeting-imminent-banner"
    >
      <div className="meeting-imminent-banner__icon" aria-hidden="true">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
      </div>
      <div className="meeting-imminent-banner__text">
        <strong>{t('reminder_starting_now', { title: event.title || t('default_event_title') })}</strong>
        <span className="meeting-imminent-banner__time">
          {fmtTime(event.start)} – {fmtTime(event.end)}
        </span>
        {videoLink && (
          <a
            className="meeting-imminent-banner__link"
            href={videoLink}
            target="_blank"
            rel="noopener noreferrer"
            onClick={onDismiss}
            data-testid="meeting-imminent-link"
          >
            {videoLink.replace(/^https?:\/\//, '').replace(/\/.*$/, '')}
          </a>
        )}
      </div>
      <div className="meeting-imminent-banner__actions">
        {videoLink && (
          <button
            type="button"
            className="meeting-imminent-banner__btn meeting-imminent-banner__btn--primary"
            onClick={handleJoin}
            data-testid="meeting-imminent-join"
          >
            {t('reminder_action_join')}
          </button>
        )}
        <button
          type="button"
          className="meeting-imminent-banner__btn"
          onClick={() => onSnooze(5)}
          data-testid="meeting-imminent-snooze"
        >
          {t('reminder_action_snooze_5')}
        </button>
        <button
          type="button"
          className="meeting-imminent-banner__btn meeting-imminent-banner__btn--ghost"
          onClick={onDismiss}
          aria-label={t('reminder_action_dismiss')}
          data-testid="meeting-imminent-dismiss"
        >
          <CloseIcon size={14} />
        </button>
      </div>
    </div>
  )
}
