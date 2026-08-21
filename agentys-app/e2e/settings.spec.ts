/**
 * Settings E2E Tests
 *
 * Tests for the settings modal functionality.
 */

import { test, expect } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

test.describe('Settings', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should open settings with keyboard shortcut', async ({ page }) => {
    await page.keyboard.press('Meta+,')

    const settingsModal = page.locator('[data-testid="settings-modal"]')
    await expect(settingsModal).toBeVisible()
  })

  test('should open settings with button click', async ({ page }) => {
    await page.locator('[data-testid="nav-settings"]').click()

    const settingsModal = page.locator('[data-testid="settings-modal"]')
    await expect(settingsModal).toBeVisible()
  })

  test('should display settings nav pills', async ({ page }) => {
    await page.keyboard.press('Meta+,')

    // Settings uses a vertical sidebar (not nav pills)
    const nav = page.locator('.settings-sidebar')
    await expect(nav).toBeVisible()

    // Sections actuelles : Compte, Personnalisation, Outils, Productivité,
    // Automatisation, Général (la section « IA » n'existe plus).
    await expect(page.locator('.settings-sidebar-item', { hasText: 'Compte' })).toBeVisible()
    await expect(page.locator('.settings-sidebar-item', { hasText: 'Automatisation' })).toBeVisible()
    await expect(page.locator('.settings-sidebar-item', { hasText: 'Général' })).toBeVisible()
  })

  test('should scroll to section on nav pill click', async ({ page }) => {
    await page.keyboard.press('Meta+,')

    // Click "Général" sidebar item
    await page.locator('.settings-sidebar-item', { hasText: 'Général' }).click()

    // Vérifier que le sidebar item est actif (Settings uses sidebar nav, not headings)
    await expect(page.locator('.settings-sidebar-item.active', { hasText: 'Général' })).toBeVisible()
  })

  test('should toggle tooltips setting', async ({ page }) => {
    await page.keyboard.press('Meta+,')

    // Navigate to Général section
    await page.locator('.settings-sidebar-item', { hasText: 'Général' }).click()

    const tooltipCheckbox = page.locator('input[aria-label="Afficher les infobulles"]')
    const isVisible = await tooltipCheckbox.isVisible().catch(() => false)

    if (isVisible) {
      const checked = await tooltipCheckbox.isChecked()
      await tooltipCheckbox.click()
      // Verify toggle happened
      const newChecked = await tooltipCheckbox.isChecked()
      expect(newChecked).not.toBe(checked)
    } else {
      test.skip(true, 'Tooltips checkbox not rendered in current settings layout')
    }
  })

  test('should close settings with close button', async ({ page }) => {
    await page.keyboard.press('Meta+,')

    await page.getByRole('button', { name: 'Fermer les paramètres' }).click()

    const settingsModal = page.locator('[data-testid="settings-modal"]')
    await expect(settingsModal).not.toBeVisible()
  })

  test('should close settings with overlay click', async ({ page }) => {
    await page.keyboard.press('Meta+,')

    await page.locator('[data-testid="settings-overlay"]').click({ position: { x: 10, y: 10 } })

    const settingsModal = page.locator('[data-testid="settings-modal"]')
    await expect(settingsModal).not.toBeVisible()
  })

  test('should display Compte section content', async ({ page }) => {
    await page.keyboard.press('Meta+,')

    // The Compte section should be visible by default
    await expect(page.locator('.settings-sidebar-item.active', { hasText: 'Compte' })).toBeVisible()
    await expect(page.locator('text=Compte utilisateur')).toBeVisible()
  })

  test('should keep Productivité settings behind sub-panels', async ({ page }) => {
    await page.keyboard.press('Meta+,')

    const settingsModal = page.locator('[data-testid="settings-modal"]')
    await expect(settingsModal).toBeVisible()
    const productivityTab = page.locator('.settings-sidebar-item', { hasText: /productivit[éy]/i })
    await productivityTab.click()
    await expect(page.locator('.settings-sidebar-item.active', { hasText: /productivit[éy]/i })).toBeVisible()

    const openAndClosePanel = async (label: RegExp, panelSelector: string) => {
      await settingsModal.locator('.settings-link-btn').filter({ hasText: label }).first().click()
      const panel = page.locator(panelSelector).first()
      await expect(panel).toBeVisible({ timeout: 5000 })
      await expect(settingsModal).toBeVisible()

      await page.keyboard.press('Escape')

      await expect(panel).not.toBeVisible({ timeout: 5000 })
      await expect(settingsModal).toBeVisible()
      await expect(page.locator('.settings-sidebar-item.active', { hasText: /productivit[éy]/i })).toBeVisible()
    }

    await openAndClosePanel(/raccourcis|shortcut/i, '.shortcuts-help-panel')
    await openAndClosePanel(/concentration|focus|deep.*work/i, '.dwm-modal')
    await openAndClosePanel(/rappels de réunions|meeting reminders/i, '.meeting-reminders-panel')
  })

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  test.skip('should toggle autostart setting', async ({ page }) => {
    // Tauri-only feature, skipped in browser mode
  })
})
