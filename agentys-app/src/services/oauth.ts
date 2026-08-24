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
 * OAuth utilities for Agentys
 *
 * Handles PKCE flow and OAuth URL generation.
 * Token exchange and storage are now handled server-side for security.
 *
 * Migration: The following functions have been moved to the backend:
 * - exchangeCodeForTokens() -> backend /api/oauth/gmail/callback
 * - refreshAccessToken() -> backend /api/oauth/tokens/<id>/refresh
 * - storeTokens() -> backend stores tokens server-side (encrypted)
 * - getTokens() -> use tokenStorage.ts abstraction
 * - deleteTokens() -> use tokenStorage.ts abstraction
 */

// Google OAuth Configuration
const GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'

// Microsoft OAuth Configuration
const MICROSOFT_AUTH_URL = 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize'

// Default redirect URIs for desktop apps (localhost callback)
import { API_URL } from '../config'

const DEFAULT_GOOGLE_REDIRECT_URI = `${API_URL}/api/oauth/gmail/callback`
const DEFAULT_MICROSOFT_REDIRECT_URI = `${API_URL}/api/oauth/outlook/callback`

// Legacy - kept for backwards compatibility
const DEFAULT_REDIRECT_URI = DEFAULT_GOOGLE_REDIRECT_URI

export interface OAuthTokens {
  access_token: string
  refresh_token: string
  expires_at: number
  scope: string
  token_type: string
}

export interface PKCEChallenge {
  codeVerifier: string
  codeChallenge: string
  state: string
}

/**
 * Generate cryptographically secure random string
 */
function generateRandomString(length: number): string {
  const array = new Uint8Array(length)
  crypto.getRandomValues(array)
  return Array.from(array, (byte) => byte.toString(16).padStart(2, '0')).join('')
}

/**
 * Generate base64url encoded string from ArrayBuffer
 */
function base64UrlEncode(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte)
  })
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/**
 * Generate PKCE code verifier and challenge
 * Using S256 method as required by Google and Microsoft
 */
export async function generatePKCE(): Promise<PKCEChallenge> {
  // Generate random code verifier (43-128 characters)
  const codeVerifier = generateRandomString(32) // 64 hex chars

  // Generate code challenge using SHA256
  const encoder = new TextEncoder()
  const data = encoder.encode(codeVerifier)
  const hash = await crypto.subtle.digest('SHA-256', data)
  const codeChallenge = base64UrlEncode(hash)

  // Generate state parameter for CSRF protection
  const state = generateRandomString(16)

  return {
    codeVerifier,
    codeChallenge,
    state,
  }
}

/**
 * Build Google OAuth authorization URL
 */
export function buildGoogleAuthUrl(
  clientId: string,
  pkce: PKCEChallenge,
  redirectUri: string = DEFAULT_REDIRECT_URI
): string {
  // ⚠️ Liste MIROIR côté mobile : agentys-mobile/src/services/auth.ts
  // (GMAIL_SCOPES) — garder les deux synchronisées.
  const scopes = [
    // Email scopes
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/gmail.settings.basic',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    // Calendar scopes (Issue #26)
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events',
  ]

  const params = new URLSearchParams({
    client_id: clientId,
    redirect_uri: redirectUri,
    response_type: 'code',
    scope: scopes.join(' '),
    access_type: 'offline', // Required for refresh token
    prompt: 'consent', // Force consent to get refresh token
    code_challenge: pkce.codeChallenge,
    code_challenge_method: 'S256',
    state: pkce.state,
  })

  return `${GOOGLE_AUTH_URL}?${params.toString()}`
}

/**
 * Build Microsoft OAuth authorization URL
 */
export function buildMicrosoftAuthUrl(
  clientId: string,
  pkce: PKCEChallenge,
  redirectUri: string = DEFAULT_MICROSOFT_REDIRECT_URI
): string {
  // ⚠️ Liste MIROIR côté mobile : agentys-mobile/src/services/auth.ts
  // (OUTLOOK_SCOPES) — garder les deux synchronisées.
  const scopes = [
    // OIDC scopes — required for id_token issuance.
    // Backend's _validate_outlook_identity() (AUTH-VULN-04, issue #557)
    // rejects logins without an id_token in prod with `identity_invalid`.
    'openid',
    'email',
    'profile',
    // Email scopes
    'https://graph.microsoft.com/Mail.Read',
    'https://graph.microsoft.com/Mail.Send',
    'https://graph.microsoft.com/Mail.ReadWrite',
    'https://graph.microsoft.com/User.Read',
    'offline_access', // Required for refresh token
    // Calendar scopes (Issue #26)
    'https://graph.microsoft.com/Calendars.ReadWrite',
    // Contacts scope for autocomplete + photo lookup (/api/contacts/avatar)
    'https://graph.microsoft.com/People.Read',
    'https://graph.microsoft.com/Contacts.Read',
    // mailboxSettings exposes the server-side signature so get_signature()
    // doesn't 403 and fall back to scraping sent mail (delegated, user-consentable)
    'https://graph.microsoft.com/MailboxSettings.Read',
  ]

  const params = new URLSearchParams({
    client_id: clientId,
    redirect_uri: redirectUri,
    response_type: 'code',
    scope: scopes.join(' '),
    response_mode: 'query',
    prompt: 'select_account',
    code_challenge: pkce.codeChallenge,
    code_challenge_method: 'S256',
    state: pkce.state,
  })

  return `${MICROSOFT_AUTH_URL}?${params.toString()}`
}

/**
 * Check if tokens need refresh (5 min buffer)
 */
export function tokensNeedRefresh(tokens: OAuthTokens): boolean {
  const bufferMs = 5 * 60 * 1000 // 5 minutes
  return Date.now() > tokens.expires_at - bufferMs
}

/**
 * Get user email from Google userinfo endpoint
 */
export async function getGoogleUserEmail(accessToken: string): Promise<string> {
  const response = await fetch('https://www.googleapis.com/oauth2/v2/userinfo', {
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
  })

  if (!response.ok) {
    throw new Error('Failed to get user info')
  }

  const data = await response.json()
  return data.email
}

/**
 * Get user email from Microsoft Graph API
 */
export async function getMicrosoftUserEmail(accessToken: string): Promise<string> {
  const response = await fetch('https://graph.microsoft.com/v1.0/me', {
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
  })

  if (!response.ok) {
    throw new Error('Failed to get Microsoft user info')
  }

  const data = await response.json()
  // Microsoft Graph API returns mail or userPrincipalName
  return data.mail || data.userPrincipalName
}

// =============================================================================
// DEPRECATED: Legacy functions for Tauri keyring storage
// These are kept for backward compatibility but will be removed in future versions.
// Use the tokenStorage.ts abstraction instead.
// =============================================================================

/**
 * @deprecated Use tokenStorage.ts instead
 * Store OAuth tokens in OS Keychain (Tauri only)
 */
export async function storeTokens(
  provider: string,
  accountId: string,
  tokens: OAuthTokens
): Promise<void> {
  try {
    const keyring = await import('tauri-plugin-keyring-api')
    const key = `${provider}:${accountId}`
    const value = JSON.stringify(tokens)
    await keyring.setPassword('agentys', key, value)
  } catch (error) {
    console.error('[oauth] storeTokens failed (not in Tauri?):', error)
    throw error
  }
}

/**
 * @deprecated Use tokenStorage.ts instead
 * Retrieve OAuth tokens from OS Keychain (Tauri only)
 */
export async function getTokens(
  provider: string,
  accountId: string
): Promise<OAuthTokens | null> {
  try {
    const keyring = await import('tauri-plugin-keyring-api')
    const key = `${provider}:${accountId}`
    const value = await keyring.getPassword('agentys', key)
    if (!value) return null
    return JSON.parse(value) as OAuthTokens
  } catch {
    return null
  }
}

/**
 * @deprecated Use tokenStorage.ts instead
 * Delete OAuth tokens from OS Keychain (Tauri only)
 */
export async function deleteTokens(
  provider: string,
  accountId: string
): Promise<void> {
  try {
    const keyring = await import('tauri-plugin-keyring-api')
    const key = `${provider}:${accountId}`
    await keyring.deletePassword('agentys', key)
  } catch {
    // Ignore if key doesn't exist
  }
}

/**
 * @deprecated Token exchange now happens server-side
 * Exchange authorization code for tokens
 */
export async function exchangeCodeForTokens(
  _code: string, _codeVerifier: string, _clientId: string, _clientSecret: string,
  _redirectUri: string = DEFAULT_REDIRECT_URI
): Promise<OAuthTokens> {
  throw new Error(
    'exchangeCodeForTokens is deprecated. Token exchange now happens server-side.'
  )
}

/**
 * @deprecated Token refresh now happens server-side
 * Refresh access token using refresh token
 */
export async function refreshAccessToken(
  _refreshToken: string, _clientId: string, _clientSecret: string
): Promise<OAuthTokens> {
  throw new Error(
    'refreshAccessToken is deprecated. Token refresh now happens server-side via /api/oauth/tokens/<id>/refresh'
  )
}

/**
 * @deprecated Token exchange now happens server-side
 * Exchange Microsoft authorization code for tokens
 */
export async function exchangeMicrosoftCodeForTokens(
  _code: string, _codeVerifier: string, _clientId: string, _clientSecret: string,
  _redirectUri: string = DEFAULT_MICROSOFT_REDIRECT_URI
): Promise<OAuthTokens> {
  throw new Error(
    'exchangeMicrosoftCodeForTokens is deprecated. Token exchange now happens server-side.'
  )
}

/**
 * @deprecated Token refresh now happens server-side
 * Refresh Microsoft access token using refresh token
 */
export async function refreshMicrosoftAccessToken(
  _refreshToken: string, _clientId: string, _clientSecret: string
): Promise<OAuthTokens> {
  throw new Error(
    'refreshMicrosoftAccessToken is deprecated. Token refresh now happens server-side via /api/oauth/tokens/<id>/refresh'
  )
}
