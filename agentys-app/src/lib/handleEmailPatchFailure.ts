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
 * F-01 (audit regressions 2026-05-17 batch4): the backend B-02 fix wires an
 * `email_updated` WS event with `{delete_failed|archive_failed: true}` when
 * the bg provider DELETE/archive fails AFTER the optimistic 200 has already
 * been returned. Pre-batch4 the FE consumer was `setEmails(prev =>
 * prev.map(...))` on a row that `email_deleted`/`email_archived` had
 * already removed — a no-op. The user saw nothing; next sync resurrected
 * the email; trust eroded.
 *
 * This helper centralises the failure-flag detection so the inbox component
 * and any future consumer (e.g. the Sent view if delete_failed gets wired
 * there too) handle it identically and Codex can audit one path. It is
 * intentionally extracted from EmailList.tsx into a pure module so vitest
 * can verify the dispatch contract without rendering the inbox.
 */
import i18n from '../i18n'
import { invalidateEmailCache } from '../api/emails'

export interface EmailPatchFailureUpdates {
  delete_failed?: boolean
  archive_failed?: boolean
  reason?: string
}

export type EmailPatchAction = 'delete' | 'archive'

const EMAIL_PROVIDER_AUTH_FAILURE_REASONS = [
  /invalid_grant/i,
  /invalid refresh token/i,
  /expired or revoked/i,
  /expired scopes/i,
  /token has been expired/i,
  /unauthorized/i,
  /email provider authentication failed/i,
  /oauth .*auth.*fail/i,
  /insufficient authentication scopes/i,
  /insufficientpermissions/i,
  /insufficient permissions/i,
  /scopes insuffisants/i,
  /consent_required/i,
  /interaction_required/i,
  /aadsts\d+/i,
]

export function isEmailProviderAuthFailure(reason: string): boolean {
  const trimmedReason = reason.trim()
  if (!trimmedReason) return false
  return EMAIL_PROVIDER_AUTH_FAILURE_REASONS.some(pattern => pattern.test(trimmedReason))
}

export function emailActionFailureToastKey(action: EmailPatchAction, reason: string): string {
  if (isEmailProviderAuthFailure(reason)) {
    return `common:toasts.email_${action}_reauth_required`
  }
  return `common:toasts.email_${action}_failed`
}

export function emitEmailProviderAuthExpired(reason: string): void {
  if (typeof window === 'undefined') return

  const lowerReason = reason.toLowerCase()
  const provider = lowerReason.includes('outlook') || lowerReason.includes('microsoft') || lowerReason.includes('aadsts')
    ? 'outlook'
    : lowerReason.includes('imap')
      ? 'imap'
      : 'gmail'

  window.dispatchEvent(new CustomEvent('auth:token_expired', {
    detail: { provider },
  }))
}

/**
 * If `updates` carries a failure flag, surface it (toast + cache invalidate +
 * refresh event) and return `true` so the caller can short-circuit its
 * normal patch logic. Otherwise return `false` and let the caller proceed.
 */
export function handleEmailActionFailure(
  email_id: string,
  updates: EmailPatchFailureUpdates,
): boolean {
  if (!updates) return false
  const isDeleteFailed = updates.delete_failed === true
  const isArchiveFailed = updates.archive_failed === true
  if (!isDeleteFailed && !isArchiveFailed) return false

  const action: EmailPatchAction = isDeleteFailed ? 'delete' : 'archive'
  const reason = typeof updates.reason === 'string' ? updates.reason.slice(0, 200) : ''
  console.warn(`[handleEmailActionFailure] ${action} failed for ${email_id}: ${reason || 'no reason given'}`)

  invalidateEmailCache()

  if (typeof window !== 'undefined') {
    if (isEmailProviderAuthFailure(reason)) {
      emitEmailProviderAuthExpired(reason)
    }
    window.dispatchEvent(new CustomEvent('agentys:email-action-failed', {
      detail: { email_id, action, reason },
    }))
    window.dispatchEvent(new CustomEvent('agentys:toast', {
      detail: {
        message: i18n.t(emailActionFailureToastKey(action, reason)),
        type: 'error',
        duration: 7000,
      },
    }))
  }
  return true
}
