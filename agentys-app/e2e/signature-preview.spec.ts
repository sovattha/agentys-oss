/**
 * Signature Preview E2E Tests
 *
 * Vérifie que la signature du compte est visible dans les brouillons AI
 * (PendingDraftDetail) en mode read-only, et dans NewMessageModal.
 */

import { test, expect, Page } from '@playwright/test'
import { mockDraftsResponse } from './support/fixtures/draft-mocks'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

const SIGNATURE_HTML = '<div><strong>Alexandre Savageau</strong><br>CEO, Agentys</div>'

async function setupSignatureMocks(page: Page) {
  await setupBaseMocks(page)

  // Override accounts mock to include signature_html
  await page.route(`${API}/api/accounts`, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        current_account_id: '1',
        accounts: [{
          id: '1', email: 'test@example.com', status: 'active',
          signature: 'Alexandre Savageau\nCEO, Agentys',
          signature_html: SIGNATURE_HTML,
          has_signature: true,
        }],
      }),
    })
  })

  // Pending drafts
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts'), (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDraftsResponse) })
    } else { route.continue() }
  })

  // Email detail & read
  await page.route((url) => url.origin === API && url.pathname.match(/^\/api\/emails\/email-\d+$/) !== null, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'email-1', subject: 'Rapport trimestriel Q4 2025', sender: 'marie.dupont@example.com', body: '<p>Bonjour</p>', body_html: '<p>Bonjour</p>', received_at: new Date().toISOString(), to: ['test@example.com'] }) })
  })
  await page.route((url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/read$/) !== null, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
  })
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/snippets'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ snippets: [], total: 0 }) })
  })
  await page.route((url) => url.origin === API && url.pathname === '/api/contacts/autocomplete', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  })
}

test.describe('Signature Preview — PendingDraftDetail', () => {
  test.beforeEach(async ({ page }) => {
    await setupSignatureMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    // Navigate to Brouillons tab
    await page.locator('[data-testid="nav-drafts"]').click()
  })

  test('affiche la signature dans le brouillon AI', async ({ page }) => {
    const draftItem = page.locator('.draft-item').first()
    await expect(draftItem).toBeVisible({ timeout: 10000 })
    await draftItem.click()
    await page.locator('.pending-draft-detail, .pdd-email-zone, .draft-card-body-wrapper').first().waitFor({ state: 'visible', timeout: 5000 })

    // Signature preview element should be present with the signature text
    const sigPreview = page.locator('.pdd-signature-preview')
    await expect(sigPreview).toBeVisible({ timeout: 5000 })
    await expect(sigPreview).toContainText('Alexandre Savageau', { timeout: 5000 })
  })

  test('signature est non-interactive (pointer-events: none)', async ({ page }) => {
    const draftItem = page.locator('.draft-item').first()
    await expect(draftItem).toBeVisible({ timeout: 10000 })
    await draftItem.click()
    await page.locator('.pending-draft-detail, .pdd-email-zone, .draft-card-body-wrapper').first().waitFor({ state: 'visible', timeout: 5000 })

    const sigPreview = page.locator('.pdd-signature-preview')
    await expect(sigPreview).toBeVisible({ timeout: 5000 })
    const pointerEvents = await sigPreview.evaluate(el => getComputedStyle(el).pointerEvents)
    expect(pointerEvents).toBe('none')
  })

  test('signature a une opacité réduite', async ({ page }) => {
    const draftItem = page.locator('.draft-item').first()
    await expect(draftItem).toBeVisible({ timeout: 10000 })
    await draftItem.click()
    await page.locator('.pending-draft-detail, .pdd-email-zone, .draft-card-body-wrapper').first().waitFor({ state: 'visible', timeout: 5000 })

    const sigPreview = page.locator('.pdd-signature-preview')
    await expect(sigPreview).toBeVisible({ timeout: 5000 })
    const opacity = await sigPreview.evaluate(el => getComputedStyle(el).opacity)
    expect(parseFloat(opacity)).toBeLessThan(1)
  })
})
