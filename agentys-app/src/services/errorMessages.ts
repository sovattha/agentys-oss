/**
 * Human-readable error messages with solutions
 *
 * Story 7-7: Plain Language Error Messages
 * - AC1: All user-facing error text is localized via i18n (errors:human.*)
 *        and resolves in the active UI language (fr / en / es).
 * - AC2: Each error proposes a concrete action
 * - AC3: No technical jargon (HTTP codes, stack traces)
 * - AC4: Contextual errors (e.g., "Unable to sync" vs "Error 500")
 * - AC5: "Technical details" option for advanced users
 * - AC6: Direct action buttons when possible (e.g., "Retry", "Open settings")
 *
 * The translatable strings live in `src/i18n/locales/<lng>/errors.json` under
 * the `human` key (one entry per ErrorCode, lower-cased). This module keeps
 * only the non-translatable metadata (severity, action type, delay) and
 * resolves text through i18next at call time so it follows the active language.
 */

import i18n from 'i18next'

export const ErrorCode = {
  // Network errors
  NETWORK_OFFLINE: 'NETWORK_OFFLINE',
  CONNECTION_FAILED: 'CONNECTION_FAILED',
  TIMEOUT: 'TIMEOUT',
  NETWORK_ERROR: 'NETWORK_ERROR',

  // Authentication errors
  AUTH_TOKEN_EXPIRED: 'AUTH_TOKEN_EXPIRED',
  UNAUTHORIZED: 'UNAUTHORIZED',
  FORBIDDEN: 'FORBIDDEN',
  OAUTH_REVOKED: 'OAUTH_REVOKED',
  INVALID_CREDENTIALS: 'INVALID_CREDENTIALS',

  // Sync errors
  SYNC_RATE_LIMITED: 'SYNC_RATE_LIMITED',
  SYNC_CONFLICT: 'SYNC_CONFLICT',
  GMAIL_QUOTA_EXCEEDED: 'GMAIL_QUOTA_EXCEEDED',
  OUTLOOK_QUOTA_EXCEEDED: 'OUTLOOK_QUOTA_EXCEEDED',

  // AI/Draft errors
  DRAFT_GENERATION_FAILED: 'DRAFT_GENERATION_FAILED',
  LLM_UNAVAILABLE: 'LLM_UNAVAILABLE',
  LLM_TIMEOUT: 'LLM_TIMEOUT',
  LLM_RATE_LIMITED: 'LLM_RATE_LIMITED',

  // Email errors
  SEND_FAILED: 'SEND_FAILED',
  INVALID_RECIPIENT: 'INVALID_RECIPIENT',
  EMAIL_BOUNCED: 'EMAIL_BOUNCED',
  EMAIL_PROVIDER_ERROR: 'EMAIL_PROVIDER_ERROR',

  // Server errors
  NOT_FOUND: 'NOT_FOUND',
  SERVER_ERROR: 'SERVER_ERROR',
  SERVICE_UNAVAILABLE: 'SERVICE_UNAVAILABLE',
  DRAFT_CREATION_FAILED: 'DRAFT_CREATION_FAILED',

  // Generic
  UNKNOWN: 'UNKNOWN',
} as const

export type ErrorCode = (typeof ErrorCode)[keyof typeof ErrorCode]

export type ErrorSeverity = 'error' | 'warning' | 'info'

export type ErrorActionType =
  | 'retry'
  | 'reconnect'
  | 'settings'
  | 'regenerate'
  | 'refresh'
  | 'wait'
  | 'contact_support'
  | 'custom'

export interface ErrorAction {
  label: string
  type: ErrorActionType
  /** Delay in minutes for 'wait' actions */
  delayMinutes?: number
  /** Custom handler name for 'custom' actions */
  handlerName?: string
}

export interface HumanError {
  code: ErrorCode
  title: string
  message: string
  solution: string
  severity: ErrorSeverity
  action?: ErrorAction
  technicalDetails?: string
}

/**
 * Non-translatable metadata per error code. The visible strings (title,
 * message, solution, action label) come from `errors:human.<code>.*`.
 * `action` here omits `label` — that is filled from i18n in getErrorMessage.
 */
interface ErrorMeta {
  severity: ErrorSeverity
  action?: Omit<ErrorAction, 'label'>
}

const ERROR_META: Record<ErrorCode, ErrorMeta> = {
  [ErrorCode.NETWORK_OFFLINE]: { severity: 'error', action: { type: 'retry' } },
  [ErrorCode.CONNECTION_FAILED]: { severity: 'error', action: { type: 'retry' } },
  [ErrorCode.TIMEOUT]: { severity: 'warning', action: { type: 'retry' } },
  [ErrorCode.NETWORK_ERROR]: { severity: 'error', action: { type: 'retry' } },

  [ErrorCode.AUTH_TOKEN_EXPIRED]: { severity: 'warning', action: { type: 'reconnect' } },
  [ErrorCode.UNAUTHORIZED]: { severity: 'warning', action: { type: 'settings' } },
  [ErrorCode.FORBIDDEN]: { severity: 'error' },
  [ErrorCode.OAUTH_REVOKED]: { severity: 'error', action: { type: 'reconnect' } },
  [ErrorCode.INVALID_CREDENTIALS]: { severity: 'error', action: { type: 'settings' } },

  [ErrorCode.SYNC_RATE_LIMITED]: { severity: 'warning', action: { type: 'wait', delayMinutes: 5 } },
  [ErrorCode.SYNC_CONFLICT]: { severity: 'warning', action: { type: 'refresh' } },
  [ErrorCode.GMAIL_QUOTA_EXCEEDED]: { severity: 'warning', action: { type: 'wait', delayMinutes: 60 } },
  [ErrorCode.OUTLOOK_QUOTA_EXCEEDED]: { severity: 'warning', action: { type: 'wait', delayMinutes: 60 } },

  [ErrorCode.DRAFT_GENERATION_FAILED]: { severity: 'error', action: { type: 'regenerate' } },
  [ErrorCode.LLM_UNAVAILABLE]: { severity: 'warning', action: { type: 'retry' } },
  [ErrorCode.LLM_TIMEOUT]: { severity: 'warning', action: { type: 'retry' } },
  [ErrorCode.LLM_RATE_LIMITED]: { severity: 'warning', action: { type: 'wait', delayMinutes: 2 } },

  [ErrorCode.SEND_FAILED]: { severity: 'error', action: { type: 'retry' } },
  [ErrorCode.INVALID_RECIPIENT]: { severity: 'error' },
  [ErrorCode.EMAIL_BOUNCED]: { severity: 'error' },
  [ErrorCode.EMAIL_PROVIDER_ERROR]: { severity: 'error', action: { type: 'settings' } },

  [ErrorCode.NOT_FOUND]: { severity: 'warning', action: { type: 'refresh' } },
  [ErrorCode.SERVER_ERROR]: { severity: 'error', action: { type: 'retry' } },
  [ErrorCode.SERVICE_UNAVAILABLE]: { severity: 'warning', action: { type: 'wait', delayMinutes: 1 } },
  [ErrorCode.DRAFT_CREATION_FAILED]: { severity: 'error', action: { type: 'settings' } },

  [ErrorCode.UNKNOWN]: { severity: 'error', action: { type: 'retry' } },
}

/**
 * Get a human-readable, localized error message from an error code.
 * Resolves title/message/solution/action label from `errors:human.<code>.*`
 * in the active language.
 */
export function getErrorMessage(code: ErrorCode, technicalDetails?: string): HumanError {
  const known: ErrorCode = code in ERROR_META ? code : ErrorCode.UNKNOWN
  const meta = ERROR_META[known]
  const base = `human.${known.toLowerCase()}`
  const tr = (suffix: string) => i18n.t(`${base}.${suffix}`, { ns: 'errors' })

  const action: ErrorAction | undefined = meta.action
    ? { ...meta.action, label: tr('action') }
    : undefined

  return {
    code,
    title: tr('title'),
    message: tr('message'),
    solution: tr('solution'),
    severity: meta.severity,
    action,
    technicalDetails,
  }
}

/**
 * Map HTTP status code to error code
 */
export function fromHttpStatus(status: number): ErrorCode {
  switch (status) {
    case 401:
      return ErrorCode.UNAUTHORIZED
    case 403:
      return ErrorCode.FORBIDDEN
    case 404:
      return ErrorCode.NOT_FOUND
    case 408:
      return ErrorCode.TIMEOUT
    case 429:
      return ErrorCode.SYNC_RATE_LIMITED
    case 500:
      return ErrorCode.SERVER_ERROR
    case 502:
    case 503:
    case 504:
      return ErrorCode.SERVICE_UNAVAILABLE
    default:
      return ErrorCode.UNKNOWN
  }
}

/**
 * Detect error code from network error
 */
export function fromNetworkError(error: Error): ErrorCode {
  const message = error.message.toLowerCase()

  // Check for offline/no connection
  if (
    (message.includes('network') && message.includes('offline')) ||
    message.includes('no internet') ||
    message.includes('net::err_internet_disconnected')
  ) {
    return ErrorCode.NETWORK_OFFLINE
  }

  // Check for fetch failures (connection refused, etc.)
  if (error instanceof TypeError && message.includes('fetch')) {
    return ErrorCode.CONNECTION_FAILED
  }

  // Check for timeout
  if (error.name === 'AbortError' || message.includes('timeout') || message.includes('timed out')) {
    return ErrorCode.TIMEOUT
  }

  // Check for DNS errors
  if (message.includes('dns') || message.includes('could not resolve')) {
    return ErrorCode.NETWORK_OFFLINE
  }

  return ErrorCode.NETWORK_ERROR
}

/**
 * Convert API error to human-readable error with context
 */
export function fromApiError(
  error: unknown,
  context?: 'email' | 'draft' | 'send' | 'health' | 'sync' | 'auth' | 'ai'
): HumanError {
  // Handle network errors
  if (error instanceof TypeError) {
    return getErrorMessage(fromNetworkError(error), error.message)
  }

  // Handle Error objects
  if (error instanceof Error) {
    const message = error.message.toLowerCase()

    // OAuth/Token errors
    if (
      (message.includes('token') && (message.includes('expired') || message.includes('invalid'))) ||
      (message.includes('oauth') && message.includes('revoked'))
    ) {
      return getErrorMessage(ErrorCode.AUTH_TOKEN_EXPIRED, error.message)
    }

    // Rate limiting
    if (
      message.includes('rate limit') ||
      message.includes('too many requests') ||
      message.includes('quota')
    ) {
      if (message.includes('gmail')) {
        return getErrorMessage(ErrorCode.GMAIL_QUOTA_EXCEEDED, error.message)
      }
      if (message.includes('outlook') || message.includes('microsoft')) {
        return getErrorMessage(ErrorCode.OUTLOOK_QUOTA_EXCEEDED, error.message)
      }
      if (context === 'ai' || message.includes('claude') || message.includes('llm')) {
        return getErrorMessage(ErrorCode.LLM_RATE_LIMITED, error.message)
      }
      return getErrorMessage(ErrorCode.SYNC_RATE_LIMITED, error.message)
    }

    // Email provider errors
    if (message.includes('imap') || message.includes('smtp') || message.includes('mail server')) {
      return getErrorMessage(ErrorCode.EMAIL_PROVIDER_ERROR, error.message)
    }

    // LLM/AI errors
    if (
      message.includes('llm') ||
      message.includes('claude') ||
      message.includes('ollama') ||
      message.includes('anthropic')
    ) {
      if (message.includes('timeout')) {
        return getErrorMessage(ErrorCode.LLM_TIMEOUT, error.message)
      }
      return getErrorMessage(ErrorCode.LLM_UNAVAILABLE, error.message)
    }

    // Context-specific errors
    if (context === 'draft') {
      return getErrorMessage(ErrorCode.DRAFT_GENERATION_FAILED, error.message)
    }

    if (context === 'send') {
      if (message.includes('invalid') && message.includes('recipient')) {
        return getErrorMessage(ErrorCode.INVALID_RECIPIENT, error.message)
      }
      if (message.includes('bounce')) {
        return getErrorMessage(ErrorCode.EMAIL_BOUNCED, error.message)
      }
      return getErrorMessage(ErrorCode.SEND_FAILED, error.message)
    }

    if (context === 'auth') {
      if (message.includes('credentials') || message.includes('password')) {
        return getErrorMessage(ErrorCode.INVALID_CREDENTIALS, error.message)
      }
      return getErrorMessage(ErrorCode.UNAUTHORIZED, error.message)
    }
  }

  // Default fallback
  const originalMessage = error instanceof Error ? error.message : String(error)
  return getErrorMessage(ErrorCode.UNKNOWN, originalMessage)
}

/**
 * Check if user is online
 */
export function isOnline(): boolean {
  return typeof navigator !== 'undefined' ? navigator.onLine : true
}

/**
 * Create an error for offline state
 */
export function createOfflineError(): HumanError {
  return getErrorMessage(ErrorCode.NETWORK_OFFLINE)
}
