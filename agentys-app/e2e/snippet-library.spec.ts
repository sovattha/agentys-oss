/**
 * Snippet Library E2E Tests
 *
 * Tests for the snippet library panel: search, tabs, create, delete.
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

async function setupSnippetMocks(page: Page) {
  await setupBaseMocks(page)

  // Mock /api/snippets
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/snippets'), (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          snippets: [
            { id: 's1', title: 'Signature formelle', body: 'Cordialement, [Nom]', category: 'Signatures', is_shared: false },
            { id: 's2', title: 'Merci rapide', body: 'Merci pour votre retour rapide.', category: 'Réponses', is_shared: false },
            { id: 's3', title: 'Template équipe', body: 'Bonjour l\'équipe, ...', category: null, is_shared: true },
          ],
          total: 3,
        }),
      })
    } else {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
    }
  })
}

async function openSnippetLibrary(page: Page) {
  await page.keyboard.press('Control+,')
  await expect(page.getByTestId('settings-modal')).toBeVisible()

  const snippetLink = page.locator('text=/Snippet/i').first()
  await expect(snippetLink).toBeVisible({ timeout: 5000 })
  await snippetLink.click()
}

test.describe('Snippet Library', () => {
  test.beforeEach(async ({ page }) => {
    await setupSnippetMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should open snippet library', async ({ page }) => {
    await openSnippetLibrary(page)

    const library = page.locator('.snippet-library')
    await expect(library).toBeVisible({ timeout: 5000 })
  })

  test('should display snippets list', async ({ page }) => {
    await openSnippetLibrary(page)

    await expect(page.locator('.snippet-library')).toBeVisible({ timeout: 5000 })
    const items = page.locator('.snippet-item')
    const count = await items.count()
    expect(count).toBeGreaterThan(0)
  })

  test('should have search input', async ({ page }) => {
    await openSnippetLibrary(page)

    await expect(page.locator('.snippet-library')).toBeVisible({ timeout: 5000 })
    const searchInput = page.locator('.snippet-library-search input')
    await expect(searchInput).toBeVisible()
  })

  test('should have tab switcher', async ({ page }) => {
    await openSnippetLibrary(page)

    await expect(page.locator('.snippet-library')).toBeVisible({ timeout: 5000 })
    const tabs = page.locator('.snippet-tab')
    const count = await tabs.count()
    expect(count).toBeGreaterThanOrEqual(2)
  })

  test('should have create button', async ({ page }) => {
    await openSnippetLibrary(page)

    await expect(page.locator('.snippet-library')).toBeVisible({ timeout: 5000 })
    const createBtn = page.locator('.snippet-library-create')
    await expect(createBtn).toBeVisible()
  })

  test('should close snippet library', async ({ page }) => {
    await openSnippetLibrary(page)

    const library = page.locator('.snippet-library')
    await expect(library).toBeVisible({ timeout: 5000 })
    const backBtn = page.locator('.snippet-library-back')
    await backBtn.click()
    await expect(library).not.toBeVisible()
  })
})
