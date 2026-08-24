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

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../i18n', () => ({
  default: { t: (k: string) => `T:${k}` },
}))

const invalidateEmailCacheSpy = vi.fn()
vi.mock('../api/emails', () => ({
  invalidateEmailCache: () => invalidateEmailCacheSpy(),
}))

import {
  emailActionFailureToastKey,
  handleEmailActionFailure,
  isEmailProviderAuthFailure,
} from './handleEmailPatchFailure'

interface ToastDetail { message: string; type: string; duration: number }
interface ActionFailedDetail { email_id: string; action: 'delete' | 'archive'; reason: string }
interface AuthExpiredDetail { provider: string }

describe('handleEmailActionFailure (F-01 regression fix)', () => {
  let dispatched: CustomEvent[] = []

  beforeEach(() => {
    invalidateEmailCacheSpy.mockClear()
    dispatched = []
    vi.spyOn(window, 'dispatchEvent').mockImplementation((evt) => {
      if (evt instanceof CustomEvent) dispatched.push(evt)
      return true
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('returns false and emits nothing when updates lacks failure flags', () => {
    const handled = handleEmailActionFailure('email-1', { is_read: true } as never)
    expect(handled).toBe(false)
    expect(dispatched).toHaveLength(0)
    expect(invalidateEmailCacheSpy).not.toHaveBeenCalled()
  })

  it('returns false on falsy `updates` payload', () => {
    // CustomEvent.detail can be null in degenerate cases — handler must not crash.
    expect(handleEmailActionFailure('e', null as unknown as never)).toBe(false)
    expect(handleEmailActionFailure('e', undefined as unknown as never)).toBe(false)
  })

  it('handles delete_failed: dispatches both events, invalidates cache, returns true', () => {
    const handled = handleEmailActionFailure('email-abc', {
      delete_failed: true,
      reason: 'provider_delete_returned_false',
    })

    expect(handled).toBe(true)
    expect(invalidateEmailCacheSpy).toHaveBeenCalledOnce()
    expect(dispatched).toHaveLength(2)

    const actionFailedEvt = dispatched.find(e => e.type === 'agentys:email-action-failed')
    expect(actionFailedEvt).toBeDefined()
    const actionFailedDetail = (actionFailedEvt as CustomEvent<ActionFailedDetail>).detail
    expect(actionFailedDetail.action).toBe('delete')
    expect(actionFailedDetail.email_id).toBe('email-abc')
    expect(actionFailedDetail.reason).toBe('provider_delete_returned_false')

    const toastEvt = dispatched.find(e => e.type === 'agentys:toast')
    expect(toastEvt).toBeDefined()
    const toastDetail = (toastEvt as CustomEvent<ToastDetail>).detail
    expect(toastDetail.message).toBe('T:common:toasts.email_delete_failed')
    expect(toastDetail.type).toBe('error')
    expect(toastDetail.duration).toBe(7000)
  })

  it('handles archive_failed: dispatches with action=archive', () => {
    const handled = handleEmailActionFailure('email-xyz', {
      archive_failed: true,
      reason: 'provider_archive_exception: IMAP timeout',
    })
    expect(handled).toBe(true)
    const actionFailedEvt = dispatched.find(e => e.type === 'agentys:email-action-failed')
    expect((actionFailedEvt as CustomEvent<ActionFailedDetail>).detail.action).toBe('archive')
    const toastEvt = dispatched.find(e => e.type === 'agentys:toast')
    expect((toastEvt as CustomEvent<ToastDetail>).detail.message).toBe('T:common:toasts.email_archive_failed')
  })

  it('maps OAuth failures to reconnect toast and auth-expired event', () => {
    const handled = handleEmailActionFailure('email-auth', {
      delete_failed: true,
      reason: 'invalid_grant: Token has been expired or revoked',
    })

    expect(handled).toBe(true)
    expect(dispatched).toHaveLength(3)

    const authEvt = dispatched.find(e => e.type === 'auth:token_expired')
    expect(authEvt).toBeDefined()
    expect((authEvt as CustomEvent<AuthExpiredDetail>).detail.provider).toBe('gmail')

    const toastEvt = dispatched.find(e => e.type === 'agentys:toast')
    expect((toastEvt as CustomEvent<ToastDetail>).detail.message).toBe('T:common:toasts.email_delete_reauth_required')
  })

  it('classifies insufficient scope failures as reauth-required', () => {
    const reason = 'HttpError 403: Request had insufficient authentication scopes.'

    expect(isEmailProviderAuthFailure(reason)).toBe(true)
    expect(emailActionFailureToastKey('archive', reason)).toBe('common:toasts.email_archive_reauth_required')
  })

  it('truncates reason to 200 chars to prevent unbounded payload in WS-event chain', () => {
    const longReason = 'X'.repeat(500)
    handleEmailActionFailure('e', { delete_failed: true, reason: longReason })
    const actionFailedEvt = dispatched.find(e => e.type === 'agentys:email-action-failed')
    const detail = (actionFailedEvt as CustomEvent<ActionFailedDetail>).detail
    expect(detail.reason.length).toBe(200)
  })

  it('handles missing/non-string reason gracefully', () => {
    handleEmailActionFailure('e', { delete_failed: true })
    const actionFailedEvt = dispatched.find(e => e.type === 'agentys:email-action-failed')
    expect((actionFailedEvt as CustomEvent<ActionFailedDetail>).detail.reason).toBe('')
  })

  it('delete_failed wins when both flags somehow set (no double dispatch)', () => {
    handleEmailActionFailure('e', { delete_failed: true, archive_failed: true })
    expect(dispatched).toHaveLength(2)
    const actionFailedEvt = dispatched.find(e => e.type === 'agentys:email-action-failed')
    expect((actionFailedEvt as CustomEvent<ActionFailedDetail>).detail.action).toBe('delete')
  })
})
