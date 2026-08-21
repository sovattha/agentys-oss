import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import './DeepWorkRecapCard.css'

interface DeepWorkRecapCardProps {
  focusMinutes: number
  emailsProcessed: number
  streakDays: number
  onDismiss: () => void
}

export function DeepWorkRecapCard({ focusMinutes, emailsProcessed, streakDays, onDismiss }: DeepWorkRecapCardProps) {
  const { t } = useTranslation('deepfocus')
  const [visible, setVisible] = useState(true)

  // Auto-dismiss after 30s
  useEffect(() => {
    const timer = setTimeout(() => {
      setVisible(false)
      setTimeout(onDismiss, 300) // wait for fade-out
    }, 30_000)
    return () => clearTimeout(timer)
  }, [onDismiss])

  const handleDismiss = useCallback(() => {
    setVisible(false)
    setTimeout(onDismiss, 300)
  }, [onDismiss])

  const h = Math.floor(focusMinutes / 60)
  const m = focusMinutes % 60
  const timeLabel = h > 0 ? `${h}h${m > 0 ? ` ${m}min` : ''}` : `${m} min`

  return (
    <div className={`dw-recap-card${visible ? '' : ' dw-recap-card--out'}`} onClick={handleDismiss}>
      <div className="dw-recap-icon">
        <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        </svg>
      </div>
      <div className="dw-recap-body">
        <span className="dw-recap-title">{t('dw_session_done')}</span>
        <span className="dw-recap-stats">
          {t('concentration_time_label', { duration: timeLabel })}
          {emailsProcessed > 0 && ` \u00b7 ${emailsProcessed} email${emailsProcessed > 1 ? 's' : ''}`}
          {streakDays > 0 && ` · ${t('dw_streak_days', { count: streakDays })}`}
        </span>
      </div>
    </div>
  )
}
