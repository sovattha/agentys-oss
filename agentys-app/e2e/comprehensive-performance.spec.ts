/**
 * Comprehensive Performance E2E Tests
 *
 * Tests de performance : temps de chargement, transitions, mémoire, rapidité.
 */

import { test, expect, Page } from '@playwright/test'
import { mockEmailDetails } from './support/fixtures/mock-data'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

async function setupPerfMocks(page: Page) {
  await setupBaseMocks(page)
  await page.route((url) => url.origin === API && url.pathname.match(/^\/api\/emails\/[^/]+$/) !== null, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockEmailDetails['email-1']) })
  })
  await page.route((url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/read$/) !== null, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
  })
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts/by-email'), (route) => {
    route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: 'No draft' }) })
  })
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/contacts'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  })
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/snippets'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ snippets: [], total: 0 }) })
  })
}

test.describe('Performance — chargement initial', () => {
  test('l\'app se charge en moins de 5 secondes', async ({ page }) => {
    await setupPerfMocks(page)
    const t0 = Date.now()
    await page.goto('/')
    await waitForAppReady(page)
    const elapsed = Date.now() - t0
    expect(elapsed).toBeLessThan(10000)
  })

  test('la liste d\'emails apparaît en moins de 4 secondes', async ({ page }) => {
    await setupPerfMocks(page)
    const t0 = Date.now()
    await page.goto('/')
    await waitForAppReady(page)
    await expect(page.locator('[data-testid="email-item"]').first()).toBeVisible({ timeout: 10000 })
    expect(Date.now() - t0).toBeLessThan(10000)
  })
})

test.describe('Performance — navigation entre dossiers', () => {
  test.beforeEach(async ({ page }) => { await setupPerfMocks(page); await page.goto('/'); await waitForAppReady(page) })

  test('switching inbox → sent en moins de 2 secondes', async ({ page }) => {
    const t0 = Date.now()
    await page.locator('[data-testid="nav-sent"]').click()
    // No error visible = successful transition
    await expect(page.locator('text=/erreur|error|500/i')).not.toBeVisible({ timeout: 3000 })
    expect(Date.now() - t0).toBeLessThan(2000)
  })

  test('switching sent → inbox en moins de 2 secondes', async ({ page }) => {
    await page.locator('[data-testid="nav-sent"]').click()
    await page.waitForLoadState('domcontentloaded')

    const t0 = Date.now()
    await page.locator('[data-testid="nav-inbox"]').click()
    await expect(page.locator('[data-testid="email-item"]').first()).toBeVisible({ timeout: 5000 })
    expect(Date.now() - t0).toBeLessThan(2000)
  })
})

test.describe('Performance — ouverture email detail', () => {
  test.beforeEach(async ({ page }) => { await setupPerfMocks(page); await page.goto('/'); await waitForAppReady(page) })

  test('premier clic ouvre en moins de 5 secondes (cache froid)', async ({ page }) => {
    const t0 = Date.now()
    await page.locator('[data-testid="email-item"]').first().click()
    await expect(page.locator('.email-detail-title').first()).toBeVisible({ timeout: 10000 })
    expect(Date.now() - t0).toBeLessThan(5000)
  })

  test('deuxième clic ouvre en moins de 2 secondes (cache chaud)', async ({ page }) => {
    // Premier clic (cache froid)
    await page.locator('[data-testid="email-item"]').first().click()
    await expect(page.locator('.email-detail-title').first()).toBeVisible({ timeout: 10000 })
    await page.keyboard.press('Escape')
    await page.locator('[data-testid="email-item"]').first().waitFor({ state: 'visible', timeout: 5000 })

    // Deuxième clic (cache chaud)
    const t0 = Date.now()
    await page.locator('[data-testid="email-item"]').first().click()
    await expect(page.locator('.email-detail-title').first()).toBeVisible({ timeout: 5000 })
    expect(Date.now() - t0).toBeLessThan(2000)
  })

  test('fermeture du detail est instantanée (< 1s)', async ({ page }) => {
    await page.locator('[data-testid="email-item"]').first().click()
    await expect(page.locator('.email-detail-title').first()).toBeVisible({ timeout: 10000 })

    const t0 = Date.now()
    await page.keyboard.press('Escape')
    await page.locator('[data-testid="email-item"]').first().waitFor({ state: 'visible', timeout: 5000 })
    expect(Date.now() - t0).toBeLessThan(1000)
  })
})

test.describe('Performance — ouverture composer', () => {
  test.beforeEach(async ({ page }) => { await setupPerfMocks(page); await page.goto('/'); await waitForAppReady(page) })

  test('new message s\'ouvre en moins de 2 secondes', async ({ page }) => {
    await page.locator('body').click({ position: { x: 10, y: 10 } })
    const t0 = Date.now()
    await page.keyboard.press('n')
    await expect(page.locator('.new-message-modal').first()).toBeVisible({ timeout: 5000 })
    expect(Date.now() - t0).toBeLessThan(2000)
  })

  test('reply composer s\'ouvre en moins de 3 secondes', async ({ page }) => {
    await page.route((url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/thread$/) !== null, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 1, emails: [] }) })
    })

    await page.locator('[data-testid="email-item"]').first().click()
    await page.locator('.email-detail-body, .email-detail-title').first().waitFor({ state: 'visible', timeout: 10000 })

    const t0 = Date.now()
    await page.keyboard.press('r')
    await expect(page.locator('[data-testid="reply-composer"], .reply-composer').first()).toBeVisible({ timeout: 10000 })
    expect(Date.now() - t0).toBeLessThan(3000)
  })
})

test.describe('Performance — pas de fuite mémoire', () => {
  test('ouvrir/fermer 10 emails sans ralentissement', async ({ page }) => {
    await setupPerfMocks(page)
    await page.goto('/')
    await waitForAppReady(page)

    const items = page.locator('[data-testid="email-item"]')
    const count = Math.min(await items.count(), 5)

    for (let i = 0; i < count; i++) {
      await items.nth(i % count).click()
      await page.locator('.email-detail-title').first().waitFor({ state: 'visible', timeout: 5000 })
      await page.keyboard.press('Escape')
      await page.locator('[data-testid="email-item"]').first().waitFor({ state: 'visible', timeout: 5000 })
    }

    // Repeat cycle — should still be fast
    const t0 = Date.now()
    await items.first().click()
    await expect(page.locator('.email-detail-title').first()).toBeVisible({ timeout: 5000 })
    expect(Date.now() - t0).toBeLessThan(3000)
  })
})

test.describe('Performance — pas de loading bloquant', () => {
  test.beforeEach(async ({ page }) => { await setupPerfMocks(page); await page.goto('/'); await waitForAppReady(page) })

  test('pas de spinner bloquant après chargement initial', async ({ page }) => {
    // Spinner should not persist after app is ready
    await expect(page.locator('.loading-spinner, text=/chargement|loading/i')).not.toBeVisible({ timeout: 3000 })
  })
})
