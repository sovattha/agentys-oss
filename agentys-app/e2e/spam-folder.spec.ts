/**
 * Spam Folder E2E Tests
 *
 * Tests pour le dossier Indésirables (Spam) de l'application Agentys.
 */

import { test, expect, Page } from '@playwright/test'
import { mockEmails, mockEmailDetails } from './support/fixtures/mock-data'
import { setupBaseMocks } from './support/fixtures/setup'
import { AppPage } from './pages/AppPage'

const API = 'http://127.0.0.1:5050'

const mockSpamEmails = {
  count: 3,
  emails: [
    { ...mockEmails[0], id: 'spam-email-0', subject: 'Gagnez 10 000 € maintenant', sender: 'promo@spam-site.com', sender_name: 'Super Promo', folder: 'spam' },
    { ...mockEmails[1], id: 'spam-email-1', subject: 'Offre exclusive - Ne ratez pas', sender: 'deals@untrusted.net', sender_name: 'Deals Incroyables', folder: 'spam' },
    { ...mockEmails[2], id: 'spam-email-2', subject: 'Votre compte a été compromis', sender: 'security@fake-bank.xyz', sender_name: 'Fausse Banque', folder: 'spam' },
  ],
  has_more: false, offset: 0, filter: 'all', source: 'cache',
}

async function setupSpamMocks(page: Page) {
  await setupBaseMocks(page)
  await page.route(`${API}/api/emails?*`, (route) => {
    const url = new URL(route.request().url())
    const folder = url.searchParams.get('folder') || 'inbox'
    if (folder === 'spam') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSpamEmails) })
    } else {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 2, emails: mockEmails.slice(0, 2), has_more: false, offset: 0, filter: 'all', source: 'cache' }) })
    }
  })
}

test.describe('Indésirables — navigation', () => {
  let app: AppPage
  test.beforeEach(async ({ page }) => { await setupSpamMocks(page); app = new AppPage(page); await app.goto(); await app.waitForReady() })

  test('navigue vers les Indésirables sans erreur', async ({ page }) => {
    await app.navigateToSpam()
    await expect(page.locator('text=/Failed to fetch emails|erreur|500/i')).not.toBeVisible({ timeout: 10000 })
  })
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  test('nav Indésirables a la classe active', async ({ page }) => {
    await app.navigateToSpam()
    await expect(app.navSpam).toHaveClass(/active/, { timeout: 10000 })
  })
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  test('retour inbox depuis les Indésirables', async ({ page }) => {
    await app.navigateToSpam(); await app.navigateToInbox()
    await expect(app.navInbox).toHaveClass(/active/, { timeout: 10000 })
  })
  test('le titre de page est mis à jour', async ({ page }) => {
    await app.navigateToSpam()
    await expect(async () => { expect((await page.title()).toLowerCase()).toMatch(/indésirables|spam/i) }).toPass({ timeout: 10000 })
  })
})

test.describe('Indésirables — affichage liste', () => {
  let app: AppPage
  test.beforeEach(async ({ page }) => { await setupSpamMocks(page); app = new AppPage(page); await app.goto(); await app.waitForReady() })

  test('affiche les emails spam', async ({ page }) => {
    await app.navigateToSpam()
    await expect(page.locator('[data-testid="email-item"]').first()).toBeVisible({ timeout: 10000 })
  })
  test('affiche le nombre correct d\'emails', async ({ page }) => {
    await app.navigateToSpam()
    await expect(page.locator('[data-testid="email-item"]')).toHaveCount(3, { timeout: 10000 })
  })
  test('affiche les sujets des emails spam', async ({ page }) => {
    await app.navigateToSpam()
    await expect(page.locator('text=Gagnez 10 000 € maintenant').first()).toBeVisible({ timeout: 10000 })
    await expect(page.locator('text=Offre exclusive - Ne ratez pas').first()).toBeVisible({ timeout: 10000 })
  })
  test('affiche la bannière spam avec info 30 jours', async ({ page }) => {
    await app.navigateToSpam()
    const banner = page.locator('.spam-banner')
    await expect(banner).toBeVisible({ timeout: 10000 })
    await expect(banner).toContainText('30 jours')
  })
  test('affiche le bouton Vider les indésirables', async ({ page }) => {
    await app.navigateToSpam()
    await expect(page.locator('.spam-empty-btn')).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Indésirables — erreur 500', () => {
  test('affiche l\'état d\'erreur quand l\'API retourne 500', async ({ page }) => {
    await setupBaseMocks(page)
    await page.route(`${API}/api/emails?*`, (route) => {
      const folder = new URL(route.request().url()).searchParams.get('folder') || 'inbox'
      if (folder === 'spam') {
        route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: 'Internal server error' }) })
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 2, emails: mockEmails.slice(0, 2), has_more: false, offset: 0, filter: 'all', source: 'cache' }) })
      }
    })
    const app = new AppPage(page); await app.goto(); await app.waitForReady(); await app.navigateToSpam()
    await expect(page.locator('.error-state, .email-list-error, [class*="error"]').first()).toBeVisible({ timeout: 10000 })
  })

  test('bouton Réessayer re-fetche les emails (1er 500, 2ème 200)', async ({ page }) => {
    await setupBaseMocks(page)
    let spamCallCount = 0
    await page.route(`${API}/api/emails?*`, (route) => {
      const folder = new URL(route.request().url()).searchParams.get('folder') || 'inbox'
      if (folder === 'spam') {
        spamCallCount++
        if (spamCallCount <= 1) {
          route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: 'Internal server error' }) })
        } else {
          route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSpamEmails) })
        }
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 2, emails: mockEmails.slice(0, 2), has_more: false, offset: 0, filter: 'all', source: 'cache' }) })
      }
    })
    const app = new AppPage(page); await app.goto(); await app.waitForReady(); await app.navigateToSpam()
    await expect(page.locator('.error-state, .email-list-error, [class*="error"]').first()).toBeVisible({ timeout: 10000 })
    await page.locator('button:has-text("Réessayer"), button:has-text("Retry")').first().click()
    await expect(page.locator('[data-testid="email-item"]').first()).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Indésirables — détail email', () => {
  test.beforeEach(async ({ page }) => {
    await setupSpamMocks(page)
    await page.route((url) => url.origin === API && url.pathname.match(/^\/api\/emails\/spam-email-\d+$/) !== null, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...mockEmailDetails['email-1'], id: 'spam-email-0', subject: 'Gagnez 10 000 € maintenant', sender: 'promo@spam-site.com' }) })
    })
    await page.route((url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/read$/) !== null, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
    })
    await page.route((url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/thread$/) !== null, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 1, emails: [] }) })
    })
  })

  test('clic sur un email spam ouvre son détail', async ({ page }) => {
    const app = new AppPage(page); await app.goto(); await app.waitForReady(); await app.navigateToSpam()
    await page.locator('[data-testid="email-item"]').first().click()
    await expect(page.locator('.email-detail-body, .email-detail-inline, .email-detail-modal').first()).toBeVisible({ timeout: 10000 })
  })
  test('le sujet est visible dans le détail', async ({ page }) => {
    const app = new AppPage(page); await app.goto(); await app.waitForReady(); await app.navigateToSpam()
    await page.locator('[data-testid="email-item"]').first().click()
    await expect(page.locator('text=Gagnez 10 000 € maintenant').first()).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Indésirables — comportements spécifiques', () => {
  test('affiche un état vide quand aucun email', async ({ page }) => {
    await setupBaseMocks(page)
    await page.route(`${API}/api/emails?*`, (route) => {
      const folder = new URL(route.request().url()).searchParams.get('folder') || 'inbox'
      if (folder === 'spam') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 0, emails: [], has_more: false, offset: 0, filter: 'all', source: 'cache' }) })
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 2, emails: mockEmails.slice(0, 2), has_more: false, offset: 0, filter: 'all', source: 'cache' }) })
      }
    })
    const app = new AppPage(page); await app.goto(); await app.waitForReady(); await app.navigateToSpam()
    await expect(page.locator('.email-list-empty').first()).toBeVisible({ timeout: 10000 })
  })
})
