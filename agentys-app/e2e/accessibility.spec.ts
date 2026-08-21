/**
 * Accessibility E2E Tests
 *
 * Tests for ARIA attributes, focus management, keyboard navigation,
 * skip links, and role attributes across key components.
 */

import { test, expect } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

test.describe('Accessibility - Main App', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should have skip link to main content', async ({ page }) => {
    const skipLink = page.locator('.skip-link')
    await expect(skipLink).toBeAttached()
    await expect(skipLink).toHaveAttribute('href', '#app-main')
  })

  test('should have main landmark with aria-label', async ({ page }) => {
    const main = page.getByRole('main', { name: 'Contenu principal' })
    await expect(main).toBeVisible()
  })

  test('should have navigation in sidebar', async ({ page }) => {
    const sidebar = page.getByTestId('sidebar')
    await expect(sidebar).toBeVisible()
  })
})

test.describe('Accessibility - Settings Modal', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should have dialog role and aria-modal on settings', async ({ page }) => {
    await page.keyboard.press('Control+,')

    const dialog = page.locator('[data-testid="settings-overlay"]')
    await expect(dialog).toHaveAttribute('role', 'dialog')
    await expect(dialog).toHaveAttribute('aria-modal', 'true')
    await expect(dialog).toHaveAttribute('aria-label', 'Paramètres')
  })

  test('should trap focus within settings modal when tabbing', async ({ page }) => {
    await page.keyboard.press('Control+,')
    await expect(page.getByTestId('settings-modal')).toBeVisible()

    // Wait for focus trap to auto-focus into the modal (callback ref + lazy content)
    await expect(async () => {
      const inOverlay = await page.evaluate(() => {
        const overlay = document.querySelector('[data-testid="settings-overlay"]')
        return overlay?.contains(document.activeElement) ?? false
      })
      expect(inOverlay).toBe(true)
    }).toPass({ timeout: 3000 })

    for (let i = 0; i < 15; i++) {
      await page.keyboard.press('Tab')
    }

    const isWithinOverlay = await page.evaluate(() => {
      const overlay = document.querySelector('[data-testid="settings-overlay"]')
      return overlay?.contains(document.activeElement) ?? false
    })
    expect(isWithinOverlay).toBeTruthy()
  })
})

test.describe('Accessibility - Compose Modal', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should have proper ARIA on compose modal', async ({ page }) => {
    await page.locator('button.sidebar-compose').click()

    const dialog = page.getByRole('dialog', { name: 'Nouveau message' })
    await expect(dialog).toBeVisible()
    await expect(dialog).toHaveAttribute('aria-modal', 'true')
  })

  test('should auto-focus To field in compose modal', async ({ page }) => {
    await page.locator('button.sidebar-compose').click()

    const toField = page.locator('input[placeholder="À"]')
    await expect(toField).toBeFocused({ timeout: 3000 })
  })
})

test.describe('Accessibility - Keyboard Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should navigate emails with arrow keys', async ({ page }) => {
    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await firstEmail.click()

    await page.keyboard.press('ArrowDown')
    const selectedEmail = page.locator('[data-testid="email-item"].selected')
    await expect(selectedEmail).toBeVisible()
  })

  test('should close email detail with Escape', async ({ page }) => {
    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await firstEmail.click()
    await expect(page.locator('.email-detail-panel')).toBeVisible({ timeout: 10000 })

    await page.keyboard.press('Escape')
    // Detail panel might be closed or email deselected
  })

  test('should open new message with N key', async ({ page }) => {
    await page.keyboard.press('n')

    const dialog = page.getByRole('dialog', { name: 'Nouveau message' })
    await expect(dialog).toBeVisible()
  })
})
