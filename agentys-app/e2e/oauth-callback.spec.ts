/**
 * OAuth Callback E2E Tests
 *
 * Tests for OAuthCallback.tsx — the page displayed after OAuth redirect.
 * All API calls are mocked via page.route().
 */

import { test, expect, Page } from '@playwright/test'

const API_ORIGINS = new Set([
  'http://localhost:5050',
  'http://127.0.0.1:5050',
])
const VITE_ORIGINS = new Set([
  'http://localhost:1420',
  'http://127.0.0.1:1420',
])

function isBackendApi(url: URL) {
  return API_ORIGINS.has(url.origin) ||
    (VITE_ORIGINS.has(url.origin) && url.pathname.startsWith('/api/'))
}

function apiPath(path: string) {
  return (url: URL) => isBackendApi(url) && url.pathname === path
}

function apiPathPrefix(prefix: string) {
  return (url: URL) => isBackendApi(url) && url.pathname.startsWith(prefix)
}

/**
 * Setup common mocks for OAuth callback tests.
 * Mocks auth endpoints so the app doesn't redirect to login.
 */
async function setupOAuthMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  // Catch-all for API (return empty JSON by default)
  await page.route((url) => isBackendApi(url), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })

  // Auth verify — allow (simulate logged-in state)
  await page.route(apiPath('/api/auth/verify'), (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ valid: true, user: { email: 'test@example.com' } }),
    })
  })

  await page.route(apiPath('/api/auth/me'), (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ user: { email: 'test@example.com', id: 1 } }),
    })
  })
}

// =============================================================================
// Group 1: OAuth Callback - Success (backend redirect)
// =============================================================================

test.describe('OAuth Callback - Success (backend redirect)', () => {
  test('displays success for Outlook', async ({ page }) => {
    await setupOAuthMocks(page)
    await page.goto(
      '/oauth/callback?provider=outlook&success=true&email=user@outlook.com&account_id=abc123'
    )

    await expect(page.locator('.oauth-callback-title')).toHaveText('Connected!', {
      timeout: 10000,
    })
    await expect(page.locator('.oauth-callback-message')).toContainText(
      'user@outlook.com'
    )
  })

  test('displays success for Gmail', async ({ page }) => {
    await setupOAuthMocks(page)
    await page.goto(
      '/oauth/callback?provider=gmail&success=true&email=user@gmail.com&account_id=def456'
    )

    await expect(page.locator('.oauth-callback-title')).toHaveText('Connected!', {
      timeout: 10000,
    })
    await expect(page.locator('.oauth-callback-message')).toContainText(
      'user@gmail.com'
    )
  })
})

// =============================================================================
// Group 2: OAuth Callback - Code exchange (SPA flow)
// =============================================================================

test.describe('OAuth Callback - Code exchange (SPA flow)', () => {
  test('exchanges code for Outlook via /complete', async ({ page }) => {
    await setupOAuthMocks(page)

    // Store PKCE verifier in localStorage (simulating what LoginPage does)
    await page.addInitScript(() => {
      localStorage.setItem('pkce_verifier_state_test', 'test_verifier')
      localStorage.setItem('pkce_provider_state_test', 'outlook')
    })

    // Mock the /outlook/complete endpoint
    await page.route(apiPath('/api/oauth/outlook/complete'), (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          email: 'user@outlook.com',
          account_id: 'acc_123',
          token: 'jwt_token',
        }),
      })
    })

    await page.goto('/oauth/callback?code=outlook_code&state=state_test')

    await expect(page.locator('.oauth-callback-title')).toHaveText('Connected!', {
      timeout: 10000,
    })
    await expect(page.locator('.oauth-callback-message')).toContainText(
      'user@outlook.com'
    )
  })

  test('exchanges code for Gmail via /complete', async ({ page }) => {
    await setupOAuthMocks(page)

    await page.addInitScript(() => {
      localStorage.setItem('pkce_verifier_state_gmail', 'gmail_verifier')
      localStorage.setItem('pkce_provider_state_gmail', 'gmail')
    })

    await page.route(apiPath('/api/oauth/gmail/complete'), (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          email: 'user@gmail.com',
          account_id: 'gmail_acc',
          token: 'jwt_gmail',
        }),
      })
    })

    await page.goto('/oauth/callback?code=gmail_code&state=state_gmail')

    await expect(page.locator('.oauth-callback-title')).toHaveText('Connected!', {
      timeout: 10000,
    })
    await expect(page.locator('.oauth-callback-message')).toContainText(
      'user@gmail.com'
    )
  })

  test('handles backend error during exchange', async ({ page }) => {
    await setupOAuthMocks(page)

    await page.addInitScript(() => {
      localStorage.setItem('pkce_verifier_state_err', 'err_verifier')
      localStorage.setItem('pkce_provider_state_err', 'outlook')
    })

    await page.route(apiPath('/api/oauth/outlook/complete'), (route) => {
      route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'invalid_grant: Code has expired' }),
      })
    })

    await page.goto('/oauth/callback?code=bad_code&state=state_err')

    await expect(page.locator('.oauth-callback-title')).toHaveText('Error', {
      timeout: 10000,
    })
    await expect(page.locator('.oauth-callback-message')).toContainText(
      'Authorization expired'
    )
  })

  test('handles unreachable backend', async ({ page }) => {
    await setupOAuthMocks(page)

    await page.addInitScript(() => {
      localStorage.setItem('pkce_verifier_state_down', 'down_verifier')
      localStorage.setItem('pkce_provider_state_down', 'outlook')
    })

    // Make the /complete endpoint abort (simulating unreachable backend)
    await page.route(apiPath('/api/oauth/outlook/complete'), (route) => {
      route.abort('connectionrefused')
    })

    // Also abort the PKCE fallback fetch
    await page.route(apiPathPrefix('/api/oauth/pkce/'), (route) => {
      route.abort('connectionrefused')
    })

    await page.goto('/oauth/callback?code=some_code&state=state_down')

    await expect(page.locator('.oauth-callback-title')).toHaveText('Error', {
      timeout: 10000,
    })
    await expect(page.locator('.oauth-callback-message')).toContainText(
      'backend'
    )
  })
})

// =============================================================================
// Group 3: OAuth Callback - Mobile Safari fallback (no window.opener)
// =============================================================================

test.describe('OAuth Callback - Mobile Safari fallback', () => {
  test('shows "Redirecting" message when no window.opener (same-tab flow)', async ({ page }) => {
    await setupOAuthMocks(page)

    // Use backend-redirect flow (query params) — no window.opener in Playwright
    await page.goto(
      '/oauth/callback?provider=gmail&success=true&email=mobile@gmail.com&account_id=mob1&token=jwt_mob'
    )

    await expect(page.locator('.oauth-callback-title')).toHaveText('Connected!', {
      timeout: 10000,
    })

    // Without window.opener, should show "Redirecting" not "window will close"
    await expect(page.locator('.oauth-callback-hint')).toContainText('Redirecting', {
      timeout: 5000,
    })
  })

  test('shows Return to Agentys button immediately on success', async ({ page }) => {
    await setupOAuthMocks(page)

    await page.goto(
      '/oauth/callback?provider=gmail&success=true&email=btn@gmail.com&account_id=btn1&token=jwt_btn'
    )

    await expect(page.locator('.oauth-callback-title')).toHaveText('Connected!', {
      timeout: 10000,
    })

    // Button visible immediately on success (no-opener flow = same-tab / mobile)
    await expect(page.locator('.oauth-callback-return-btn')).toBeVisible({
      timeout: 3000,
    })
    await expect(page.locator('.oauth-callback-return-btn')).toHaveText('Return to Agentys')
  })

  test('countdown completes and leaves OAuth screen (Safari mobile fix)', async ({ page }) => {
    await setupOAuthMocks(page)

    await page.goto(
      '/oauth/callback?provider=gmail&success=true&email=safari@gmail.com&account_id=saf1&token=jwt_saf'
    )

    await expect(page.locator('.oauth-callback-title')).toHaveText('Connected!', {
      timeout: 10000,
    })

    // Core Safari mobile fix: after 2s countdown + onComplete, the callback screen
    // must disappear (component unmounts). Without the fix, it stays stuck forever.
    await expect(page.locator('.oauth-callback')).not.toBeAttached({ timeout: 8000 })
  })

  test('Return to Agentys button navigates away from callback', async ({ page }) => {
    await setupOAuthMocks(page)

    await page.goto(
      '/oauth/callback?provider=gmail&success=true&email=click@gmail.com&account_id=clk1&token=jwt_clk'
    )

    await expect(page.locator('.oauth-callback-title')).toHaveText('Connected!', {
      timeout: 10000,
    })
    await expect(page.locator('.oauth-callback-return-btn')).toBeVisible({ timeout: 3000 })

    // Click the manual fallback button — should leave the OAuth callback screen
    await page.locator('.oauth-callback-return-btn').click()
    await expect(page.locator('.oauth-callback')).not.toBeAttached({ timeout: 5000 })
  })

  test('never shows "window will close" when no opener', async ({ page }) => {
    await setupOAuthMocks(page)

    await page.goto(
      '/oauth/callback?provider=gmail&success=true&email=noop@gmail.com&account_id=no1&token=jwt_no'
    )

    await expect(page.locator('.oauth-callback-title')).toHaveText('Connected!', {
      timeout: 10000,
    })

    // Must show "Redirecting", never "window will close" on same-tab/mobile
    const hintText = await page.locator('.oauth-callback-hint').textContent()
    expect(hintText).not.toContain('window will close')
    expect(hintText).toContain('Redirecting')
  })
})

// =============================================================================
// Group 3b: OAuth Callback - Popup flow where window.close() fails (mobile Safari)
// =============================================================================

test.describe('OAuth Callback - window.close() failure fallback', () => {
  test('shows Return to Agentys button when window.close() fails', async ({ page }) => {
    await setupOAuthMocks(page)

    // Simulate window.opener existing (popup flow) but window.close() being a no-op
    await page.addInitScript(() => {
      Object.defineProperty(window, 'opener', {
        value: { closed: false },
        writable: false,
      })
      window.close = () => { /* no-op — simulates Safari blocking close */ }
    })

    await page.goto(
      '/oauth/callback?provider=gmail&success=true&email=safari@gmail.com&account_id=saf1&token=jwt_saf'
    )

    await expect(page.locator('.oauth-callback-title')).toHaveText('Connected!', {
      timeout: 10000,
    })

    // Initially shows "window will close" (popup detected)
    await expect(page.locator('.oauth-callback-hint')).toContainText('window will close', {
      timeout: 3000,
    })

    // After countdown + close failure, button should appear
    await expect(page.locator('.oauth-callback-return-btn')).toBeVisible({
      timeout: 10000,
    })
    await expect(page.locator('.oauth-callback-return-btn')).toHaveText('Return to Agentys')
  })
})

// =============================================================================
// Group 4: OAuth Callback - Error handling
// =============================================================================

test.describe('OAuth Callback - Error handling', () => {
  test('displays error param', async ({ page }) => {
    await setupOAuthMocks(page)
    await page.goto('/oauth/callback?error=access_denied&provider=outlook')

    await expect(page.locator('.oauth-callback-title')).toHaveText('Error', {
      timeout: 10000,
    })
    // Should show the known error message for access_denied
    await expect(page.locator('.oauth-callback-message')).toContainText(
      'denied'
    )
  })

  test('displays error_description', async ({ page }) => {
    await setupOAuthMocks(page)
    await page.goto(
      '/oauth/callback?error=invalid_grant&error_description=Code%20expired&provider=outlook'
    )

    await expect(page.locator('.oauth-callback-title')).toHaveText('Error', {
      timeout: 10000,
    })
    await expect(page.locator('.oauth-callback-message')).toContainText(
      'Authorization expired'
    )
  })

  test('invalid OAuth result (no params)', async ({ page }) => {
    await setupOAuthMocks(page)
    await page.goto('/oauth/callback')

    await expect(page.locator('.oauth-callback-title')).toHaveText('Error', {
      timeout: 10000,
    })
    await expect(page.locator('.oauth-callback-message')).toContainText(
      'Invalid OAuth result'
    )
  })
})

// =============================================================================
// Group 5: Full mobile OAuth flow — same-tab, no popup (regression for #Safari-stuck)
// =============================================================================

test.describe('OAuth Full Mobile Flow — same-tab auth', () => {
  // Retry once — this test depends on Vite dev server module cache being warm.
  // First run after code changes can fail due to HMR latency.
  test.describe.configure({ retries: 1 })

  /**
   * Core regression test: after OAuth success on mobile (same-tab, no window.opener),
   * the user must land on the main app — NOT back on the login page.
   *
   * Root cause fixed: OAuthCallback now passes auth data to onComplete(),
   * which calls auth.loginWithToken() directly — no full page reload needed.
   */
  test('user does NOT land on login page after OAuth callback', async ({ page }) => {
    await setupOAuthMocks(page)

    // Step 1: Navigate to OAuth callback (simulating Google redirecting back to app)
    // No window.opener in Playwright = same-tab flow (like mobile Safari)
    await page.goto(
      '/oauth/callback?provider=gmail&success=true&email=mobile@gmail.com&account_id=acc_1&token=fake_jwt_for_test'
    )

    // Step 2: "Connected!" screen appears
    await expect(page.locator('.oauth-callback-title')).toHaveText('Connected!', {
      timeout: 10000,
    })

    // Step 3: OAuth callback completes (countdown + onComplete)
    // After fix: onComplete passes auth data → loginWithOAuth sets isAuthenticated=true
    await expect(page.locator('.oauth-callback')).not.toBeAttached({ timeout: 8000 })

    // Step 4: User must NOT be on the login page — this was the bug
    // Before fix: useAuth's useEffect([]) already ran when no JWT existed,
    // so isAuthenticated stayed false after OAuthCallback stored the JWT.
    await expect(page.locator('.login-page')).not.toBeAttached({ timeout: 5000 })
  })

  test('JWT is stored in localStorage after callback', async ({ page }) => {
    await setupOAuthMocks(page)

    await page.goto(
      '/oauth/callback?provider=gmail&success=true&email=jwt@gmail.com&account_id=acc_jwt&token=test_jwt_token_123'
    )

    await expect(page.locator('.oauth-callback-title')).toHaveText('Connected!', {
      timeout: 10000,
    })

    // Verify JWT was stored in localStorage
    const storedToken = await page.evaluate(() => localStorage.getItem('agentys_jwt'))
    expect(storedToken).toBe('test_jwt_token_123')
  })

  test('no unnecessary page reload after successful auth (same-tab)', async ({ page }) => {
    await setupOAuthMocks(page)

    // Track full navigations (window.location.replace causes one)
    let navigationCount = 0
    page.on('load', () => { navigationCount++ })

    await page.goto(
      '/oauth/callback?provider=gmail&success=true&email=noreload@gmail.com&account_id=acc_nr&token=jwt_nr'
    )
    navigationCount = 0 // Reset after initial goto

    await expect(page.locator('.oauth-callback-title')).toHaveText('Connected!', {
      timeout: 10000,
    })

    // Wait for callback to complete
    await expect(page.locator('.oauth-callback')).not.toBeAttached({ timeout: 8000 })

    // After fix: no unnecessary page reload since auth state was updated via React
    // (window.location.replace is skipped when authData was passed successfully)
    await page.waitForTimeout(1000)
    expect(navigationCount).toBe(0)
  })
})
