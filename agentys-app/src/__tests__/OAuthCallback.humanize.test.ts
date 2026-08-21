/**
 * Tests for humanizeOAuthError — focus on the AUTH-VULN-04 / issue #557
 * identity_invalid sub-cases. Without these, prod users saw the literal
 * string `identity_invalid` on the login screen with no actionable hint.
 */

import { describe, it, expect } from 'vitest'
import { humanizeOAuthError } from '../services/oauthErrors'

describe('humanizeOAuthError — identity_invalid sub-cases (#557)', () => {
  it('maps id_token_absent to a hard-reload hint (stale frontend)', () => {
    // This is the cause that hit prod between 2026-05-05 (backend defense)
    // and 2026-05-12 (frontend OIDC-scopes fix). Users on stale bundles
    // still see it days later until they bust their cache.
    const msg = humanizeOAuthError('identity_invalid', 'outlook', 'id_token_absent')
    expect(msg).toMatch(/à jour/i)
    expect(msg).toMatch(/Ctrl\+Maj\+R|Cmd\+Maj\+R/i)
  })

  it('maps id_token_unreadable to a retry hint', () => {
    const msg = humanizeOAuthError('identity_invalid', 'outlook', 'id_token_unreadable')
    expect(msg).toMatch(/mal formé/i)
    expect(msg).toMatch(/réessayer/i)
  })

  it('maps tenant_not_allowed to an IT-admin hint', () => {
    const msg = humanizeOAuthError('identity_invalid', 'outlook', 'tenant_not_allowed')
    expect(msg).toMatch(/tenant/i)
    expect(msg).toMatch(/administrateur/i)
  })

  it('maps oid_userinfo_mismatch to a contact-support hint', () => {
    const msg = humanizeOAuthError('identity_invalid', 'outlook', 'oid_userinfo_mismatch')
    expect(msg).toMatch(/identité/i)
    expect(msg).toMatch(/support/i)
  })

  it('falls back to a generic message when reason is missing', () => {
    // Belt-and-suspenders: if the backend ever forgets to send `reason`,
    // we must NOT show the opaque `identity_invalid` literal.
    const msg = humanizeOAuthError('identity_invalid', 'outlook')
    expect(msg).not.toBe('identity_invalid')
    expect(msg).toMatch(/identité/i)
  })

  it('falls back to a generic message when reason is empty/null', () => {
    expect(humanizeOAuthError('identity_invalid', 'outlook', '')).not.toBe('identity_invalid')
    expect(humanizeOAuthError('identity_invalid', 'outlook', null)).not.toBe('identity_invalid')
  })

  it('falls back to a generic message when reason key is unknown', () => {
    // Forward-compat: if the backend adds a new reason key tomorrow we
    // still want a usable message, not the raw code.
    const msg = humanizeOAuthError('identity_invalid', 'outlook', 'some_future_key')
    expect(msg).not.toBe('identity_invalid')
    expect(msg).not.toBe('some_future_key')
  })
})

describe('humanizeOAuthError — pre-existing behaviour preserved', () => {
  it('passes through unrelated errors unchanged (no false positive on reason arg)', () => {
    const msg = humanizeOAuthError('something else', 'outlook', 'id_token_absent')
    // reason is only honored when raw === 'identity_invalid'; otherwise
    // the existing pattern matchers run.
    expect(msg).toBe('something else')
  })

  it('still humanizes AADSTS codes', () => {
    const msg = humanizeOAuthError('AADSTS65001: consent required', 'outlook')
    expect(msg).toMatch(/Consentement administrateur/i)
    expect(msg).toMatch(/AADSTS65001/)
  })

  it('still humanizes "Malformed auth code" for outlook', () => {
    const msg = humanizeOAuthError('Malformed auth code.', 'outlook')
    expect(msg).toMatch(/rejeté par Microsoft/i)
  })

  it('returns generic fallback for empty input', () => {
    expect(humanizeOAuthError('', 'outlook')).toMatch(/connexion a échoué/i)
  })
})
