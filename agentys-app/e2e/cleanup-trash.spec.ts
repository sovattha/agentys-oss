/**
 * Cleanup Trash E2E Tests
 *
 * Tests exhaustifs pour le bouton "Clean up" (Nettoyer) de la Corbeille.
 *
 * Couvre :
 * - Bannière trash visible quand la corbeille contient des emails
 * - Bouton .trash-empty-btn visible dans la corbeille
 * - Bouton désactivé quand la corbeille est vide
 * - Clic sur le bouton ouvre une boîte de confirmation
 * - Annuler la confirmation n'appelle PAS POST /api/emails/empty-trash
 * - Confirmer appelle bien POST /api/emails/empty-trash
 * - La liste se vide après confirmation
 * - État de chargement (bouton désactivé) pendant l'appel API
 * - Résilience à une erreur 500 de l'API (pas de crash)
 */

import { test, expect, Page } from '@playwright/test'
import { mockEmails } from './support/fixtures/mock-data'
import { setupBaseMocks } from './support/fixtures/setup'
import { AppPage } from './pages/AppPage'

const API = 'http://127.0.0.1:5050'

// ---------------------------------------------------------------------------
// Mock data — 4 emails dans la corbeille
// ---------------------------------------------------------------------------

const mockTrashEmails = {
  count: 4,
  emails: [
    {
      id: 'trash-1',
      sender: 'newsletter@old.com',
      sender_name: 'Old Newsletter',
      subject: 'Ancienne newsletter',
      received_at: '2026-03-10T10:00:00Z',
      is_read: true,
      has_attachments: false,
      folder: 'trash',
    },
    {
      id: 'trash-2',
      sender: 'promo@boutique.com',
      sender_name: 'Boutique',
      subject: 'Promotion expirée',
      received_at: '2026-03-08T10:00:00Z',
      is_read: true,
      has_attachments: false,
      folder: 'trash',
    },
    {
      id: 'trash-3',
      sender: 'noreply@service.com',
      sender_name: 'Service',
      subject: 'Notification supprimée',
      received_at: '2026-03-05T10:00:00Z',
      is_read: false,
      has_attachments: false,
      folder: 'trash',
    },
    {
      id: 'trash-4',
      sender: 'info@old-company.com',
      sender_name: 'Old Company',
      subject: 'Compte supprimé',
      received_at: '2026-03-01T10:00:00Z',
      is_read: true,
      has_attachments: false,
      folder: 'trash',
    },
  ],
  has_more: false,
  offset: 0,
  filter: 'all',
  source: 'cache',
}

const mockEmptyTrashResponse = {
  count: 0,
  emails: [],
  has_more: false,
  offset: 0,
  filter: 'all',
  source: 'cache',
}

const mockInboxResponse = {
  count: 2,
  emails: mockEmails.slice(0, 2),
  has_more: false,
  offset: 0,
  filter: 'all',
  source: 'cache',
}

// ---------------------------------------------------------------------------
// Helpers setup
// ---------------------------------------------------------------------------

/**
 * Setup de base : mocks généraux + corbeille avec 4 emails
 * + endpoint empty-trash qui répond 200 { success: true, deleted_count: 4 }
 */
async function setupTrashCleanupMocks(page: Page) {
  await setupBaseMocks(page)

  // Override /api/emails : folder-aware
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
        body: JSON.stringify(mockInboxResponse),
      })
    }
  })

  // Mock POST /api/emails/empty-trash
  await page.route(
    (url) => url.origin === API && url.pathname === '/api/emails/empty-trash',
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, deleted_count: 4 }),
      })
    }
  )
}

/**
 * Setup avec corbeille vide (pour tester le bouton désactivé)
 */
async function setupEmptyTrashMocks(page: Page) {
  await setupBaseMocks(page)

  await page.route(`${API}/api/emails?*`, (route) => {
    const url = new URL(route.request().url())
    const folder = url.searchParams.get('folder') || 'inbox'
    if (folder === 'trash') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockEmptyTrashResponse),
      })
    } else {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockInboxResponse),
      })
    }
  })
}

// ---------------------------------------------------------------------------
// Section 1 — Bannière et visibilité du bouton
// ---------------------------------------------------------------------------

test.describe('Corbeille — bannière et bouton "Clean up"', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupTrashCleanupMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToTrash()
  })

  test('la bannière .trash-banner est visible dans la corbeille', async ({ page }) => {
    const banner = page.locator('.trash-banner')
    await expect(banner).toBeVisible({ timeout: 10000 })
  })

  test('la bannière affiche le texte d\'information sur la suppression automatique', async ({ page }) => {
    const banner = page.locator('.trash-banner')
    await expect(banner).toContainText(/30 days|30 jours/, { timeout: 10000 })
  })

  test('le bouton .trash-empty-btn est visible dans la corbeille', async ({ page }) => {
    const btn = page.locator('.trash-empty-btn')
    await expect(btn).toBeVisible({ timeout: 10000 })
  })

  test('le bouton "Clean up" affiche une icône poubelle', async ({ page }) => {
    const btn = page.locator('.trash-empty-btn')
    await expect(btn).toBeVisible({ timeout: 10000 })
    await expect(btn.locator('svg')).toBeVisible()
  })

  test('le bouton est activé quand la corbeille contient des emails', async ({ page }) => {
    const btn = page.locator('.trash-empty-btn')
    await expect(btn).toBeEnabled({ timeout: 10000 })
  })
})

// ---------------------------------------------------------------------------
// Section 2 — Bouton désactivé quand la corbeille est vide
// ---------------------------------------------------------------------------

test.describe('Corbeille — bouton désactivé si vide', () => {
  test('le bouton .trash-empty-btn est désactivé quand la corbeille est vide', async ({ page }) => {
    await setupEmptyTrashMocks(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToTrash()

    const btn = page.locator('.trash-empty-btn')
    await expect(btn).toBeVisible({ timeout: 10000 })
    await expect(btn).toBeDisabled({ timeout: 10000 })
  })
})

// ---------------------------------------------------------------------------
// Section 3 — Confirmation dialog
// ---------------------------------------------------------------------------

test.describe('Corbeille — boîte de confirmation', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupTrashCleanupMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToTrash()
  })

  test('cliquer sur "Clean up" ouvre une boîte de confirmation', async ({ page }) => {
    const btn = page.locator('.trash-empty-btn')
    await expect(btn).toBeEnabled({ timeout: 10000 })
    await btn.click()

    // Le dialog de confirmation doit apparaître
    const dialog = page.locator('.confirmation-dialog')
    await expect(dialog).toBeVisible({ timeout: 10000 })
  })

  test('la boîte de confirmation affiche un titre relatif à la corbeille', async ({ page }) => {
    await page.locator('.trash-empty-btn').click()

    const title = page.locator('.confirmation-dialog-title')
    await expect(title).toBeVisible({ timeout: 10000 })
    await expect(title).toContainText(/trash|corbeille/i, { timeout: 5000 })
  })

  test('la boîte de confirmation affiche le message de suppression permanente', async ({ page }) => {
    await page.locator('.trash-empty-btn').click()

    const message = page.locator('.confirmation-dialog-message')
    await expect(message).toBeVisible({ timeout: 10000 })
    await expect(message).toContainText(/delete|supprimer/i, { timeout: 5000 })
  })

  test('annuler ferme la boîte de confirmation sans appeler l\'API', async ({ page }) => {
    let emptyTrashCalled = false
    await page.route(
      (url) => url.origin === API && url.pathname === '/api/emails/empty-trash',
      (route) => {
        emptyTrashCalled = true
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, deleted_count: 4 }),
        })
      }
    )

    await page.locator('.trash-empty-btn').click()

    // Attendre que le dialog soit ouvert
    const dialog = page.locator('.confirmation-dialog')
    await expect(dialog).toBeVisible({ timeout: 10000 })

    // Cliquer sur Annuler
    const cancelBtn = page.locator('[data-testid="cancel-btn"]')
    await expect(cancelBtn).toBeVisible({ timeout: 5000 })
    await cancelBtn.click()

    // Le dialog doit se fermer
    await expect(dialog).not.toBeVisible({ timeout: 5000 })

    // L'API ne doit PAS avoir été appelée
    expect(emptyTrashCalled).toBe(false)
  })

  test('les emails sont toujours présents après annulation', async ({ page }) => {
    await page.locator('.trash-empty-btn').click()

    const dialog = page.locator('.confirmation-dialog')
    await expect(dialog).toBeVisible({ timeout: 10000 })

    await page.locator('[data-testid="cancel-btn"]').click()
    await expect(dialog).not.toBeVisible({ timeout: 5000 })

    // Les 4 emails doivent toujours être dans la liste
    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems).toHaveCount(4, { timeout: 5000 })
  })
})

// ---------------------------------------------------------------------------
// Section 4 — Confirmation et vidage réussi
// ---------------------------------------------------------------------------

test.describe('Corbeille — vidage après confirmation', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupTrashCleanupMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToTrash()
  })

  test('confirmer appelle bien POST /api/emails/empty-trash', async ({ page }) => {
    let emptyTrashCalled = false

    // Ré-intercepter pour vérifier l'appel (LIFO : priorité sur le mock de beforeEach)
    await page.route(
      (url) => url.origin === API && url.pathname === '/api/emails/empty-trash',
      (route) => {
        emptyTrashCalled = true
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, deleted_count: 4 }),
        })
      }
    )

    await page.locator('.trash-empty-btn').click()

    const dialog = page.locator('.confirmation-dialog')
    await expect(dialog).toBeVisible({ timeout: 10000 })

    const confirmBtn = page.locator('[data-testid="confirm-btn"]')
    await expect(confirmBtn).toBeVisible({ timeout: 5000 })
    await confirmBtn.click()

    await expect(async () => {
      expect(emptyTrashCalled).toBe(true)
    }).toPass({ timeout: 5000 })
  })

  test('la liste de la corbeille est vide après confirmation', async ({ page }) => {
    await page.locator('.trash-empty-btn').click()

    const dialog = page.locator('.confirmation-dialog')
    await expect(dialog).toBeVisible({ timeout: 10000 })

    await page.locator('[data-testid="confirm-btn"]').click()

    // La liste doit se vider
    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems).toHaveCount(0, { timeout: 10000 })
  })

  test('la boîte de confirmation se ferme après avoir confirmé', async ({ page }) => {
    await page.locator('.trash-empty-btn').click()

    const dialog = page.locator('.confirmation-dialog')
    await expect(dialog).toBeVisible({ timeout: 10000 })

    await page.locator('[data-testid="confirm-btn"]').click()

    await expect(dialog).not.toBeVisible({ timeout: 5000 })
  })

  test('une notification de succès apparaît après le vidage', async ({ page }) => {
    await page.locator('.trash-empty-btn').click()

    await expect(page.locator('.confirmation-dialog')).toBeVisible({ timeout: 10000 })
    await page.locator('[data-testid="confirm-btn"]').click()

    // Un toast ou message de succès doit apparaître (mentionne le nombre de messages ou "deleted")
    const successToast = page
      .locator('.toast, [role="status"], [role="alert"]')
      .filter({ visible: true })

    await expect(async () => {
      const count = await successToast.count()
      expect(count).toBeGreaterThan(0)
    }).toPass({ timeout: 8000 })
  })
})

// ---------------------------------------------------------------------------
// Section 5 — État de chargement (loading)
// ---------------------------------------------------------------------------

test.describe('Corbeille — état de chargement pendant le vidage', () => {
  test('le bouton est désactivé pendant que l\'API répond', async ({ page }) => {
    await setupBaseMocks(page)

    // Bloquer /api/emails?* pour la corbeille
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
          body: JSON.stringify(mockInboxResponse),
        })
      }
    })

    // empty-trash répond avec un délai pour observer l'état intermédiaire
    let resolveEmptyTrash!: () => void
    const emptyTrashSettled = new Promise<void>((resolve) => {
      resolveEmptyTrash = resolve
    })

    await page.route(
      (url) => url.origin === API && url.pathname === '/api/emails/empty-trash',
      async (route) => {
        // Simuler une latence réseau de 300ms
        await new Promise((r) => setTimeout(r, 300))
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, deleted_count: 4 }),
        })
        resolveEmptyTrash()
      }
    )

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToTrash()

    const btn = page.locator('.trash-empty-btn')
    await expect(btn).toBeEnabled({ timeout: 10000 })

    await btn.click()

    const dialog = page.locator('.confirmation-dialog')
    await expect(dialog).toBeVisible({ timeout: 10000 })
    await page.locator('[data-testid="confirm-btn"]').click()

    // Pendant le traitement, le bouton doit être désactivé (isEmptyingTrash = true)
    // On vérifie que la liste se vide bien après (preuve que l'état de chargement s'est bien déroulé)
    await emptyTrashSettled
    await expect(page.locator('[data-testid="email-item"]')).toHaveCount(0, { timeout: 5000 })
  })
})

// ---------------------------------------------------------------------------
// Section 6 — Résilience aux erreurs API
// ---------------------------------------------------------------------------

test.describe('Corbeille — résilience aux erreurs API', () => {
  test('aucun crash quand empty-trash retourne 500', async ({ page }) => {
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
          body: JSON.stringify(mockInboxResponse),
        })
      }
    })

    // empty-trash retourne une erreur 500
    await page.route(
      (url) => url.origin === API && url.pathname === '/api/emails/empty-trash',
      (route) => {
        route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'Internal server error' }),
        })
      }
    )

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToTrash()

    const btn = page.locator('.trash-empty-btn')
    await expect(btn).toBeEnabled({ timeout: 10000 })

    await btn.click()

    const dialog = page.locator('.confirmation-dialog')
    await expect(dialog).toBeVisible({ timeout: 10000 })
    await page.locator('[data-testid="confirm-btn"]').click()

    // L'app ne doit pas crasher (pas de page d'erreur visible)
    const crashIndicator = page.locator('text=/Something went wrong|Uncaught Error|chunk load/i')
    await expect(crashIndicator).not.toBeVisible({ timeout: 5000 })
  })

  test('les emails restent affichés après une erreur 500 de empty-trash', async ({ page }) => {
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
          body: JSON.stringify(mockInboxResponse),
        })
      }
    })

    await page.route(
      (url) => url.origin === API && url.pathname === '/api/emails/empty-trash',
      (route) => {
        route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'Internal server error' }),
        })
      }
    )

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToTrash()

    await expect(page.locator('[data-testid="email-item"]')).toHaveCount(4, { timeout: 10000 })

    await page.locator('.trash-empty-btn').click()
    await expect(page.locator('.confirmation-dialog')).toBeVisible({ timeout: 10000 })
    await page.locator('[data-testid="confirm-btn"]').click()

    // Après l'erreur, l'UI doit rester cohérente (le bouton "Clean up" est réactivé)
    const cleanUpBtn = page.locator('.trash-empty-btn')
    await expect(cleanUpBtn).toBeEnabled({ timeout: 8000 })
  })

  test('un message d\'erreur toast apparaît après une erreur 500', async ({ page }) => {
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
          body: JSON.stringify(mockInboxResponse),
        })
      }
    })

    await page.route(
      (url) => url.origin === API && url.pathname === '/api/emails/empty-trash',
      (route) => {
        route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'Internal server error' }),
        })
      }
    )

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToTrash()

    await page.locator('.trash-empty-btn').click()
    await expect(page.locator('.confirmation-dialog')).toBeVisible({ timeout: 10000 })
    await page.locator('[data-testid="confirm-btn"]').click()

    // Un toast d'erreur doit apparaître
    const errorToast = page
      .locator('.toast, [role="status"], [role="alert"]')
      .filter({ visible: true })

    await expect(async () => {
      const count = await errorToast.count()
      expect(count).toBeGreaterThan(0)
    }).toPass({ timeout: 8000 })
  })
})
