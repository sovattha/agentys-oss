/**
 * My Style E2E Tests
 *
 * Tests for the "Mon style" modal: loading state, patterns display,
 * maturity progress bar, close behavior.
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

async function setupMyStyleMocks(page: Page) {
  await setupBaseMocks(page)

  // Mock /api/style endpoint
  await page.route(`${API}/api/style`, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        maturity: 72,
        patterns: [
          { id: 'p1', label: 'Formules de politesse', count: 15, examples: ['Cordialement', 'Bien à vous'] },
          { id: 'p2', label: 'Ton professionnel', count: 8, examples: ['Je me permets de', 'Suite à notre échange'] },
        ],
        stats: { emails_analyzed: 42, avg_length: 150, response_time_avg: '2h' },
      }),
    })
  })
}

async function openMyStyle(page: Page) {
  // Open via Settings → Mon style link, or dispatch event
  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent('open-settings'))
  })
  const settingsModal = page.getByTestId('settings-modal')
  await expect(settingsModal).toBeVisible()

  // Look for "Mon style" link in settings and click it
  const myStyleLink = page.locator('text=/Mon style/i').first()
  await expect(myStyleLink).toBeVisible({ timeout: 5000 })
  await myStyleLink.click()
}

test.describe('My Style - Modal', () => {
  test.beforeEach(async ({ page }) => {
    await setupMyStyleMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should open My Style modal', async ({ page }) => {
    await openMyStyle(page)

    const myStylePanel = page.locator('.my-style')
    await expect(myStylePanel).toBeVisible({ timeout: 5000 })
  })

  test('should display maturity progress bar', async ({ page }) => {
    await openMyStyle(page)

    const myStylePanel = page.locator('.my-style')
    await expect(myStylePanel).toBeVisible({ timeout: 5000 })
    const progressBar = page.getByRole('progressbar')
    await expect(progressBar).toBeVisible()
  })

  test('should close My Style with close button', async ({ page }) => {
    await openMyStyle(page)

    const myStylePanel = page.locator('.my-style')
    await expect(myStylePanel).toBeVisible({ timeout: 5000 })
    const closeBtn = page.getByLabel('Fermer mon style')
    await closeBtn.click()
    await expect(myStylePanel).not.toBeVisible()
  })
})
