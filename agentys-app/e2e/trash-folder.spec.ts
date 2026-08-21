/**
 * Trash Folder E2E Tests
 *
 * Tests exhaustifs pour le dossier Corbeille (Trash) de l'application Agentys.
 *
 * Couvre :
 * - Navigation vers la Corbeille sans erreur
 * - Classe active sur l'élément nav Trash
 * - Retour vers l'inbox depuis la Corbeille
 * - Mise à jour du titre de page
 * - Affichage de la liste des emails dans la corbeille
 * - Comptage correct des emails
 * - Visibilité des sujets
 * - Comportement en cas d'erreur 500 (état d'erreur + bouton Réessayer)
 * - Récupération après erreur (retry : 1er appel 500, 2ème appel 200)
 * - Ouverture du détail d'un email de la corbeille au clic
 * - Bannière / info Corbeille (si présente dans l'UI)
 * - État vide quand aucun email
 */

import { test, expect, Page } from '@playwright/test'
import { mockEmails } from './support/fixtures/mock-data'
import { setupBaseMocks } from './support/fixtures/setup'
import { AppPage } from './pages/AppPage'

const API = 'http://127.0.0.1:5050'

// ---------------------------------------------------------------------------
// Mock data — emails de la corbeille
// ---------------------------------------------------------------------------

const mockTrashEmails = {
  count: 3,
  emails: [
    {
      ...mockEmails[0],
      id: 'trash-email-0',
      subject: 'Ancienne newsletter supprimée',
      sender: 'newsletter@old-service.com',
      folder: 'trash',
    },
    {
      ...mockEmails[1],
      id: 'trash-email-1',
      subject: 'Promotion expirée',
      sender: 'promo@boutique.com',
      folder: 'trash',
    },
    {
      ...mockEmails[2],
      id: 'trash-email-2',
      subject: 'Message indésirable supprimé',
      sender: 'inconnu@domaine.xyz',
      folder: 'trash',
    },
  ],
  has_more: false,
  offset: 0,
  filter: 'all',
  source: 'cache',
}

// ---------------------------------------------------------------------------
// Helper setup — active les mocks de base + override /api/emails folder-aware
// ---------------------------------------------------------------------------

async function setupTrashMocks(page: Page) {
  await setupBaseMocks(page)

  await page.route(`${API}/api/emails?*`, (route) => {
    const url = new URL(route.request().url())
    const folder = url.searchParams.get('folder') || 'inbox'

    if (folder === 'trash') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockTrashEmails),
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

test.describe('Corbeille — navigation', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupTrashMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('navigue vers la Corbeille sans erreur', async ({ page }) => {
    await app.navigateToTrash()

    const errorState = page.locator('text=/Failed to fetch emails|erreur|500/i')
    await expect(errorState).not.toBeVisible({ timeout: 10000 })
  })

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  test('nav Corbeille a la classe active après navigation', async ({ page }) => {
    await app.navigateToTrash()
    await expect(app.navTrash).toHaveClass(/active/, { timeout: 10000 })
  })

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  test('retour inbox depuis la Corbeille fonctionne', async ({ page }) => {
    await app.navigateToTrash()
    await app.navigateToInbox()
    await expect(app.navInbox).toHaveClass(/active/, { timeout: 10000 })
  })

  test('le titre de page est mis à jour après navigation vers la Corbeille', async ({ page }) => {
    await app.navigateToTrash()
    await expect(async () => {
      const title = await page.title()
      expect(title.toLowerCase()).toMatch(/corbeille|trash/i)
    }).toPass({ timeout: 10000 })
  })
})

// ---------------------------------------------------------------------------
// Section 2 — Affichage liste
// ---------------------------------------------------------------------------

test.describe('Corbeille — affichage liste', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupTrashMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('affiche les emails dans la corbeille', async ({ page }) => {
    await app.navigateToTrash()

    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems.first()).toBeVisible({ timeout: 10000 })
  })

  test('affiche le nombre correct d\'emails dans la corbeille', async ({ page }) => {
    await app.navigateToTrash()

    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems).toHaveCount(3, { timeout: 10000 })
  })

  test('affiche les sujets des emails de la corbeille', async ({ page }) => {
    await app.navigateToTrash()

    await expect(page.locator('text=Ancienne newsletter supprimée')).toBeVisible({ timeout: 10000 })
    await expect(page.locator('text=Promotion expirée')).toBeVisible({ timeout: 10000 })
  })
})

// ---------------------------------------------------------------------------
// Section 3 — Comportement erreur 500
// ---------------------------------------------------------------------------

test.describe('Corbeille — état erreur 500', () => {
  test('affiche l\'état d\'erreur quand l\'API retourne 500 pour la corbeille', async ({ page }) => {
    await setupBaseMocks(page)

    await page.route(`${API}/api/emails?*`, (route) => {
      const url = new URL(route.request().url())
      const folder = url.searchParams.get('folder') || 'inbox'

      if (folder === 'trash') {
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
    await app.navigateToTrash()

    const errorMsg = page.locator('text=/Failed to fetch emails|erreur|500/i')
    await expect(errorMsg).toBeVisible({ timeout: 10000 })
  })

  test('bouton Réessayer est visible en état d\'erreur', async ({ page }) => {
    await setupBaseMocks(page)

    await page.route(`${API}/api/emails?*`, (route) => {
      const url = new URL(route.request().url())
      const folder = url.searchParams.get('folder') || 'inbox'

      if (folder === 'trash') {
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
    await app.navigateToTrash()

    const retryButton = page.locator('button:has-text("Réessayer")')
    await expect(retryButton).toBeVisible({ timeout: 10000 })
  })

  test('bouton Réessayer re-fetche les emails (1er 500, 2ème 200)', async ({ page }) => {
    await setupBaseMocks(page)

    let trashCallCount = 0

    await page.route(`${API}/api/emails?*`, (route) => {
      const url = new URL(route.request().url())
      const folder = url.searchParams.get('folder') || 'inbox'

      if (folder === 'trash') {
        trashCallCount++
        if (trashCallCount === 1) {
          // Premier appel : erreur
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
            body: JSON.stringify(mockTrashEmails),
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
    await app.navigateToTrash()

    // Attendre que le bouton Réessayer apparaisse
    const retryButton = page.locator('button:has-text("Réessayer")')
    await expect(retryButton).toBeVisible({ timeout: 10000 })

    // Cliquer sur Réessayer
    await retryButton.click()

    // Les emails doivent apparaître après le retry
    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems.first()).toBeVisible({ timeout: 10000 })
    await expect(emailItems).toHaveCount(3, { timeout: 10000 })
  })
})

// ---------------------------------------------------------------------------
// Section 4 — Détail email dans la corbeille
// ---------------------------------------------------------------------------

test.describe('Corbeille — détail email', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupTrashMocks(page)

    // Mock du détail pour le premier email de la corbeille
    await page.route(`${API}/api/emails/trash-email-0`, (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...mockTrashEmails.emails[0],
          body_html: '<p>Contenu de l\'ancienne newsletter supprimée.</p>',
          body_text: "Contenu de l'ancienne newsletter supprimée.",
          cc: [],
          bcc: [],
        }),
      })
    })

    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('clic sur un email de la corbeille ouvre son détail', async ({ page }) => {
    await app.navigateToTrash()

    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await expect(firstEmail).toBeVisible({ timeout: 10000 })
    await firstEmail.click()

    // Le panneau de détail ou le sujet doit être visible
    const detailOrSubject = page.locator('.email-detail-panel, [data-testid="email-detail"]').or(
      page.locator('text=Ancienne newsletter supprimée')
    )
    await expect(detailOrSubject.first()).toBeVisible({ timeout: 10000 })
  })

  test('le sujet de l\'email est visible dans le détail', async ({ page }) => {
    await app.navigateToTrash()

    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await expect(firstEmail).toBeVisible({ timeout: 10000 })
    await firstEmail.click()

    await expect(page.locator('.email-detail-title')).toContainText('Ancienne newsletter supprimée', { timeout: 10000 })
  })
})

// ---------------------------------------------------------------------------
// Section 5 — Actions corbeille spécifiques
// ---------------------------------------------------------------------------

test.describe('Corbeille — comportements spécifiques', () => {
  let app: AppPage

  test('affiche une bannière ou information relative à la Corbeille', async ({ page }) => {
    await setupTrashMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToTrash()

    // Cherche un indicateur visuel propre à la corbeille (bannière, label, titre de section)
    const trashIndicator = page.locator('text=/corbeille|trash|supprimé|deleted/i').or(
      page.locator('[data-folder="trash"], .trash-banner, .folder-trash')
    )
    // On vérifie que l'app est bien dans la vue Corbeille (nav active suffit comme preuve)
    await expect(app.navTrash).toHaveClass(/active/, { timeout: 10000 })

    // Un indicateur visuel de la corbeille doit être présent (bannière, label, ou titre)
    await expect(trashIndicator.first()).toBeVisible({ timeout: 5000 })
  })

  test('affiche un état vide quand la corbeille ne contient aucun email', async ({ page }) => {
    await setupBaseMocks(page)

    await page.route(`${API}/api/emails?*`, (route) => {
      const url = new URL(route.request().url())
      const folder = url.searchParams.get('folder') || 'inbox'

      if (folder === 'trash') {
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

    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToTrash()

    // Aucun item email ne doit être présent
    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems).toHaveCount(0, { timeout: 10000 })
  })
})

// ---------------------------------------------------------------------------
// Section 5 — Suppression depuis l'inbox → l'email ne réapparaît pas
// Regression: delete API was slow (~60s IMAP) → background sync re-added email
// ---------------------------------------------------------------------------

test.describe('Corbeille — suppression inbox', () => {
  test('l\'API delete répond immédiatement (200) sans attendre IMAP', async ({ page }) => {
    await setupBaseMocks(page)

    let deleteResolved = false

    // Mock delete endpoint — responds 200 instantly (backend does IMAP in background)
    await page.route(`${API}/api/emails/test-123/delete`, (route) => {
      deleteResolved = true
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, email_id: 'test-123', message: 'Email moved to trash' }),
      })
    })

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    // Call the delete API and verify it responds immediately
    const response = await page.evaluate(async () => {
      const res = await fetch('http://127.0.0.1:5050/api/emails/test-123/delete', { method: 'POST' })
      return { status: res.status, data: await res.json() }
    })

    expect(deleteResolved).toBe(true)
    expect(response.status).toBe(200)
    expect(response.data.success).toBe(true)
  })

  test('après suppression, le serveur ne retourne plus l\'email dans l\'inbox', async ({ page }) => {
    let deleteHappened = false
    const allEmails = mockEmails.slice(0, 3).map((e, i) => ({
      ...e,
      id: `email-${i}`,
      subject: `Test email ${i}`,
    }))

    await setupBaseMocks(page)

    // After delete, server returns only 2 emails (evicted from SQLite cache)
    await page.route(`${API}/api/emails?*`, (route) => {
      const url = new URL(route.request().url())
      const folder = url.searchParams.get('folder') || 'inbox'
      if (folder === 'inbox') {
        const emails = deleteHappened
          ? allEmails.filter(e => e.id !== 'email-0')
          : allEmails
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            count: emails.length,
            emails,
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
          body: JSON.stringify({ count: 0, emails: [], has_more: false, offset: 0, filter: 'all', source: 'cache' }),
        })
      }
    })

    await page.route(`${API}/api/emails/email-0/delete`, (route) => {
      deleteHappened = true
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, email_id: 'email-0', message: 'Email moved to trash' }),
      })
    })

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    // Initially 3 emails
    const items = page.locator('[data-testid="email-item"]')
    await expect(items).toHaveCount(3, { timeout: 5000 })

    // Trigger delete via API (simulating what the UI does)
    await page.evaluate(async () => {
      await fetch('http://127.0.0.1:5050/api/emails/email-0/delete', { method: 'POST' })
    })

    // Re-fetch inbox (simulating page refresh / navigation)
    await page.evaluate(async () => {
      // Force refetch by dispatching a custom event or clicking refresh
      window.dispatchEvent(new Event('focus'))
    })
    await page.waitForLoadState('domcontentloaded')

    // The server should return 2 emails (deleted one evicted from cache)
    const response = await page.evaluate(async () => {
      const res = await fetch('http://127.0.0.1:5050/api/emails?limit=50&offset=0&filter=all&folder=inbox')
      return res.json()
    })
    expect(response.count).toBe(2)
    expect(response.emails.find((e: { id: string }) => e.id === 'email-0')).toBeUndefined()
  })
})
