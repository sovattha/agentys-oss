/**
 * OAuth Troubleshooting Panel — E2E
 *
 * Reproduces the failure modes Carol Migneault hit: popup blocker silently
 * preventing the OAuth flow. Verifies the new pre-flight detection +
 * `OAuthTroubleshootingPanel` surface clear UX instead of a silent stall.
 *
 * Two scenarios:
 *   1. Popup blocker → window.open returns null → "popup blocked, redirecting…"
 *      brief notice + same-tab navigation to Google's OAuth URL.
 *   2. Stalled polling (postMessage dropped by COOP / 3p-cookies) → after ~16s
 *      the panel shows "[Use redirect flow instead] / [Cancel]" CTAs.
 *
 * We do NOT test the full Google consent screen — that requires real
 * credentials and is blocked by Google's anti-automation. We intercept the
 * redirect to confirm the URL is correctly constructed.
 */

import { test, expect, Page } from '@playwright/test'

const API = 'http://127.0.0.1:5050'
const API_LOCALHOST = 'http://localhost:5050'
const API_VITE = 'http://localhost:1420'
const GOOGLE_OAUTH = 'https://accounts.google.com/o/oauth2/v2/auth'

async function setupUnauthMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  const catchAll = (route: import('@playwright/test').Route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  }
  await page.route((url) => url.origin === API, catchAll)
  await page.route((url) => url.origin === API_LOCALHOST, catchAll)
  await page.route(
    (url) => url.origin === API_VITE && url.pathname.startsWith('/api/'),
    catchAll,
  )

  // Ensure user is treated as unauthenticated so LoginPage renders.
  const unauthorized = (route: import('@playwright/test').Route) => {
    route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ error: 'Unauthorized' }),
    })
  }
  await page.route(`${API}/api/auth/me`, unauthorized)
  await page.route(`${API_LOCALHOST}/api/auth/me`, unauthorized)
  await page.route(`${API_VITE}/api/auth/me`, unauthorized)
  await page.route(`${API}/api/auth/verify`, unauthorized)
  await page.route(`${API_LOCALHOST}/api/auth/verify`, unauthorized)
  await page.route(`${API_VITE}/api/auth/verify`, unauthorized)

  // Health check passes so the OAuth pre-flight allows the popup to open.
  const healthOk = (route: import('@playwright/test').Route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'ok' }),
    })
  }
  await page.route(`${API}/api/health`, healthOk)
  await page.route(`${API_LOCALHOST}/api/health`, healthOk)
  await page.route(`${API_VITE}/api/health`, healthOk)

  const pkceOk = (route: import('@playwright/test').Route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true }),
    })
  }
  await page.route(`${API}/api/oauth/pkce/store`, pkceOk)
  await page.route(`${API_LOCALHOST}/api/oauth/pkce/store`, pkceOk)
  await page.route(`${API_VITE}/api/oauth/pkce/store`, pkceOk)
}

test.describe('OAuth Troubleshooting — popup blocker', () => {
  test('shows "popup blocked, redirecting…" notice and triggers same-tab redirect', async ({ page }) => {
    await setupUnauthMocks(page)

    // Stub window.open to return null — Chrome's popup blocker behavior.
    // Must be installed before any user code runs.
    await page.addInitScript(() => {
      const origOpen = window.open
      Object.defineProperty(window, 'open', {
        configurable: true,
        writable: true,
        value: function (url?: string | URL, target?: string) {
          // Only fail OAuth-targeted opens; let any other window.open behave.
          if (target === 'oauth-popup') return null
          return origOpen?.call(window, url, target)
        },
      })
    })

    // Intercept the eventual Google OAuth navigation so the test page doesn't
    // actually leave the dev server. Capture the URL for assertions.
    let capturedAuthUrl: string | null = null
    await page.route(
      (url) => url.toString().startsWith(GOOGLE_OAUTH),
      (route) => {
        capturedAuthUrl = route.request().url()
        // Return a tiny page so navigation completes locally without errors.
        route.fulfill({
          status: 200,
          contentType: 'text/html',
          body: '<html><body>Stubbed Google OAuth — test stops here.</body></html>',
        })
      },
    )

    await page.goto('/')

    // Wait for the LoginPage to render.
    const loginCard = page.locator('.login-card')
    await expect(loginCard).toBeVisible({ timeout: 10000 })

    // Click the Gmail OAuth button. The hook will:
    //   1. health-check (200)
    //   2. generate PKCE
    //   3. POST /api/oauth/pkce/store
    //   4. attempt window.open(...) → returns null (stubbed)
    //   5. setState({ popupBlocked: true })
    //   6. setTimeout(150) → window.location.href = authUrl
    const gmailBtn = page.locator('.login-oauth-card', { hasText: 'Gmail' })
    await gmailBtn.click()

    // The brief notice should render before the 150ms redirect fires. We give
    // it a wider window to accommodate the health-check + PKCE roundtrip
    // (typically <1s on a quiet machine).
    const briefNotice = page.locator('.oauth-troubleshoot--brief')
    await expect(briefNotice).toBeVisible({ timeout: 5000 })

    // The brief notice text is i18n-driven. The dev server runs in French
    // (lang="fr" on <html>), so check for the FR string.
    await expect(briefNotice).toContainText(/redirection directe|redirecting you/i)

    // Eventually the redirect to Google happens (intercepted, see above).
    await expect.poll(() => capturedAuthUrl, { timeout: 5000 }).not.toBeNull()
    expect(capturedAuthUrl!).toContain('client_id=')
    expect(capturedAuthUrl!).toContain('code_challenge=')
    expect(capturedAuthUrl!).toContain('redirect_uri=')
    expect(capturedAuthUrl!).toContain('scope=')
  })
})

test.describe('OAuth Troubleshooting — stalled polling', () => {
  test('after ~16s of silent polling, panel offers redirect flow + cancel', async ({ page }) => {
    test.slow() // 60s timeout — needs to wait past stalledThreshold (8 polls × 2s = 16s)

    await setupUnauthMocks(page)

    // Mock the polling endpoint to ALWAYS return pending, simulating a flow
    // where postMessage was dropped (COOP / 3p-cookies) and only polling can
    // detect completion.
    const pendingResponse = (route: import('@playwright/test').Route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'pending' }),
      })
    }
    await page.route(/\/api\/oauth\/session\/[^/]+\/poll/, pendingResponse)

    // Stub window.open so the popup "opens" but the postMessage never arrives.
    // We open about:blank locally so the popup is real but inert.
    await page.addInitScript(() => {
      const origOpen = window.open
      Object.defineProperty(window, 'open', {
        configurable: true,
        writable: true,
        value: function (url?: string | URL, target?: string, features?: string) {
          if (target === 'oauth-popup') {
            // Open about:blank locally — same effect as a real popup that
            // navigated to Google but had postMessage stripped.
            return origOpen?.call(window, 'about:blank', target, features) ?? null
          }
          return origOpen?.call(window, url, target, features)
        },
      })
    })

    await page.goto('/')

    const loginCard = page.locator('.login-card')
    await expect(loginCard).toBeVisible({ timeout: 10000 })

    const gmailBtn = page.locator('.login-oauth-card', { hasText: 'Gmail' })
    await gmailBtn.click()

    // The stalled panel should appear after ~16s (8 polls × 2s). Give it 25s.
    const stalledPanel = page.locator('.oauth-troubleshoot--stalled')
    await expect(stalledPanel).toBeVisible({ timeout: 25_000 })

    // Both CTAs should be present.
    const useRedirectBtn = stalledPanel.getByRole('button', {
      name: /redirection|redirect/i,
    })
    const cancelBtn = stalledPanel.getByRole('button', { name: /annuler|cancel/i })
    await expect(useRedirectBtn).toBeVisible()
    await expect(cancelBtn).toBeVisible()

    // Cancel should reset the flow back to disconnected — panel disappears.
    await cancelBtn.click()
    await expect(stalledPanel).toBeHidden({ timeout: 2000 })
  })
})
