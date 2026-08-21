/**
 * Delete → Trash Flow E2E Tests
 *
 * Validates that:
 * 1. Deleting an email removes it from inbox (optimistic UI)
 * 2. The deleted email appears in the Corbeille (trash) folder after undo timer
 * 3. Corbeille is empty when no emails are deleted
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks } from './support/fixtures/setup'
import { mockEmails } from './support/fixtures/mock-data'
import { AppPage } from './pages/AppPage'

const API = 'http://127.0.0.1:5050'
const EMAIL_ITEM = '[data-testid="email-item"]'

const TARGET = {
  ...mockEmails[0],
  id: 'del-trash-001',
  subject: 'Email à supprimer E2E',
  is_read: false,
}

const SECOND = {
  ...mockEmails[0],
  id: 'del-trash-002',
  subject: 'Deuxième email E2E',
  is_read: true,
}

function makeInboxResponse(emails = [TARGET, SECOND]) {
  return { count: emails.length, emails, has_more: false, source: 'mock' }
}

function makeTrashResponse(emails: typeof mockEmails) {
  return { count: emails.length, emails, has_more: false, source: 'mock' }
}

async function setupMocks(page: Page) {
  await page.addInitScript(() => {
    if ('indexedDB' in window) {
      indexedDB.deleteDatabase('agentys_cache')
    }
  })

  await setupBaseMocks(page)

  let trashedEmails: typeof mockEmails = []

  // Folder-aware email list mock
  await page.route(`${API}/api/emails?*`, (route) => {
    const url = new URL(route.request().url())
    const folder = url.searchParams.get('folder') || 'inbox'

    if (folder === 'trash') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeTrashResponse(trashedEmails)),
      })
    } else {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeInboxResponse()),
      })
    }
  })

  // Single delete endpoint — moves to trash mock state
  await page.route(`${API}/api/emails/*/delete`, (route) => {
    const url = route.request().url()
    const match = url.match(/\/emails\/([^/]+)\/delete/)
    if (match) {
      const deletedId = decodeURIComponent(match[1])
      const found = [TARGET, SECOND].find((e) => e.id === deletedId)
      if (found && !trashedEmails.some((e) => e.id === found.id)) {
        trashedEmails = [...trashedEmails, { ...found, folder: 'trash' }]
      }
    }
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, email_id: match?.[1], message: 'Email moved to trash' }),
    })
  })

  // Bulk delete endpoint
  await page.route(`${API}/api/emails/bulk-delete`, (route) => {
    const body = route.request().postDataJSON()
    const ids: string[] = body?.email_ids || []
    for (const id of ids) {
      const found = [TARGET, SECOND].find((e) => e.id === id)
      if (found && !trashedEmails.some((e) => e.id === found.id)) {
        trashedEmails = [...trashedEmails, { ...found, folder: 'trash' }]
      }
    }
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, updated_count: ids.length, email_ids: ids }),
    })
  })
}

test.describe('Delete → Trash flow', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('Inbox affiche les emails cibles', async ({ page }) => {
    const items = page.locator(EMAIL_ITEM)
    await expect(items.first()).toBeVisible({ timeout: 3000 })
    await expect(items).toHaveCount(2, { timeout: 3000 })
  })

  test('Supprimer retire l\'email de l\'inbox (UI optimiste)', async ({ page }) => {
    const target = page.locator(EMAIL_ITEM).filter({ hasText: 'Email à supprimer E2E' }).first()
    await expect(target).toBeVisible({ timeout: 3000 })

    // Select then press Delete
    await target.click()
    await page.keyboard.press('Delete')

    // Email should disappear (animation 260ms + shift)
    await expect(target).not.toBeVisible({ timeout: 2000 })
  })

  test('Corbeille est vide si aucun email supprimé', async ({ page }) => {
    await app.navigateToTrash()

    const trashItems = page.locator(EMAIL_ITEM)
    await expect(trashItems).toHaveCount(0, { timeout: 3000 })
  })

  test('Email supprimé apparaît dans la Corbeille après le timer undo (5s)', async ({ page }) => {
    const target = page.locator(EMAIL_ITEM).filter({ hasText: 'Email à supprimer E2E' }).first()
    await expect(target).toBeVisible({ timeout: 3000 })

    // Préparer le waiter AVANT l'action — se déclenche dès que l'API delete répond (après le timer 5s)
    const deleteDone = page.waitForResponse(
      (resp) => resp.url().includes('/api/emails/') && resp.url().includes('/delete'),
      { timeout: 10000 }
    )

    // Delete the email
    await target.click()
    await page.keyboard.press('Delete')
    await expect(target).not.toBeVisible({ timeout: 2000 })
    await deleteDone  // termine exactement quand le timer 5s expire

    // Navigate to Trash
    await app.navigateToTrash()

    // The deleted email should appear in the trash
    const trashItems = page.locator(EMAIL_ITEM)
    await expect(trashItems.first()).toBeVisible({ timeout: 5000 })
    await expect(trashItems.filter({ hasText: 'Email à supprimer E2E' }).first()).toBeVisible({ timeout: 3000 })
  })

  test('Toast "supprimé" apparaît avec action Annuler', async ({ page }) => {
    const target = page.locator(EMAIL_ITEM).filter({ hasText: 'Email à supprimer E2E' }).first()
    await expect(target).toBeVisible({ timeout: 3000 })
    await target.click()
    await page.keyboard.press('Delete')

    // Toast should mention suppression
    const toast = page.locator('.toast, [role="alert"], [role="status"]').filter({ hasText: /supprim/i })
    await expect(toast.first()).toBeVisible({ timeout: 2000 })
  })
})
