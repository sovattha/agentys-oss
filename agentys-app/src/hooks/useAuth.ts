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
import i18n from '../i18n'
import { API_URL } from '../config'
import { getStoredToken, setStoredToken, clearStoredToken, JWT_STORAGE_KEY } from '../services/authToken'
import { clearLocalData } from '../services/clearUserData'
import { fetchAuthMeCached, invalidateAuthMeCache } from '../services/bootstrapCache'

export interface AuthUser {
  id: number
  email: string
  plan?: string
  subscription_status?: string
  ai_enabled?: boolean
  billing?: {
    plan: string
    subscription_status: string
    ai_enabled: boolean
    reason: string
    current_period_end?: string | null
    cancel_at_period_end?: boolean
  }
}

interface AuthState {
  user: AuthUser | null
  token: string | null
  isAuthenticated: boolean
  isLoading: boolean
}

export function useAuth() {
  const [state, setState] = useState<AuthState>({
    user: null,
    token: getStoredToken(),
    isAuthenticated: false,
    isLoading: true,
  })
  // Tracks the last token we adopted from a storage event, so an in-flight
  // /api/auth/me verification can't overwrite a fresher JWT we just picked up.
  const tokenRef = useRef<string | null>(null)
  tokenRef.current = state.token

  // Cross-window JWT propagation: when the OAuth popup writes the JWT to
  // localStorage, browsers fire a `storage` event in OTHER windows of the
  // same origin (the popup itself is excluded). This is the only reliable
  // signal in incognito + COOP, where:
  //   - the parent's mounted useAuth has already read getStoredToken() = null
  //   - window.opener.postMessage is silently dropped (Google sets COOP)
  //   - the polling fallback may resolve before useOAuth threads the token
  //     into loginWithOAuth
  // Without this listener the parent stays unauthenticated even though the
  // popup successfully completed the OAuth round-trip.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== JWT_STORAGE_KEY) return
      const newToken = e.newValue
      if (newToken && newToken !== tokenRef.current) {
        // Popup just wrote a fresh JWT — adopt it. Best-effort decode of the
        // email from the JWT payload (no signature check; the server-side
        // /api/auth/me will reject if the token is forged).
        let email = ''
        try {
          const payload = JSON.parse(atob(newToken.split('.')[1] || '')) as { email?: string }
          email = payload.email || ''
        } catch { /* malformed JWT — let /api/auth/me decide */ }
        const userId = email
          ? Math.abs(Array.from(email).reduce((h, c) => (Math.imul(31, h) + c.charCodeAt(0)) | 0, 0)) % 100000
          : 0
        setState({
          user: email ? { id: userId, email } : null,
          token: newToken,
          isAuthenticated: true,
          isLoading: false,
        })
        // Refire the bootstrap so useBackendConnection reloads /api/init etc.
        try {
          window.dispatchEvent(new CustomEvent('auth:login_success', { detail: { email } }))
        } catch { /* CustomEvent guaranteed in supported browsers */ }
      } else if (!newToken && tokenRef.current) {
        // Token cleared in another window (logout from sibling tab) — mirror it.
        invalidateAuthMeCache()
        setState({ user: null, token: null, isAuthenticated: false, isLoading: false })
      }
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  // On mount: verify existing JWT with /api/auth/me
  useEffect(() => {
    const token = getStoredToken()
    if (!token) {
      setState({ user: null, token: null, isAuthenticated: false, isLoading: false })
      return
    }

    // Dev bypass — stored as "dev:<email>", no backend needed
    if (import.meta.env.DEV && token.startsWith('dev:')) {
      const email = token.slice(4)
      const user = { id: 1, email }
      setState({ user, token, isAuthenticated: true, isLoading: false })
      return
    }

    fetchAuthMeCached()
      .then(data => {
        if (!data?.user) throw new Error('Invalid token')
        setState({ user: data.user as AuthUser, token, isAuthenticated: true, isLoading: false })
      })
      .catch(err => {
        // Differentiate real auth rejection from transient network/CORS/5xx.
        // bootstrapCache throws `Error('auth/me failed: <status>')` on non-2xx
        // responses; a native TypeError ('Failed to fetch') fires on network
        // errors (offline, CORS preflight failure, Railway cold-start 502…).
        // Nuking the JWT on any failure — the previous behaviour — meant a
        // single network blip during a deploy cutover logged the user out and
        // cascaded into a /api/init 401 flood. Only 401/403 mean "server
        // rejected this JWT"; everything else we treat as transient and keep
        // the token, letting the first real API call 401-out via the normal
        // auth:unauthorized path if the JWT is genuinely dead.
        const msg = err instanceof Error ? err.message : String(err)
        const statusMatch = msg.match(/auth\/me failed: (\d+)/)
        const httpStatus = statusMatch ? parseInt(statusMatch[1], 10) : null
        const isFatal = httpStatus === 401 || httpStatus === 403
        if (isFatal) {
          console.info('[useAuth] JWT rejected by server (', httpStatus, ') — logging out')
          clearStoredToken()
          invalidateAuthMeCache()
          setState({ user: null, token: null, isAuthenticated: false, isLoading: false })
        } else {
          console.warn('[useAuth] /api/auth/me transient failure, keeping token:', err)
          invalidateAuthMeCache()
          // Trust the JWT until a subsequent call definitively rejects it.
          // user is null; consumers read accountEmail from useBackendConnection.
          setState({ user: null, token, isAuthenticated: true, isLoading: false })
        }
      })
  }, [])

  const requestMagicLink = useCallback(async (email: string): Promise<{ dev_magic_url?: string }> => {
    const res = await fetch(`${API_URL}/api/auth/request-magic-link`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.error || 'Erreur lors de l\'envoi du lien')
    }
    return res.json()
  }, [])

  const verifyToken = useCallback(async (magicToken: string) => {
    const res = await fetch(`${API_URL}/api/auth/verify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: magicToken }),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.error || i18n.t('errors:invalid_token'))
    }
    const data = await res.json()
    const jwt = data.access_token
    setStoredToken(jwt)
    setState({ user: data.user, token: jwt, isAuthenticated: true, isLoading: false })
  }, [])

  const loginDev = useCallback((email: string) => {
    const devToken = `dev:${email}`
    setStoredToken(devToken)
    setState({ user: { id: 1, email }, token: devToken, isAuthenticated: true, isLoading: false })
  }, [])

  // Synchronous login — for same-tab OAuth flow where token is already available.
  // Unlike loginWithOAuth (async), this guarantees React batches the state update
  // with any sibling setState calls in the same synchronous block.
  const loginWithToken = useCallback((email: string, token: string) => {
    const user_id = Math.abs(Array.from(email).reduce((h, c) => (Math.imul(31, h) + c.charCodeAt(0)) | 0, 0)) % 100000
    setStoredToken(token)
    setState({ user: { id: user_id, email }, token, isAuthenticated: true, isLoading: false })
    // Signal to useBackendConnection (and any other listener) that auth is now
    // established. Without this, the backend connection hook's initial
    // checkBackendAndOnboarding ran with no JWT and never re-fetched, so the
    // wizard stayed stuck on "En attente des informations du compte...".
    try {
      window.dispatchEvent(new CustomEvent('auth:login_success', { detail: { email } }))
    } catch { /* CustomEvent should always exist in supported browsers */ }
  }, [])

  const loginWithOAuth = useCallback(async (accountId: string, email: string, token?: string) => {
    let jwt: string
    if (token) {
      // JWT already minted server-side during OAuth callback — use directly
      jwt = token
    } else {
      // Le popup OAuthCallback a pu stocker le JWT directement dans localStorage
      // avant que le polling ne résolve dans cette fenêtre. Vérifier d'abord.
      const storedJwt = getStoredToken()
      if (storedJwt && storedJwt !== state.token) {
        jwt = storedJwt
      } else {
        // Fallback: ask backend to issue JWT (Tauri polling flow or re-auth)
        const res = await fetch(`${API_URL}/api/auth/oauth-login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ account_id: accountId, email }),
        })
        if (!res.ok) {
          const data = await res.json().catch(() => ({}))
          throw new Error(data.error || i18n.t('errors:oauth_failed'))
        }
        const data = await res.json()
        jwt = data.access_token
      }
    }
    const user_id = Math.abs(Array.from(email).reduce((h, c) => (Math.imul(31, h) + c.charCodeAt(0)) | 0, 0)) % 100000
    setStoredToken(jwt)
    setState({ user: { id: user_id, email }, token: jwt, isAuthenticated: true, isLoading: false })
    try {
      window.dispatchEvent(new CustomEvent('auth:login_success', { detail: { email } }))
    } catch { /* CustomEvent should always exist in supported browsers */ }
  }, [])

  const logout = useCallback(() => {
    // Nettoyage immédiat de l'état en mémoire pour que l'UI
    // reflète instantanément la déconnexion.
    clearStoredToken()
    invalidateAuthMeCache()
    setState({ user: null, token: null, isAuthenticated: false, isLoading: false })

    // Nettoyage local uniquement (localStorage, sessionStorage, IndexedDB).
    // Les comptes backend sont conservés — au re-login, tout est retrouvé.
    clearLocalData().catch(err => {
      console.error('[useAuth] clearLocalData failed during logout:', err)
    })
  }, [])

  return {
    ...state,
    requestMagicLink,
    verifyToken,
    loginWithOAuth,
    loginWithToken,
    loginDev,
    logout,
  }
}
