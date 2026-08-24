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

import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { monthlySummaryService } from '../services/subscription'
import { handleKeyboardClick } from '@/lib/utils'
import './RecapBanner.css'

interface RecapBannerProps {
  month: string
  onOpenRecap: () => void
  onDismiss: () => void
}

export function RecapBanner({ month, onOpenRecap, onDismiss }: RecapBannerProps) {
  const { t } = useTranslation('common')
  const monthLabel = monthlySummaryService.getMonthLabel(month)

  const handleDismiss = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    onDismiss()
  }, [onDismiss])

  return (
    <div className="recap-banner" onClick={onOpenRecap} onKeyDown={handleKeyboardClick(onOpenRecap)} role="button" tabIndex={0} aria-live="polite">
      <span className="recap-banner-text">
        {t('recap_banner_ready', { month: monthLabel })}{' '}
        <span className="recap-banner-cta">{t('recap_banner_cta')}</span>
      </span>
      <button
        className="recap-banner-dismiss"
        onClick={handleDismiss}
        aria-label={t('dismiss_banner')}
      >
        <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 6 6 18"/><path d="m6 6 12 12"/>
        </svg>
      </button>
    </div>
  )
}
