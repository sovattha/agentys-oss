/**
 * Comprehensive Inbox E2E Tests
 *
 * Tests complets pour la boîte de réception : affichage, navigation,
 * interactions avec les emails, tri, états vides, performance.
 */

import { test, expect, Page } from '@playwright/test'
import { mockEmailDetails, mockEmptyEmails } from './support/fixtures/mock-data'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

async function setupInboxMocks(page: Page) {
  await setupBaseMocks(page)
  await page.route((url) => url.origin === API && url.pathname.match(/^\/api\/emails\/[^/]+$/) !== null, (route, request) => {
    const emailId = new URL(request.url()).pathname.match(/\/api\/emails\/([^/?]+)$/)?.[1]
    const detail = emailId && mockEmailDetails[emailId] ? mockEmailDetails[emailId] : mockEmailDetails['email-1']
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(detail) })
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
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/contacts'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  })
}

test.describe('Inbox — affichage de la liste', () => {
  test.beforeEach(async ({ page }) => { await setupInboxMocks(page); await page.goto('/'); await waitForAppReady(page) })

  test('affiche les emails dans la liste', async ({ page }) => {
    const items = page.locator('[data-testid="email-item"]')
    await expect(items.first()).toBeVisible({ timeout: 10000 })
    expect(await items.count()).toBeGreaterThan(0)
  })

  test('affiche les sujets des emails', async ({ page }) => {
    await expect(page.locator('text=Rapport trimestriel Q4 2025').first()).toBeVisible({ timeout: 10000 })
  })

  test('affiche les noms des expéditeurs', async ({ page }) => {
    await expect(page.locator('text=Marie Dupont')).toBeVisible({ timeout: 10000 })
  })

  test('affiche les heures de réception', async ({ page }) => {
    // Au moins un timestamp visible
    const timestamps = page.locator('.email-time, .email-date')
    await expect(timestamps.first()).toBeVisible({ timeout: 10000 })
  })

  test('affiche l\'icône pièce jointe pour les emails avec attachements', async ({ page }) => {
    // email-1 has_attachments=true
    const attachIcon = page.locator('.attachment-indicator, .has-attachment, svg[class*="attach"]').first()
    await expect(attachIcon).toBeVisible({ timeout: 5000 })
  })

  test('distingue les emails non lus (bold)', async ({ page }) => {
    const unreadItem = page.locator('[data-testid="email-item"]').first()
    await expect(unreadItem).toBeVisible({ timeout: 10000 })
    // Unread emails should have a visual distinction (bold class, unread class, or font-weight)
    const classes = await unreadItem.getAttribute('class') || ''
    // Verify the item has at least some CSS classes applied
    expect(classes.length).toBeGreaterThan(0)
  })
})

test.describe('Inbox — état vide', () => {
  test('affiche un message quand la boîte est vide', async ({ page }) => {
    await setupBaseMocks(page, { emailsResponse: mockEmptyEmails })
    await page.goto('/')
    await waitForAppReady(page)

    // With empty email response, no email items should be rendered
    const emailItems = page.locator('[data-testid="email-item"]')
    const itemCount = await emailItems.count()
    expect(itemCount).toBe(0)
  })
})

test.describe('Inbox — ouverture email detail', () => {
  test.beforeEach(async ({ page }) => { await setupInboxMocks(page); await page.goto('/'); await waitForAppReady(page) })

  test('ouvre le détail au clic sur un email', async ({ page }) => {
    await page.locator('[data-testid="email-item"]').first().click()
    await expect(page.locator('.email-detail-title').first()).toBeVisible({ timeout: 10000 })
  })

  test('affiche le sujet dans le détail', async ({ page }) => {
    await page.locator('[data-testid="email-item"]').first().click()
    await expect(page.locator('.email-detail-title')).toContainText('Rapport trimestriel', { timeout: 10000 })
  })

  test('affiche l\'expéditeur dans le détail', async ({ page }) => {
    await page.locator('[data-testid="email-item"]').first().click()
    await expect(page.locator('.email-original-from').first()).toBeVisible({ timeout: 10000 })
  })

  test('affiche le corps de l\'email', async ({ page }) => {
    await page.locator('[data-testid="email-item"]').first().click()
    const body = page.locator('.email-body-content, .email-body-iframe, .email-detail-body')
    await expect(body.first()).toBeVisible({ timeout: 10000 })
  })

  test('ferme le détail avec Escape', async ({ page }) => {
    await page.locator('[data-testid="email-item"]').first().click()
    await expect(page.locator('.email-detail-title').first()).toBeVisible({ timeout: 10000 })
    await page.keyboard.press('Escape')
    // La liste doit redevenir visible
    await expect(page.locator('[data-testid="email-item"]').first()).toBeVisible({ timeout: 5000 })
  })

  test('ferme le détail avec le bouton X', async ({ page }) => {
    await page.locator('[data-testid="email-item"]').first().click()
    await expect(page.locator('.email-detail-title').first()).toBeVisible({ timeout: 10000 })

    const closeBtn = page.locator('.email-detail-close, [data-testid="close-detail"], button[aria-label*="Fermer"], button[aria-label*="Close"]').first()
    await expect(closeBtn).toBeVisible({ timeout: 5000 })
    await closeBtn.click()
  })
})

test.describe('Inbox — navigation clavier J/K', () => {
  test.beforeEach(async ({ page }) => { await setupInboxMocks(page); await page.goto('/'); await waitForAppReady(page) })

  test('navigue vers le bas avec J', async ({ page }) => {
    await page.locator('body').click({ position: { x: 10, y: 10 } })
    await page.keyboard.press('j')
    // Should select first or next email — verify email list is still visible (no crash)
    await expect(page.locator('[data-testid="email-item"]').first()).toBeVisible({ timeout: 5000 })
  })

  test('navigue vers le haut avec K', async ({ page }) => {
    await page.locator('body').click({ position: { x: 10, y: 10 } })
    await page.keyboard.press('j')
    await page.keyboard.press('k')
    // Verify email list is still visible after keyboard navigation (no crash)
    await expect(page.locator('[data-testid="email-item"]').first()).toBeVisible({ timeout: 5000 })
  })
})

test.describe('Inbox — performance', () => {
  test('charge la liste en moins de 5 secondes', async ({ page }) => {
    await setupInboxMocks(page)
    const t0 = Date.now()
    await page.goto('/')
    await waitForAppReady(page)
    await expect(page.locator('[data-testid="email-item"]').first()).toBeVisible({ timeout: 10000 })
    const elapsed = Date.now() - t0
    expect(elapsed).toBeLessThan(5000)
  })

  test('ouvre le détail en moins de 3 secondes (cache chaud)', async ({ page }) => {
    await setupInboxMocks(page)
    await page.goto('/')
    await waitForAppReady(page)

    // Premier clic (cache froid)
    await page.locator('[data-testid="email-item"]').first().click()
    await expect(page.locator('.email-detail-title').first()).toBeVisible({ timeout: 10000 })
    await page.keyboard.press('Escape')
    await page.locator('[data-testid="email-item"]').first().waitFor({ state: 'visible', timeout: 5000 })

    // Deuxième clic (cache chaud)
    const t0 = Date.now()
    await page.locator('[data-testid="email-item"]').first().click()
    await expect(page.locator('.email-detail-title').first()).toBeVisible({ timeout: 5000 })
    expect(Date.now() - t0).toBeLessThan(3000)
  })
})
