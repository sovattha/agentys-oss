import { API_URL } from '../config'
import { getAuthHeaders } from './authToken'

export type OAuthReadinessProvider = 'gmail' | 'outlook'

export interface OAuthReadiness {
  ready: boolean
  needs_reauth: boolean
  problem: 'missing_scopes' | 'no_tokens' | 'unsupported_provider' | null
  account_id?: string
  provider?: OAuthReadinessProvider | null
  email?: string | null
  missing_scopes?: string[]
  missing_scope_labels?: string[]
  granted_scopes?: string[]
  scope_verified?: boolean
  repair_url?: string | null
}

export async function fetchOAuthReadiness(
  accountId: string,
  token?: string | null,
): Promise<OAuthReadiness | null> {
  if (!accountId) return null

  const headers: Record<string, string> = { ...getAuthHeaders() }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  try {
    const response = await fetch(
      `${API_URL}/api/oauth/tokens/${encodeURIComponent(accountId)}/readiness`,
      { headers },
    )
    if (!response.ok) return null
    return await response.json()
  } catch {
    return null
  }
}

export function hasOAuthPermissionGap(readiness: OAuthReadiness | null): boolean {
  return Boolean(readiness && !readiness.ready && readiness.needs_reauth)
}

export function oauthMissingPermissionLabels(readiness: OAuthReadiness | null): string[] {
  if (!readiness) return []
  const labels = readiness.missing_scope_labels || []
  if (labels.length > 0) return labels
  return readiness.missing_scopes || []
}
