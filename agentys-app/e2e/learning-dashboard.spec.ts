/**
 * Learning Dashboard E2E Tests
 *
 * Tests for the learning/AI dashboard modal: stats, period selection,
 * trend chart, tier breakdown.
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

async function setupLearningMocks(page: Page) {
  await setupBaseMocks(page)

  // Mock /api/learning/dashboard
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/learning'), (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        acceptance_rate: 85,
        total_drafts: 42,
        avg_score: 78,
        improvement: 12,
        trend: Array.from({ length: 14 }, (_, i) => ({
          date: `2026-02-${String(i + 1).padStart(2, '0')}`,
          rate: 70 + Math.random() * 20,
          count: Math.floor(Math.random() * 10) + 1,
        })),
        tiers: {
          VIP: { count: 5, rate: 95 },
          STANDARD: { count: 25, rate: 82 },
          BULK: { count: 12, rate: 75 },
        },
        rules: [],
      }),
    })
  })
}

async function openLearningDashboard(page: Page) {
  // Open via Settings → Learning link
  await page.keyboard.press('Control+,')
  await expect(page.getByTestId('settings-modal')).toBeVisible()

  const learningLink = page.locator('text=/Apprentissage|Dashboard/i').first()
  await expect(learningLink).toBeVisible({ timeout: 5000 })
  await learningLink.click()
}

test.describe('Learning Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await setupLearningMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should open learning dashboard', async ({ page }) => {
    await openLearningDashboard(page)

    const dashboard = page.locator('.learning-dashboard')
    await expect(dashboard).toBeVisible({ timeout: 5000 })
  })

  test('should display hero stats', async ({ page }) => {
    await openLearningDashboard(page)

    const dashboard = page.locator('.learning-dashboard')
    await expect(dashboard).toBeVisible({ timeout: 5000 })
    const heroGrid = page.locator('.ld-hero-grid')
    await expect(heroGrid).toBeVisible()

    const tiles = page.locator('.ld-hero-tile')
    const count = await tiles.count()
    expect(count).toBeGreaterThanOrEqual(2)
  })

  test('should have period selector buttons', async ({ page }) => {
    await openLearningDashboard(page)

    const dashboard = page.locator('.learning-dashboard')
    await expect(dashboard).toBeVisible({ timeout: 5000 })
    const periodBtns = page.locator('.ld-period-btn')
    const count = await periodBtns.count()
    expect(count).toBeGreaterThanOrEqual(2)
  })

  test('should close learning dashboard', async ({ page }) => {
    await openLearningDashboard(page)

    const dashboard = page.locator('.learning-dashboard')
    await expect(dashboard).toBeVisible({ timeout: 5000 })
    const closeBtn = page.getByLabel('Fermer')
    await closeBtn.click()
    await expect(dashboard).not.toBeVisible()
  })
})
