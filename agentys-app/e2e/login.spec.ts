/**
 * Login Page E2E Tests
 *
 * Tests for the authentication flow: magic link, OAuth, dev mode.
 * LoginPage is shown when auth.isAuthenticated === false.
 *
 * Since Playwright tests run in a browser (not Tauri), we mock the
 * auth endpoints and test the login UI behavior.
 */

import { test, expect, Page } from '@playwright/test'

const API = 'http://127.0.0.1:5050'

/**
 * Setup mocks that keep the user NOT authenticated.
 * The app shows LoginPage when no valid token is found.
 */
async function setupLoginMocks(page: Page) {
  // Clear any stored tokens so the app shows login
  await page.addInitScript(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  // Catch-all for API
  await page.route((url) => url.origin === API, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })

  // Auth verify — reject (no valid token)
  await page.route(`${API}/api/auth/verify`, (route) => {
    route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ error: 'Unauthorized' }) })
  })

  // Auth me — reject (no valid session)
  await page.route(`${API}/api/auth/me`, (route) => {
    route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ error: 'Unauthorized' }) })
  })

  // Magic link request
  await page.route(`${API}/api/auth/request-magic-link`, (route) => {
    if (route.request().method() === 'POST') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, message: 'Magic link sent' }),
      })
    } else {
      route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    }
  })
}

test.describe('Login Page - Display', () => {
  test.beforeEach(async ({ page }) => {
    await setupLoginMocks(page)
    await page.goto('/')
  })

  test('should display login page when not authenticated', async ({ page }) => {
    const loginCard = page.locator('.login-card')
    await expect(loginCard).toBeVisible({ timeout: 10000 })
  })

  test('should have email input', async ({ page }) => {
    const emailInput = page.getByLabel('Adresse email')
    await expect(emailInput).toBeVisible({ timeout: 10000 })
  })

  test('should have magic link submit button', async ({ page }) => {
    const submitBtn = page.locator('.login-btn[type="submit"]')
    await expect(submitBtn).toBeVisible({ timeout: 10000 })
    await expect(submitBtn).toContainText('Envoyer un lien magique')
  })

  test('should have OAuth buttons', async ({ page }) => {
    const _googleBtn = page.locator('.login-oauth-btn', { hasText: 'Google' })
    const _outlookBtn = page.locator('.login-oauth-btn', { hasText: 'Outlook' })

    // At least one OAuth option should be visible
    const oauthBtn = page.locator('.login-oauth-btn').first()
    await expect(oauthBtn).toBeVisible({ timeout: 10000 })

    const count = await page.locator('.login-oauth-btn').count()
    expect(count).toBeGreaterThanOrEqual(1)
  })
})

test.describe('Login Page - Magic Link Flow', () => {
  test.beforeEach(async ({ page }) => {
    await setupLoginMocks(page)
    await page.goto('/')
    await page.locator('.login-card').waitFor({ state: 'visible', timeout: 10000 })
  })

  test('should submit magic link request', async ({ page }) => {
    const emailInput = page.getByLabel('Adresse email')
    await emailInput.fill('test@example.com')

    const submitBtn = page.locator('.login-btn[type="submit"]')
    await submitBtn.click()

    // Should show "sent" confirmation
    const sentConfirmation = page.locator('.login-sent')
    await expect(sentConfirmation).toBeVisible({ timeout: 5000 })
  })

  test('should keep form visible with empty email', async ({ page }) => {
    const submitBtn = page.locator('.login-btn[type="submit"]')
    // Button is disabled when email is empty — clicking does nothing
    await expect(submitBtn).toBeDisabled()

    // Form should still be visible (not transition to sent state)
    const emailInput = page.getByLabel('Adresse email')
    await expect(emailInput).toBeVisible()
  })

  test('should show error on server failure', async ({ page }) => {
    // Clear ALL routes and re-register with magic-link returning 500
    await page.unrouteAll()

    // Auth routes — reject
    await page.route(`${API}/api/auth/me`, (route) => {
      route.fulfill({ status: 401, contentType: 'application/json', body: '{"error":"Unauthorized"}' })
    })

    // Magic link — 500 error
    await page.route(`${API}/api/auth/request-magic-link`, (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Erreur serveur' }),
      })
    })

    await page.goto('/')
    await page.locator('.login-card').waitFor({ state: 'visible', timeout: 10000 })

    const emailInput = page.getByLabel('Adresse email')
    await emailInput.fill('test@example.com')

    const submitBtn = page.locator('.login-btn[type="submit"]')
    await submitBtn.click()

    // Error should be displayed
    const errorBanner = page.locator('.login-error')
    await expect(errorBanner).toBeVisible({ timeout: 5000 })
  })
})
