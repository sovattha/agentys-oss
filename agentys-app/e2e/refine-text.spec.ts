/**
 * Refine Text E2E Tests (Phase 18)
 *
 * Tests pour POST /api/refine-text depuis :
 * - NewMessageModal (refine le corps du message)
 * - ReplyComposer (refine le brouillon via AI)
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'
import { mockEmailDetails } from './support/fixtures/mock-data'

const API = 'http://127.0.0.1:5050'

async function setupRefineMocks(page: Page) {
  await setupBaseMocks(page)

  await page.route((url) => url.origin === API && url.pathname === '/api/refine-text', (route) => {
    const body = route.request().postDataJSON()
    const instruction = body?.instruction || ''
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        refined_text: `Texte raffiné selon: "${instruction}". Lorem ipsum refined content here.`,
      }),
    })
  })

  await page.route((url) => url.origin === API && url.pathname === '/api/emails/compose', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, message_id: 'msg-refine-1' }) })
  })

  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/snippets'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ snippets: [], total: 0 }) })
  })

  await page.route((url) => url.origin === API && url.pathname === '/api/contacts/autocomplete', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  })

  // Email detail mocks for reply tests
  await page.route((url) => url.origin === API && url.pathname.match(/^\/api\/emails\/[^/]+$/) !== null, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockEmailDetails['email-1']) })
  })

  await page.route((url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/read$/) !== null, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
  })

  await page.route((url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/thread$/) !== null, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 1, emails: [] }) })
  })

  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts/by-email'), (route) => {
    route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: 'No draft' }) })
  })
}

async function openNewMessage(page: Page) {
  await page.locator('body').click({ position: { x: 10, y: 10 } })
  await page.keyboard.press('n')
  await page.locator('.new-message-modal').first().waitFor({ state: 'visible', timeout: 10000 })
}

test.describe('Refine Text — NewMessageModal', () => {
  test.beforeEach(async ({ page }) => {
    await setupRefineMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openNewMessage(page)
  })

  test('affiche le trigger AICommandMenu dans NewMessage', async ({ page }) => {
    await expect(page.locator('[data-testid="ai-command-trigger"]').first()).toBeVisible({ timeout: 5000 })
  })

  test('peut taper une instruction dans le champ AI', async ({ page }) => {
    await page.locator('[data-testid="ai-command-trigger"]').first().click()
    const input = page.locator('.ai-cmd-input').first()
    await expect(input).toBeVisible({ timeout: 5000 })
    await input.fill('Rendre plus professionnel')
    const val = await input.inputValue()
    expect(val).toBe('Rendre plus professionnel')
  })

  test('lance le refine via Enter dans le popover', async ({ page }) => {
    const textarea = page.locator('.gmail-textarea').first()
    await expect(textarea).toBeVisible({ timeout: 5000 })
    await textarea.fill('Bonjour, voici mon message original.')

    await page.locator('[data-testid="ai-command-trigger"]').first().click()
    const input = page.locator('.ai-cmd-input').first()
    await expect(input).toBeVisible({ timeout: 5000 })
    await input.fill('Améliorer le ton')
    await page.keyboard.press('Enter')

    await expect(page.locator('.new-message-modal').first()).toBeVisible({ timeout: 5000 })
  })

  test('liste les commandes prédéfinies dans le popover', async ({ page }) => {
    await page.locator('[data-testid="ai-command-trigger"]').first().click()
    const rows = page.locator('.ai-cmd-popover .ai-cmd-row')
    await expect(rows.first()).toBeVisible({ timeout: 5000 })
    expect(await rows.count()).toBeGreaterThan(0)
  })

  test('sélectionner une commande ferme le popover', async ({ page }) => {
    await page.locator('[data-testid="ai-command-trigger"]').first().click()
    const firstRow = page.locator('.ai-cmd-popover .ai-cmd-row').first()
    await expect(firstRow).toBeVisible({ timeout: 5000 })
    await firstRow.click({ force: true })
    await expect(page.locator('.ai-cmd-popover').first()).toBeHidden({ timeout: 5000 })
  })
})

test.describe('Refine Text — ReplyComposer', () => {
  test.beforeEach(async ({ page }) => {
    await setupRefineMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    // Open email and reply
    await page.locator('[data-testid="email-item"]').first().click()
    await page.locator('.email-detail-body, .email-detail-title').first().waitFor({ state: 'visible', timeout: 10000 })
    await page.keyboard.press('r')
    await page.locator('[data-testid="reply-composer"], .reply-composer').first().waitFor({ state: 'visible', timeout: 10000 })
  })

  test('affiche le champ refine dans le reply composer', async ({ page }) => {
    await expect(page.locator('[data-testid="ai-prompt-input"], .rc-refine-input').first()).toBeVisible({ timeout: 5000 })
  })

  test('peut taper une instruction de refine', async ({ page }) => {
    const input = page.locator('[data-testid="ai-prompt-input"], .rc-refine-input').first()
    await input.focus()
    await input.fill('Rendre plus formel')
    await expect(input).toHaveValue('Rendre plus formel', { timeout: 3000 })
  })

  test('affiche le menu slash dans le reply composer', async ({ page }) => {
    const input = page.locator('[data-testid="ai-prompt-input"], .rc-refine-input').first()
    await input.focus()
    await input.fill('/')
    await expect(page.locator('.rc-slash-menu')).toBeVisible({ timeout: 5000 })
  })
})
