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
 * API client for account management
 */

import i18n from '../i18n'
import { API_URL } from '../config'
import { getAuthHeaders, getStoredToken } from '../services/authToken'
import { ACCOUNT_CHANGED, appEvents } from '../lib/appEvents'

const API_BASE = `${API_URL}/api/accounts`

/**
 * Backend returns avatar_url as a relative path (e.g. "/api/accounts/avatars/abc.jpg").
 * In Tauri / prod builds the frontend origin has no `/api` route, so the <img> 404s.
 * Prefix with API_URL when relative; leave absolute URLs untouched.
 */
export function normalizeAvatarUrl(url: string | null | undefined): string | null | undefined {
  if (!url) return url
  return url.startsWith('/') ? `${API_URL}${url}` : url
}

function normalizeAccountAvatar<T extends { avatar_url?: string | null }>(account: T): T {
  return { ...account, avatar_url: normalizeAvatarUrl(account.avatar_url) ?? null }
}

function normalizeFreshAvatarUrl(url: string): string {
  const normalized = normalizeAvatarUrl(url) ?? url
  const separator = normalized.includes('?') ? '&' : '?'
  return `${normalized}${separator}v=${Date.now()}`
}

export interface Account {
  id: string
  name: string
  email: string
  provider: string
  status: string
  is_current: boolean
  last_sync: string | null
  signature?: string
  signature_html?: string
  has_signature?: boolean
  avatar_url?: string | null
}

export interface UpdateAccountPayload {
  name?: string
  check_interval_minutes?: number
  auto_reply_enabled?: boolean
  draft_only?: boolean
  signature?: string
  signature_html?: string
  default_language?: string
}

/**
 * Fetch all accounts. Returns an empty list synchronously when no JWT is
 * stored — the user is on the login page and the server would 401 anyway
 * (audit 2026-05-01 P1 finding #5). The post-OAuth `auth:login_success`
 * event handler in `lib/currentAccountId.ts` invalidates the cache so this
 * gets retried with a real token in hand.
 */
export async function fetchAccounts(): Promise<{
  count: number
  current_account_id: string | null
  accounts: Account[]
}> {
  if (!getStoredToken()) {
    return { count: 0, current_account_id: null, accounts: [] }
  }
  const response = await fetch(API_BASE, {
    cache: 'no-store',
    headers: { ...getAuthHeaders() },
  })
  if (!response.ok) {
    throw new Error(`Failed to fetch accounts: ${response.statusText}`)
  }
  const data = await response.json()
  return { ...data, accounts: data.accounts.map(normalizeAccountAvatar) }
}

/**
 * Fetch a specific account by ID
 */
export async function fetchAccount(accountId: string): Promise<Account> {
  const response = await fetch(`${API_BASE}/${accountId}`, {
    headers: { ...getAuthHeaders() },
  })
  if (!response.ok) {
    throw new Error(`Failed to fetch account: ${response.statusText}`)
  }
  return normalizeAccountAvatar(await response.json())
}

/**
 * Update an account
 */
export async function updateAccount(
  accountId: string,
  updates: UpdateAccountPayload
): Promise<{ success: boolean; account: Account }> {
  const response = await fetch(`${API_BASE}/${accountId}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify(updates),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `Failed to update account: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Update account signature
 */
export async function updateAccountSignature(
  accountId: string,
  signature: string,
  signatureHtml?: string
): Promise<{ success: boolean; account: Account }> {
  const payload: UpdateAccountPayload = { signature }
  if (signatureHtml !== undefined) payload.signature_html = signatureHtml
  return updateAccount(accountId, payload)
}

/**
 * Activate an account (make it the current active account)
 */
export async function activateAccount(accountId: string): Promise<{ success: boolean }> {
  const response = await fetch(`${API_BASE}/${accountId}/activate`, {
    method: 'POST',
    headers: { ...getAuthHeaders() },
  })

  if (!response.ok) {
    throw new Error(`Failed to activate account: ${response.statusText}`)
  }

  const result = await response.json()
  appEvents.dispatchEvent(new Event(ACCOUNT_CHANGED))
  return result
}

/**
 * Share signature with a colleague by their Agentys email
 */
export async function shareSignature(
  accountId: string,
  targetEmail: string
): Promise<{ success: boolean; message?: string; error?: string; not_found?: boolean }> {
  const response = await fetch(`${API_BASE}/${accountId}/share-signature`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ target_email: targetEmail }),
  })

  const data = await response.json()
  if (!response.ok) {
    throw Object.assign(new Error(data.error || 'Erreur lors du partage'), { not_found: data.not_found })
  }

  return data
}

/**
 * Upload a signature image file, returns the hosted URL
 */
export async function uploadSignatureImage(accountId: string, file: File): Promise<string> {
  const formData = new FormData()
  formData.append('image', file)
  const response = await fetch(`${API_BASE}/${accountId}/signature-image`, {
    method: 'POST',
    headers: { ...getAuthHeaders() },
    body: formData,
  })
  if (!response.ok) {
    const err = await response.json().catch(() => ({}))
    throw new Error((err as { error?: string }).error || i18n.t('errors:signature_image_upload_failed'))
  }
  const data = await response.json() as { url: string }
  return `${API_URL}${data.url}`
}

/**
 * Signature library — multiple named signatures per account.
 * The DEFAULT entry is mirrored into accounts.signature/_html (the canonical
 * pair every composer and the send path read), so consumers stay untouched.
 */
export interface SignatureEntry {
  id: string
  name: string
  html: string
  text: string
  is_default: boolean
  created_at?: string
  updated_at?: string
}

async function signatureLibraryRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...getAuthHeaders(),
      ...(init?.headers || {}),
    },
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error((data as { error?: string }).error || `Signature library request failed: ${response.statusText}`)
  }
  return data as T
}

export async function listSignatures(
  accountId: string
): Promise<{ signatures: SignatureEntry[]; default_id: string | null }> {
  return signatureLibraryRequest(`/${accountId}/signatures`)
}

export async function createSignature(
  accountId: string,
  payload: { name: string; html: string; text?: string }
): Promise<{ success: boolean; signature: SignatureEntry }> {
  return signatureLibraryRequest(`/${accountId}/signatures`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateSignatureEntry(
  accountId: string,
  sigId: string,
  payload: { name?: string; html?: string; text?: string }
): Promise<{ success: boolean; signature: SignatureEntry }> {
  return signatureLibraryRequest(`/${accountId}/signatures/${encodeURIComponent(sigId)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deleteSignatureEntry(
  accountId: string,
  sigId: string
): Promise<{ success: boolean }> {
  return signatureLibraryRequest(`/${accountId}/signatures/${encodeURIComponent(sigId)}`, {
    method: 'DELETE',
  })
}

export async function setDefaultSignature(
  accountId: string,
  sigId: string
): Promise<{ success: boolean; signature: SignatureEntry }> {
  return signatureLibraryRequest(`/${accountId}/signatures/${encodeURIComponent(sigId)}/set-default`, {
    method: 'POST',
  })
}

/**
 * Sync signature from email provider (Gmail, etc.)
 *
 * `dryRun` fetches the provider signature WITHOUT persisting it to the
 * account — used by the signature-library editor, where the import only
 * fills the editor and persistence happens at Save (library entry).
 */
export async function syncSignature(accountId: string, dryRun = false): Promise<{
  success: boolean
  message?: string
  signature?: string | null
  signature_html?: string | null
  account?: Account
  error?: string
}> {
  const response = await fetch(`${API_BASE}/${accountId}/sync-signature${dryRun ? '?dry_run=1' : ''}`, {
    method: 'POST',
    headers: { ...getAuthHeaders() },
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `Failed to sync signature: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Upload a custom avatar image for an account
 */
export async function uploadAccountAvatar(accountId: string, file: File): Promise<string> {
  const formData = new FormData()
  formData.append('image', file)
  const response = await fetch(`${API_BASE}/${accountId}/avatar`, {
    method: 'POST',
    headers: { ...getAuthHeaders() },
    body: formData,
  })
  if (!response.ok) {
    const err = await response.json().catch(() => ({}))
    throw new Error((err as { error?: string }).error || i18n.t('errors:avatar_upload_failed'))
  }
  const data = await response.json() as { url: string }
  return normalizeFreshAvatarUrl(data.url)
}

/**
 * Import avatar from Gmail or Outlook profile
 */
export async function importAccountAvatar(accountId: string): Promise<string> {
  const response = await fetch(`${API_BASE}/${accountId}/avatar/import`, {
    method: 'POST',
    headers: { ...getAuthHeaders() },
  })
  if (!response.ok) {
    const err = await response.json().catch(() => ({}))
    throw new Error((err as { error?: string }).error || i18n.t('errors:avatar_import_failed'))
  }
  const data = await response.json() as { url: string }
  return normalizeFreshAvatarUrl(data.url)
}
