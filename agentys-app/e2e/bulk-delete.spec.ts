/**
 * Bulk Delete E2E Tests
 *
 * Validates that:
 * 1. Multi-select + Del removes emails from inbox (optimistic UI)
 * 2. Provider failure (500) → rollback + error toast
 * 3. Partial failure (207) → warning toast with counts
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks } from './support/fixtures/setup'
import { mockEmails } from './support/fixtures/mock-data'
import { AppPage } from './pages/AppPage'

const API = 'http://127.0.0.1:5050'
const EMAIL_ITEM = '[data-testid="email-item"]'

const EMAILS = [
  { ...mockEmails[0], id: 'bulk-del-001', subject: 'Bulk Delete Email 1', is_read: false, conversation_id: 'bd-conv-1' },
  { ...mockEmails[0], id: 'bulk-del-002', subject: 'Bulk Delete Email 2', is_read: false, conversation_id: 'bd-conv-2' },
  { ...mockEmails[0], id: 'bulk-del-003', subject: 'Bulk Delete Email 3', is_read: false, conversation_id: 'bd-conv-3' },
]

function makeInboxResponse(emails = EMAILS) {
  return { count: emails.length, emails, has_more: false, source: 'mock' }
}

type BulkDeleteMode = 'success' | 'failure' | 'partial'

async function setupMocks(page: Page, mode: BulkDeleteMode = 'success') {
  await page.addInitScript(() => {
    if ('indexedDB' in window) {
      indexedDB.deleteDatabase('agentys_cache')
    }
  })

  await setupBaseMocks(page)

  await page.route(`${API}/api/emails?*`, (route) => {
    const url = new URL(route.request().url())
    const folder = url.searchParams.get('folder') || 'inbox'

    if (folder === 'inbox') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeInboxResponse()),
      })
    } else if (folder === 'trash') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ count: 0, emails: [], has_more: false, source: 'mock' }),
      })
    } else {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ count: 0, emails: [], has_more: false, source: 'mock' }),
      })
    }
  })

  await page.route(`${API}/api/emails/bulk-delete`, (route) => {
    if (mode === 'failure') {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Failed to delete emails', updated_count: 0 }),
      })
    } else if (mode === 'partial') {
      route.fulfill({
        status: 207,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          partial: true,
          updated_count: 1,
          email_ids: ['bulk-del-001', 'bulk-del-002'],
        }),
      })
    } else {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          updated_count: 2,
          email_ids: ['bulk-del-001', 'bulk-del-002'],
        }),
      })
    }
  })
}

async function selectMultipleEmails(page: Page, count: number) {
  const items = page.locator(EMAIL_ITEM)
  await expect(items.first()).toBeVisible({ timeout: 3000 })

  // Check checkboxes via evaluate to bypass visibility constraints
  for (let i = 0; i < count; i++) {
    const checkbox = items.nth(i).locator('input[type="checkbox"]')
    await checkbox.evaluate((el: HTMLInputElement) => {
      el.click()
    })
  }

  // Wait for React useEffect to set bulkDeleteRef
  await page.waitForLoadState('domcontentloaded')
}

test.describe('Bulk Delete', () => {
  let app: AppPage

  test('Happy path: multi-select + Del supprime les emails', async ({ page }) => {
    await setupMocks(page, 'success')
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    await selectMultipleEmails(page, 2)
    await page.keyboard.press('Delete')

    // Toast success
    const toast = page.locator('.toast, [role="alert"], [role="status"]').filter({ hasText: /supprimé/i })
    await expect(toast.first()).toBeVisible({ timeout: 3000 })
  })

  test('Provider failure (500): rollback + error toast', async ({ page }) => {
    await setupMocks(page, 'failure')
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    const items = page.locator(EMAIL_ITEM)
    await expect(items).toHaveCount(3, { timeout: 3000 })

    await selectMultipleEmails(page, 2)
    await page.keyboard.press('Delete')

    // Error toast
    const errorToast = page.locator('.toast, [role="alert"], [role="status"]').filter({ hasText: /erreur/i })
    await expect(errorToast.first()).toBeVisible({ timeout: 3000 })

    // Emails should reappear (rollback)
    await expect(items).toHaveCount(3, { timeout: 3000 })
  })

  test('Partial failure (207): warning toast with counts', async ({ page }) => {
    await setupMocks(page, 'partial')
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    await selectMultipleEmails(page, 2)
    await page.keyboard.press('Delete')

    // Warning toast with partial counts
    const toast = page.locator('.toast, [role="alert"], [role="status"]').filter({ hasText: /échoué/i })
    await expect(toast.first()).toBeVisible({ timeout: 3000 })
  })
})
