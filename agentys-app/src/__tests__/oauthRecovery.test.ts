/**
 * Tests for attemptStaleBundleRecovery (#557 follow-up, audit 2026-05-15).
 *
 * The recovery helper transparently bursts a user's browser cache when the
 * backend rejects with `identity_invalid/id_token_absent` — the signature
 * of a pre-2026-05-12 bundle that doesn't request OIDC scopes. Without
 * this, support would have to walk every affected user through Ctrl+Shift+R.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { attemptStaleBundleRecovery } from '../services/oauthRecovery'

describe('attemptStaleBundleRecovery', () => {
  let replaceSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
    sessionStorage.clear()
    replaceSpy = vi.fn()
    Object.defineProperty(window, 'location', {
      value: {
        href: 'https://app.agentys.io/',
        replace: replaceSpy,
      },
      writable: true,
    })
  })

  afterEach(() => {
    sessionStorage.clear()
  })

  it('reloads with cache-buster when reason is id_token_absent', () => {
    const recovered = attemptStaleBundleRecovery('id_token_absent')
    expect(recovered).toBe(true)
    expect(replaceSpy).toHaveBeenCalledTimes(1)
    const target = String(replaceSpy.mock.calls[0][0])
    expect(target).toMatch(/_oauth_recover=/)
  })

  it('does not reload for other identity_invalid sub-cases', () => {
    // tenant_not_allowed / oid_userinfo_mismatch / id_token_unreadable
    // are legitimate rejections — reloading the page won't help and would
    // just thrash the user.
    expect(attemptStaleBundleRecovery('tenant_not_allowed')).toBe(false)
    expect(attemptStaleBundleRecovery('oid_userinfo_mismatch')).toBe(false)
    expect(attemptStaleBundleRecovery('id_token_unreadable')).toBe(false)
    expect(replaceSpy).not.toHaveBeenCalled()
  })

  it('does not reload when reason is missing or null', () => {
    expect(attemptStaleBundleRecovery(undefined)).toBe(false)
    expect(attemptStaleBundleRecovery(null)).toBe(false)
    expect(attemptStaleBundleRecovery('')).toBe(false)
    expect(replaceSpy).not.toHaveBeenCalled()
  })

  it('only attempts recovery once per session (loop guard)', () => {
    // First call reloads.
    expect(attemptStaleBundleRecovery('id_token_absent')).toBe(true)
    expect(replaceSpy).toHaveBeenCalledTimes(1)
    // Second call in the same session must NOT reload again — otherwise
    // a backend that's broken in a way the reload can't fix would lock
    // the user in an infinite refresh loop.
    expect(attemptStaleBundleRecovery('id_token_absent')).toBe(false)
    expect(replaceSpy).toHaveBeenCalledTimes(1)
  })
})
