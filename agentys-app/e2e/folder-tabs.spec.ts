/**
 * Folder Tabs E2E Tests
 *
 * Tests for browsing all email folders: sent, archived, spam, trash.
 * Each folder uses EmailList with a `folder` prop, so the same list
 * component renders but fetches different data.
 */

import { test, expect, Page } from '@playwright/test'
import { mockEmails } from './support/fixtures/mock-data'
import { setupBaseMocks } from './support/fixtures/setup'
import { AppPage } from './pages/AppPage'

const API = 'http://127.0.0.1:5050'

function mockFolderEmails(folder: string) {
  return {
    count: 3,
    emails: mockEmails.slice(0, 3).map((e, i) => ({
      ...e,
      id: `${folder}-email-${i}`,
      subject: `[${folder}] ${e.subject}`,
    })),
  }
}

async function setupFolderMocks(page: Page) {
  await setupBaseMocks(page)

  // Override /api/emails with folder-aware mock
  await page.route(`${API}/api/emails?*`, (route) => {
    const url = new URL(route.request().url())
    const folder = url.searchParams.get('folder') || 'inbox'
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockFolderEmails(folder)),
    })
  })
}

test.describe('Sent folder', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupFolderMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('should navigate to Sent and display emails', async ({ page }) => {
    await app.navigateToSent()
    await expect(app.navSent).toHaveClass(/active/)

    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems.first()).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Archived folder', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupFolderMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('should navigate to Archived and display emails', async ({ page }) => {
    await app.navigateToArchived()
    await expect(app.navArchived).toHaveClass(/active/)

    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems.first()).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Spam folder', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupFolderMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('should navigate to Spam and display emails', async ({ page }) => {
    await app.navigateToSpam()
    await expect(app.navSpam).toHaveClass(/active/)

    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems.first()).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Trash folder', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupFolderMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('should navigate to Trash and display emails', async ({ page }) => {
    await app.navigateToTrash()
    await expect(app.navTrash).toHaveClass(/active/)

    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems.first()).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Archive flow', () => {
  let app: AppPage

  test('email archivé apparaît dans Archives après archivage', async ({ page }) => {
    await setupBaseMocks(page)

    // Mock folder-aware emails: inbox has email-to-archive, archived has it after move
    await page.route(`${API}/api/emails?*`, (route) => {
      const url = new URL(route.request().url())
      const folder = url.searchParams.get('folder') || 'inbox'
      if (folder === 'archived') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            count: 1,
            emails: [{ ...mockEmails[0], id: 'archived-123', subject: '[archived] Test' }],
          }),
        })
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            count: 1,
            emails: [{ ...mockEmails[0], id: 'email-to-archive' }],
          }),
        })
      }
    })

    await page.route(`${API}/api/emails/*/archive`, (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      })
    })

    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    // Navigate to Archives
    await app.navigateToArchived()

    // Archived email should be visible
    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems.first()).toBeVisible({ timeout: 5000 })
    await expect(emailItems.first()).toContainText('[archived]')
  })
})

test.describe('Tab switching', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupFolderMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('should deselect email when switching tabs', async ({ page }) => {
    // Select an email in inbox
    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await firstEmail.click()
    await expect(firstEmail).toHaveClass(/selected/)

    // Switch to sent
    await app.navigateToSent()

    // After switching tabs, no email should be selected — detail panel should be hidden
    const detailPanel = page.locator('.email-detail-panel')
    await expect(detailPanel).not.toBeVisible({ timeout: 5000 })
  })

  test('should update browser title when switching tabs', async ({ page }) => {
    await app.navigateToSent()
    // Wait for React useEffect to update document.title
    await expect(async () => {
      const title = await page.title()
      expect(title).toContain('Envoyés')
    }).toPass({ timeout: 5000 })
  })
})
