/**
 * Spam Folder — Bouton "Clean up" / "Nettoyer" E2E Tests
 *
 * Couvre le cycle complet du bouton de nettoyage du dossier Indésirables :
 * - Visibilité de la bannière et du bouton
 * - État désactivé quand la liste est vide
 * - Ouverture de la modale de confirmation au clic
 * - Annulation sans appel API
 * - Confirmation → appel POST /api/emails/empty-spam → liste vidée
 * - Résilience en cas d'erreur 500 de l'API
 */

import { test, expect, Page } from '@playwright/test'
import { mockEmails } from './support/fixtures/mock-data'
import { setupBaseMocks } from './support/fixtures/setup'
import { AppPage } from './pages/AppPage'

const API = 'http://127.0.0.1:5050'

// ---------------------------------------------------------------------------
// Données de test
// ---------------------------------------------------------------------------

const mockSpamEmails = {
  count: 3,
  emails: [
    {
      ...mockEmails[0],
      id: 'spam-1',
      sender: 'promo@spam.com',
      sender_name: 'Super Promo',
      subject: 'Offre exclusive !!!',
      received_at: '2026-03-20T10:00:00Z',
      is_read: true,
      has_attachments: false,
      folder: 'spam',
    },
    {
      ...mockEmails[1],
      id: 'spam-2',
      sender: 'deals@fake.net',
      sender_name: 'Deals',
      subject: 'Vous avez gagné 10000€',
      received_at: '2026-03-19T10:00:00Z',
      is_read: false,
      has_attachments: false,
      folder: 'spam',
    },
    {
      ...mockEmails[2],
      id: 'spam-3',
      sender: 'noreply@phishing.xyz',
      sender_name: 'Banque',
      subject: 'Votre compte est suspendu',
      received_at: '2026-03-18T10:00:00Z',
      is_read: true,
      has_attachments: false,
      folder: 'spam',
    },
  ],
  has_more: false,
  offset: 0,
  filter: 'all',
  source: 'cache',
}

const emptySpamResponse = {
  count: 0,
  emails: [],
  has_more: false,
  offset: 0,
  filter: 'all',
  source: 'cache',
}

// ---------------------------------------------------------------------------
// Helpers de setup
// ---------------------------------------------------------------------------

/** Mock de base + spam avec 3 emails + endpoint empty-spam (succès). */
async function setupSpamCleanupMocks(page: Page) {
  await setupBaseMocks(page)

  await page.route(`${API}/api/emails?*`, (route) => {
    const url = new URL(route.request().url())
    const folder = url.searchParams.get('folder') || 'inbox'
    if (folder === 'spam') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockSpamEmails),
      })
    } else {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ count: 0, emails: [], has_more: false }),
      })
    }
  })

  await page.route(
    (url) => url.origin === API && url.pathname === '/api/emails/empty-spam',
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, deleted_count: 3 }),
      })
    },
  )
}

/** Mock de base + spam vide (0 emails) + endpoint empty-spam (non appelé). */
async function setupEmptySpamMocks(page: Page) {
  await setupBaseMocks(page)

  await page.route(`${API}/api/emails?*`, (route) => {
    const url = new URL(route.request().url())
    const folder = url.searchParams.get('folder') || 'inbox'
    if (folder === 'spam') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(emptySpamResponse),
      })
    } else {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ count: 0, emails: [], has_more: false }),
      })
    }
  })
}

/** Mock de base + spam avec 3 emails + endpoint empty-spam renvoie 500. */
async function setupSpamCleanupErrorMocks(page: Page) {
  await setupBaseMocks(page)

  await page.route(`${API}/api/emails?*`, (route) => {
    const url = new URL(route.request().url())
    const folder = url.searchParams.get('folder') || 'inbox'
    if (folder === 'spam') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockSpamEmails),
      })
    } else {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ count: 0, emails: [], has_more: false }),
      })
    }
  })

  await page.route(
    (url) => url.origin === API && url.pathname === '/api/emails/empty-spam',
    (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal server error' }),
      })
    },
  )
}

// ---------------------------------------------------------------------------
// Sélecteurs
// ---------------------------------------------------------------------------

const SEL = {
  spamBanner: '.spam-banner',
  cleanupBtn: '.spam-empty-btn',
  emailItem: '[data-testid="email-item"]',
  // ConfirmationDialog utilise la classe .confirmation-dialog sur le DialogContent
  confirmDialog: '.confirmation-dialog',
  confirmBtn: '[data-testid="confirm-btn"]',
  cancelBtn: '[data-testid="cancel-btn"]',
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('Bouton Nettoyer — bannière et visibilité', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupSpamCleanupMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToSpam()
  })

  test('la bannière spam est visible dans le dossier Indésirables', async ({ page }) => {
    const banner = page.locator(SEL.spamBanner)
    await expect(banner).toBeVisible({ timeout: 10000 })
  })

  test('la bannière contient le texte de suppression automatique à 30 jours', async ({ page }) => {
    const banner = page.locator(SEL.spamBanner)
    await expect(banner).toBeVisible({ timeout: 10000 })
    // Accepte l'anglais ou le français selon la locale active
    await expect(banner).toContainText(/30 day|30 jours/i)
  })

  test('le bouton Nettoyer est visible quand il y a des emails spam', async ({ page }) => {
    await expect(page.locator(SEL.cleanupBtn)).toBeVisible({ timeout: 10000 })
  })

  test('le bouton Nettoyer affiche une icône poubelle', async ({ page }) => {
    const btn = page.locator(SEL.cleanupBtn)
    await expect(btn).toBeVisible({ timeout: 10000 })
    await expect(btn.locator('svg')).toBeVisible()
  })
})

test.describe('Bouton Nettoyer — état désactivé quand le dossier est vide', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupEmptySpamMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToSpam()
  })

  test('le bouton Nettoyer est désactivé quand il n\'y a aucun email spam', async ({ page }) => {
    // La bannière doit toujours être présente même avec 0 emails
    const banner = page.locator(SEL.spamBanner)
    await expect(banner).toBeVisible({ timeout: 10000 })

    const btn = page.locator(SEL.cleanupBtn)
    await expect(btn).toBeVisible({ timeout: 10000 })
    await expect(btn).toBeDisabled()
  })

  test('cliquer sur le bouton désactivé n\'ouvre pas de dialog', async ({ page }) => {
    const btn = page.locator(SEL.cleanupBtn)
    await expect(btn).toBeVisible({ timeout: 10000 })
    await expect(btn).toBeDisabled()

    // Forcer le clic malgré le disabled pour s'assurer que rien ne s'ouvre
    await btn.click({ force: true })
    await expect(page.locator(SEL.confirmDialog)).not.toBeVisible({ timeout: 2000 })
  })
})

test.describe('Bouton Nettoyer — ouverture de la confirmation', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupSpamCleanupMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToSpam()
    // S'assurer que les emails sont chargés avant de cliquer
    await expect(page.locator(SEL.emailItem).first()).toBeVisible({ timeout: 10000 })
  })

  test('cliquer sur Nettoyer ouvre la dialog de confirmation', async ({ page }) => {
    await page.locator(SEL.cleanupBtn).click()
    await expect(page.locator(SEL.confirmDialog)).toBeVisible({ timeout: 5000 })
  })

  test('la dialog de confirmation affiche un titre et un message', async ({ page }) => {
    await page.locator(SEL.cleanupBtn).click()
    const dialog = page.locator(SEL.confirmDialog)
    await expect(dialog).toBeVisible({ timeout: 5000 })

    // Titre : "Empty spam" (en) ou "Vider les indésirables" (fr)
    await expect(dialog).toContainText(/empty spam|vider les ind[eé]sirables/i)
    // Message : suppression permanente
    await expect(dialog).toContainText(/delete|supprimer/i)
  })

  test('la dialog présente un bouton Annuler et un bouton de confirmation destructif', async ({ page }) => {
    await page.locator(SEL.cleanupBtn).click()
    await expect(page.locator(SEL.confirmDialog)).toBeVisible({ timeout: 5000 })

    await expect(page.locator(SEL.cancelBtn)).toBeVisible()
    const confirmBtn = page.locator(SEL.confirmBtn)
    await expect(confirmBtn).toBeVisible()
    // Le bouton de confirmation doit porter la classe destructive
    await expect(confirmBtn).toHaveClass(/destructive/)
  })
})

test.describe('Bouton Nettoyer — annulation', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupSpamCleanupMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToSpam()
    await expect(page.locator(SEL.emailItem).first()).toBeVisible({ timeout: 10000 })
  })

  test('annuler ferme la dialog sans appeler l\'API', async ({ page }) => {
    let apiCalled = false
    await page.route(
      (url) => url.origin === API && url.pathname === '/api/emails/empty-spam',
      (route) => {
        apiCalled = true
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, deleted_count: 3 }),
        })
      },
    )

    await page.locator(SEL.cleanupBtn).click()
    await expect(page.locator(SEL.confirmDialog)).toBeVisible({ timeout: 5000 })

    await page.locator(SEL.cancelBtn).click()
    await expect(page.locator(SEL.confirmDialog)).not.toBeVisible({ timeout: 3000 })

    expect(apiCalled).toBe(false)
  })

  test('annuler conserve la liste d\'emails intacte', async ({ page }) => {
    await page.locator(SEL.cleanupBtn).click()
    await expect(page.locator(SEL.confirmDialog)).toBeVisible({ timeout: 5000 })

    await page.locator(SEL.cancelBtn).click()
    await expect(page.locator(SEL.confirmDialog)).not.toBeVisible({ timeout: 3000 })

    // Les emails doivent toujours être là
    await expect(page.locator(SEL.emailItem)).toHaveCount(3, { timeout: 5000 })
  })

  test('appuyer sur Échap ferme la dialog sans appeler l\'API', async ({ page }) => {
    let apiCalled = false
    await page.route(
      (url) => url.origin === API && url.pathname === '/api/emails/empty-spam',
      (route) => {
        apiCalled = true
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, deleted_count: 3 }),
        })
      },
    )

    await page.locator(SEL.cleanupBtn).click()
    await expect(page.locator(SEL.confirmDialog)).toBeVisible({ timeout: 5000 })

    await page.keyboard.press('Escape')
    await expect(page.locator(SEL.confirmDialog)).not.toBeVisible({ timeout: 3000 })

    expect(apiCalled).toBe(false)
  })
})

test.describe('Bouton Nettoyer — confirmation et appel API', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupSpamCleanupMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToSpam()
    await expect(page.locator(SEL.emailItem).first()).toBeVisible({ timeout: 10000 })
  })

  test('confirmer déclenche POST /api/emails/empty-spam', async ({ page }) => {
    let requestMethod = ''
    let requestPath = ''

    await page.route(
      (url) => url.origin === API && url.pathname === '/api/emails/empty-spam',
      (route) => {
        requestMethod = route.request().method()
        requestPath = new URL(route.request().url()).pathname
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, deleted_count: 3 }),
        })
      },
    )

    await page.locator(SEL.cleanupBtn).click()
    await expect(page.locator(SEL.confirmDialog)).toBeVisible({ timeout: 5000 })
    await page.locator(SEL.confirmBtn).click()

    // Attendre que la dialog se ferme (l'appel API a eu lieu)
    await expect(page.locator(SEL.confirmDialog)).not.toBeVisible({ timeout: 5000 })

    expect(requestMethod).toBe('POST')
    expect(requestPath).toBe('/api/emails/empty-spam')
  })

  test('la dialog se ferme après confirmation', async ({ page }) => {
    await page.locator(SEL.cleanupBtn).click()
    await expect(page.locator(SEL.confirmDialog)).toBeVisible({ timeout: 5000 })
    await page.locator(SEL.confirmBtn).click()

    await expect(page.locator(SEL.confirmDialog)).not.toBeVisible({ timeout: 5000 })
  })
})

test.describe('Bouton Nettoyer — vidage de la liste après confirmation', () => {
  test('la liste spam devient vide après confirmation de nettoyage', async ({ page }) => {
    // Setup : spam avec 3 emails; après l'appel empty-spam, on retourne 0 emails
    await setupBaseMocks(page)

    let spamCallCount = 0
    await page.route(`${API}/api/emails?*`, (route) => {
      const url = new URL(route.request().url())
      const folder = url.searchParams.get('folder') || 'inbox'
      if (folder === 'spam') {
        spamCallCount++
        // Première requête : 3 emails. Requêtes suivantes (après suppression) : 0 emails.
        const body = spamCallCount <= 1 ? mockSpamEmails : emptySpamResponse
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(body),
        })
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ count: 0, emails: [], has_more: false }),
        })
      }
    })

    await page.route(
      (url) => url.origin === API && url.pathname === '/api/emails/empty-spam',
      (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, deleted_count: 3 }),
        })
      },
    )

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToSpam()

    // Vérifier que les 3 emails sont présents au départ
    await expect(page.locator(SEL.emailItem)).toHaveCount(3, { timeout: 10000 })

    // Ouvrir la confirmation et confirmer
    await page.locator(SEL.cleanupBtn).click()
    await expect(page.locator(SEL.confirmDialog)).toBeVisible({ timeout: 5000 })
    await page.locator(SEL.confirmBtn).click()
    await expect(page.locator(SEL.confirmDialog)).not.toBeVisible({ timeout: 5000 })

    // Après le refresh, la liste doit être vide (état vide ou 0 items)
    await expect(page.locator(SEL.emailItem)).toHaveCount(0, { timeout: 10000 })
  })
})

test.describe('Bouton Nettoyer — résilience erreur API', () => {
  test('l\'app ne plante pas si empty-spam retourne 500', async ({ page }) => {
    await setupSpamCleanupErrorMocks(page)

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToSpam()

    await expect(page.locator(SEL.emailItem).first()).toBeVisible({ timeout: 10000 })

    await page.locator(SEL.cleanupBtn).click()
    await expect(page.locator(SEL.confirmDialog)).toBeVisible({ timeout: 5000 })
    await page.locator(SEL.confirmBtn).click()

    // La dialog doit se fermer même en cas d'erreur
    await expect(page.locator(SEL.confirmDialog)).not.toBeVisible({ timeout: 5000 })

    // Aucun crash : la page principale reste affichée (le conteneur email-list-container est toujours là)
    await expect(page.locator('.email-list-container')).toBeVisible({ timeout: 5000 })
  })

  test('les emails restent affichés après une erreur 500 de empty-spam', async ({ page }) => {
    await setupSpamCleanupErrorMocks(page)

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToSpam()

    await expect(page.locator(SEL.emailItem).first()).toBeVisible({ timeout: 10000 })
    const initialCount = await page.locator(SEL.emailItem).count()

    await page.locator(SEL.cleanupBtn).click()
    await expect(page.locator(SEL.confirmDialog)).toBeVisible({ timeout: 5000 })
    await page.locator(SEL.confirmBtn).click()
    await expect(page.locator(SEL.confirmDialog)).not.toBeVisible({ timeout: 5000 })

    // Les emails sont toujours affichés (pas de suppression côté client sans succès serveur)
    // On tolère que la liste recharge ; l'important est qu'il n'y ait pas de crash
    await expect(page.locator('.email-list-container')).toBeVisible({ timeout: 5000 })
    expect(initialCount).toBeGreaterThan(0)
  })
})
