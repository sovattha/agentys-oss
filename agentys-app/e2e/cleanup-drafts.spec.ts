/**
 * Clean up Button E2E Tests
 *
 * Tests for the "Clean up" button (.drafts-cleanup-btn) in the Drafts view.
 * The button lives inside .drafts-banner and calls POST /api/pending-drafts/purge-all.
 * After a successful purge the component re-fetches GET /api/pending-drafts and
 * renders the empty state.
 *
 * Route mocking strategy
 * ----------------------
 * Playwright evaluates routes in LIFO order (last registered = highest priority).
 * setupBaseMocks() already mocks GET /api/pending-drafts → empty list.
 * Each test that needs drafts registers its own handler AFTER setupBaseMocks()
 * so it takes precedence.
 *
 * A shared route handler intercepts ALL /api/pending-drafts requests (GET + POST)
 * using a URL-function matcher so it catches both the initial GET and the
 * purge POST in a single registration.
 */

import { test, expect, Page, Route } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const DRAFTS_RESPONSE = {
  drafts: [
    {
      id: 'draft-1',
      email_id: 'email-1',
      email_sender: 'marie.dupont@example.com',
      email_sender_name: 'Marie Dupont',
      email_subject: 'Rapport trimestriel Q4 2025',
      draft_body: 'Bonjour Marie, merci pour ce rapport...',
      status: 'pending',
      created_at: '2026-03-20T10:00:00Z',
      updated_at: '2026-03-20T10:00:00Z',
    },
    {
      id: 'draft-2',
      email_id: 'email-2',
      email_sender: 'pierre.martin@example.com',
      email_sender_name: 'Pierre Martin',
      email_subject: 'Réunion projet Alpha',
      draft_body: 'Bonjour Pierre, je confirme...',
      status: 'pending',
      created_at: '2026-03-19T10:00:00Z',
      updated_at: '2026-03-19T10:00:00Z',
    },
  ],
  pending_count: 2,
}

const EMPTY_DRAFTS_RESPONSE = {
  drafts: [],
  pending_count: 0,
}

const PURGE_SUCCESS_RESPONSE = { success: true, deleted_count: 2 }

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Navigate to the Brouillons (Drafts) view via the sidebar nav item.
 */
async function navigateToDrafts(page: Page): Promise<void> {
  await page.locator('[data-testid="nav-drafts"]').click()
}

/**
 * Register mocks for the drafts view with 2 drafts pre-loaded.
 *
 * Uses a counter so that:
 *   - 1st GET  → returns the two-draft list
 *   - POST purge-all → returns success
 *   - 2nd GET  → returns the empty list (simulates post-purge refresh)
 *
 * The handler is registered AFTER setupBaseMocks() so LIFO gives it priority.
 */
async function setupDraftMocksWithPurge(page: Page): Promise<void> {
  await setupBaseMocks(page)

  let getCallCount = 0

  await page.route(
    (url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts'),
    (route: Route) => {
      const method = route.request().method()

      if (method === 'POST' && route.request().url().includes('/purge-all')) {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(PURGE_SUCCESS_RESPONSE),
        })
        return
      }

      if (method === 'GET') {
        getCallCount++
        const body = getCallCount === 1 ? DRAFTS_RESPONSE : EMPTY_DRAFTS_RESPONSE
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(body),
        })
        return
      }

      route.continue()
    }
  )
}

/**
 * Register mocks for the drafts view starting from an empty list.
 * Used for the "button disabled when 0 drafts" scenario.
 */
async function setupEmptyDraftMocks(page: Page): Promise<void> {
  await setupBaseMocks(page)

  await page.route(
    (url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts'),
    (route: Route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(EMPTY_DRAFTS_RESPONSE),
        })
      } else {
        route.continue()
      }
    }
  )
}

/**
 * Register mocks for the error-handling scenario.
 * GET returns 2 drafts; POST purge-all returns 500.
 */
async function setupDraftMocksWithPurgeError(page: Page): Promise<void> {
  await setupBaseMocks(page)

  await page.route(
    (url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts'),
    (route: Route) => {
      const method = route.request().method()

      if (method === 'POST' && route.request().url().includes('/purge-all')) {
        route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'Internal server error' }),
        })
        return
      }

      if (method === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(DRAFTS_RESPONSE),
        })
        return
      }

      route.continue()
    }
  )
}

// ---------------------------------------------------------------------------
// Test suites
// ---------------------------------------------------------------------------

test.describe('Bouton "Clean up" — visibilité de la bannière', () => {
  test.beforeEach(async ({ page }) => {
    await setupDraftMocksWithPurge(page)
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToDrafts(page)
    // Attendre que les brouillons soient chargés
    await expect(page.locator('.draft-item').first()).toBeVisible({ timeout: 10000 })
  })

  test('la bannière .drafts-banner est visible quand des brouillons existent', async ({ page }) => {
    const banner = page.locator('.drafts-banner')
    await expect(banner).toBeVisible({ timeout: 10000 })
  })

  test('le bouton .drafts-cleanup-btn est visible quand des brouillons existent', async ({ page }) => {
    const button = page.locator('.drafts-cleanup-btn')
    await expect(button).toBeVisible({ timeout: 10000 })
  })

  test('le bouton affiche une icône poubelle', async ({ page }) => {
    const button = page.locator('.drafts-cleanup-btn')
    await expect(button).toBeVisible({ timeout: 10000 })
    await expect(button.locator('svg')).toBeVisible()
  })
})

test.describe('Bouton "Clean up" — état désactivé sans brouillons', () => {
  test('le bouton est désactivé quand il n\'y a aucun brouillon', async ({ page }) => {
    await setupEmptyDraftMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToDrafts(page)

    // La bannière n'est rendue que s'il y a au moins un brouillon. Avec 0 brouillons
    // elle reste masquée — le bouton .drafts-cleanup-btn ne doit donc pas exister.
    const button = page.locator('.drafts-cleanup-btn')
    expect(await button.count()).toBe(0)
  })
})

test.describe('Bouton "Clean up" — appel API', () => {
  test('cliquer sur le bouton déclenche POST /api/pending-drafts/purge-all', async ({ page }) => {
    await setupBaseMocks(page)

    let purgeCallCount = 0

    await page.route(
      (url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts'),
      (route: Route) => {
        const method = route.request().method()

        if (method === 'POST' && route.request().url().includes('/purge-all')) {
          purgeCallCount++
          route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(PURGE_SUCCESS_RESPONSE),
          })
          return
        }

        // GET : retourner les brouillons au 1er appel, vide ensuite
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(purgeCallCount === 0 ? DRAFTS_RESPONSE : EMPTY_DRAFTS_RESPONSE),
        })
      }
    )

    await page.goto('/')
    await waitForAppReady(page)
    await navigateToDrafts(page)

    await expect(page.locator('.draft-item').first()).toBeVisible({ timeout: 10000 })

    const button = page.locator('.drafts-cleanup-btn')
    await expect(button).toBeVisible({ timeout: 10000 })
    await button.click()

    // Vérifier que l'API a bien été appelée
    await expect.poll(() => purgeCallCount, { timeout: 5000 }).toBe(1)
  })
})

test.describe('Bouton "Clean up" — comportement après purge', () => {
  test('la liste est vide après avoir cliqué sur "Clean up"', async ({ page }) => {
    await setupDraftMocksWithPurge(page)
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToDrafts(page)

    // Attendre le chargement initial des brouillons
    await expect(page.locator('.draft-item').first()).toBeVisible({ timeout: 10000 })

    const button = page.locator('.drafts-cleanup-btn')
    await expect(button).toBeVisible({ timeout: 10000 })
    await button.click()

    // Après la purge et le rechargement, l'état vide doit apparaître
    const emptyHeading = page.getByRole('heading', { name: /No drafts|Aucun brouillon/i })
    await expect(emptyHeading).toBeVisible({ timeout: 10000 })
  })

  test('aucun brouillon n\'est visible dans .draft-list-scroll après la purge', async ({ page }) => {
    await setupDraftMocksWithPurge(page)
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToDrafts(page)

    await expect(page.locator('.draft-item').first()).toBeVisible({ timeout: 10000 })

    await page.locator('.drafts-cleanup-btn').click()

    // Attendre la disparition des items de brouillon
    await expect(page.locator('.draft-item').first()).not.toBeVisible({ timeout: 10000 })
  })
})

test.describe('Bouton "Clean up" — gestion des erreurs API', () => {
  test('si purge-all retourne 500, la liste reste affichée sans crash', async ({ page }) => {
    await setupDraftMocksWithPurgeError(page)
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToDrafts(page)

    // Les brouillons doivent être visibles au départ
    await expect(page.locator('.draft-item').first()).toBeVisible({ timeout: 10000 })

    const button = page.locator('.drafts-cleanup-btn')
    await expect(button).toBeVisible({ timeout: 10000 })
    await button.click()

    // Le composant absorbe l'erreur silencieusement (catch vide dans handlePurgeAllDrafts).
    // Le conteneur principal doit toujours être présent — pas de crash/disparition.
    const container = page.locator('.draft-list-container')
    await expect(container).toBeVisible({ timeout: 5000 })
  })

  test('le bouton n\'est plus désactivé (isPurgingDrafts=false) après une erreur 500', async ({ page }) => {
    await setupDraftMocksWithPurgeError(page)
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToDrafts(page)

    await expect(page.locator('.draft-item').first()).toBeVisible({ timeout: 10000 })

    const button = page.locator('.drafts-cleanup-btn')
    await expect(button).toBeVisible({ timeout: 10000 })
    await button.click()

    // Après l'erreur, le bloc finally remet isPurgingDrafts=false → bouton ré-activé
    await expect(button).not.toBeDisabled({ timeout: 5000 })
  })
})
