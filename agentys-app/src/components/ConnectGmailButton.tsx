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

/**
 * ConnectGmailButton - Button component for Gmail OAuth connection
 *
 * Displays a Google-branded button that initiates the OAuth flow
 * and shows connection status.
 */

import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useGmailAuth } from '../hooks/useGmailAuth'
import ConfirmationDialog from './ConfirmationDialog'
import { OAuthTroubleshootingPanel } from './OAuthTroubleshootingPanel'
import './ConnectGmailButton.css'

interface ConnectGmailButtonProps {
  accountId: string
  onConnected?: (email: string) => void
  onError?: (error: string) => void
  forceReconnect?: boolean
}

export function ConnectGmailButton({
  accountId,
  onConnected,
  onError,
  forceReconnect,
}: ConnectGmailButtonProps) {
  const { t } = useTranslation('settings')
  const {
    status, email, error, isLoading, connect, disconnect,
    popupBlocked, pollingStalled, cancelConnect,
  } = useGmailAuth(accountId)

  // Track if callbacks have been called to prevent duplicate calls
  const hasCalledConnected = useRef(false)
  const hasCalledError = useRef(false)

  // Notify parent of connection status changes via useEffect
  useEffect(() => {
    if (status === 'connected' && email && onConnected && !hasCalledConnected.current) {
      hasCalledConnected.current = true
      hasCalledError.current = false
      onConnected(email)
    }
  }, [status, email, onConnected])

  useEffect(() => {
    if (status === 'error' && error && onError && !hasCalledError.current) {
      hasCalledError.current = true
      hasCalledConnected.current = false
      onError(error)
    }
  }, [status, error, onError])

  // Reset refs when disconnected
  useEffect(() => {
    if (status === 'disconnected') {
      hasCalledConnected.current = false
      hasCalledError.current = false
    }
  }, [status])

  const [showDisconnectConfirm, setShowDisconnectConfirm] = useState(false)

  const handleClick = async () => {
    if (status === 'connected' && !forceReconnect) {
      setShowDisconnectConfirm(true)
    } else {
      await connect()
    }
  }

  return (
    <>
    <ConfirmationDialog
      isOpen={showDisconnectConfirm}
      onConfirm={async () => { await disconnect(); setShowDisconnectConfirm(false) }}
      onCancel={() => setShowDisconnectConfirm(false)}
      title={t('gmail_disconnect')}
      message={t('gmail_disconnect_confirm')}
      confirmLabel={t('gmail_disconnect_btn')}
      destructive
    />
    <div className="connect-gmail">
      <button
        className={`connect-gmail-btn ${status === 'connected' ? 'connected' : ''}`}
        onClick={handleClick}
        disabled={isLoading || status === 'connecting'}
        aria-label={status === 'connected' ? (forceReconnect ? t('account_reconnect') : t('gmail_disconnect')) : t('gmail_connect')}
      >
        <svg
          className="connect-gmail-icon"
          viewBox="0 0 24 24"
          width="18"
          height="18"
          aria-hidden="true"
        >
          <path
            fill="#4285F4"
            d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
          />
          <path
            fill="#34A853"
            d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
          />
          <path
            fill="#FBBC05"
            d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
          />
          <path
            fill="#EA4335"
            d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
          />
        </svg>
        <span className="connect-gmail-text">
          {isLoading ? t('loading', { ns: 'common' }) : (
            status === 'disconnected' ? t('gmail_connect') :
            status === 'connecting' ? t('gmail_connecting') :
            status === 'connected' ? (forceReconnect ? t('account_reconnect') : t('gmail_connected')) :
            t('retry', { ns: 'common' })
          )}
        </span>
      </button>

      {status === 'connected' && email && (
        <div className="connect-gmail-status">
          <span className="connect-gmail-email" title={email}>
            {email}
          </span>
          <span className="connect-gmail-badge">{t('gmail_connected')}</span>
        </div>
      )}

      {status === 'error' && error && (
        <div className="connect-gmail-error">
          <span>{error}</span>
        </div>
      )}

      <OAuthTroubleshootingPanel
        status={status}
        popupBlocked={popupBlocked}
        pollingStalled={pollingStalled}
        onCancel={cancelConnect}
        onUseRedirect={() => { cancelConnect(); connect({ method: 'redirect' }) }}
      />
    </div>
    </>
  )
}
