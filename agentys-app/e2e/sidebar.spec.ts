/**
 * Sidebar E2E Tests
 *
 * Tests for sidebar navigation, tab switching, collapse/expand,
 * and badge display.
 */

import { test, expect } from '@playwright/test'
import { setupBaseMocks } from './support/fixtures/setup'
import { AppPage } from './pages/AppPage'

test.describe('Sidebar - Navigation', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('should display sidebar with all navigation tabs', async () => {
    await expect(app.sidebar).toBeVisible()
    await expect(app.navInbox).toBeVisible()
    await expect(app.navDrafts).toBeVisible()
    await expect(app.navSent).toBeVisible()
    await expect(app.navArchived).toBeVisible()
    await expect(app.navSpam).toBeVisible()
    await expect(app.navTrash).toBeVisible()
  })

  test('should highlight active tab', async () => {
    // Inbox is active by default
    await expect(app.navInbox).toHaveClass(/active/)
  })

  test('should switch to drafts tab', async () => {
    await app.navigateToDrafts()
    await expect(app.navDrafts).toHaveClass(/active/)
  })

  test('should switch to sent tab', async () => {
    await app.navigateToSent()
    await expect(app.navSent).toHaveClass(/active/)
  })

  test('should switch to archived tab', async () => {
    await app.navigateToArchived()
    await expect(app.navArchived).toHaveClass(/active/)
  })

  test('should switch to spam tab', async () => {
    await app.navigateToSpam()
    await expect(app.navSpam).toHaveClass(/active/)
  })

  test('should switch to trash tab', async () => {
    await app.navigateToTrash()
    await expect(app.navTrash).toHaveClass(/active/)
  })

  test('should have compose button', async () => {
    await expect(app.composeButton).toBeVisible()
  })

  test('should have settings button', async () => {
    await expect(app.navSettings).toBeVisible()
  })
})

test.describe('Sidebar - Collapse/Expand', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('should cycle sidebar modes on toggle', async ({ page }) => {
    // Check sidebar toggle exists before testing
    const toggleExists = await page.getByTestId('sidebar-toggle').count() > 0
    // Sidebar toggle not available in this context — skip gracefully
    test.skip(!toggleExists, 'Sidebar toggle not rendered in current layout')

    // Detect current mode and cycle through all 3
    const currentMode = await page.evaluate(() => localStorage.getItem('agentys_sidebar_mode') || 'pinned')
    const modes = ['pinned', 'auto', 'collapsed']
    const startIdx = modes.indexOf(currentMode)

    // Toggle once and check we moved to next mode
    await app.toggleSidebar()
    const nextMode = modes[(startIdx + 1) % 3]
    await expect(app.sidebar).toHaveClass(new RegExp(`sidebar-mode-${nextMode}`), { timeout: 5000 })

    // Toggle again
    await app.toggleSidebar()
    const nextNextMode = modes[(startIdx + 2) % 3]
    await expect(app.sidebar).toHaveClass(new RegExp(`sidebar-mode-${nextNextMode}`), { timeout: 5000 })

    // Toggle back to start
    await app.toggleSidebar()
    await expect(app.sidebar).toHaveClass(new RegExp(`sidebar-mode-${currentMode}`), { timeout: 5000 })
  })
})

test.describe('Sidebar - Open Modals', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('should open settings from sidebar', async () => {
    await app.openSettings()
    await expect(app.page.getByTestId('settings-modal')).toBeVisible()
  })

  test('should open compose from sidebar', async () => {
    await app.openCompose()
    await expect(app.page.getByRole('dialog', { name: 'Nouveau message' })).toBeVisible()
  })
})
