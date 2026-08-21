import { useState, useRef, useCallback, useEffect, memo, type JSX } from 'react'
import { useTranslation } from 'react-i18next'
import { Tooltip } from './Tooltip'
import { ActivityPopover } from './ActivityPopover'
import type { ActivityState, ActivityType } from '../types/activity'
import './ActivityIndicator.css'

interface ActivityIndicatorProps {
  activityState: ActivityState
}

const ICONS: Record<ActivityType | 'done' | 'error', JSX.Element> = {
  sync: (
    <svg aria-hidden="true" className="activity-icon activity-icon--spin" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21.5 2v6h-6" /><path d="M2.5 22v-6h6" />
      <path d="M2.5 11.5a10 10 0 0 1 18.8-4.3" /><path d="M21.5 12.5a10 10 0 0 1-18.8 4.2" />
    </svg>
  ),
  draft: (
    <svg aria-hidden="true" className="activity-icon activity-icon--pulse" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 20h9" /><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
    </svg>
  ),
  classify: (
    <svg aria-hidden="true" className="activity-icon activity-icon--pulse" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2L2 7l10 5 10-5-10-5z" /><path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" />
    </svg>
  ),
  critique: (
    <svg aria-hidden="true" className="activity-icon activity-icon--pulse" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  ),
  learning: (
    <svg aria-hidden="true" className="activity-icon activity-icon--pulse" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2a7 7 0 0 1 7 7c0 2.38-1.19 4.47-3 5.74V17a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2v-2.26C6.19 13.47 5 11.38 5 9a7 7 0 0 1 7-7z" />
      <line x1="9" y1="21" x2="15" y2="21" />
    </svg>
  ),
  cleanup: (
    <svg aria-hidden="true" className="activity-icon activity-icon--pulse" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /><line x1="10" x2="10" y1="11" y2="17" /><line x1="14" x2="14" y1="11" y2="17" />
    </svg>
  ),
  followup: (
    <svg aria-hidden="true" className="activity-icon activity-icon--pulse" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" />
    </svg>
  ),
  done: (
    <svg aria-hidden="true" className="activity-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  ),
  error: (
    <svg aria-hidden="true" className="activity-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
      <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  ),
}

export const ActivityIndicator = memo(function ActivityIndicator({ activityState }: ActivityIndicatorProps) {
  const { t } = useTranslation('common')
  const [showPopover, setShowPopover] = useState(false)
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const { isActive, primaryActivity, justFinished, error, activities } = activityState

  const handleMouseEnter = useCallback(() => {
    if (hideTimerRef.current) {
      clearTimeout(hideTimerRef.current)
      hideTimerRef.current = null
    }
    if (activities.length > 0) {
      setShowPopover(true)
    }
  }, [activities.length])

  const handleMouseLeave = useCallback(() => {
    hideTimerRef.current = setTimeout(() => {
      setShowPopover(false)
    }, 200)
  }, [])

  // Escape closes the popover even though it's hover-driven — once it's open
  // we treat it like any other dropdown for keyboard accessibility.
  useEffect(() => {
    if (!showPopover) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowPopover(false)
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [showPopover])

  // Nothing to show
  if (!isActive && !justFinished && !error) return null

  // Determine what to display
  let icon: JSX.Element
  let label: string
  let statusClass = 'activity-indicator--active'

  if (error) {
    icon = ICONS.error
    label = t('activity_error')
    statusClass = 'activity-indicator--error'
  } else if (justFinished) {
    icon = ICONS.done
    label = t('activity_done')
    statusClass = 'activity-indicator--done'
  } else if (primaryActivity) {
    // Count drafts for aggregated label
    const draftCount = activities.filter(a => a.type === 'draft').length
    if (primaryActivity.type === 'draft' && draftCount > 1) {
      icon = ICONS.draft
      label = t('activity_drafting_count', { count: draftCount })
    } else {
      icon = ICONS[primaryActivity.type]
      label = t(primaryActivity.label)
    }
  } else {
    return null
  }

  const tooltipText = label

  return (
    <div
      ref={containerRef}
      className={`activity-indicator ${statusClass}`}
      role="status"
      aria-live="polite"
      aria-busy={isActive}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <Tooltip content={tooltipText} position="right" delay={300}>
        <div className="activity-indicator__inner">
          <span className="activity-indicator__icon">
            {icon}
          </span>
          <span className="activity-indicator__label sidebar-label">
            {label}
          </span>
        </div>
      </Tooltip>
      {showPopover && activities.length > 0 && (
        <ActivityPopover
          activities={activities}
          onMouseEnter={handleMouseEnter}
          onMouseLeave={handleMouseLeave}
        />
      )}
    </div>
  )
})
