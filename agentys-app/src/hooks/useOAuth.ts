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
 * useOAuth - Unified React hook for OAuth authentication
 *
 * Supports both Gmail and Outlook with automatic environment detection:
 * - Web browser: Opens popup window, listens for postMessage callback
 * - Tauri app: Opens system browser, polls backend for result
 *
 * The token exchange happens server-side for security.
 */

import { useState, useCallback, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { API_URL, IS_CLOUD } from '../config'
import { getAuthHeaders, setStoredToken } from '../services/authToken'
import {
  generatePKCE,
  buildGoogleAuthUrl,
  buildMicrosoftAuthUrl,
  type PKCEChallenge,
} from '../services/oauth'
import { isTauri, checkTokenStatus, type TokenStatus } from '../services/tokenStorage'
import { attemptStaleBundleRecovery } from '../services/oauthRecovery'
import {
  fetchOAuthReadiness,
  hasOAuthPermissionGap,
  oauthMissingPermissionLabels,
  type OAuthReadiness,
} from '../services/oauthReadiness'
export type OAuthProvider = 'gmail' | 'outlook'
export type AuthStatus = 'disconnected' | 'connecting' | 'connected' | 'error'

export interface OAuthState {
  status: AuthStatus
  email: string | null
  accountId: string | null
  token: string | null
  error: string | null
  isLoading: boolean
  // True when window.open returned null at popup pre-flight — useful for the UI to
  // surface a "popup blocked, redirecting you directly" notice. Auto-clears on retry.
  popupBlocked: boolean
  // True after ~15s of polling without a result. Lets the UI reveal a "still
  // connecting…" panel with [Cancel] / [Use redirect instead] actions so the user
  // isn't stuck staring at a silent spinner if postMessage was blocked by COOP /
  // 3rd-party-cookie / tracking-prevention settings.
  pollingStalled: boolean
}

export type ConnectMethod = 'auto' | 'popup' | 'redirect'

export interface ConnectOptions {
  // 'auto' (default): try popup, fall back to redirect if blocked.
  // 'popup': force popup, fail if blocked.
  // 'redirect': skip popup, navigate the current tab directly. Bulletproof against
  // COOP / 3rd-party cookies / tracking prevention since no cross-window messaging.
  method?: ConnectMethod
}

export interface UseOAuthResult extends OAuthState {
  connect: (options?: ConnectOptions) => Promise<void>
  cancelConnect: () => void
  disconnect: () => Promise<void>
  checkStatus: () => Promise<void>
}

interface OAuthConfig {
  clientId?: string
  client_id?: string
  redirectUri?: string
  redirect_uri?: string
  configured?: boolean
}

type TranslateFn = (key: string, options?: Record<string, unknown>) => string

function formatOAuthPermissionError(t: TranslateFn, readiness: OAuthReadiness | null): string {
  const permissions = oauthMissingPermissionLabels(readiness).join(', ')
  if (permissions) {
    return t('oauth_missing_permissions_with_list', { permissions })
  }
  return t('oauth_missing_permissions')
}

export function resolveOAuthRedirectUri(
  provider: OAuthProvider,
  configuredRedirectUri?: string,
): string {
  const envRedirectUri =
    provider === 'gmail'
      ? import.meta.env.VITE_GOOGLE_REDIRECT_URI
      : import.meta.env.VITE_MICROSOFT_REDIRECT_URI

  const backendCallback =
    provider === 'outlook'
      ? `${API_URL}/api/oauth/outlook/callback`
      : `${API_URL}/api/oauth/gmail/callback`

  return envRedirectUri || configuredRedirectUri || backendCallback
}

// Store pending PKCE challenge during OAuth flow (with timestamps for TTL)
const pendingPKCE: Map<OAuthProvider, PKCEChallenge> = new Map()
const pendingPKCETimestamps: Map<OAuthProvider, number> = new Map()
const PKCE_TTL_MS = 10 * 60 * 1000 // 10 minutes

// Cleanup stale PKCE entries
function cleanupStalePKCE(): void {
  const now = Date.now()
  for (const [provider, ts] of pendingPKCETimestamps) {
    if (now - ts > PKCE_TTL_MS) {
      pendingPKCE.delete(provider)
      pendingPKCETimestamps.delete(provider)
    }
  }
}

// Wipe localStorage PKCE entries left behind by abandoned OAuth flows.
// We don't keep an inventory of state IDs in memory after redirect, so we scan
// the prefix. Safe to call any time — only touches keys we own.
function clearPKCELocalStorage(state?: string): void {
  try {
    if (state) {
      localStorage.removeItem(`pkce_verifier_${state}`)
      localStorage.removeItem(`pkce_provider_${state}`)
      localStorage.removeItem(`pkce_redirect_uri_${state}`)
      return
    }
    const keysToRemove: string[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (key && (
        key.startsWith('pkce_verifier_') ||
        key.startsWith('pkce_provider_') ||
        key.startsWith('pkce_redirect_uri_')
      )) {
        keysToRemove.push(key)
      }
    }
    keysToRemove.forEach(k => localStorage.removeItem(k))
  } catch { /* private mode, quota — ignore */ }
}

// Open popup window for OAuth (web flow).
//
// We open at `about:blank` (same-origin) first, THEN navigate to the OAuth URL.
// Two reasons:
//   1. Popup-blocker detection is a clean null-check on `about:blank`, with no
//      COOP interference (which kicks in once the popup loads Google's page that
//      sends `Cross-Origin-Opener-Policy: same-origin`).
//   2. `popup.location.href = url` after open is more reliably treated as a
//      user-initiated navigation than `window.open(url, …)` in some browsers'
//      strict modes (e.g. Brave shields, Firefox tracking protection in private).
function openOAuthPopup(url: string): Window | null {
  const width = 500
  const height = 600
  const left = window.screenX + (window.outerWidth - width) / 2
  const top = window.screenY + (window.outerHeight - height) / 2

  const popup = window.open(
    'about:blank',
    'oauth-popup',
    `width=${width},height=${height},left=${left},top=${top},popup=yes`
  )
  if (!popup) {
    // Hard-blocked by browser popup blocker — return null so the caller can
    // fall back to a same-tab redirect (which never gets blocked).
    return null
  }
  try {
    popup.location.href = url
  } catch {
    // Some browsers throw on .location.href assignment if the popup was
    // immediately closed by an extension. Treat as blocked.
    try { popup.close() } catch { /* ignore */ }
    return null
  }
  return popup
}

// Open URL in system browser (Tauri) or fallback to window.open
async function openUrl(url: string): Promise<void> {
  if (isTauri()) {
    try {
      // Dynamic import to avoid bundler issues in web mode
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const opener = await (import('@tauri-apps/plugin-opener') as Promise<any>)
      await opener.openUrl(url)
      return
    } catch (e) {
      console.warn('[useOAuth] Tauri opener not available:', e)
      // Fallback below
    }
  }
  // Web fallback - open in new tab
  window.open(url, '_blank')
}

export function useOAuth(provider: OAuthProvider, accountId?: string): UseOAuthResult {
  const { t } = useTranslation('inbox')
  const [state, setState] = useState<OAuthState>({
    status: 'disconnected',
    email: null,
    accountId: accountId || null,
    token: null,
    error: null,
    isLoading: true,
    popupBlocked: false,
    pollingStalled: false,
  })

  const pollingIntervalRef = useRef<number | null>(null)
  const popupRef = useRef<Window | null>(null)
  // Stash the active state ID so cancelConnect can clean up the matching
  // localStorage entries without re-scanning the whole prefix.
  const activeStateRef = useRef<string | null>(null)

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current)
      }
      // COOP-safe: don't read `popupRef.current.closed` — under
      // Cross-Origin-Opener-Policy: same-origin (set by Google/Microsoft
      // OAuth pages), reading `closed` triggers a browser console warning
      // even though it doesn't throw. `.close()` is idempotent on an
      // already-closed window, so we just call it unconditionally.
      try { popupRef.current?.close() } catch { /* COOP block — ignore */ }
    }
  }, [])

  // Check existing auth status on mount
  useEffect(() => {
    if (accountId) {
      checkStatus()
    } else {
      setState((prev) => ({ ...prev, isLoading: false }))
    }
  }, [accountId])

  // Listen for postMessage from popup (web flow)
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      // Verify origin — accept same origin (works for both localhost and production)
      if (event.origin !== window.location.origin) return

      const data = event.data
      if (data?.type !== 'oauth-callback') return
      if (data.provider !== provider) return

      // FIX COMMIT-002 (audit P1): require the postMessage's `state` to
      // match the active OAuth flow this hook initiated. Without this
      // check, a sibling tab that never started its own OAuth would
      // accept the original tab's success message (same origin, same
      // provider) and silently auto-authenticate as the original tab's
      // user. OAuthCallback.tsx includes `state` in the payload (see
      // notifyParent call at OAuthCallback.tsx:296).
      if (!activeStateRef.current || data.state !== activeStateRef.current) {
        return
      }

      // Close popup — COOP-safe: don't read `.closed` (warns under COOP
      // same-origin even though it doesn't throw). `.close()` is
      // idempotent so calling it on an already-closed window is safe.
      try { popupRef.current?.close() } catch { /* COOP block — ignore */ }

      // Stop polling if running
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current)
      }

      if (data.success) {
        activeStateRef.current = null
        setState({
          status: 'connected',
          email: data.email,
          accountId: data.accountId,
          token: data.token || null,
          error: null,
          isLoading: false,
          popupBlocked: false,
          pollingStalled: false,
        })
      } else {
        // #557 follow-up: try to auto-recover from a stale-bundle reject
        // BEFORE we surface the error to the user. A successful recovery
        // navigates away — no need to update state.
        if (
          data.errorCode === 'identity_invalid' &&
          attemptStaleBundleRecovery(data.reason)
        ) {
          return
        }
        activeStateRef.current = null
        setState({
          status: 'error',
          email: null,
          accountId: null,
          token: null,
          error: data.error || 'OAuth failed',
          isLoading: false,
          popupBlocked: false,
          pollingStalled: false,
        })
      }
    }

    window.addEventListener('message', handleMessage)
    return () => window.removeEventListener('message', handleMessage)
  }, [provider])

  // Check if already authenticated
  const checkStatus = useCallback(async () => {
    if (!accountId) {
      setState((prev) => ({ ...prev, isLoading: false }))
      return
    }

    try {
      const status: TokenStatus = await checkTokenStatus(accountId)

      if (status.hasTokens && status.isValid) {
        const readiness = await fetchOAuthReadiness(accountId)
        if (hasOAuthPermissionGap(readiness)) {
          setState({
            status: 'error',
            email: status.email || null,
            accountId,
            token: null,
            error: formatOAuthPermissionError(t, readiness),
            isLoading: false,
            popupBlocked: false,
            pollingStalled: false,
          })
          return
        }

        setState({
          status: 'connected',
          email: status.email || null,
          accountId,
          token: null,
          error: null,
          isLoading: false,
          popupBlocked: false,
          pollingStalled: false,
        })
      } else if (status.hasTokens && !status.isValid) {
        // Token expired - could try refresh
        setState({
          status: 'disconnected',
          email: null,
          accountId,
          token: null,
          error: i18n.t('errors:session_expired'),
          isLoading: false,
          popupBlocked: false,
          pollingStalled: false,
        })
      } else {
        setState((prev) => ({
          ...prev,
          status: 'disconnected',
          isLoading: false,
        }))
      }
    } catch (error) {
      console.error('[useOAuth] Check status failed:', error)
      setState((prev) => ({
        ...prev,
        status: 'disconnected',
        isLoading: false,
      }))
    }
  }, [accountId, t])

  // Poll backend for OAuth result (Tauri flow + popup-postMessage fallback)
  const startPolling = useCallback((oauthState: string) => {
    const pollInterval = 2000 // 2 seconds
    const maxPolls = 150 // 5 minutes max
    // Reveal "still connecting…" UX after ~15s. The popup may still complete
    // successfully (postMessage just got dropped by COOP/3p-cookies); we keep
    // polling, but the UI now offers Cancel / Use redirect instead.
    const stalledThreshold = 8 // 8 polls × 2s ≈ 16s

    let pollCount = 0

    // Stability (audit 2026-05-19): clear any in-flight poll before starting a
    // new one. If connect() is triggered twice (double-click / re-render race),
    // the previous setInterval id would be overwritten and leak — orphaning a
    // poll loop that runs until its own maxPolls (~5 min) with no way to stop it.
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current)
      pollingIntervalRef.current = null
    }

    pollingIntervalRef.current = window.setInterval(async () => {
      pollCount++

      if (pollCount === stalledThreshold) {
        setState((prev) => prev.status === 'connecting' ? { ...prev, pollingStalled: true } : prev)
      }

      if (pollCount > maxPolls) {
        if (pollingIntervalRef.current) {
          clearInterval(pollingIntervalRef.current)
        }
        activeStateRef.current = null
        setState({
          status: 'error',
          email: null,
          accountId: null,
          token: null,
          error: t('oauth_timeout_with_hints'),
          isLoading: false,
          popupBlocked: false,
          pollingStalled: false,
        })
        pendingPKCE.delete(provider)
        pendingPKCETimestamps.delete(provider)
        clearPKCELocalStorage(oauthState)
        return
      }

      try {
        const res = await fetch(`${API_URL}/api/oauth/session/${oauthState}/poll`)

        // Backwards-compat: old backend returns 404 when session isn't ready,
        // new backend returns 200 + {status: "pending"}. Handle both.
        if (res.status === 404) {
          // Old backend: session not found yet, keep polling
          return
        }
        if (!res.ok) {
          // Unexpected HTTP error — log and keep polling (don't abort the flow)
          console.warn('[useOAuth] Unexpected poll status:', res.status)
          return
        }

        const data = await res.json()

        if (data.status === 'pending') {
          // New backend: session still being built, keep polling
          return
        }

        // Guard: if a second connect() started while this fetch was in flight,
        // activeStateRef was replaced — discard this stale response to avoid
        // authenticating with the wrong account's token (mirrors postMessage
        // guard at the top of this file).
        if (!activeStateRef.current || oauthState !== activeStateRef.current) {
          return
        }

        // Session found (success or error), stop polling
        if (pollingIntervalRef.current) {
          clearInterval(pollingIntervalRef.current)
        }

        // Clean up PKCE data now that the OAuth flow is complete (success or error)
        pendingPKCE.delete(provider)
        pendingPKCETimestamps.delete(provider)

        if (data.status === 'error') {
          // #557 follow-up: same auto-recovery as the postMessage path —
          // stale-bundle users hitting `identity_invalid/id_token_absent`
          // get a transparent hard-reload before any error surfaces.
          if (
            data.error === 'identity_invalid' &&
            attemptStaleBundleRecovery(data.reason)
          ) {
            return
          }
          activeStateRef.current = null
          setState({
            status: 'error',
            email: null,
            accountId: null,
            token: null,
            error: data.error || 'Erreur OAuth',
            isLoading: false,
            popupBlocked: false,
            pollingStalled: false,
          })
        } else if (data.status === 'success') {
          const token = typeof data.token === 'string' ? data.token : null
          if (token && data.account_id) {
            const readiness = await fetchOAuthReadiness(data.account_id, token)
            if (hasOAuthPermissionGap(readiness)) {
              activeStateRef.current = null
              setState({
                status: 'error',
                email: data.email || null,
                accountId: data.account_id,
                token: null,
                error: formatOAuthPermissionError(t, readiness),
                isLoading: false,
                popupBlocked: false,
                pollingStalled: false,
              })
              clearPKCELocalStorage(oauthState)
              return
            }
          }

          // Persist the JWT immediately when the backend returns one in the
          // poll response. This is the COOP-safe path: the popup's
          // window.opener.postMessage may be silently dropped in incognito
          // (Google's pages set COOP=same-origin which severs the opener),
          // and the popup's localStorage write to the same key may not
          // propagate to the parent before useAuth re-reads. Reading the JWT
          // directly from the polling endpoint short-circuits both races.
          if (token) {
            // setStoredToken swallows its own localStorage errors (Safari
            // private mode, quota exceeded). Calling it unconditionally is
            // safe and synchronous.
            setStoredToken(token)
          }
          activeStateRef.current = null
          setState({
            status: 'connected',
            email: data.email,
            accountId: data.account_id,
            token,
            error: null,
            isLoading: false,
            popupBlocked: false,
            pollingStalled: false,
          })
          clearPKCELocalStorage(oauthState)
        }
      } catch (err) {
        console.error('[useOAuth] Polling error:', err)
        // Don't stop polling on network errors — PKCE must remain for next iteration
      }
    }, pollInterval)
  }, [provider, t])

  // Start OAuth flow.
  //
  // `options.method`:
  //   - 'auto' (default) — try popup, fall back to same-tab redirect if blocked.
  //   - 'popup'         — force popup (used by tests; rarely needed in UI).
  //   - 'redirect'      — skip popup entirely. Bulletproof against COOP /
  //                       3p-cookies / tracking-prevention since no cross-window
  //                       messaging is involved. Use when popup-flow has stalled
  //                       or the user has hardened browser settings.
  const connect = useCallback(async (options: ConnectOptions = {}) => {
    const method: ConnectMethod = options.method ?? 'auto'
    try {
      setState((prev) => ({
        ...prev,
        status: 'connecting',
        error: null,
        isLoading: true,
        popupBlocked: false,
        pollingStalled: false,
      }))

      // Pre-flight: backend must be reachable before opening the system browser.
      // The OAuth redirect_uri points to localhost:5050 — if the backend is down,
      // Chrome will get ERR_CONNECTION_REFUSED after Google consent.
      // Retry once after 1s to handle backend cold-start / transient failures.
      let healthOk = false
      for (let attempt = 0; attempt < 2 && !healthOk; attempt++) {
        try {
          if (attempt > 0) await new Promise(r => setTimeout(r, 1000))
          const healthRes = await fetch(`${API_URL}/api/health`, { signal: AbortSignal.timeout(4000) })
          if (healthRes.ok) healthOk = true
        } catch { /* retry */ }
      }
      if (!healthOk) {
        throw new Error(t(IS_CLOUD ? 'oauth_server_unavailable_cloud' : 'oauth_server_unavailable'))
      }

      // Étape 1 : client_id depuis les variables d'environnement (pas de backend requis)
      let clientId: string | undefined
      let redirectUri: string | undefined

      const envClientId =
        provider === 'gmail'
          ? import.meta.env.VITE_GOOGLE_CLIENT_ID
          : import.meta.env.VITE_MICROSOFT_CLIENT_ID

      if (envClientId) {
        clientId = envClientId as string
        redirectUri = resolveOAuthRedirectUri(provider)
      } else {
        // Fallback : GET /api/oauth/config (ancien comportement si les env vars ne sont pas définies)
        const configRes = await fetch(`${API_URL}/api/oauth/config`)
        if (!configRes.ok) {
          throw new Error('Configuration OAuth non disponible')
        }
        const config = await configRes.json()
        const providerConfig: OAuthConfig =
          provider === 'outlook' ? config.outlook : config.gmail

        // Block flow if backend reports provider as not configured (placeholder credentials)
        if (providerConfig?.configured === false) {
          const name = provider === 'outlook' ? 'Microsoft (Azure)' : 'Google'
          throw new Error(i18n.t('errors:oauth_not_configured', { provider: name }))
        }

        clientId = providerConfig?.clientId || providerConfig?.client_id ||
          (provider === 'gmail' ? config.client_id : undefined)
        // Use the redirect_uri from the backend config — this matches what's registered
        // in the OAuth provider (Google Cloud Console / Azure Portal).
        redirectUri = resolveOAuthRedirectUri(
          provider,
          providerConfig?.redirectUri || providerConfig?.redirect_uri,
        )
      }

      if (!clientId) {
        throw new Error(i18n.t('errors:oauth_client_id_missing', { provider: provider === 'outlook' ? 'Microsoft' : 'Google' }))
      }

      // Étape 2 : PKCE — générer et stocker le verifier en localStorage (pas de backend requis)
      cleanupStalePKCE()
      const pkce = await generatePKCE()
      pendingPKCE.set(provider, pkce)
      pendingPKCETimestamps.set(provider, Date.now())

      // Stocker le verifier, le provider et la redirect_uri en localStorage pour le callback
      // La redirect_uri doit être identique byte-à-byte entre l'auth (ici) et l'échange
      // du code (/complete), sinon Google renvoie 400 redirect_uri_mismatch.
      localStorage.setItem(`pkce_verifier_${pkce.state}`, pkce.codeVerifier)
      localStorage.setItem(`pkce_provider_${pkce.state}`, provider)
      if (redirectUri) {
        localStorage.setItem(`pkce_redirect_uri_${pkce.state}`, redirectUri)
      }

      // Stocker le verifier côté backend (primaire pour le flow cross-origin popup)
      try {
        const storeRes = await fetch(`${API_URL}/api/oauth/pkce/store`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            state: pkce.state,
            code_verifier: pkce.codeVerifier,
          }),
        })
        if (!storeRes.ok) {
          console.warn('[useOAuth] Backend PKCE store failed:', storeRes.status)
        }
      } catch (e) {
        console.warn('[useOAuth] Backend PKCE store unreachable:', e)
      }

      // Build OAuth URL
      const authUrl =
        provider === 'outlook'
          ? buildMicrosoftAuthUrl(clientId, pkce, redirectUri)
          : buildGoogleAuthUrl(clientId, pkce, redirectUri)

      activeStateRef.current = pkce.state

      // Different flow based on environment + caller preference
      if (isTauri()) {
        // Tauri: Open system browser, poll for result
        startPolling(pkce.state)
        await openUrl(authUrl)
      } else if (method === 'redirect') {
        // Explicit redirect flow — skip the popup entirely. Page navigates away;
        // OAuthCallback persists JWT and routes back to '/'. No polling needed
        // since this hook instance unmounts when the navigation happens.
        window.location.href = authUrl
      } else {
        // Web: Open popup, listen for postMessage. COOP-safe — only check
        // null (not `.closed`) to avoid console warnings under strict COOP.
        popupRef.current = openOAuthPopup(authUrl)

        if (!popupRef.current) {
          // Popup blocked. In 'popup' method we fail fast so the consumer can
          // decide what to do; in 'auto' we silently fall back to redirect
          // (with popupBlocked flag so the UI can surface a brief notice).
          if (method === 'popup') {
            throw new Error(t('oauth_popup_blocked'))
          }
          console.warn('[useOAuth] Popup blocked, falling back to same-tab redirect')
          setState((prev) => ({ ...prev, popupBlocked: true }))
          // Tiny delay so React commits the popupBlocked flag before navigation
          // (lets a "popup blocked, redirecting…" notice render even briefly).
          setTimeout(() => {
            window.location.href = authUrl
          }, 150)
        } else {
          // Polling runs as a backup in case postMessage is blocked (COOP /
          // incognito 3p-cookies / hardened tracking prevention). Without
          // this, the user would stare at a silent spinner indefinitely.
          startPolling(pkce.state)
        }
      }

      setState((prev) => ({
        ...prev,
        isLoading: false,
        error: null,
      }))
    } catch (err) {
      console.error('[useOAuth] Failed to start OAuth flow:', err)
      const stateToClear = activeStateRef.current
      activeStateRef.current = null
      setState({
        status: 'error',
        email: null,
        accountId: null,
        token: null,
        error: err instanceof Error
          ? (err.message === 'Failed to fetch'
            ? t(IS_CLOUD ? 'oauth_server_unavailable_cloud' : 'oauth_server_unavailable')
            : err.message)
          : t('oauth_start_failed'),
        isLoading: false,
        popupBlocked: false,
        pollingStalled: false,
      })
      pendingPKCE.delete(provider)
      pendingPKCETimestamps.delete(provider)
      if (stateToClear) clearPKCELocalStorage(stateToClear)
    }
  }, [provider, startPolling, t])

  // Cancel an in-flight OAuth attempt. Closes the popup, stops polling, wipes
  // the PKCE state, and resets the hook to 'disconnected'. Idempotent.
  const cancelConnect = useCallback(() => {
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current)
      pollingIntervalRef.current = null
    }
    try { popupRef.current?.close() } catch { /* COOP — ignore */ }
    popupRef.current = null
    const stateToClear = activeStateRef.current
    activeStateRef.current = null
    pendingPKCE.delete(provider)
    pendingPKCETimestamps.delete(provider)
    if (stateToClear) clearPKCELocalStorage(stateToClear)
    setState((prev) => ({
      ...prev,
      status: 'disconnected',
      error: null,
      isLoading: false,
      popupBlocked: false,
      pollingStalled: false,
    }))
  }, [provider])

  // Disconnect account
  const disconnect = useCallback(async () => {
    const currentAccountId = state.accountId || accountId
    if (!currentAccountId) return

    try {
      setState((prev) => ({ ...prev, isLoading: true }))

      // Stop any pending polling
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current)
      }

      // Notify backend — soft disconnect: drops OAuth tokens + marks account INACTIVE.
      // The email history stored in the DB is intentionally preserved so the user
      // keeps read-only access until they reconnect or explicitly delete the account.
      const res = await fetch(`${API_URL}/api/oauth/${currentAccountId}/disconnect`, {
        method: 'POST',
        headers: { ...getAuthHeaders() },
      })
      // Silent-failure fix (issue #315) : sans ce check, un 500 backend faisait
      // flipper silencieusement le state local à 'disconnected' alors que le
      // token OAuth restait potentiellement valide côté serveur — risque
      // sécurité (user croit avoir coupé l'accès) + état zombie (row orpheline).
      if (!res.ok) {
        const errText = await res.text().catch(() => 'unknown')
        throw new Error(`Disconnect failed: ${res.status} ${errText}`)
      }

      // Preserve accountId so views filtered by active account keep displaying
      // the cached / DB-backed history. Only the auth status flips to 'disconnected'.
      // Do NOT call invalidateEmailCache(): the server DB is the source of truth
      // and flushing IndexedDB here causes a visible "data loss" flicker (issue #176).
      setState((prev) => ({
        ...prev,
        status: 'disconnected',
        token: null,
        error: null,
        isLoading: false,
      }))
    } catch (err) {
      console.error('[useOAuth] Failed to disconnect:', err)
      const message = err instanceof Error ? err.message : 'unknown error'
      const errorMessage = i18n.t('errors:oauth_disconnect_failed', { message })
      setState((prev) => ({
        ...prev,
        error: errorMessage,
        isLoading: false,
      }))
      // FE-10: the component-local error is invisible if the user already closed
      // the Settings modal — they'd believe the account disconnected while the
      // OAuth token is still valid server-side. Surface a global toast too.
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: { message: errorMessage, type: 'error', duration: 8000 },
      }))
    }
  }, [state.accountId, accountId])

  return {
    ...state,
    connect,
    cancelConnect,
    disconnect,
    checkStatus,
  }
}

// Convenience hooks for specific providers
export function useGmailOAuth(accountId?: string): UseOAuthResult {
  return useOAuth('gmail', accountId)
}

export function useOutlookOAuth(accountId?: string): UseOAuthResult {
  return useOAuth('outlook', accountId)
}
