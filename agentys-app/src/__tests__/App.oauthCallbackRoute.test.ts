import { describe, expect, it } from 'vitest'
import {
  getBillingAiEnabled,
  shouldBypassPaidOnboardingForFreeUser,
  shouldRenderOAuthCallback,
} from '../App'

describe('OAuth callback route guard', () => {
  it('does not render stale OAuth callback state on inbox routes', () => {
    window.history.replaceState({}, '', '/inbox')

    expect(shouldRenderOAuthCallback(true)).toBe(false)
  })

  it('renders OAuth callback only on callback routes', () => {
    window.history.replaceState({}, '', '/oauth/callback?code=abc&state=xyz')

    expect(shouldRenderOAuthCallback(true)).toBe(true)
  })
})

describe('paid onboarding route guard', () => {
  it('lets a free user with an existing account enter the app shell', () => {
    expect(shouldBypassPaidOnboardingForFreeUser(false, 42, 'nat@example.com')).toBe(true)
    expect(shouldBypassPaidOnboardingForFreeUser(false, null, 'nat@example.com')).toBe(true)
  })

  it('keeps onboarding available when a free user has no email account yet', () => {
    expect(shouldBypassPaidOnboardingForFreeUser(false, null, null)).toBe(false)
  })

  it('prefers refreshed billing entitlement over legacy top-level fields', () => {
    expect(getBillingAiEnabled({
      ai_enabled: false,
      billing: { ai_enabled: true },
    })).toBe(true)
  })
})
