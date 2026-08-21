/**
 * Command Palette E2E Tests
 *
 * Tests for the Cmd+K command palette: open, search, navigate, execute.
 */

import { test, expect } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

test.describe('Command Palette - Open/Close', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should open command palette with Cmd+K', async ({ page }) => {
    await page.keyboard.press('Control+k')
    const palette = page.getByRole('dialog', { name: 'Palette de commandes' })
    await expect(palette).toBeVisible()
  })

  test('should close command palette with Escape', async ({ page }) => {
    await page.keyboard.press('Control+k')
    const palette = page.getByRole('dialog', { name: 'Palette de commandes' })
    await expect(palette).toBeVisible()

    await page.keyboard.press('Escape')
    await expect(palette).not.toBeVisible()
  })

  test('should close on overlay click', async ({ page }) => {
    await page.keyboard.press('Control+k')
    const palette = page.getByRole('dialog', { name: 'Palette de commandes' })
    await expect(palette).toBeVisible()

    // Click outside the palette (on overlay)
    await page.locator('.command-palette-overlay').click({ position: { x: 10, y: 10 } })
    await expect(palette).not.toBeVisible()
  })

  test('should toggle with repeated Cmd+K', async ({ page }) => {
    await page.keyboard.press('Control+k')
    const palette = page.getByRole('dialog', { name: 'Palette de commandes' })
    await expect(palette).toBeVisible()

    await page.keyboard.press('Control+k')
    await expect(palette).not.toBeVisible()
  })
})

test.describe('Command Palette - Search & Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await page.keyboard.press('Control+k')
  })

  test('should focus search input on open', async ({ page }) => {
    const input = page.getByRole('combobox')
    await expect(input).toBeFocused()
  })

  test('should display command items', async ({ page }) => {
    const palette = page.getByRole('dialog', { name: 'Palette de commandes' })
    await expect(palette).toBeVisible()

    const listbox = palette.locator('[role="listbox"]')
    await expect(listbox).toBeVisible()

    const options = palette.locator('[role="option"]')
    const count = await options.count()
    expect(count).toBeGreaterThan(0)
  })

  test('should filter commands by search query', async ({ page }) => {
    const input = page.getByRole('combobox')
    await input.fill('Répondre')

    const options = page.getByRole('option')
    const count = await options.count()
    expect(count).toBeGreaterThanOrEqual(1)
  })

  test('should show empty state for unmatched query', async ({ page }) => {
    const input = page.getByRole('combobox')
    await input.fill('xyznonexistent123')

    const empty = page.locator('.command-palette-empty')
    await expect(empty).toBeVisible()
  })

  test('should navigate items with arrow keys', async ({ page }) => {
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('ArrowUp')

    const selectedItem = page.locator('.command-palette-item.selected')
    await expect(selectedItem).toBeVisible()
  })
})

test.describe('Command Palette - Execute Actions', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should open settings via command palette', async ({ page }) => {
    await page.keyboard.press('Control+k')

    const input = page.getByRole('combobox')
    await input.fill('Paramètres')

    const option = page.getByRole('option', { name: /Paramètres/ })
    await option.click()

    await expect(page.getByTestId('settings-modal')).toBeVisible()
  })

  test('should open new message via command palette', async ({ page }) => {
    await page.keyboard.press('Control+k')

    const input = page.getByRole('combobox')
    await input.fill('Nouveau')

    const option = page.getByRole('option', { name: /Nouveau message/ })
    await option.click()

    await expect(page.getByRole('dialog', { name: 'Nouveau message' })).toBeVisible()
  })
})
