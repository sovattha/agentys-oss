/**
 * API client for snippet management
 */

import type {
  Snippet,
  SnippetsResponse,
  SharedSnippetsResponse,
  SnippetSharesResponse,
  CreateSnippetPayload,
  UpdateSnippetPayload,
  ShareSnippetPayload,
} from '../types/snippets'
import { getAuthHeaders } from '../services/authToken'
import { API_URL } from '../config'
import { getActiveAccountId } from './emails'
import { chipsToTokens } from '../utils/placeholderChips'

const API_BASE = `${API_URL}/api/snippets`

/**
 * Fetch all snippets (own + legacy)
 */
export async function fetchSnippets(accountId?: number): Promise<SnippetsResponse> {
  const url = accountId != null ? `${API_BASE}?account_id=${accountId}` : API_BASE
  const response = await fetch(url, {
    headers: { ...getAuthHeaders() },
  })
  if (!response.ok) {
    throw new Error(`Failed to fetch snippets: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Fetch snippets shared with current user
 */
export async function fetchSharedSnippets(): Promise<SharedSnippetsResponse> {
  const response = await fetch(`${API_BASE}/shared-with-me`, {
    headers: { ...getAuthHeaders() },
  })
  if (!response.ok) {
    throw new Error(`Failed to fetch shared snippets: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Fetch a specific snippet by ID
 */
export async function fetchSnippet(id: string): Promise<{ snippet: Snippet }> {
  const response = await fetch(`${API_BASE}/${encodeURIComponent(id)}`, {
    headers: { ...getAuthHeaders() },
  })
  if (!response.ok) {
    throw new Error(`Failed to fetch snippet: ${response.statusText}`)
  }
  return response.json()
}

/**
 * Create a new snippet
 */
export async function createSnippet(
  payload: CreateSnippetPayload,
  accountId?: number
): Promise<{
  snippet: Snippet
  message: string
}> {
  const body = accountId != null ? { ...payload, account_id: accountId } : payload
  const response = await fetch(API_BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `Failed to create snippet: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Update an existing snippet
 */
export async function updateSnippet(
  id: string,
  payload: UpdateSnippetPayload
): Promise<{ snippet: Snippet; message: string }> {
  const response = await fetch(`${API_BASE}/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `Failed to update snippet: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Delete a snippet
 */
export async function deleteSnippet(id: string): Promise<{ message: string }> {
  const response = await fetch(`${API_BASE}/${encodeURIComponent(id)}`, {
    method: 'DELETE',
    headers: { ...getAuthHeaders() },
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `Failed to delete snippet: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Record snippet usage (increments use_count)
 */
export async function recordSnippetUsage(id: string): Promise<{ snippet: Snippet }> {
  const response = await fetch(`${API_BASE}/${encodeURIComponent(id)}/use`, {
    method: 'POST',
    headers: { ...getAuthHeaders() },
  })

  if (!response.ok) {
    // Non-critical, don't throw
    console.warn('Failed to record snippet usage')
    return { snippet: {} as Snippet }
  }

  return response.json()
}

/**
 * Share a snippet with another user
 */
export async function shareSnippet(
  id: string,
  payload: ShareSnippetPayload
): Promise<{ share: { id: string }; message: string }> {
  const response = await fetch(`${API_BASE}/${encodeURIComponent(id)}/share`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `Failed to share snippet: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Revoke a snippet share
 */
export async function unshareSnippet(id: string, email: string): Promise<{ message: string }> {
  const response = await fetch(
    `${API_BASE}/${encodeURIComponent(id)}/share?email=${encodeURIComponent(email)}`,
    {
      method: 'DELETE',
      headers: { ...getAuthHeaders() },
    }
  )

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `Failed to unshare snippet: ${response.statusText}`)
  }

  return response.json()
}

/**
 * List who a snippet is shared with
 */
export async function fetchSnippetShares(id: string): Promise<SnippetSharesResponse> {
  const response = await fetch(`${API_BASE}/${encodeURIComponent(id)}/shares`, {
    headers: { ...getAuthHeaders() },
  })

  if (!response.ok) {
    throw new Error(`Failed to fetch snippet shares: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Duplicate a shared snippet into own library
 */
export async function duplicateSnippet(id: string): Promise<{
  snippet: Snippet
  message: string
}> {
  const response = await fetch(`${API_BASE}/${encodeURIComponent(id)}/duplicate`, {
    method: 'POST',
    headers: { ...getAuthHeaders() },
  })

  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `Failed to duplicate snippet: ${response.statusText}`)
  }

  return response.json()
}

/**
 * Replace variables in snippet content
 */
export function replaceSnippetVariables(
  content: string,
  variables: Record<string, string>
): string {
  // Convert any `{x}` placeholder chips (data-ar-token spans) back to their
  // plain `{token}` form so the substitution below resolves them like the
  // legacy plain-text tokens.
  let result = chipsToTokens(content)

  // Replace all known variables
  for (const [key, value] of Object.entries(variables)) {
    const regex = new RegExp(`\\{${key}\\}`, 'gi')
    result = result.replace(regex, value)
  }

  return result
}

/**
 * Find unreplaced variables in content (custom placeholders)
 */
export function findUnreplacedVariables(content: string): string[] {
  const regex = /\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g
  const matches: string[] = []
  let match

  while ((match = regex.exec(content)) !== null) {
    if (!matches.includes(match[0])) {
      matches.push(match[0])
    }
  }

  return matches
}

// LocalStorage key for snippets (fallback when backend not available).
// Scoped per-account so multi-account users don't share snippets across profiles.
const LEGACY_STORAGE_KEY = 'agentys_snippets'

function getStorageKey(): string {
  const accountId = getActiveAccountId()
  return accountId && accountId !== 'default' ? `agentys_snippets:${accountId}` : LEGACY_STORAGE_KEY
}

/**
 * Get snippets from localStorage (fallback) — scoped to the active account.
 *
 * Falls back to the legacy global key the FIRST time a user opens snippets
 * after upgrading, so existing local-only snippets aren't lost. Once any save
 * happens, the legacy key is dropped.
 */
export function getLocalSnippets(): Snippet[] {
  try {
    const scoped = localStorage.getItem(getStorageKey())
    if (scoped) return JSON.parse(scoped)
    // One-shot fallback to legacy global key (pre-account-scoping) so the
    // user's existing local snippets remain visible after the upgrade.
    const legacy = localStorage.getItem(LEGACY_STORAGE_KEY)
    return legacy ? JSON.parse(legacy) : []
  } catch {
    return []
  }
}

/**
 * Save snippets to localStorage (fallback) — scoped to the active account.
 * Also drops the legacy global key on first write so the next read is clean.
 */
export function saveLocalSnippets(snippets: Snippet[]): void {
  localStorage.setItem(getStorageKey(), JSON.stringify(snippets))
  // Drop the legacy global key once we've migrated this account's data
  if (localStorage.getItem(LEGACY_STORAGE_KEY) !== null) {
    localStorage.removeItem(LEGACY_STORAGE_KEY)
  }
}
