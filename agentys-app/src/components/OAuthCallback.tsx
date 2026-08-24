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
 * OAuthCallback - Handles OAuth redirect callback
 *
 * This component is displayed when the OAuth provider (Google/Microsoft)
 * redirects back to the app after consent.
 *
 * The backend has already exchanged the code for tokens.
 * This component just:
 * 1. Reads the result from query parameters
 * 2. Notifies the parent window (if opened as popup)
 * 3. Displays success/error to the user
 */

import { useEffect, useState, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { API_URL } from '../config'
import { setStoredToken } from '../services/authToken'
import { attemptStaleBundleRecovery } from '../services/oauthRecovery'
import { humanizeOAuthError } from '../services/oauthErrors'
import { buildGoogleAuthUrl, buildMicrosoftAuthUrl, generatePKCE } from '../services/oauth'
import {
  fetchOAuthReadiness,
  hasOAuthPermissionGap,
  oauthMissingPermissionLabels,
  type OAuthReadinessProvider,
} from '../services/oauthReadiness'
import './OAuthCallback.css'

export interface OAuthAuthData {
  email: string
  token: string
  accountId: string
}

interface OAuthCallbackProps {
  onComplete: (authData?: OAuthAuthData) => void
  initialSearch?: string
}

type CallbackStatus = 'processing' | 'success' | 'error' | 'repair'

interface OAuthRepairDetails {
  provider: OAuthReadinessProvider
  email: string
  missingLabels: string[]
  repairUrl: string | null
}

/**
 * Fallback: request a JWT from the backend when the OAuth callback
 * didn't return one (e.g. backend JWT generation failed silently).
 * Without a JWT the auth state can't be established and the user
 * loops back to the login page.
 */
async function requestJwtFallback(accountId: string, email: string): Promise<string | null> {
  try {
    const res = await fetch(`${API_URL}/api/auth/oauth-login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId, email }),
    })
    if (!res.ok) return null
    const data = await res.json()
    return data.access_token || null
  } catch {
    return null
  }
}

export function OAuthCallback({ onComplete, initialSearch }: OAuthCallbackProps) {
  const { t } = useTranslation('errors')
  // The callback effect runs once (guarded by hasProcessed) and sets messages
  // imperatively; read t through a ref so we keep the [onComplete] dep array
  // and still resolve in the current language.
  const tRef = useRef(t)
  tRef.current = t
  const [status, setStatus] = useState<CallbackStatus>('processing')
  const [message, setMessage] = useState(() => t('oauth_ui_finalizing'))
  const [countdown, setCountdown] = useState(5)
  const [closeFailed, setCloseFailed] = useState(false)
  const [repairDetails, setRepairDetails] = useState<OAuthRepairDetails | null>(null)
  const hasProcessed = useRef(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const authDataRef = useRef<OAuthAuthData | null>(null)

  const restartOAuth = async (provider: OAuthReadinessProvider) => {
    try {
      setStatus('processing')
      setRepairDetails(null)
      setMessage(tRef.current('oauth_ui_repair_starting'))

      const configRes = await fetch(`${API_URL}/api/oauth/config`)
      if (!configRes.ok) {
        throw new Error('oauth_config_unavailable')
      }
      const config = await configRes.json()
      const providerConfig = config[provider] || {}
      const clientId = providerConfig.client_id || providerConfig.clientId
      if (!clientId || providerConfig.configured === false) {
        throw new Error('oauth_provider_unconfigured')
      }

      const envRedirectUri =
        provider === 'gmail'
          ? import.meta.env.VITE_GOOGLE_REDIRECT_URI
          : import.meta.env.VITE_MICROSOFT_REDIRECT_URI
      const fallbackRedirectUri =
        provider === 'gmail'
          ? `${API_URL}/api/oauth/gmail/callback`
          : `${API_URL}/api/oauth/outlook/callback`
      const redirectUri = envRedirectUri || providerConfig.redirect_uri || providerConfig.redirectUri || fallbackRedirectUri
      const pkce = await generatePKCE()

      localStorage.setItem(`pkce_verifier_${pkce.state}`, pkce.codeVerifier)
      localStorage.setItem(`pkce_provider_${pkce.state}`, provider)
      localStorage.setItem(`pkce_redirect_uri_${pkce.state}`, redirectUri)

      try {
        await fetch(`${API_URL}/api/oauth/pkce/store`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            state: pkce.state,
            code_verifier: pkce.codeVerifier,
          }),
        })
      } catch {
        // localStorage PKCE is still enough for the same-tab repair flow.
      }

      window.location.href = provider === 'outlook'
        ? buildMicrosoftAuthUrl(clientId, pkce, redirectUri)
        : buildGoogleAuthUrl(clientId, pkce, redirectUri)
    } catch {
      setStatus('error')
      setMessage(tRef.current('oauth_ui_repair_config_error'))
      setTimeout(onComplete, 8000)
    }
  }

  useEffect(() => {
    // Prevent double execution (React StrictMode)
    if (hasProcessed.current) return
    hasProcessed.current = true

    // Shared countdown completion logic — handles close/redirect for all flows
    const handleCountdownDone = () => {
      if (intervalRef.current) clearInterval(intervalRef.current)

      const canClose = !!(window.opener && !window.opener.closed)

      setCountdown(0)

      if (canClose) {
        // Popup flow: try to close the window
        try { window.close() } catch { /* ignored */ }
        // Detect if window.close() failed (e.g. mobile Safari blocks it)
        setTimeout(() => {
          // If we're still here, close didn't work
          setCloseFailed(true)
          setMessage(tRef.current('oauth_ui_close_tab'))
        }, 500)
      } else {
        // Pass auth data so the app updates React auth state directly
        // (eliminates dependency on full page reload for same-tab/mobile flow)
        try { onComplete(authDataRef.current ?? undefined) } catch { /* ignored */ }
        // Same-tab / mobile redirect flow: redirect immediately
        setMessage(tRef.current('oauth_ui_redirecting'))
      }

      // Fallback redirect — only needed when auth state couldn't be updated directly.
      // If authData was passed to onComplete, loginWithOAuth already set isAuthenticated=true
      // and a full page reload would be wasteful (and disruptive on mobile).
      // If window.close() fails in popup mode, keep this page open with the
      // manual return button instead of navigating away before the user can act.
      if (!canClose && !authDataRef.current) {
        setTimeout(() => {
          window.location.replace('/')
        }, 200)
      }
    }

    const handleCallback = async () => {
      const params = new URLSearchParams(initialSearch ?? window.location.search)
      const state = params.get('state')
      // Detect provider: localStorage (stored during OAuth initiation) is the
      // authoritative binding — it was written by useOAuth.connect() right
      // before opening the popup and is keyed by the same `state` we just
      // received back. The URL `provider=` query param is informational only
      // (for backend logging) and must not override what we stored locally.
      const storedProvider = state ? localStorage.getItem(`pkce_provider_${state}`) : null
      const urlProvider = params.get('provider')
      // Reject mismatch: a popup that was opened for Gmail must not return a
      // state the user later associated with Outlook (or vice versa). This
      // also catches phishing flows where an attacker forges `provider=gmail`
      // in a URL that has no matching localStorage entry.
      if (state && storedProvider && urlProvider && urlProvider !== storedProvider) {
        const errMsg = tRef.current('oauth_ui_state_mismatch')
        setStatus('error')
        setMessage(errMsg)
        setTimeout(onComplete, 5000)
        return
      }
      const provider = storedProvider || urlProvider || 'gmail'
      if (state && storedProvider) {
        localStorage.removeItem(`pkce_provider_${state}`)
      }
      const error = params.get('error')
      const errorDescription = params.get('error_description')
      // #557: backend redirect-callback path appends `reason` for
      // identity_invalid sub-cases. Used to pick the right humanization.
      const errorReason = params.get('reason')

      const startSuccessCountdown = () => {
        const duration = (window.opener && !window.opener.closed) ? 5 : 2
        let count = duration
        setCountdown(count)
        intervalRef.current = setInterval(() => {
          count--
          setCountdown(count)
          if (count <= 0) handleCountdownDone()
        }, 1000)
      }

      const completeSuccessfulOAuth = async (
        email: string,
        accountId: string,
        token: string | null,
      ) => {
        if (token && accountId) {
          const readiness = await fetchOAuthReadiness(accountId, token)
          if (hasOAuthPermissionGap(readiness)) {
            const providerName = readiness?.provider || provider
            setStatus('repair')
            setRepairDetails({
              provider: providerName === 'outlook' ? 'outlook' : 'gmail',
              email,
              missingLabels: oauthMissingPermissionLabels(readiness),
              repairUrl: readiness?.repair_url || null,
            })
            setMessage(tRef.current('oauth_ui_repair_message', { email }))
            return
          }
        }

        if (token) {
          setStoredToken(token)
        }
        if (token && email) {
          authDataRef.current = { email, token, accountId }
        }

        setStatus('success')
        setMessage(tRef.current('oauth_ui_connected_as', { email }))
        notifyParent({ provider, success: true, email, accountId, token, state })
        startSuccessCountdown()
      }

      // Notify parent window (popup flow)
      const notifyParent = (data: Record<string, unknown>) => {
        if (window.opener && !window.opener.closed) {
          try {
            window.opener.postMessage(
              { type: 'oauth-callback', ...data },
              window.location.origin
            )
          } catch (e) {
            console.error('[OAuthCallback] Failed to notify parent:', e)
          }
        }
      }

      if (error) {
        // #557 follow-up: when the redirect flow (no popup, same tab) lands
        // here with a stale-bundle reject, auto-recover here too — the
        // parent's useOAuth handler only fires for the popup/postMessage
        // path. attemptStaleBundleRecovery navigates away on success.
        if (error === 'identity_invalid' && attemptStaleBundleRecovery(errorReason)) {
          return
        }
        const knownErrors: Record<string, string> = {
          invalid_state: tRef.current('oauth_ui_err_invalid_state'),
          access_denied: tRef.current('oauth_ui_err_access_denied'),
          missing_code: tRef.current('oauth_ui_err_missing_code'),
          invalid_grant: tRef.current('oauth_ui_err_invalid_grant'),
        }
        const rawMsg = errorDescription || knownErrors[error] || error
        const errorMsg = humanizeOAuthError(rawMsg, provider, errorReason)
        // Drop any PKCE artefacts left behind for this state — provider already
        // gone in the storedProvider cleanup above; verifier + redirect uri
        // would otherwise sit in localStorage for the full session.
        if (state) {
          localStorage.removeItem(`pkce_verifier_${state}`)
          localStorage.removeItem(`pkce_redirect_uri_${state}`)
        }
        setStatus('error')
        setMessage(errorMsg)
        // Pass the machine-readable `errorCode` + `reason` separately so the
        // parent can auto-recover (#557 follow-up): a stale-bundle user hits
        // `identity_invalid/id_token_absent` and we hard-reload to bust their
        // cache instead of leaving them stuck.
        notifyParent({
          provider,
          success: false,
          error: errorMsg,
          errorCode: error,
          reason: errorReason,
          state,
        })
        setTimeout(onComplete, 8000)
        return
      }

      // Nouveau flow : Google redirige directement ici avec un code brut
      const code = params.get('code')
      if (code && state && !params.get('success')) {
        // Audit Codex 2026-04-25 [F-OAUTH-03]: require the PKCE verifier to
        // exist in this browser's localStorage. Falling back to a server-side
        // GET /api/oauth/pkce/<state> for an unknown state lets a phishing
        // URL (state=ATTACKER_STATE) complete OAuth with no client-side proof
        // that this device initiated the flow. Reject hard.
        const codeVerifier = localStorage.getItem(`pkce_verifier_${state}`)
        if (!codeVerifier) {
          const errMsg = tRef.current('oauth_ui_session_not_found')
          setStatus('error')
          setMessage(errMsg)
          notifyParent({ provider, success: false, error: errMsg, state })
          setTimeout(onComplete, 5000)
          return
        }
        localStorage.removeItem(`pkce_verifier_${state}`)

        // La redirect_uri doit matcher byte-à-byte celle utilisée à l'auth, sinon
        // Google répond 400 redirect_uri_mismatch. Sources par ordre de priorité :
        // 1) query param `auth_redirect_uri` (fallback backend, voir oauth.py)
        // 2) localStorage (stocké par useOAuth.connect au démarrage du flow)
        // 3) heuristique legacy (peut échouer si le backend a renvoyé sa propre URI via /api/oauth/config)
        const urlAuthRedirectUri = params.get('auth_redirect_uri')
        const storedRedirectUri = localStorage.getItem(`pkce_redirect_uri_${state}`)
        if (storedRedirectUri) {
          localStorage.removeItem(`pkce_redirect_uri_${state}`)
        }
        const redirectUri =
          urlAuthRedirectUri ||
          storedRedirectUri ||
          (provider === 'outlook'
            ? ((import.meta.env.VITE_MICROSOFT_REDIRECT_URI as string | undefined) ||
               `${window.location.origin}/oauth/callback`)
            : ((import.meta.env.VITE_GOOGLE_REDIRECT_URI as string | undefined) ||
               `${window.location.origin}/oauth/callback`))

        const endpoint =
          provider === 'outlook'
            ? `${API_URL}/api/oauth/outlook/complete`
            : `${API_URL}/api/oauth/gmail/complete`

        try {
          const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code, state, code_verifier: codeVerifier, redirect_uri: redirectUri }),
          })

          if (!res.ok) {
            const errData = await res.json().catch(() => ({}))
            const rawMsg = errData.error || tRef.current('oauth_ui_server_error', { status: res.status })
            // #557 follow-up: stale-bundle auto-recovery in the same-tab
            // redirect flow too (popup flow runs via the parent's useOAuth
            // postMessage handler).
            if (
              errData.error === 'identity_invalid' &&
              attemptStaleBundleRecovery(errData.reason)
            ) {
              return
            }
            // #557: backend /complete returns `reason` for identity_invalid
            // sub-cases — pass it through so the user sees an actionable
            // message instead of the opaque error code.
            const errMsg = humanizeOAuthError(rawMsg, provider, errData.reason)
            setStatus('error')
            setMessage(errMsg)
            notifyParent({
              provider,
              success: false,
              error: errMsg,
              errorCode: errData.error,
              reason: errData.reason,
              state,
            })
            setTimeout(onComplete, 8000)
            return
          }

          const data = await res.json()
          const email = data.email || ''
          const accountId = data.account_id || ''
          let token: string | null = data.token || null

          // If backend didn't return a JWT (silent generation failure),
          // explicitly request one so the auth state can be established.
          if (!token && email && accountId) {
            token = await requestJwtFallback(accountId, email)
          }

          await completeSuccessfulOAuth(email, accountId, token)
          return
        } catch {
          const errMsg = tRef.current('oauth_ui_backend_unreachable')
          setStatus('error')
          setMessage(errMsg)
          notifyParent({ provider, success: false, error: errMsg, state })
          setTimeout(onComplete, 5000)
          return
        }
      }

      // Ancien flow : paramètres déjà traités par le backend (redirect depuis /gmail/callback)
      const success = params.get('success') === 'true'
      const email = params.get('email')
      const accountId = params.get('account_id')
      let token = params.get('token')

      if (success && email) {
        // If backend redirect didn't include a JWT, request one explicitly
        if (!token && accountId) {
          token = await requestJwtFallback(accountId, email)
        }
        await completeSuccessfulOAuth(email, accountId || '', token)
        return
      }

      // No valid parameters
      setStatus('error')
      setMessage(tRef.current('oauth_ui_invalid_result'))
      notifyParent({ provider, success: false, error: 'invalid_response', state })
      setTimeout(onComplete, 5000)
    }

    handleCallback()
    // No cleanup: the interval self-clears in handleCountdownDone() and
    // React safely ignores setState on unmounted components. Removing
    // cleanup prevents StrictMode from killing the countdown interval
    // (StrictMode unmounts/remounts but hasProcessed blocks re-init).
  }, [onComplete, initialSearch])

  return (
    <div className="oauth-callback">
      <div className="oauth-callback-card">
        <div className={`oauth-callback-icon ${status}`}>
          {status === 'processing' && (
            <svg aria-hidden="true" viewBox="0 0 24 24" className="spinner">
              <circle cx="12" cy="12" r="10" strokeWidth="3" fill="none" />
            </svg>
          )}
          {status === 'success' && (
            <svg aria-hidden="true" viewBox="0 0 24 24">
              <path
                fill="currentColor"
                d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"
              />
            </svg>
          )}
          {status === 'error' && (
            <svg aria-hidden="true" viewBox="0 0 24 24">
              <path
                fill="currentColor"
                d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"
              />
            </svg>
          )}
          {status === 'repair' && (
            <svg aria-hidden="true" viewBox="0 0 24 24">
              <path
                fill="currentColor"
                d="M12 2 1 21h22L12 2zm1 15h-2v-2h2v2zm0-4h-2V8h2v5z"
              />
            </svg>
          )}
        </div>
        <h2 className="oauth-callback-title">
          {status === 'processing' && t('oauth_ui_title_connecting')}
          {status === 'success' && t('oauth_ui_title_connected')}
          {status === 'error' && t('oauth_ui_title_error')}
          {status === 'repair' && t('oauth_ui_title_repair')}
        </h2>
        <p className="oauth-callback-message">{message}</p>
        {status === 'repair' && repairDetails && (
          <div className="oauth-callback-repair">
            <p className="oauth-callback-repair-label">
              {t('oauth_ui_repair_missing')}
            </p>
            <ul className="oauth-callback-repair-list">
              {(repairDetails.missingLabels.length > 0
                ? repairDetails.missingLabels
                : [t('oauth_ui_repair_missing_fallback')]
              ).map((label) => (
                <li key={label}>{label}</li>
              ))}
            </ul>
            <p className="oauth-callback-hint">
              {t('oauth_ui_repair_steps')}
            </p>
            <button
              className="oauth-callback-return-btn"
              onClick={() => restartOAuth(repairDetails.provider)}
            >
              {t('oauth_ui_repair_retry', {
                provider: repairDetails.provider === 'outlook' ? 'Outlook' : 'Gmail',
              })}
            </button>
            {repairDetails.repairUrl && (
              <a
                className="oauth-callback-secondary-link"
                href={repairDetails.repairUrl}
                target="_blank"
                rel="noreferrer"
              >
                {t('oauth_ui_repair_permissions')}
              </a>
            )}
          </div>
        )}
        {status === 'success' && (
          <>
            <p className="oauth-callback-hint">
              {countdown > 0
                ? (window.opener
                    ? t('oauth_ui_close_in', { count: countdown })
                    : t('oauth_ui_redirect_in', { count: countdown }))
                : message}
            </p>
            {(!window.opener || closeFailed) && (
              <button
                className="oauth-callback-return-btn"
                onClick={() => window.location.replace('/')}
              >
                {t('oauth_ui_return')}
              </button>
            )}
          </>
        )}
        {status === 'error' && (
          <>
            <p className="oauth-callback-hint">
              {t('oauth_ui_returning_soon')}
            </p>
            <button
              className="oauth-callback-return-btn"
              onClick={() => window.location.replace('/')}
            >
              {t('oauth_ui_return_now')}
            </button>
          </>
        )}
      </div>
    </div>
  )
}
