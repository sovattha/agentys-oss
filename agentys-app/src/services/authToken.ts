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
 * JWT token management for auth requests.
 * Single source of truth for token storage/retrieval.
 */

// Exported so cross-window listeners (storage events) can compare event.key
// against this single source of truth instead of duplicating the literal.
export const JWT_STORAGE_KEY = 'agentys_jwt'
const STORAGE_KEY = JWT_STORAGE_KEY
const ACCOUNT_HEADER = 'X-Account-Id'

export function getStoredToken(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

export function setStoredToken(token: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, token)
  } catch {
    // localStorage unavailable (e.g. Safari private mode)
  }
}

export function clearStoredToken(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // localStorage unavailable (e.g. Safari private mode)
  }
}

/**
 * Decodes the email claim from the stored JWT (no signature check).
 * Used as a fallback to identify the logged-in user when the parent
 * component cannot pass an explicit accountEmail prop (multi-account
 * users should still pass it explicitly).
 */
export function getJwtEmail(): string | null {
  const token = getStoredToken()
  if (!token) return null
  // Dev bypass token: "dev:<email>"
  if (token.startsWith('dev:')) return token.slice(4) || null
  try {
    const payload = JSON.parse(atob(token.split('.')[1] || '')) as { email?: string }
    return payload.email || null
  } catch {
    return null
  }
}

/**
 * Provider du compte actif — registerable via registerActiveAccountProvider().
 *
 * Permet à authToken de récupérer le compte actif sans créer de cycle
 * d'import avec api/emails.ts (qui importe déjà getAuthHeaders).
 */
type AccountProvider = () => string | null | undefined

let _accountProvider: AccountProvider | null = null

export function registerActiveAccountProvider(fn: AccountProvider): void {
  _accountProvider = fn
}

/**
 * Retourne les headers d'authentification pour les fetchs API.
 *
 * - Authorization: Bearer <JWT> — authentifie l'utilisateur.
 * - X-Account-Id: <hash> — identifie explicitement le compte actif côté
 *   frontend. Double-clé côté backend pour détecter les tentatives de
 *   mix (JWT de A + X-Account-Id de B → 403). Isolation multi-compte.
 */
export function getAuthHeaders(): Record<string, string> {
  const token = getStoredToken()
  const headers: Record<string, string> = {}
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  if (_accountProvider) {
    try {
      const accountId = _accountProvider()
      if (accountId && accountId !== 'default') {
        headers[ACCOUNT_HEADER] = accountId
      }
    } catch {
      // Provider a throw → pas de header X-Account-Id (fail safe)
    }
  }
  return headers
}

/**
 * Inspects a fetch response and dispatches `auth:unauthorized` on 401 so that
 * App.tsx can logout + redirect the user to the login flow. Call this on any
 * raw `fetch()` that uses `getAuthHeaders()` — apiClient (services/api.ts)
 * already handles this internally, but hooks that bypass apiClient and use
 * `fetch()` directly (useLearningProgress, useSettingsCache, ...) would
 * otherwise stay stuck on a 401 response forever (observed: onboarding stuck
 * at 0% when the JWT is expired/missing, no UI feedback).
 *
 * Always dispatches on 401 — we used to gate on `getStoredToken()` but that
 * created a worse race : when useAuth's /api/auth/me failure already cleared
 * the token, a concurrent 401 from /api/init/settings/accounts couldn't
 * escalate and the user sat stuck on the onboarding screen with 38 piled-up
 * 401s. Callers that might fire before auth is established should gate on
 * `auth.isAuthenticated` at the consumer level, not here.
 *
 * Returns the response unchanged so callers can continue their flow (typically
 * a `response.ok` branch that errors out normally).
 */
export function handleAuthResponse(response: Response): Response {
  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent('auth:unauthorized'))
  }
  return response
}
