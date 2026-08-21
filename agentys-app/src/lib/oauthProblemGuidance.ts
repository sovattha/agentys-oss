export type OAuthProblemKey =
  | 'missing_scopes'
  | 'callback_loop'
  | 'wrong_account'
  | 'popup_blocked'

export interface OAuthErrorGuidance {
  provider: 'gmail' | 'outlook' | 'unknown'
  defaultProblem: OAuthProblemKey
}

const MISSING_SCOPE_PATTERNS = [
  /^reauth_required$/i,
  /insufficient authentication scopes/i,
  /insufficientpermissions/i,
  /insufficient permissions/i,
  /access_token_scope_insufficient/i,
  /insufficientscope/i,
  /scopes insuffisants/i,
  /permission.*scope/i,
]

const CALLBACK_LOOP_PATTERNS = [
  /invalid oauth result/i,
  /oauth.*invalid result/i,
  /oauth.*callback/i,
  /state.*mismatch/i,
  /missing.*code/i,
]

const POPUP_PATTERNS = [
  /popup/i,
  /pop-up/i,
  /fenêtre.*bloqu/i,
  /blocked.*window/i,
]

const WRONG_ACCOUNT_PATTERNS = [
  /wrong account/i,
  /mauvais compte/i,
  /account.*mismatch/i,
  /compte.*différent/i,
]

function detectProvider(message: string): OAuthErrorGuidance['provider'] {
  const lower = message.toLowerCase()
  if (lower.includes('outlook') || lower.includes('microsoft') || lower.includes('aadsts')) {
    return 'outlook'
  }
  if (lower.includes('gmail') || lower.includes('google') || lower.includes('googleapis')) {
    return 'gmail'
  }
  return 'unknown'
}

function matchesAny(message: string, patterns: RegExp[]): boolean {
  return patterns.some(pattern => pattern.test(message))
}

export function detectOAuthErrorGuidance(error: string | null | undefined): OAuthErrorGuidance | null {
  const message = error?.trim()
  if (!message) return null

  const provider = detectProvider(message)
  if (matchesAny(message, MISSING_SCOPE_PATTERNS)) {
    return { provider, defaultProblem: 'missing_scopes' }
  }
  if (matchesAny(message, CALLBACK_LOOP_PATTERNS)) {
    return { provider, defaultProblem: 'callback_loop' }
  }
  if (matchesAny(message, POPUP_PATTERNS)) {
    return { provider, defaultProblem: 'popup_blocked' }
  }
  if (matchesAny(message, WRONG_ACCOUNT_PATTERNS)) {
    return { provider, defaultProblem: 'wrong_account' }
  }
  if (/oauth/i.test(message) && /(auth|token|grant|permission|scope|consent)/i.test(message)) {
    return { provider, defaultProblem: 'missing_scopes' }
  }
  return null
}
