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

import { useTranslation } from 'react-i18next'
import { useConnectionHealth } from '../hooks/useConnectionHealth'
import './ConnectionBanner.css'

interface ConnectionBannerProps {
  /** Re-probe the backend (wired to useBackendConnection.recheckConnection). */
  onRetry?: () => void
}

/**
 * Y001: a debounced, full-width top strip shown only when the backend has been
 * unreachable past the grace window (see {@link useConnectionHealth}). Replaces
 * the previous behaviour where a backend-down burst produced silent empty views
 * with no user-facing signal. The Retry button re-probes the backend; once the
 * backend answers again, polling hooks self-heal and the banner auto-hides.
 */
export function ConnectionBanner({ onRetry }: ConnectionBannerProps) {
  const { t } = useTranslation('common')
  const { offline, clientOffline, clear } = useConnectionHealth()

  if (!offline && !clientOffline) return null

  const handleRetry = () => {
    clear()
    onRetry?.()
  }

  return (
    <div
      className="connection-banner"
      role="status"
      aria-live="polite"
      data-testid="connection-banner"
    >
      <svg
        className="connection-banner__icon"
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M12 9v4" />
        <path d="M12 17h.01" />
        <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
      </svg>
      {/* Audit connectivité 2026-06-13 : le message client-offline prime —
          quand c'est le réseau de l'utilisateur, inutile d'accuser le backend
          ni de proposer Retry (re-prober sans réseau ne peut pas aboutir). */}
      <span className="connection-banner__text">
        {clientOffline ? t('client_offline') : t('connection_lost')}
      </span>
      {!clientOffline && (
        <button
          type="button"
          className="connection-banner__btn"
          onClick={handleRetry}
          data-testid="connection-banner-retry"
        >
          {t('retry')}
        </button>
      )}
    </div>
  )
}

export default ConnectionBanner
