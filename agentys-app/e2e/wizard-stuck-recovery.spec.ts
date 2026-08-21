/**
 * Regression test: wizard must unblock after OAuth completes even if the
 * initial /api/init fetch happened before the backend registered the account.
 *
 * Guards the fix for "En attente des informations du compte..." stuck state.
 */
import { test, expect } from '@playwright/test'

const APP = 'http://localhost:1420'

test.describe('Wizard — En attente recovery', () => {
  test('auth:login_success event re-runs /api/init and unblocks the wizard', async ({ page }) => {
    // Track /api/init call count to verify the event triggers a re-fetch.
    let initCallCount = 0
    let returnAccounts = false

    await page.route('**/api/ping', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: '1.0.0' }) })
    )
    await page.route('**/api/init**', route => {
      initCallCount += 1
      const accounts = returnAccounts
        ? [{ id: 1, email: 'test@example.com', name: '', provider: 'gmail', status: 'active' }]
        : []
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          accounts,
          current_account_id: returnAccounts ? 1 : null,
          emails: { emails: [], has_more: false, source: 'sqlite' },
          label_counts: { counts: {}, total: 0 },
          pending_drafts: { drafts: [], pending_count: 0 },
          spam_count: 0,
        }),
      })
    })
    await page.route('**/api/wizard/status', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ onboarding_complete: false, has_config: false }),
      })
    )
    await page.route('**/api/auth/me', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: 1, email: 'test@example.com' }),
      })
    )

    // Seed localStorage with a valid JWT so auth boot thinks we're logged in.
    await page.addInitScript(() => {
      localStorage.setItem('agentys_auth_token', 'test-jwt-token')
      localStorage.removeItem('agentys_onboarding_complete')
      localStorage.removeItem('agentys_onboarding_kb_complete')
    })

    await page.goto(APP)
    await page.waitForLoadState('domcontentloaded')

    // Wait for the initial /api/init call to land.
    await expect.poll(() => initCallCount, { timeout: 10_000 }).toBeGreaterThanOrEqual(1)
    const initialCalls = initCallCount

    // Flip the mock to return an account, then fire the auth:login_success event
    // (simulates the OAuthCallback.onComplete path after /api/oauth/gmail/complete).
    returnAccounts = true
    await page.evaluate(() => {
      window.dispatchEvent(new CustomEvent('auth:login_success', { detail: { email: 'test@example.com' } }))
    })

    // The listener must re-run checkBackendAndOnboarding → /api/init called again.
    await expect.poll(() => initCallCount, { timeout: 5_000 }).toBeGreaterThan(initialCalls)
  })

  test('visibility change refreshes account data when wizard is stuck without accountId', async ({ page }) => {
    let initCallCount = 0

    await page.route('**/api/ping', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ version: '1.0.0' }) })
    )
    await page.route('**/api/init**', route => {
      initCallCount += 1
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          accounts: [],
          current_account_id: null,
          emails: { emails: [], has_more: false, source: 'sqlite' },
          label_counts: { counts: {}, total: 0 },
          pending_drafts: { drafts: [], pending_count: 0 },
          spam_count: 0,
        }),
      })
    })
    await page.route('**/api/wizard/status', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ onboarding_complete: false, has_config: false }),
      })
    )
    await page.route('**/api/auth/me', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: 1, email: 'test@example.com' }),
      })
    )

    await page.addInitScript(() => {
      localStorage.setItem('agentys_auth_token', 'test-jwt-token')
      localStorage.removeItem('agentys_onboarding_complete')
      localStorage.removeItem('agentys_onboarding_kb_complete')
    })

    await page.goto(APP)
    await page.waitForLoadState('domcontentloaded')
    await expect.poll(() => initCallCount, { timeout: 10_000 }).toBeGreaterThanOrEqual(1)
    const baseline = initCallCount

    // Simulate the user switching to another tab (OAuth flow), then coming back.
    // In a real browser this fires visibilitychange → onVisible → refreshAccountData.
    // We drive both events manually because Playwright's tab-switching is flaky in CI.
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' })
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await page.waitForTimeout(200)
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
      document.dispatchEvent(new Event('visibilitychange'))
      window.dispatchEvent(new Event('focus'))
    })

    // At least one more /api/init call should fire (refreshAccountData from visibility).
    await expect.poll(() => initCallCount, { timeout: 5_000 }).toBeGreaterThan(baseline)
  })
})
