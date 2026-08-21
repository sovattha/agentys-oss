/**
 * OAuth error humanization (#557 follow-up, audit 2026-05-15).
 *
 * Lives outside the component file because:
 *   1. Unit-testable in isolation (no React/JSDom required for the logic).
 *   2. Avoids react-refresh/only-export-components ESLint violation.
 *   3. Reusable from any component that surfaces OAuth errors.
 *
 * User-facing strings are localized via i18n (`errors:oauth.*`) so they
 * follow the active UI language (fr / en / es).
 */

import i18n from 'i18next'

const t = (key: string) => i18n.t(key, { ns: 'errors' })

/**
 * AUTH-VULN-04 / issue #557: backend `_validate_outlook_identity()` rejects
 * with `error=identity_invalid` + a granular `reason` key. Mapping each key
 * to an actionable message keeps support out of Sentry for the common cases.
 *
 * `identity_invalid` (no reason) is the fallback when the backend couldn't
 * categorize the reject — surface a generic but recognisable message.
 */
const IDENTITY_INVALID_KEYS: Record<string, string> = {
  // Microsoft did not issue an id_token — almost always means the frontend
  // bundle in the user's browser predates the 2026-05-12 OIDC-scopes fix
  // (#557). A hard reload busts the cache.
  id_token_absent: 'oauth.identity_id_token_absent',
  id_token_unreadable: 'oauth.identity_id_token_unreadable',
  tenant_not_allowed: 'oauth.identity_tenant_not_allowed',
  oid_userinfo_mismatch: 'oauth.identity_invalid_generic',
}

const AADSTS_KEYS: Record<string, string> = {
  '50011': 'oauth.aadsts_50011',
  '50194': 'oauth.aadsts_50194',
  '50020': 'oauth.aadsts_50020',
  '65001': 'oauth.aadsts_65001',
  '70008': 'oauth.aadsts_70008',
  '54005': 'oauth.aadsts_54005',
  '700016': 'oauth.aadsts_700016',
  '900971': 'oauth.aadsts_900971',
  '9002313': 'oauth.aadsts_9002313',
}

/**
 * Translate raw OAuth error_description (often a Microsoft AADSTS code or a
 * terse text like "Malformed auth code.") into an actionable user-facing
 * message. When the backend gave us a granular `reason` (identity_invalid
 * sub-case), that takes precedence. Falls back to the raw text when nothing
 * matches.
 */
export function humanizeOAuthError(
  raw: string,
  provider: string,
  reason?: string | null,
): string {
  const text = (raw || '').trim()
  // Granular identity_invalid mapping (#557). Even when the backend forgot
  // to include a `reason`, surface a recognisable fallback instead of the
  // raw code so the login screen doesn't show literal `identity_invalid`.
  if (text === 'identity_invalid') {
    const key = (reason || '').trim()
    return t(IDENTITY_INVALID_KEYS[key] || 'oauth.identity_invalid_generic')
  }
  if (!text) return t('oauth.connection_failed_generic')
  // Microsoft AADSTS codes — surface the most common ones with a hint.
  const aadsts = text.match(/AADSTS(\d+)/)
  if (aadsts) {
    const code = aadsts[1]
    if (AADSTS_KEYS[code]) return `${t(AADSTS_KEYS[code])} (AADSTS${code})`
  }
  const lower = text.toLowerCase()
  if (lower.includes('malformed') && lower.includes('code')) {
    return provider === 'outlook'
      ? t('oauth.malformed_code_outlook')
      : t('oauth.malformed_code_generic')
  }
  if (lower.includes('already redeemed') || lower.includes('already been used')) {
    return t('oauth.already_used')
  }
  if (lower.includes('expired')) {
    return t('oauth.expired_generic')
  }
  if (lower.includes('redirect_uri') || lower.includes('redirect uri')) {
    return t('oauth.redirect_uri_mismatch')
  }
  // Default: pass through but trim verbose AADSTS preamble for readability.
  return text.replace(/^AADSTS\d+:\s*/, '').slice(0, 240)
}
