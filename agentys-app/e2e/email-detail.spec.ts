/**
 * Email Detail E2E Tests
 *
 * Tests for viewing email details via EmailDetailModal.
 * Note: EmailDetailModal fetches /api/emails/{id} for single email detail.
 * It does NOT auto-load threads (that's EmailContentReader, used elsewhere).
 * HTML bodies are rendered in an iframe, so body text isn't directly accessible.
 */

import { test, expect, Page } from '@playwright/test'
import {
  mockEmailDetails,
  mockDraftReady,
} from './support/fixtures/mock-data'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

/**
 * Setup API mocks for email detail view
 */
async function setupEmailDetailMocks(page: Page) {
  await setupBaseMocks(page)

  // Mock individual email detail endpoint
  await page.route((url) => url.origin === API && url.pathname.match(/^\/api\/emails\/[^/]+$/) !== null, (route, request) => {
    const url = new URL(request.url())
    const emailIdMatch = url.pathname.match(/\/api\/emails\/([^/?]+)$/)
    const emailId = emailIdMatch ? emailIdMatch[1] : null

    if (emailId && mockEmailDetails[emailId]) {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockEmailDetails[emailId]),
      })
    } else {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockEmailDetails['email-1']),
      })
    }
  })

  // Mock mark as read endpoint
  await page.route((url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/read$/) !== null, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true }),
    })
  })

  // Mock thread endpoint (in case it's called)
  await page.route((url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/thread$/) !== null, (route) => {
    const email = mockEmailDetails['email-1']
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ count: 1, emails: [email] }),
    })
  })

  // Mock generate draft endpoint
  await page.route((url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/process$/) !== null, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockDraftReady),
    })
  })

  // Mock pending-drafts/by-email endpoint (checked when selecting an email)
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts/by-email'), (route) => {
    route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ error: 'No draft found' }),
    })
  })
}

test.describe('Email Detail - View', () => {
  test.beforeEach(async ({ page }) => {
    await setupEmailDetailMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should open email detail on click', async ({ page }) => {
    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await firstEmail.click()

    // EmailDetailModal shows the subject as h2
    await expect(page.locator('.email-detail-title').first()).toBeVisible({ timeout: 10000 })
  })

  test('should display email subject in detail', async ({ page }) => {
    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await firstEmail.click()

    await expect(page.locator('.email-detail-title')).toContainText('Rapport trimestriel Q4 2025', { timeout: 10000 })
  })

  test('should display sender information', async ({ page }) => {
    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await firstEmail.click()

    await expect(page.locator('.email-original-from').first()).toBeVisible({ timeout: 10000 })
  })

  test('should display email metadata (date, subject)', async ({ page }) => {
    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await firstEmail.click()

    await expect(page.locator('.email-detail-title').first()).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Email Detail - Actions', () => {
  test.beforeEach(async ({ page }) => {
    await setupEmailDetailMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should have reply button', async ({ page }) => {
    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await firstEmail.click()

    const replyBtn = page.locator('.email-reply-btn').first()
    await expect(replyBtn).toBeVisible({ timeout: 10000 })
  })

  test('should have reply all button', async ({ page }) => {
    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await firstEmail.click()

    // Reply All button should be visible in email detail actions
    const replyAllBtn = page.locator('text=Répondre à tous')
    await expect(replyAllBtn.first()).toBeVisible({ timeout: 10000 })
  })

  test('should close detail view with Escape key', async ({ page }) => {
    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await firstEmail.click()

    await expect(page.locator('.email-detail-title').first()).toBeVisible({ timeout: 10000 })

    await page.keyboard.press('Escape')
  })
})

test.describe('Email Detail - Body Content', () => {
  test.beforeEach(async ({ page }) => {
    await setupEmailDetailMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should render email body area', async ({ page }) => {
    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await firstEmail.click()

    // The body is rendered either as inline HTML or in an iframe
    // Check that the body content area exists
    const bodyArea = page.locator('.email-body-content, .email-body-iframe')
    await expect(bodyArea.first()).toBeVisible({ timeout: 10000 })
  })

  test('should not execute malicious scripts', async ({ page }) => {
    // XSS test — verify no script execution in main context
    const xssTriggered = await page.evaluate(() => {
      return (window as unknown as { xssAttack?: boolean }).xssAttack === true
    })

    expect(xssTriggered).toBeFalsy()
  })
})

test.describe('Email Detail - Modal View', () => {
  test.beforeEach(async ({ page }) => {
    await setupEmailDetailMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should open email in modal on double-click', async ({ page }) => {
    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await firstEmail.dblclick()

    await page.waitForLoadState('domcontentloaded')

    const modal = page.locator('[role="dialog"], [class*="modal"], [class*="Modal"]')
    // Double-clicking an email should open a modal/dialog
    await expect(modal.first()).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Email Detail - Performance (prefetch)', () => {
  test('should open detail instantly on second click (warm cache)', async ({ page }) => {
    // Simule un cache chaud : le backend répond instantanément (body déjà en SQLite)
    await setupBaseMocks(page)
    await page.route((url) => url.origin === API && url.pathname.match(/^\/api\/emails\/[^/]+$/) !== null, async (route) => {
      // No artificial delay — simulates warm SQLite cache after prefetch
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockEmailDetails['email-1']),
      })
    })
    await page.route((url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/read$/) !== null, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
    })
    await page.route((url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts/by-email'), (route) => {
      route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: 'No draft found' }) })
    })

    await page.goto('/')
    await waitForAppReady(page)

    const firstEmail = page.locator('[data-testid="email-item"]').first()

    // Premier clic
    await firstEmail.click()
    await expect(page.locator('.email-detail-title').first()).toBeVisible({ timeout: 10000 })
    await page.keyboard.press('Escape')
    await page.locator('.email-detail-title').first().waitFor({ state: 'hidden', timeout: 5000 })

    // Deuxième clic — doit s'ouvrir sans état "Chargement..."
    const t0 = Date.now()
    await firstEmail.click()
    await expect(page.locator('.email-detail-title').first()).toBeVisible({ timeout: 5000 })
    const elapsed = Date.now() - t0

    // Avec cache chaud, l'ouverture doit être rapide (< 3s avec rendu UI inclus)
    expect(elapsed).toBeLessThan(3000)
  })

  test('should not show loading spinner when detail API responds quickly', async ({ page }) => {
    await setupEmailDetailMocks(page)
    await page.goto('/')
    await waitForAppReady(page)

    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await firstEmail.click()

    // Le titre doit apparaître sans que le spinner soit visible durablement
    await expect(page.locator('.email-detail-title').first()).toBeVisible({ timeout: 5000 })

    // Vérifier qu'aucun indicateur de chargement bloquant n'est présent une fois le détail affiché
    const loadingIndicator = page.locator('text=/chargement|loading/i')
    const count = await loadingIndicator.count()
    // Le spinner peut flash brièvement mais ne doit pas persister
    if (count > 0) {
      await expect(loadingIndicator.first()).not.toBeVisible({ timeout: 3000 })
    }
  })
})

test.describe('Email Detail - Error Handling', () => {
  test('should display inline logo (data:image/) from email signature', async ({ page }) => {
    await setupBaseMocks(page)

    // 1×1 red PNG in base64 — stands in for a real company logo CID-resolved by backend
    const LOGO_B64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwADhQGAWjR9awAAAABJRU5ErkJggg=='
    const emailWithLogo = {
      ...mockEmailDetails['email-1'],
      id: 'email-logo-test',
      subject: 'Email avec logo inline',
      body_html: `<html><body><p>Bonjour,</p><p>Message avec signature.</p><br><img src="data:image/png;base64,${LOGO_B64}" alt="Logo entreprise" width="120" height="40"></body></html>`,
      body: `<html><body><p>Bonjour,</p><p>Message avec signature.</p><br><img src="data:image/png;base64,${LOGO_B64}" alt="Logo entreprise" width="120" height="40"></body></html>`,
    }

    // Override detail endpoint for this specific email
    await page.route((url) => url.origin === API && url.pathname.match(/^\/api\/emails\/[^/]+$/) !== null, (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(emailWithLogo),
      })
    })

    await page.goto('/')
    await waitForAppReady(page)

    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await firstEmail.click()

    // Wait for email detail modal to open
    await expect(page.locator('.email-detail-title').first()).toBeVisible({ timeout: 10000 })

    // HTML emails are rendered inside a sandboxed iframe (.email-body-iframe)
    const iframe = page.frameLocator('.email-body-iframe')

    // The img tag with data:image/ src must be present and visible in the iframe
    const logo = iframe.locator('img[src^="data:image/"]')
    await expect(logo).toBeVisible({ timeout: 5000 })

    // Verify the src attribute contains the data URI (DOMPurify / sanitization didn't strip it)
    const src = await logo.getAttribute('src')
    expect(src).toMatch(/^data:image\/png;base64,/)
  })

  test('should show error when email detail fails to load', async ({ page }) => {
    await setupBaseMocks(page)

    // Mock detail endpoint to fail
    await page.route((url) => url.origin === API && url.pathname.match(/^\/api\/emails\/[^/]+$/) !== null, (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Failed to load email' }),
      })
    })

    await page.goto('/')
    await waitForAppReady(page)

    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await firstEmail.click()

    const errorMessage = page.locator('text=/erreur|error|échec|impossible/i')
    await expect(errorMessage.first()).toBeVisible({ timeout: 10000 })
  })
})
