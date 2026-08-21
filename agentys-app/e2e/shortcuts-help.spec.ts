/**
 * Shortcuts Help Panel E2E Tests
 *
 * Tests for the keyboard shortcuts help panel: open, sections,
 * customization, close behavior.
 */

import { test, expect } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

test.describe('Shortcuts Help Panel', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should open shortcuts panel with Cmd+/', async ({ page }) => {
    await page.keyboard.press('Control+/')
    const panel = page.locator('.shortcuts-help-panel')
    await expect(panel).toBeVisible()
  })

  test('should display shortcut sections', async ({ page }) => {
    await page.keyboard.press('Control+/')
    await expect(page.locator('.shortcuts-help-panel')).toBeVisible()

    const sections = page.locator('.shortcuts-help-panel .shortcuts-section')
    const count = await sections.count()
    expect(count).toBeGreaterThan(0)
  })

  test('should display keyboard keys', async ({ page }) => {
    await page.keyboard.press('Control+/')
    await expect(page.locator('.shortcuts-help-panel')).toBeVisible()

    const keys = page.locator('.shortcut-key')
    const count = await keys.count()
    expect(count).toBeGreaterThan(5)
  })

  test('should close panel with close button', async ({ page }) => {
    await page.keyboard.press('Control+/')
    const panel = page.locator('.shortcuts-help-panel')
    await expect(panel).toBeVisible()

    const closeBtn = panel.locator('button[aria-label="Fermer"]')
    await closeBtn.click()

    await expect(panel).not.toBeVisible()
  })

  test('should close panel with Escape', async ({ page }) => {
    await page.keyboard.press('Control+/')
    const panel = page.locator('.shortcuts-help-panel')
    await expect(panel).toBeVisible()

    await page.keyboard.press('Escape')
    await expect(panel).not.toBeVisible()
  })

  test('should have reset all shortcuts button', async ({ page }) => {
    await page.keyboard.press('Control+/')

    const resetBtn = page.getByLabel('Réinitialiser tous les raccourcis')
    await expect(resetBtn).toBeVisible({ timeout: 5000 })
  })
})
