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

import { useState, useEffect, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useOAuth } from '../hooks/useOAuth'
import { apiClient } from '../services/api'
import { OAuthTroubleshootingPanel } from './OAuthTroubleshootingPanel'
import './LoginPage.css'


// Triangle logo
const TriangleLogo = ({ size = 80 }: { size?: number }) => (
  <svg aria-hidden="true" width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M16 2.5L1.5 29.5h29z" stroke="#2dd4bf" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" fill="none" opacity="0.7"/>
    <path d="M16 12L8.5 25h15L16 12z" fill="#0d9488"/>
    <path d="M16 16.5L11.5 23.5h9L16 16.5z" fill="var(--surface-primary, #f0f1f5)"/>
  </svg>
)

const GoogleIcon = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
  </svg>
)

const MicrosoftIcon = () => (
  <svg viewBox="0 0 21 21" width="18" height="18" aria-hidden="true">
    <rect x="1" y="1" width="9" height="9" fill="#f25022" />
    <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
    <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
    <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
  </svg>
)

function friendlyError(err: unknown, fallback: string, tErr: (key: string) => string): string {
  if (err instanceof TypeError && err.message.startsWith('Failed to fetch')) {
    return tErr('server_unreachable')
  }
  return err instanceof Error ? err.message : fallback
}

interface LoginPageProps {
  onOAuthLogin: (accountId: string, email: string, token?: string) => Promise<void>
}

export function LoginPage({ onOAuthLogin }: LoginPageProps) {
  const { t } = useTranslation('errors')
  const [error, setError] = useState<string | null>(null)
  const [oauthLoading, setOauthLoading] = useState<'gmail' | 'outlook' | null>(null)
  const [legalAccepted, setLegalAccepted] = useState(false)

  const gmail = useOAuth('gmail', undefined)
  const outlook = useOAuth('outlook', undefined)

  const oauthLoginCalledRef = useRef(false)
  // Only show OAuth errors after the user has clicked a button
  const userInteractedRef = useRef(false)

  // Clear any stale error on mount (e.g. from HMR state preservation)
  useEffect(() => { setError(null) }, [])

  // document.title is mutated by other routes (inbox sets "Boîte de réception").
  // Reset it on the login page so SEO, the browser tab, and screenshots show
  // the right thing. Restore the inbox title on unmount so the post-login
  // route picks up where it left off without flicker.
  useEffect(() => {
    const previous = document.title
    document.title = `${t('login_title')} — ${t('login_subtitle')}`
    return () => { document.title = previous }
  }, [t])

  useEffect(() => {
    if (oauthLoginCalledRef.current) return
    if (gmail.status === 'connected' && gmail.email) {
      oauthLoginCalledRef.current = true
      setOauthLoading('gmail')
      onOAuthLogin(gmail.accountId!, gmail.email, gmail.token ?? undefined).catch(err => {
        setError(friendlyError(err, t('oauth_failed'), t))
        setOauthLoading(null)
        oauthLoginCalledRef.current = false
      })
    }
  }, [gmail.status, gmail.email, gmail.accountId, gmail.token, onOAuthLogin])

  useEffect(() => {
    if (oauthLoginCalledRef.current) return
    if (outlook.status === 'connected' && outlook.email) {
      oauthLoginCalledRef.current = true
      setOauthLoading('outlook')
      onOAuthLogin(outlook.accountId!, outlook.email, outlook.token ?? undefined).catch(err => {
        setError(friendlyError(err, t('oauth_failed'), t))
        setOauthLoading(null)
        oauthLoginCalledRef.current = false
      })
    }
  }, [outlook.status, outlook.email, outlook.accountId, outlook.token, onOAuthLogin])

  useEffect(() => {
    if (gmail.status === 'error' && gmail.error && userInteractedRef.current) {
      setError(gmail.error)
      setOauthLoading(null)
    }
  }, [gmail.status, gmail.error])

  useEffect(() => {
    if (outlook.status === 'error' && outlook.error && userInteractedRef.current) {
      setError(outlook.error)
      setOauthLoading(null)
    }
  }, [outlook.status, outlook.error])

  const handleGoogleLogin = useCallback(async () => {
    if (!legalAccepted) {
      setError(t('login_legal_required'))
      return
    }
    userInteractedRef.current = true
    setError(null)
    setOauthLoading('gmail')
    try {
      await apiClient.recordLegalConsent('gmail')
    } catch (err) {
      setError(friendlyError(err, t('login_consent_record_failed'), t))
      setOauthLoading(null)
      return
    }
    try {
      await gmail.connect()
    } catch (err) {
      setError(friendlyError(err, t('google_failed'), t))
      setOauthLoading(null)
    }
  }, [gmail, legalAccepted, t])

  const handleOutlookLogin = useCallback(async () => {
    if (!legalAccepted) {
      setError(t('login_legal_required'))
      return
    }
    userInteractedRef.current = true
    setError(null)
    setOauthLoading('outlook')
    try {
      await apiClient.recordLegalConsent('outlook')
    } catch (err) {
      setError(friendlyError(err, t('login_consent_record_failed'), t))
      setOauthLoading(null)
      return
    }
    try {
      await outlook.connect()
    } catch (err) {
      setError(friendlyError(err, t('outlook_failed'), t))
      setOauthLoading(null)
    }
  }, [legalAccepted, outlook, t])

  const isOauthBusy = oauthLoading !== null || gmail.status === 'connecting' || outlook.status === 'connecting'

  return (
    <main className="login-page" aria-labelledby="login-heading">
      <div className="login-card">
        <div className="login-logo">
          <TriangleLogo />
        </div>
        <h1 id="login-heading" className="login-title">{t('login_title')}</h1>
        <p className="login-subtitle">{t('login_subtitle')}</p>

        <label className="login-consent" htmlFor="login-legal-consent">
          <input
            id="login-legal-consent"
            type="checkbox"
            checked={legalAccepted}
            onChange={(event) => {
              setLegalAccepted(event.currentTarget.checked)
              if (event.currentTarget.checked && error === t('login_legal_required')) {
                setError(null)
              }
            }}
          />
          <span>
            {t('login_legal_accept')}{' '}
            <a href="https://www.agentys.io/terms" target="_blank" rel="noopener noreferrer">
              {t('login_legal_terms')}
            </a>{' '}
            {t('login_legal_and')}{' '}
            <a href="https://www.agentys.io/privacy" target="_blank" rel="noopener noreferrer">
              {t('login_legal_privacy')}
            </a>
            {t('login_legal_suffix')}
          </span>
        </label>

        <div className="login-oauth-grid" role="group" aria-label={t('login_choose_account')}>
          <button
            className="login-oauth-card"
            onClick={handleGoogleLogin}
            disabled={isOauthBusy || !legalAccepted}
            type="button"
            aria-label={t('login_google')}
            aria-busy={oauthLoading === 'gmail'}
          >
            {/* QA 2026-05-19 — Bug #1: spinner gated by oauthLoading (set only
                by the user-initiated click handlers). The underlying hook can
                briefly report 'connecting' on first mount as it checks for an
                existing session, which produced a spinner where the Microsoft
                logo should be on a fresh visitor's first paint. */}
            {oauthLoading === 'gmail' ? (
              <span className="login-btn-spinner login-oauth-spinner" aria-hidden="true" />
            ) : (
              <span className="login-oauth-icon" aria-hidden="true"><GoogleIcon /></span>
            )}
            <span className="login-oauth-label">Gmail</span>
          </button>
          <button
            className="login-oauth-card"
            onClick={handleOutlookLogin}
            disabled={isOauthBusy || !legalAccepted}
            type="button"
            aria-label={t('login_outlook')}
            aria-busy={oauthLoading === 'outlook'}
          >
            {oauthLoading === 'outlook' ? (
              <span className="login-btn-spinner login-oauth-spinner" aria-hidden="true" />
            ) : (
              <span className="login-oauth-icon" aria-hidden="true"><MicrosoftIcon /></span>
            )}
            <span className="login-oauth-label">Outlook</span>
          </button>
        </div>

        {error && <div id="login-error" className="login-error" role="alert">{error}</div>}

        {/* Surface popup-blocker / stalled-polling guidance for whichever
            provider is currently mid-connect. Only one is ever in 'connecting'
            at a time (the other button is disabled via isOauthBusy). */}
        {gmail.status === 'connecting' && (
          <OAuthTroubleshootingPanel
            status={gmail.status}
            popupBlocked={gmail.popupBlocked}
            pollingStalled={gmail.pollingStalled}
            onCancel={() => { gmail.cancelConnect(); setOauthLoading(null) }}
            onUseRedirect={() => { gmail.cancelConnect(); gmail.connect({ method: 'redirect' }) }}
          />
        )}
        {outlook.status === 'connecting' && (
          <OAuthTroubleshootingPanel
            status={outlook.status}
            popupBlocked={outlook.popupBlocked}
            pollingStalled={outlook.pollingStalled}
            onCancel={() => { outlook.cancelConnect(); setOauthLoading(null) }}
            onUseRedirect={() => { outlook.cancelConnect(); outlook.connect({ method: 'redirect' }) }}
          />
        )}
      </div>
    </main>
  )
}
