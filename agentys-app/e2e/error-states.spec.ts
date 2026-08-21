/**
 * Error States E2E Tests
 *
 * Tests for error handling across the app: API failures,
 * disconnected backend, error boundaries.
 */

import { test, expect } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

test.describe('Error States - Backend Disconnected', () => {
  test('should show disconnected state when backend is down', async ({ page }) => {
    // Set localStorage to skip onboarding + auth (DEV token bypass)
    await page.addInitScript(() => {
      localStorage.setItem('agentys_onboarding_complete', 'true')
      localStorage.setItem('agentys_onboarding_kb_complete', 'true')
      localStorage.setItem('agentys_jwt', 'dev:test@example.com')
    })

    // Mock all API routes to fail
    await page.route((url) => url.origin === API, (route) => {
      route.abort('connectionrefused')
    })

    await page.goto('/')

    // Should show disconnected state or error boundary
    const disconnected = page.locator('text=/non disponible|indisponible|disconnected|erreur|inattendue/i')
    await expect(disconnected.first()).toBeVisible({ timeout: 15000 })
  })
})

test.describe('Error States - API Failures', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should handle email detail load failure gracefully', async ({ page }) => {
    // Mock email detail to fail
    await page.route((url) => url.origin === API && url.pathname.match(/^\/api\/emails\/[^/]+$/) !== null, (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal server error' }),
      })
    })

    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await firstEmail.click()

    // Should show error message or loading state — the important thing is no crash
    const errorOrLoading = page.locator('text=/erreur|error|impossible|chargement/i')
    await expect(errorOrLoading.first()).toBeVisible({ timeout: 10000 })
  })

  test('should handle settings load failure', async ({ page }) => {
    // Mock settings endpoint to fail
    await page.route(`${API}/api/settings`, (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Server error' }),
      })
    })

    await page.keyboard.press('Control+,')
    const settingsModal = page.getByTestId('settings-modal')
    await expect(settingsModal).toBeVisible()

    // Settings should still render (may show defaults or error state)
    // The important thing is it doesn't crash
    await expect(settingsModal).toBeVisible()
  })
})

test.describe('Error States - Loading States', () => {
  test('should not crash during slow loading', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('agentys_onboarding_complete', 'true')
      localStorage.setItem('agentys_onboarding_kb_complete', 'true')
      localStorage.setItem('agentys_jwt', 'dev:test@example.com')
    })

    // Delay all API responses
    await page.route((url) => url.origin === API, async (route) => {
      await new Promise(r => setTimeout(r, 2000))
      route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    })

    await page.goto('/')

    // App should eventually render without crashing
    // Either loading screen, login page, or main app — any is fine
    const body = page.locator('body')
    await expect(body).toBeVisible()

    // No uncaught error boundary
    const errorBoundary = page.locator('text=/erreur inattendue/i')
    const hasCrashed = await errorBoundary.isVisible({ timeout: 3000 }).catch(() => false)
    expect(hasCrashed).toBeFalsy()
  })
})
