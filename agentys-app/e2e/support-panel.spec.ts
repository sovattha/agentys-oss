/**
 * Support Panel E2E Tests
 *
 * Tests for the support/help panel: intent cards, navigation, form submission.
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

async function setupSupportMocks(page: Page) {
  await setupBaseMocks(page)

  // Mock support/ticket endpoint
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/support'), (route) => {
    if (route.request().method() === 'POST') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, ticket_ref: 'AGT-12345' }),
      })
    } else {
      route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    }
  })
}

test.describe('Support Panel - Open/Close', () => {
  test.beforeEach(async ({ page }) => {
    await setupSupportMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should open support panel from sidebar', async ({ page }) => {
    const supportBtn = page.getByTestId('nav-support')
    await supportBtn.click()

    const panel = page.getByRole('dialog', { name: 'Support Agentys' })
    await expect(panel).toBeVisible()
  })

  test('should close support panel with close button', async ({ page }) => {
    const supportBtn = page.getByTestId('nav-support')
    await supportBtn.click()

    const panel = page.getByRole('dialog', { name: 'Support Agentys' })
    await expect(panel).toBeVisible()

    const closeBtn = page.getByLabel('Fermer')
    await closeBtn.click()
    await expect(panel).not.toBeVisible()
  })
})

test.describe('Support Panel - Chat Home', () => {
  test.beforeEach(async ({ page }) => {
    await setupSupportMocks(page)
    await page.goto('/')
    await waitForAppReady(page)

    await page.getByTestId('nav-support').click()
    await expect(page.getByRole('dialog', { name: 'Support Agentys' })).toBeVisible()
  })

  test('should display chat home with action buttons', async ({ page }) => {
    // SupportChat renders action buttons on the home screen
    const dialog = page.getByRole('dialog', { name: 'Support Agentys' })
    const buttons = dialog.locator('button')
    const count = await buttons.count()
    expect(count).toBeGreaterThan(0)
  })

  test('should have chat input area', async ({ page }) => {
    const dialog = page.getByRole('dialog', { name: 'Support Agentys' })
    // Chat input (textarea or input) should be available
    const input = dialog.locator('textarea, input[type="text"]').first()
    // Chat mode uses a text input for user messages
    await expect(input).toBeVisible({ timeout: 5000 })
  })

  test('welcome cards should have subtitles', async ({ page }) => {
    const dialog = page.getByRole('dialog', { name: 'Support Agentys' })
    // Each of the 4 grid cards should have a subtitle element
    const subtitles = dialog.locator('.sp-welcome-card-sub')
    await expect(subtitles).toHaveCount(4)
    // Subtitles should have visible text content
    for (let i = 0; i < 4; i++) {
      const text = await subtitles.nth(i).textContent()
      expect(text?.trim().length).toBeGreaterThan(0)
    }
  })

  test('should display popular articles section', async ({ page }) => {
    const dialog = page.getByRole('dialog', { name: 'Support Agentys' })
    // Section label should be visible
    const sectionLabel = dialog.locator('.sp-welcome-section-label')
    await expect(sectionLabel).toBeVisible()
    // Should have 5 popular article links
    const articles = dialog.locator('.sp-welcome-article')
    await expect(articles).toHaveCount(5)
  })

  test('clicking popular article navigates to help article', async ({ page }) => {
    const dialog = page.getByRole('dialog', { name: 'Support Agentys' })
    const firstArticle = dialog.locator('.sp-welcome-article').first()
    await firstArticle.click()
    // Should navigate to help article screen (header title changes to "Article")
    const articleTitle = dialog.locator('.sp-header-title', { hasText: 'Article' })
    await expect(articleTitle).toBeVisible()
  })

  test('should display Browse all help link', async ({ page }) => {
    const dialog = page.getByRole('dialog', { name: 'Support Agentys' })
    // The link actions (below the grid) should include Browse all help (3 links total)
    const links = dialog.locator('.sp-welcome-link')
    const count = await links.count()
    expect(count).toBe(3)
  })

  test('typing a query should return a chat response', async ({ page }) => {
    const dialog = page.getByRole('dialog', { name: 'Support Agentys' })
    const input = dialog.locator('input[type="text"]').first()
    await input.fill('where are my drafts')
    await input.press('Enter')
    // A bot response bubble should appear
    const botBubble = dialog.locator('.sp-chat-bubble').first()
    await expect(botBubble).toBeVisible({ timeout: 5000 })
  })
})
