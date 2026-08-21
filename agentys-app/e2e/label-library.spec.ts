/**
 * Label Library E2E Tests
 *
 * Tests for the label library panel: default labels, favorites,
 * custom labels, create label.
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

async function setupLabelMocks(page: Page) {
  await setupBaseMocks(page)

  // Mock /api/labels with rich data
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/labels'), (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        labels: [
          { id: 'l1', name: 'Important', color: '#ef4444', is_default: true, is_favorite: true },
          { id: 'l2', name: 'Projet Alpha', color: '#3b82f6', is_default: false, is_favorite: false },
          { id: 'l3', name: 'À suivre', color: '#f59e0b', is_default: true, is_favorite: false },
        ],
        counts: { l1: 5, l2: 12, l3: 3 },
      }),
    })
  })
}

async function openLabelLibrary(page: Page) {
  await page.keyboard.press('Control+,')
  await expect(page.getByTestId('settings-modal')).toBeVisible()

  const labelLink = page.locator('text=/Label/i').first()
  await expect(labelLink).toBeVisible({ timeout: 5000 })
  await labelLink.click()
}

test.describe('Label Library', () => {
  test.beforeEach(async ({ page }) => {
    await setupLabelMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should open label library', async ({ page }) => {
    await openLabelLibrary(page)

    const library = page.locator('.label-library-container')
    await expect(library).toBeVisible({ timeout: 5000 })
  })

  test('should display label items', async ({ page }) => {
    await openLabelLibrary(page)

    const library = page.locator('.label-library-container')
    await expect(library).toBeVisible({ timeout: 5000 })
    const items = page.locator('.label-library-item')
    const count = await items.count()
    expect(count).toBeGreaterThan(0)
  })

  test('should have favorite star toggle', async ({ page }) => {
    await openLabelLibrary(page)

    const library = page.locator('.label-library-container')
    await expect(library).toBeVisible({ timeout: 5000 })
    const stars = page.locator('.label-library-star')
    const count = await stars.count()
    expect(count).toBeGreaterThan(0)
  })

  test('should close label library', async ({ page }) => {
    await openLabelLibrary(page)

    const library = page.locator('.label-library-container')
    await expect(library).toBeVisible({ timeout: 5000 })
    const closeBtn = page.locator('.label-library-close')
    await closeBtn.click()
    await expect(library).not.toBeVisible()
  })
})
