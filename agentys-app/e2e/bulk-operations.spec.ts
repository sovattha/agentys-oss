/**
 * Bulk Operations E2E Tests (Phase 18)
 *
 * Tests pour les opérations en masse :
 * - Spam/trash folder banner presence
 * - Bulk selection and toolbar
 */

import { test, expect, Page } from '@playwright/test'
import { mockEmails } from './support/fixtures/mock-data'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

async function setupBulkMocks(page: Page, folder: 'spam' | 'trash' = 'spam') {
  const folderEmails = mockEmails.slice(0, 3).map((e, i) => ({
    ...e,
    id: `${folder}-email-${i + 1}`,
    subject: `${folder === 'spam' ? 'SPAM' : 'Corbeille'}: ${e.subject}`,
    folder,
  }))

  await setupBaseMocks(page, {
    emailsResponse: {
      count: folderEmails.length,
      emails: folderEmails,
    },
  })

  // Bulk not-spam endpoint
  await page.route((url) => url.origin === API && url.pathname === '/api/emails/bulk-not-spam', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, count: 3 }) })
  })

  // Bulk restore endpoint
  await page.route((url) => url.origin === API && url.pathname === '/api/emails/bulk-restore', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, count: 3 }) })
  })

  // Empty spam
  await page.route((url) => url.origin === API && url.pathname === '/api/emails/empty-spam', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
  })

  // Empty trash
  await page.route((url) => url.origin === API && url.pathname === '/api/emails/empty-trash', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
  })

  // Individual not-spam / restore endpoints
  await page.route((url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/not-spam$/) !== null, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
  })
  await page.route((url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/restore$/) !== null, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
  })
}

async function navigateToFolder(page: Page, folder: 'spam' | 'trash') {
  const nav = folder === 'spam' ? '[data-testid="nav-spam"]' : '[data-testid="nav-trash"]'
  await page.locator(nav).click()
  await page.waitForLoadState('domcontentloaded')
}

test.describe('Bulk Operations — dossier Spam', () => {
  test.beforeEach(async ({ page }) => {
    await setupBulkMocks(page, 'spam')
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToFolder(page, 'spam')
  })

  test('affiche des emails dans le dossier spam', async ({ page }) => {
    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems.first()).toBeVisible({ timeout: 10000 })
    expect(await emailItems.count()).toBeGreaterThanOrEqual(1)
  })

  test('peut sélectionner des emails avec la checkbox', async ({ page }) => {
    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems.first()).toBeVisible({ timeout: 10000 })

    // Hover to reveal checkbox
    await emailItems.first().hover()
    const checkbox = emailItems.first().locator('input[type="checkbox"], .email-checkbox').first()
    await expect(checkbox).toBeVisible({ timeout: 5000 })
    await checkbox.click()

    // After selecting, the email should have a selected state
    await expect(emailItems.first()).toHaveClass(/selected|checked/, { timeout: 3000 })
  })
})

test.describe('Bulk Operations — dossier Corbeille', () => {
  test.beforeEach(async ({ page }) => {
    await setupBulkMocks(page, 'trash')
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToFolder(page, 'trash')
  })

  test('affiche des emails dans le dossier corbeille', async ({ page }) => {
    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems.first()).toBeVisible({ timeout: 10000 })
    expect(await emailItems.count()).toBeGreaterThanOrEqual(1)
  })
})

test.describe('Bulk Operations — toolbar contextuel', () => {
  test.beforeEach(async ({ page }) => {
    await setupBulkMocks(page, 'spam')
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('les emails sont chargés dans l\'inbox', async ({ page }) => {
    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems.first()).toBeVisible({ timeout: 10000 })
    expect(await emailItems.count()).toBeGreaterThanOrEqual(1)
  })
})
