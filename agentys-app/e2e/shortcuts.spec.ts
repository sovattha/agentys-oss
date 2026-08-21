/**
 * Keyboard Shortcuts E2E Tests
 *
 * Tests for global keyboard shortcuts.
 */

import { test, expect } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

test.describe('Keyboard Shortcuts', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should open compose modal with Cmd+N', async ({ page }) => {
    await page.keyboard.press('Control+n')
    const composeModal = page.locator('[data-testid="compose-modal"], .compose-modal, [class*="compose"]').first()
    await expect(composeModal).toBeVisible({ timeout: 3000 })
  })

  test('should open settings with Cmd+,', async ({ page }) => {
    await page.keyboard.press('Control+,')
    const settingsModal = page.locator('[data-testid="settings-modal"]')
    await expect(settingsModal).toBeVisible()
  })

  test('should trigger sync with Cmd+Shift+S', async ({ page }) => {
    const requestPromise = page.waitForRequest(
      (request) => request.url().includes('/api/'),
      { timeout: 5000 }
    ).catch(() => null)

    await page.keyboard.press('Control+Shift+s')
    const request = await requestPromise
    // Sync should have triggered at least one API call
    expect(request).not.toBeNull()
  })

  test('should show shortcuts help with Cmd+/', async ({ page }) => {
    await page.keyboard.press('Control+/')
    const shortcutsPanel = page.locator('[class*="shortcuts-help"]')
    await expect(shortcutsPanel).toBeVisible({ timeout: 3000 })
  })

  test('should close modal with Escape', async ({ page }) => {
    // Open settings first
    await page.keyboard.press('Control+,')
    const settingsModal = page.locator('[data-testid="settings-modal"]')
    await expect(settingsModal).toBeVisible()

    // Close with Escape
    await page.keyboard.press('Escape')
    await expect(settingsModal).not.toBeVisible()
  })
})
