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

/* eslint-disable react-refresh/only-export-components */
import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { referralService, usageStatsService } from '../services/subscription'
import { copyToClipboard } from '../utils/clipboard'
import './ReferralPanel.css'

/**
 * Hook for referral and usage stats data (Story 9-7)
 */
export function useReferral() {
  const stats = useMemo(() => referralService.getReferralStats(), [])
  const monthlyStats = useMemo(() => usageStatsService.getMonthlyStats(), [])
  const timeSavedFormatted = useMemo(() => usageStatsService.getTimeSavedFormatted(), [])

  return {
    stats,
    monthlyStats,
    timeSavedFormatted,
    hasReferral: stats !== null,
  }
}

/**
 * ReferralPanel Component (Story 9-7)
 * Displays referral link, monthly stats, and share options
 *
 * ACs covered:
 * - AC1: Unique link per user
 * - AC2: "Copy link" button with feedback
 * - AC3: Stats: time saved this month, emails processed
 * - AC4: Customizable share message
 */
export function ReferralPanel() {
  const { t } = useTranslation('common')
  const { stats, monthlyStats, timeSavedFormatted, hasReferral } = useReferral()
  const [linkCopied, setLinkCopied] = useState(false)
  const [messageCopied, setMessageCopied] = useState(false)
  const [shareMessage, setShareMessage] = useState(
    t('referral_share_message', { timeSaved: timeSavedFormatted })
  )

  // Don't render if no referral data (user not signed up)
  if (!hasReferral || !stats) {
    return null
  }

  /**
   * Copy referral link to clipboard (AC2)
   */
  // F-11 / Site 8 (audit 2026-06-11) : copyToClipboard ne throw jamais — il
  // retourne false quand les deux stratégies échouent. Les anciens try/catch ne
  // captaient donc rien : échec 100 % silencieux, l'utilisateur collait du vide.
  const notifyCopyFailed = () => {
    window.dispatchEvent(new CustomEvent('agentys:toast', {
      detail: { message: t('toasts.copy_failed'), type: 'warning' },
    }))
  }

  const handleCopyLink = async () => {
    const ok = await copyToClipboard(stats.link)
    if (ok) {
      setLinkCopied(true)
      setTimeout(() => setLinkCopied(false), 2000)
    } else {
      notifyCopyFailed()
    }
  }

  /**
   * Copy share message with link to clipboard (AC4)
   */
  const handleCopyMessage = async () => {
    const fullMessage = `${shareMessage}\n${stats.link}`
    const ok = await copyToClipboard(fullMessage)
    if (ok) {
      setMessageCopied(true)
      setTimeout(() => setMessageCopied(false), 2000)
    } else {
      notifyCopyFailed()
    }
  }

  return (
    <div className="referral-panel" data-testid="referral-panel">
      <h3 className="referral-panel-title">{t('refer_friends')}</h3>

      {/* Referral Link Section (AC1, AC2) */}
      <div className="referral-link-section">
        <label className="referral-label">{t('your_referral_link')}</label>
        <div className="referral-link-container">
          <input
            type="text"
            className="referral-link-input"
            value={stats.link}
            readOnly
            data-testid="referral-link-input"
          />
          <button
            className={`referral-copy-button ${linkCopied ? 'copied' : ''}`}
            onClick={handleCopyLink}
            data-testid="copy-link-button"
          >
            {linkCopied ? t('copied') : t('copy_link')}
          </button>
        </div>
      </div>

      {/* Monthly Stats Section (AC3) */}
      <div className="referral-stats-section">
        <h4 className="referral-stats-title">{t('your_stats_this_month')}</h4>
        <ul className="referral-stats-list">
          <li data-testid="stat-emails">
            <span className="stat-value">{monthlyStats.emailsProcessed}</span> {t('emails_processed')}
          </li>
          <li data-testid="stat-drafts">
            <span className="stat-value">{monthlyStats.draftsGenerated}</span> {t('drafts_generated')}
          </li>
          <li data-testid="stat-time">
            <span className="stat-value">~{timeSavedFormatted}</span> {t('time_saved_unit')}
          </li>
        </ul>
      </div>

      {/* Share Message Section (AC4) */}
      <div className="referral-message-section">
        <label className="referral-label">{t('share_message_label')}</label>
        <textarea
          className="referral-message-textarea"
          value={shareMessage}
          onChange={(e) => setShareMessage(e.target.value)}
          rows={4}
          data-testid="share-message-textarea"
        />
        <button
          className={`referral-copy-message-button ${messageCopied ? 'copied' : ''}`}
          onClick={handleCopyMessage}
          data-testid="copy-message-button"
        >
          {messageCopied ? t('copied') : t('copy_message_with_link')}
        </button>
      </div>

      {/* Referral Count (AC5) */}
      {stats.referralsCount > 0 && (
        <div className="referral-count-section" data-testid="referral-count">
          {t('person_registered', { count: stats.referralsCount })}
        </div>
      )}
    </div>
  )
}
