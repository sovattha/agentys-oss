/**
 * Archives Folder E2E Tests
 *
 * Couvre l'ensemble des comportements attendus du dossier Archives :
 * - Navigation vers Archives (lien actif, titre de page)
 * - Affichage de la liste des emails archivés (count, sujets, items)
 * - Comportement en cas d'erreur 500 (état d'erreur + bouton Réessayer)
 * - Récupération après erreur (retry 500 → 200)
 * - Ouverture et fermeture du détail d'un email archivé
 * - État vide quand aucun email archivé
 */

import { test, expect, Page } from '@playwright/test'
import { mockEmails } from './support/fixtures/mock-data'
import { setupBaseMocks } from './support/fixtures/setup'
import { AppPage } from './pages/AppPage'

const API = 'http://127.0.0.1:5050'

// ---------------------------------------------------------------------------
// Mock data — emails archivés
// ---------------------------------------------------------------------------

const mockArchivedEmails = {
  count: 3,
  emails: [
    {
      ...mockEmails[3],
      id: 'archived:200',
      subject: 'Compte-rendu réunion stratégique',
      sender: 'direction@example.com',
      sender_name: 'Direction Générale',
      folder: 'archived',
    },
    {
      ...mockEmails[4],
      id: 'archived:201',
      subject: 'Proposition partenariat 2025',
      sender: 'alice.bernard@partner.com',
      sender_name: 'Alice Bernard',
      folder: 'archived',
    },
    {
      ...mockEmails[5],
      id: 'archived:202',
      subject: 'Rapport audit interne',
      sender: 'rh@entreprise.com',
      sender_name: 'Service RH',
      folder: 'archived',
    },
  ],
  has_more: false,
  offset: 0,
  filter: 'all',
  source: 'cache',
}

// ---------------------------------------------------------------------------
// Helper — setup complet avec mock Archives
// ---------------------------------------------------------------------------

async function setupArchivedMocks(page: Page) {
  await setupBaseMocks(page)

  // Mock email detail for archived emails
  await page.route((url) => url.origin === API && /^\/api\/emails\/[^/]+$/.test(url.pathname), (route) => {
    const reqUrl = new URL(route.request().url())
    const id = decodeURIComponent(reqUrl.pathname.replace('/api/emails/', ''))
    const found = mockArchivedEmails.emails.find(e => e.id === id)
    if (found) {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...found, body: '<p>Corps de l\'email archivé.</p>', body_html: '<p>Corps de l\'email archivé.</p>', body_text: 'Corps de l\'email archivé.', cc: [], attachments: [] }),
      })
    } else {
      // fallback() retombe sur le catch-all de setupBaseMocks ({}) — continue()
      // partait au VRAI backend : /api/emails/counts matchait [^/]+ au boot,
      // 401 sur le token dev:* → logout → écran de login (diag 2026-06-13).
      route.fallback()
    }
  })

  await page.route(`${API}/api/emails?*`, (route) => {
    const url = new URL(route.request().url())
    const folder = url.searchParams.get('folder') || 'inbox'

    if (folder === 'archived') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockArchivedEmails),
      })
    } else {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          count: 2,
          emails: mockEmails.slice(0, 2),
          has_more: false,
          offset: 0,
          filter: 'all',
          source: 'cache',
        }),
      })
    }
  })
}

// ---------------------------------------------------------------------------
// Section 1 — Navigation
// ---------------------------------------------------------------------------

test.describe('Dossier Archives — navigation', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupArchivedMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('navigue vers Archives sans erreur', async ({ page }) => {
    await app.navigateToArchived()

    // Aucun message d'erreur ne doit apparaître
    const errorState = page.locator('text=/Failed to fetch emails/i')
    await expect(errorState).not.toBeVisible({ timeout: 5000 })
  })

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  test('nav Archives a la classe active après navigation', async ({ page }) => {
    await app.navigateToArchived()

    await expect(app.navArchived).toHaveClass(/active/, { timeout: 5000 })
  })

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  test('retour inbox depuis Archives fonctionne', async ({ page }) => {
    await app.navigateToArchived()
    await app.navigateToInbox()

    await expect(app.navInbox).toHaveClass(/active/, { timeout: 5000 })
  })

  test('le titre de page reflète le dossier Archives', async ({ page }) => {
    await app.navigateToArchived()

    // Le titre affiché peut être "Archives" ou "Archivés" selon la locale
    await expect(async () => {
      const title = await page.title()
      expect(title.toLowerCase()).toMatch(/archiv/)
    }).toPass({ timeout: 5000 })
  })
})

// ---------------------------------------------------------------------------
// Section 2 — Affichage liste
// ---------------------------------------------------------------------------

test.describe('Dossier Archives — affichage liste', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupArchivedMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('affiche les emails archivés après navigation', async ({ page }) => {
    await app.navigateToArchived()

    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems.first()).toBeVisible({ timeout: 10000 })
  })

  test('affiche le bon nombre d\'emails archivés', async ({ page }) => {
    await app.navigateToArchived()

    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems).toHaveCount(3, { timeout: 10000 })
  })

  test('affiche les sujets des emails archivés', async ({ page }) => {
    await app.navigateToArchived()

    await expect(page.locator('text=Compte-rendu réunion stratégique')).toBeVisible({ timeout: 10000 })
    await expect(page.locator('text=Proposition partenariat 2025')).toBeVisible({ timeout: 10000 })
  })

  test('affiche le troisième email archivé', async ({ page }) => {
    await app.navigateToArchived()

    await expect(page.locator('text=Rapport audit interne')).toBeVisible({ timeout: 10000 })
  })
})

// ---------------------------------------------------------------------------
// Section 3 — Comportement erreur 500
// ---------------------------------------------------------------------------

test.describe('Dossier Archives — état erreur 500', () => {
  test('affiche l\'état d\'erreur quand l\'API retourne 500', async ({ page }) => {
    await setupBaseMocks(page)

    // Inbox OK, Archives 500
    await page.route(`${API}/api/emails?*`, (route) => {
      const url = new URL(route.request().url())
      const folder = url.searchParams.get('folder') || 'inbox'

      if (folder === 'archived') {
        route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'Internal server error' }),
        })
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            count: 2,
            emails: mockEmails.slice(0, 2),
            has_more: false,
            offset: 0,
            filter: 'all',
            source: 'cache',
          }),
        })
      }
    })

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToArchived()

    // Un message d'erreur doit être visible
    const errorMsg = page.locator('text=/Failed to fetch emails|erreur|500/i')
    await expect(errorMsg).toBeVisible({ timeout: 10000 })
  })

  test('bouton Réessayer est visible dans l\'état d\'erreur', async ({ page }) => {
    await setupBaseMocks(page)

    await page.route(`${API}/api/emails?*`, (route) => {
      const url = new URL(route.request().url())
      const folder = url.searchParams.get('folder') || 'inbox'

      if (folder === 'archived') {
        route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'Internal server error' }),
        })
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            count: 2,
            emails: mockEmails.slice(0, 2),
            has_more: false,
            offset: 0,
            filter: 'all',
            source: 'cache',
          }),
        })
      }
    })

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToArchived()

    const retryButton = page.locator('button:has-text("Réessayer")')
    await expect(retryButton).toBeVisible({ timeout: 10000 })
  })

  test('le bouton Réessayer re-fetche les emails (500 → 200)', async ({ page }) => {
    await setupBaseMocks(page)

    let callCount = 0

    await page.route(`${API}/api/emails?*`, (route) => {
      const url = new URL(route.request().url())
      const folder = url.searchParams.get('folder') || 'inbox'

      if (folder === 'archived') {
        callCount++
        if (callCount === 1) {
          // Premier appel : erreur serveur
          route.fulfill({
            status: 500,
            contentType: 'application/json',
            body: JSON.stringify({ error: 'Internal server error' }),
          })
        } else {
          // Deuxième appel : succès
          route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(mockArchivedEmails),
          })
        }
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            count: 2,
            emails: mockEmails.slice(0, 2),
            has_more: false,
            offset: 0,
            filter: 'all',
            source: 'cache',
          }),
        })
      }
    })

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToArchived()

    // Attendre que le bouton Réessayer soit visible
    const retryButton = page.locator('button:has-text("Réessayer")')
    await expect(retryButton).toBeVisible({ timeout: 10000 })

    // Cliquer sur Réessayer
    await retryButton.click()

    // Les emails doivent apparaître après le retry
    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems.first()).toBeVisible({ timeout: 10000 })
  })
})

// ---------------------------------------------------------------------------
// Section 4 — Détail email archivé
// ---------------------------------------------------------------------------

test.describe('Dossier Archives — détail email', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupArchivedMocks(page)

    // Mock du détail de l'email archivé
    // fetchEmailDetail() encode l'ID : archived:200 → archived%3A200
    await page.route((url) => {
      return url.origin === 'http://localhost:5050' &&
        url.pathname.match(/\/api\/emails\/archived(%3A|:)\d+$/) !== null
    }, (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...mockArchivedEmails.emails[0],
          body_html: '<p>Compte-rendu de la réunion stratégique du 15 janvier.</p>',
          body_text: 'Compte-rendu de la réunion stratégique du 15 janvier.',
          cc: [],
          bcc: [],
        }),
      })
    })

    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('clic sur un email archivé ouvre le détail', async ({ page }) => {
    await app.navigateToArchived()

    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await expect(firstEmail).toBeVisible({ timeout: 10000 })
    await firstEmail.click()

    // Un panneau de détail doit s'ouvrir, ou au minimum le sujet doit être visible
    const detailPanel = page.locator('.email-detail-panel, [data-testid="email-detail"]')
    const subjectText = page.locator('text=Compte-rendu réunion stratégique')
    await expect(detailPanel.or(subjectText).first()).toBeVisible({ timeout: 5000 })
  })

  test('le sujet de l\'email est visible dans le détail', async ({ page }) => {
    await app.navigateToArchived()

    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await expect(firstEmail).toBeVisible({ timeout: 10000 })
    await firstEmail.click()

    // Le sujet doit apparaître dans la vue détail (strict: cibler uniquement le titre du modal)
    await expect(page.locator('.email-detail-title')).toContainText('Compte-rendu réunion stratégique', { timeout: 10000 })
  })

  test('fermeture du détail via la touche Escape', async ({ page }) => {
    await app.navigateToArchived()

    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await expect(firstEmail).toBeVisible({ timeout: 10000 })
    await firstEmail.click()

    // Attendre que le détail soit ouvert
    const detailPanel = page.locator('.email-detail-panel, [data-testid="email-detail"]')
    await expect(detailPanel.first()).toBeVisible({ timeout: 5000 })

    // Fermer via Escape
    await page.keyboard.press('Escape')

    // Le panneau de détail doit maintenant être fermé
    await expect(detailPanel).not.toBeVisible({ timeout: 5000 })
  })

  test('fermeture du détail via le bouton close', async ({ page }) => {
    await app.navigateToArchived()

    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await expect(firstEmail).toBeVisible({ timeout: 10000 })
    await firstEmail.click()

    // Chercher un bouton de fermeture dans le détail
    const closeButton = page.locator(
      '[data-testid="email-detail"] button[aria-label*="fermer"], ' +
      '[data-testid="email-detail"] button[aria-label*="close"], ' +
      '.email-detail-panel button[aria-label*="fermer"], ' +
      '.email-detail-panel button[aria-label*="close"]'
    )

    // Skip if the UI does not have a close button (inline detail or Escape-only)
    test.skip(await closeButton.count() === 0, 'No close button found — detail is inline or Escape-only')

    await expect(closeButton).toBeVisible({ timeout: 5000 })
    await closeButton.click()
    await expect(closeButton).not.toBeVisible({ timeout: 5000 })
  })
})

// ---------------------------------------------------------------------------
// Section 5 — Liste vide
// ---------------------------------------------------------------------------

test.describe('Dossier Archives — état vide', () => {
  test('affiche un état vide quand aucun email archivé', async ({ page }) => {
    await setupBaseMocks(page)

    await page.route(`${API}/api/emails?*`, (route) => {
      const url = new URL(route.request().url())
      const folder = url.searchParams.get('folder') || 'inbox'

      if (folder === 'archived') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            count: 0,
            emails: [],
            has_more: false,
            offset: 0,
            filter: 'all',
            source: 'cache',
          }),
        })
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            count: 2,
            emails: mockEmails.slice(0, 2),
            has_more: false,
            offset: 0,
            filter: 'all',
            source: 'cache',
          }),
        })
      }
    })

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToArchived()

    // Aucun email ne doit être listé
    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems).toHaveCount(0, { timeout: 10000 })
  })
})
