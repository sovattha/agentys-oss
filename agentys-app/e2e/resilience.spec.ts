/**
 * Connection Resilience E2E Tests
 *
 * 15 tests across 4 groups covering:
 *   1. Connection Lifecycle — startup, auto-reconnect, retry button, slow backend, 500 on ping
 *   2. API Failures Mid-Session — individual and bulk 500 errors without crash
 *   3. Malformed Data — null accounts, missing fields, empty lists
 *   4. Reconnection Mid-Session — connection loss, recovery, network timeout
 */

import { test, expect } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

// ---------------------------------------------------------------------------
// Group 1 — Connection Lifecycle
// ---------------------------------------------------------------------------

test.describe('Connection Lifecycle', () => {
  test('shows disconnected state when backend is down at startup', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('agentys_onboarding_complete', 'true')
      localStorage.setItem('agentys_onboarding_kb_complete', 'true')
      localStorage.setItem('agentys_jwt', 'dev:test@example.com')
    })

    // All API calls fail with connection refused
    await page.route(url => url.origin === API, route => route.abort('connectionrefused'))

    await page.goto('/')

    // Should show the disconnected / server unavailable message
    const disconnected = page.locator('text=/non disponible|Server connection|Serveur/i')
    await expect(disconnected.first()).toBeVisible({ timeout: 15000 })
  })

  test('auto-reconnects when backend comes back online', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('agentys_onboarding_complete', 'true')
      localStorage.setItem('agentys_onboarding_kb_complete', 'true')
      localStorage.setItem('agentys_jwt', 'dev:test@example.com')
    })

    // Start with all routes aborted
    await page.route(url => url.origin === API, route => route.abort('connectionrefused'))

    await page.goto('/')

    // Verify disconnected state
    const disconnected = page.locator('text=/non disponible|Server connection|Serveur/i')
    await expect(disconnected.first()).toBeVisible({ timeout: 15000 })

    // Simulate backend coming back: remove all route overrides and set up healthy mocks
    await page.unrouteAll()
    await setupBaseMocks(page)

    // The auto-reconnect polls /api/ping every 5s; nav-inbox should appear once reconnected
    await expect(page.locator('[data-testid="nav-inbox"]')).toBeVisible({ timeout: 15000 })
  })

  test('Retry button triggers reconnection', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('agentys_onboarding_complete', 'true')
      localStorage.setItem('agentys_onboarding_kb_complete', 'true')
      localStorage.setItem('agentys_jwt', 'dev:test@example.com')
    })

    // Start disconnected
    await page.route(url => url.origin === API, route => route.abort('connectionrefused'))
    await page.goto('/')

    // Wait for disconnected screen
    const disconnected = page.locator('text=/non disponible|Server connection|Serveur/i')
    await expect(disconnected.first()).toBeVisible({ timeout: 15000 })

    // Click the Retry button
    const retryBtn = page.locator('text=/réessayer|retry/i').first()
    await expect(retryBtn).toBeVisible({ timeout: 5000 })

    // Before clicking, restore healthy mocks
    await page.unrouteAll()
    await setupBaseMocks(page)

    await retryBtn.click()

    // App should reconnect and show the inbox
    await expect(page.locator('[data-testid="nav-inbox"]')).toBeVisible({ timeout: 15000 })
  })

  test('handles slow backend startup (3s delay)', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('agentys_onboarding_complete', 'true')
      localStorage.setItem('agentys_onboarding_kb_complete', 'true')
      localStorage.setItem('agentys_jwt', 'dev:test@example.com')
    })

    // Set up base mocks first (catch-all + specific routes)
    await setupBaseMocks(page)

    // Override /api/ping to delay 3 seconds before responding
    await page.route(`${API}/api/ping`, async (route) => {
      await new Promise(r => setTimeout(r, 3000))
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'ok', version: '1.0.0' }),
      })
    })

    await page.goto('/')

    // Despite the 3s delay, the app should eventually connect and show inbox
    await expect(page.locator('[data-testid="nav-inbox"]')).toBeVisible({ timeout: 15000 })
  })

  test('treats 500 on /api/ping as disconnected', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('agentys_onboarding_complete', 'true')
      localStorage.setItem('agentys_onboarding_kb_complete', 'true')
      localStorage.setItem('agentys_jwt', 'dev:test@example.com')
    })

    // /api/ping returns 500 (higher priority — registered last via LIFO)
    await page.route(`${API}/api/ping`, (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal server error' }),
      })
    })

    // All other API requests abort (backend unreachable except ping responding 500)
    await page.route(url => url.origin === API, (route) => {
      if (route.request().url().includes('/api/ping')) {
        // Let the specific route above handle it
        route.fallback()
      } else {
        route.abort('connectionrefused')
      }
    })

    await page.goto('/')

    // pingWithRetry does 4 attempts with 2s+4s+8s backoff = ~14s before setting disconnected
    const disconnected = page.locator('text=/non disponible|Server connection|Serveur/i')
    await expect(disconnected.first()).toBeVisible({ timeout: 25000 })
  })
})

// ---------------------------------------------------------------------------
// Group 2 — API Failures Mid-Session
// ---------------------------------------------------------------------------

test.describe('API Failures Mid-Session', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('handles /api/emails 500 without crash', async ({ page }) => {
    // Override /api/emails to return 500
    await page.route(
      url => url.origin === API && url.pathname === '/api/emails',
      (route) => route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal server error' }),
      })
    )
    await page.route(
      url => url.origin === API && url.pathname.startsWith('/api/emails?'),
      (route) => route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal server error' }),
      })
    )

    // Trigger a refresh by clicking inbox nav (re-fetches emails)
    await page.locator('[data-testid="nav-inbox"]').click()

    // Wait a moment for the request to be made and handled
    await page.waitForTimeout(2000)

    // Verify no crash (no error boundary with "erreur inattendue")
    await expect(page.locator('text=/erreur inattendue/i')).not.toBeVisible({ timeout: 3000 })
  })

  test('handles /api/labels 500 without crash', async ({ page }) => {
    // Override /api/labels to return 500
    await page.route(
      url => url.origin === API && url.pathname.startsWith('/api/labels'),
      (route) => route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal server error' }),
      })
    )

    // Trigger a navigation that may re-fetch labels
    await page.locator('[data-testid="nav-inbox"]').click()

    await page.waitForTimeout(2000)

    // Verify app still works — sidebar should remain visible
    await expect(page.locator('[data-testid="nav-inbox"]')).toBeVisible()

    // No crash
    await expect(page.locator('text=/erreur inattendue/i')).not.toBeVisible({ timeout: 3000 })
  })

  test('handles /api/pending-drafts 500 without crash', async ({ page }) => {
    // Override /api/pending-drafts to return 500
    await page.route(
      url => url.origin === API && url.pathname.startsWith('/api/pending-drafts'),
      (route) => route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal server error' }),
      })
    )

    // Trigger navigation
    await page.locator('[data-testid="nav-inbox"]').click()

    await page.waitForTimeout(2000)

    // Verify no crash
    await expect(page.locator('text=/erreur inattendue/i')).not.toBeVisible({ timeout: 3000 })

    // App should still be functional
    await expect(page.locator('[data-testid="nav-inbox"]')).toBeVisible()
  })

  test('survives all APIs returning 500 except /ping', async ({ page }) => {
    // Override catch-all to return 500 for everything...
    await page.route(
      url => url.origin === API && !url.pathname.startsWith('/api/ping'),
      (route) => route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal server error' }),
      })
    )

    // ...but keep /api/ping healthy
    await page.route(`${API}/api/ping`, (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'ok', version: '1.0.0' }),
      })
    })

    // Trigger navigation
    await page.locator('[data-testid="nav-inbox"]').click()

    await page.waitForTimeout(3000)

    // The app should not show the catastrophic error boundary
    await expect(page.locator('text=/erreur inattendue/i')).not.toBeVisible({ timeout: 3000 })
  })
})

// ---------------------------------------------------------------------------
// Group 3 — Malformed Data
// ---------------------------------------------------------------------------

test.describe('Malformed Data', () => {
  test('handles /api/init with null accounts', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('agentys_onboarding_complete', 'true')
      localStorage.setItem('agentys_onboarding_kb_complete', 'true')
      localStorage.setItem('agentys_jwt', 'dev:test@example.com')
    })

    // Catch-all
    await page.route(url => url.origin === API, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    })

    // /api/ping — healthy
    await page.route(`${API}/api/ping`, (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'ok', version: '1.0.0' }),
      })
    })

    // /api/init returns null accounts and null emails
    await page.route(`${API}/api/init`, (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          accounts: null,
          emails: null,
          label_counts: null,
          pending_drafts: null,
        }),
      })
    })

    // /api/auth/me
    await page.route(`${API}/api/auth/me`, (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ user: { id: 1, email: 'test@example.com' } }),
      })
    })

    await page.goto('/')
    await page.waitForTimeout(5000)

    // App should load without crashing
    await expect(page.locator('text=/erreur inattendue/i')).not.toBeVisible({ timeout: 3000 })
  })

  test('handles emails with missing fields', async ({ page }) => {
    // Setup mocks with malformed email data — empty subject, null body
    const malformedEmails = {
      emails: [
        {
          id: 'email_malformed_1',
          subject: '',
          from: 'sender@example.com',
          to: 'test@example.com',
          date: '2026-03-22T10:00:00Z',
          body: null,
          snippet: '',
          is_read: false,
          labels: [],
          folder: 'inbox',
        },
        {
          id: 'email_malformed_2',
          subject: null,
          from: null,
          to: 'test@example.com',
          date: '2026-03-22T09:00:00Z',
          body: '',
          snippet: null,
          is_read: true,
          labels: null,
          folder: 'inbox',
        },
      ],
      has_more: false,
      source: 'mock',
    }

    await setupBaseMocks(page, { emailsResponse: malformedEmails })
    await page.goto('/')
    await waitForAppReady(page)

    // The email list should render without crash
    await expect(page.locator('[data-testid="nav-inbox"]')).toBeVisible()

    // No error boundary
    await expect(page.locator('text=/erreur inattendue/i')).not.toBeVisible({ timeout: 3000 })
  })

  test('handles empty email list', async ({ page }) => {
    const emptyEmails = {
      emails: [],
      has_more: false,
      source: 'mock',
    }

    await setupBaseMocks(page, { emailsResponse: emptyEmails })
    await page.goto('/')
    await waitForAppReady(page)

    // App should show an empty state (e.g. "inbox zero" or similar) without crashing
    await expect(page.locator('[data-testid="nav-inbox"]')).toBeVisible()

    // No error boundary
    await expect(page.locator('text=/erreur inattendue/i')).not.toBeVisible({ timeout: 3000 })
  })
})

// ---------------------------------------------------------------------------
// Group 4 — Reconnection Mid-Session
// ---------------------------------------------------------------------------

test.describe('Reconnection Mid-Session', () => {
  test('shows error when connection lost during session', async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)

    // Connection is alive — now break it by overriding all routes to abort
    await page.route(url => url.origin === API, route => route.abort('connectionrefused'))

    // Trigger an action that will hit the backend (click inbox to refresh)
    await page.locator('[data-testid="nav-inbox"]').click()

    // Wait for the app to detect the connection loss
    // Either an error toast, disconnected banner, or the disconnect screen
    const errorState = page.locator('text=/non disponible|Server connection|Serveur|erreur|déconnecté|connexion/i')
    await expect(errorState.first()).toBeVisible({ timeout: 15000 })
  })

  test('recovers when connection restored after loss', async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)

    // Break the connection
    await page.route(url => url.origin === API, route => route.abort('connectionrefused'))

    // Trigger a navigation to force the app to detect the loss
    await page.locator('[data-testid="nav-inbox"]').click()

    // Wait for error state to appear
    const errorState = page.locator('text=/non disponible|Server connection|Serveur|erreur|déconnecté|connexion/i')
    await expect(errorState.first()).toBeVisible({ timeout: 15000 })

    // Restore connection
    await page.unrouteAll()
    await setupBaseMocks(page)

    // App should recover (auto-reconnect via /api/ping polling or user retry)
    // Wait for nav-inbox to reappear, indicating successful reconnection
    await expect(page.locator('[data-testid="nav-inbox"]')).toBeVisible({ timeout: 15000 })
  })

  test('handles network timeout on email processing', async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)

    // Mock /api/emails/:id/process with a 10s delay (simulates network timeout)
    await page.route(
      url => url.origin === API && /\/api\/emails\/[^/]+\/process/.test(url.pathname),
      async (route) => {
        await new Promise(r => setTimeout(r, 10000))
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'ok' }),
        })
      }
    )

    // Wait a moment — the app may or may not trigger /process automatically
    await page.waitForTimeout(3000)

    // The key assertion: the app should not crash while the request is pending
    await expect(page.locator('text=/erreur inattendue/i')).not.toBeVisible({ timeout: 3000 })

    // App should still be responsive — sidebar visible
    await expect(page.locator('[data-testid="nav-inbox"]')).toBeVisible()
  })
})
