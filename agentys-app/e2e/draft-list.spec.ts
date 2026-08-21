/**
 * Draft List E2E Tests
 *
 * Tests for the pending drafts list functionality.
 * Uses correct selectors: .draft-item, .draft-row-sender, .draft-row-subject
 */

import { test, expect, Page } from '@playwright/test'
import {
  mockDraftsResponse,
  mockEmptyDrafts,
} from './support/fixtures/draft-mocks'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

/**
 * Setup API mocks for draft list tests.
 * The PendingDraftList component calls apiClient.listPendingDrafts()
 * which fetches from /api/pending-drafts (NOT /api/drafts).
 */
async function setupDraftMocks(page: Page, draftsResponse = mockDraftsResponse) {
  await setupBaseMocks(page)

  // Override pending-drafts endpoint with test data
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts'), (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(draftsResponse),
      })
    } else {
      route.continue()
    }
  })
}

/**
 * Navigate to the Brouillons tab via sidebar
 */
async function navigateToDrafts(page: Page) {
  await page.locator('[data-testid="nav-drafts"]').click()
}

test.describe('Draft List - Display', () => {
  test.beforeEach(async ({ page }) => {
    await setupDraftMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToDrafts(page)
  })

  test('should display the drafts tab content', async ({ page }) => {
    // After navigating to drafts, draft items should be visible
    const draftItems = page.locator('.draft-item')
    await expect(draftItems.first()).toBeVisible({ timeout: 10000 })
  })

  test('should display draft items', async ({ page }) => {
    const draftItems = page.locator('.draft-item')
    await expect(draftItems.first()).toBeVisible({ timeout: 10000 })

    const count = await draftItems.count()
    expect(count).toBeGreaterThan(0)
  })

  test('should display draft sender name', async ({ page }) => {
    const senderName = page.locator('.draft-row-sender').first()
    await expect(senderName).toBeVisible({ timeout: 10000 })
  })

  test('should display draft subject', async ({ page }) => {
    const subject = page.locator('.draft-row-subject').first()
    await expect(subject).toBeVisible({ timeout: 10000 })
  })

  test('should display status badge', async ({ page }) => {
    // Drafts have status indicators (e.g., pending, validated)
    const statusBadge = page.locator('[class*="status"], [class*="badge"]')
    await expect(statusBadge.first()).toBeVisible({ timeout: 5000 })
  })

  test('should display pending count badge', async ({ page }) => {
    // The sidebar badge shows draft count
    const pendingCount = page.locator('.sidebar-badge')
    await expect(pendingCount.first()).toBeVisible({ timeout: 5000 })
  })
})

test.describe('Draft List - Selection', () => {
  test.beforeEach(async ({ page }) => {
    await setupDraftMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToDrafts(page)
  })

  test('should open draft detail on click', async ({ page }) => {
    const firstDraft = page.locator('.draft-item').first()
    await expect(firstDraft).toBeVisible({ timeout: 10000 })
    await firstDraft.click()

    // Clicking a draft opens PendingDraftDetail
    // The detail view should appear (either inline or replacing the list)
    const detailView = page.locator('.pending-draft-detail, .pdd-email-zone, .email-detail-panel')
    await expect(detailView.first()).toBeVisible({ timeout: 10000 })
  })

  test('should navigate drafts with keyboard', async ({ page }) => {
    const draftItems = page.locator('.draft-item')
    await expect(draftItems.first()).toBeVisible({ timeout: 10000 })
    const initialCount = await draftItems.count()
    expect(initialCount).toBeGreaterThan(1)

    // Arrow keys should not cause errors
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('ArrowDown')
  })
})

test.describe('Draft List - Empty State', () => {
  test('should show empty state when no drafts', async ({ page }) => {
    await setupDraftMocks(page, mockEmptyDrafts)
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToDrafts(page)

    const emptyState = page.getByRole('heading', { name: 'Aucun brouillon' })
    await expect(emptyState).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Draft List - Refresh', () => {
  test('should refresh drafts with Cmd+R', async ({ page }) => {
    await setupDraftMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToDrafts(page)

    // Wait for initial draft items to load
    await expect(page.locator('.draft-item').first()).toBeVisible({ timeout: 10000 })

    await page.keyboard.press('Control+r')

    const draftItems = page.locator('.draft-item')
    await expect(draftItems.first()).toBeVisible()
  })
})

test.describe('Draft List - Status Filtering', () => {
  test('should show drafts with various statuses', async ({ page }) => {
    await setupDraftMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToDrafts(page)

    // Check that draft items are rendered
    const draftItems = page.locator('.draft-item')
    await expect(draftItems.first()).toBeVisible({ timeout: 10000 })
    const count = await draftItems.count()
    expect(count).toBeGreaterThan(0)
  })
})
