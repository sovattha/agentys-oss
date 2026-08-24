/*
 * Agentys — voice-first email assistant.
 * Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version. See the LICENSE file for details.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

import { useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useAnimatedUnmount } from '../hooks/useAnimatedUnmount'
import { useMeetingReminderSettings } from '../hooks/useMeetingReminderSettings'
import { ChevronLeftIcon, CloseIcon } from './icons/ActionIcons'
import './MeetingRemindersPanel.css'

interface MeetingRemindersPanelProps {
  isOpen: boolean
  onClose: () => void
  onBack?: () => void
}

export function MeetingRemindersPanel({ isOpen, onClose, onBack }: MeetingRemindersPanelProps) {
  const { t } = useTranslation('settings')
  const { t: tc } = useTranslation('common')
  const { shouldRender, isClosing, handleClose } = useAnimatedUnmount(isOpen, onClose)
  const {
    settings,
    setImminentBanner,
    setSoundBuzzer,
  } = useMeetingReminderSettings()

  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        handleClose()
      }
    },
    [handleClose]
  )

  useEffect(() => {
    if (!isOpen) return
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, handleKeyDown])

  if (!shouldRender) return null

  return (
    <div className="meeting-reminders-overlay" onClick={handleClose}>
      <div
        className={`meeting-reminders-panel${isClosing ? ' closing' : ''}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="meeting-reminders-header">
          <div className="meeting-reminders-header-left">
            {onBack && (
              <button
                type="button"
                className="meeting-reminders-back"
                onClick={onBack}
                aria-label={tc('back')}
                title={tc('back')}
              >
                <ChevronLeftIcon size={20} />
              </button>
            )}
            <h2>{t('meeting_reminders_title')}</h2>
          </div>
          <button
            type="button"
            className="meeting-reminders-close"
            onClick={handleClose}
            aria-label={tc('close')}
          >
            <CloseIcon />
          </button>
        </div>

        <div className="meeting-reminders-content">
          <p className="meeting-reminders-intro">{t('meeting_reminders_hint')}</p>
          <div className="meeting-reminders-cards">

            {/* Surface 1 — In-app banner */}
            <div className={`mr-card${settings.imminentBanner ? ' is-on' : ''}`}>
              <div className="mr-card-icon" aria-hidden="true">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="4" width="18" height="14" rx="2" />
                  <path d="M8 22h8" />
                  <path d="M12 18v4" />
                </svg>
              </div>
              <div className="mr-card-body">
                <div className="mr-card-head">
                  <h3 className="mr-card-title">{t('meeting_reminders_imminent')}</h3>
                  <label className="mr-toggle">
                    <input
                      type="checkbox"
                      checked={settings.imminentBanner}
                      onChange={(e) => setImminentBanner(e.target.checked)}
                      aria-label={t('meeting_reminders_imminent_aria')}
                      data-testid="meeting-reminders-imminent"
                    />
                    <span className="mr-toggle-track" />
                  </label>
                </div>
                <p className="mr-card-hint">{t('meeting_reminders_imminent_hint')}</p>
              </div>
            </div>

            {/* Surface 2 — Sound buzzer */}
            <div className={`mr-card${settings.soundBuzzer ? ' is-on' : ''}`}>
              <div className="mr-card-icon" aria-hidden="true">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M11 5 6 9H2v6h4l5 4V5z" />
                  <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
                  <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
                </svg>
              </div>
              <div className="mr-card-body">
                <div className="mr-card-head">
                  <h3 className="mr-card-title">{t('meeting_reminders_sound_buzzer')}</h3>
                  <label className="mr-toggle">
                    <input
                      type="checkbox"
                      checked={settings.soundBuzzer}
                      onChange={(e) => setSoundBuzzer(e.target.checked)}
                      aria-label={t('meeting_reminders_sound_buzzer_aria')}
                      data-testid="meeting-reminders-sound-buzzer"
                    />
                    <span className="mr-toggle-track" />
                  </label>
                </div>
                <p className="mr-card-hint">{t('meeting_reminders_sound_buzzer_hint')}</p>
              </div>
            </div>

          </div>
        </div>
      </div>
    </div>
  )
}
