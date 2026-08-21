/**
 * ConnectOutlookButton - Button component for Outlook/Microsoft OAuth connection
 *
 * Displays a Microsoft-branded button that initiates the OAuth flow
 * and shows connection status.
 */

import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useOutlookAuth } from '../hooks/useOutlookAuth'
import ConfirmationDialog from './ConfirmationDialog'
import { OAuthTroubleshootingPanel } from './OAuthTroubleshootingPanel'
import './ConnectOutlookButton.css'

interface ConnectOutlookButtonProps {
  accountId: string
  onConnected?: (email: string) => void
  onError?: (error: string) => void
  forceReconnect?: boolean
}

export function ConnectOutlookButton({
  accountId,
  onConnected,
  onError,
  forceReconnect,
}: ConnectOutlookButtonProps) {
  const { t } = useTranslation('settings')
  const {
    status, email, error, isLoading, connect, disconnect,
    popupBlocked, pollingStalled, cancelConnect,
  } = useOutlookAuth(accountId)

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
      onConfirm={() => { disconnect() }}
      onCancel={() => setShowDisconnectConfirm(false)}
      title={t('outlook_disconnect')}
      message={t('outlook_disconnect_confirm')}
      confirmLabel={t('outlook_disconnect_btn')}
      destructive
    />
    <div className="connect-outlook">
      <button
        className={`connect-outlook-btn ${status === 'connected' ? 'connected' : ''}`}
        onClick={handleClick}
        disabled={isLoading || status === 'connecting'}
        aria-label={status === 'connected' ? (forceReconnect ? t('account_reconnect') : t('outlook_disconnect')) : t('outlook_connect')}
      >
        {/* Microsoft logo SVG */}
        <svg
          className="connect-outlook-icon"
          viewBox="0 0 21 21"
          width="18"
          height="18"
          aria-hidden="true"
        >
          <rect x="1" y="1" width="9" height="9" fill="#f25022" />
          <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
          <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
          <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
        </svg>
        <span className="connect-outlook-text">
          {isLoading ? t('loading', { ns: 'common' }) : (
            status === 'disconnected' ? t('outlook_connect') :
            status === 'connecting' ? t('outlook_connecting') :
            status === 'connected' ? (forceReconnect ? t('account_reconnect') : t('outlook_connected')) :
            t('retry', { ns: 'common' })
          )}
        </span>
      </button>

      {status === 'connected' && email && (
        <div className="connect-outlook-status">
          <span className="connect-outlook-email" title={email}>
            {email}
          </span>
          <span className="connect-outlook-badge">{t('outlook_connected')}</span>
        </div>
      )}

      {status === 'error' && error && (
        <div className="connect-outlook-error">
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
