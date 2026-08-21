/**
 * Auto-Cleanup Toggles — E2E Tests
 *
 * Vérifie que les bannières d'auto-suppression affichent le bon message
 * selon l'état des toggles (ON/OFF) dans les paramètres, pour les 4 dossiers :
 *   - Indésirables (spam)
 *   - Corbeille (trash)
 *   - Bruit (noise)
 *   - Brouillons (drafts)
 *
 * Quand le toggle est ON  → bannière affiche "automatiquement supprimés après X jours"
 * Quand le toggle est OFF → bannière affiche "paramètres" (suggestion d'activer)
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks } from './support/fixtures/setup'
import { AppPage } from './pages/AppPage'

const API = 'http://127.0.0.1:5050'

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

// Base email fields required by the component.
// conversation_id MUST be truthy (thread collapsing skips null/undefined).
// labels array is needed for client-side label filtering.
const baseEmail = {
  has_attachments: false,
  is_read: true,
  body_preview: 'Lorem ipsum...',
}

const mockSpamEmails = {
  count: 2,
  emails: [
    {
      ...baseEmail,
      id: 'spam-1',
      conversation_id: 'conv-spam-1',
      sender: 'promo@spam.com',
      sender_name: 'Spam Promo',
      subject: 'Offre exclusive',
      received_at: '2026-03-20T10:00:00Z',
      folder: 'spam',
    },
    {
      ...baseEmail,
      id: 'spam-2',
      conversation_id: 'conv-spam-2',
      sender: 'deals@fake.net',
      sender_name: 'Deals',
      subject: 'Vous avez gagné',
      received_at: '2026-03-19T10:00:00Z',
      is_read: false,
      folder: 'spam',
    },
  ],
  has_more: false,
  offset: 0,
  filter: 'all',
  source: 'cache',
}

const mockTrashEmails = {
  count: 2,
  emails: [
    {
      ...baseEmail,
      id: 'trash-1',
      conversation_id: 'conv-trash-1',
      sender: 'old@mail.com',
      sender_name: 'Old Mail',
      subject: 'Ancien message',
      received_at: '2026-03-10T10:00:00Z',
      folder: 'trash',
    },
    {
      ...baseEmail,
      id: 'trash-2',
      conversation_id: 'conv-trash-2',
      sender: 'expired@promo.com',
      sender_name: 'Expired',
      subject: 'Promo expirée',
      received_at: '2026-03-08T10:00:00Z',
      folder: 'trash',
    },
  ],
  has_more: false,
  offset: 0,
  filter: 'all',
  source: 'cache',
}

const mockNoiseEmails = {
  count: 2,
  emails: [
    {
      ...baseEmail,
      id: 'noise-1',
      conversation_id: 'conv-noise-1',
      sender: 'newsletter@marketing.com',
      sender_name: 'Newsletter',
      subject: 'Nouvelles du mois',
      received_at: '2026-03-20T10:00:00Z',
      labels: [{ name: 'Noise' }],
    },
    {
      ...baseEmail,
      id: 'noise-2',
      conversation_id: 'conv-noise-2',
      sender: 'notif@app.io',
      sender_name: 'Notifications',
      subject: 'Rapport hebdomadaire',
      received_at: '2026-03-19T10:00:00Z',
      labels: [{ name: 'Noise' }],
    },
  ],
  has_more: false,
  offset: 0,
  filter: 'all',
  source: 'cache',
}

const mockDrafts = {
  drafts: [
    {
      id: 'draft-1',
      email_id: 'email-1',
      email_sender: 'marie@example.com',
      email_sender_name: 'Marie',
      email_subject: 'Rapport Q4',
      draft_body: 'Bonjour Marie...',
      status: 'pending',
      created_at: '2026-03-20T10:00:00Z',
      updated_at: '2026-03-20T10:00:00Z',
    },
  ],
  pending_count: 1,
}

const emptyResponse = {
  count: 0,
  emails: [],
  has_more: false,
  offset: 0,
  filter: 'all',
  source: 'cache',
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface ToggleSettings {
  auto_empty_spam_30d: boolean
  auto_empty_trash_30d: boolean
  auto_delete_noise_30d: boolean
}

const ALL_ON: ToggleSettings = {
  auto_empty_spam_30d: true,
  auto_empty_trash_30d: true,
  auto_delete_noise_30d: true,
}

const ALL_OFF: ToggleSettings = {
  auto_empty_spam_30d: false,
  auto_empty_trash_30d: false,
  auto_delete_noise_30d: false,
}

/**
 * Setup all mocks with configurable toggle settings.
 * Sets localStorage + /api/settings + folder-specific email routes.
 */
async function setupMocks(page: Page, settings: ToggleSettings) {
  // Set localStorage BEFORE page load
  await page.addInitScript(
    (s: ToggleSettings) => {
      localStorage.setItem('agentys_auto_empty_spam_30d_0', String(s.auto_empty_spam_30d))
      localStorage.setItem('agentys_auto_empty_trash_30d_0', String(s.auto_empty_trash_30d))
      localStorage.setItem('agentys_auto_delete_noise_30d_0', String(s.auto_delete_noise_30d))
    },
    settings
  )

  await setupBaseMocks(page)

  // Mock /api/settings
  await page.route(
    (url) => (url.origin === API || url.origin === 'http://localhost:5050') && url.pathname === '/api/settings',
    (route) => {
      if (route.request().method() === 'PATCH') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(settings),
        })
      }
    }
  )

  // Mock /api/pending-drafts
  await page.route(
    (url) => (url.origin === API || url.origin === 'http://localhost:5050') && url.pathname.startsWith('/api/pending-drafts'),
    (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDrafts) })
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, deleted_count: 1 }) })
      }
    }
  )

  // Mock cleanup endpoints (registered BEFORE emails route so emails route wins via LIFO)
  await page.route(`${API}/api/emails/empty-spam`, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, deleted_count: 2 }) })
  })
  await page.route(`${API}/api/emails/empty-trash`, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, deleted_count: 2 }) })
  })
  await page.route(`${API}/api/emails/clean-noise`, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, archived_count: 2, deleted_count: 0 }) })
  })

  // Mock /api/emails — registered LAST for highest LIFO priority.
  // Uses function matcher to avoid glob ambiguity with /api/emails/* cleanup routes.
  await page.route(
    (url) => (url.origin === API || url.origin === 'http://localhost:5050') && url.pathname === '/api/emails' && url.search.length > 0,
    (route) => {
      const url = new URL(route.request().url())
      const folder = url.searchParams.get('folder') || 'inbox'
      const label = url.searchParams.get('label')

      if (folder === 'spam') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSpamEmails) })
      } else if (folder === 'trash') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockTrashEmails) })
      } else if (folder === 'inbox' && label === 'Noise') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockNoiseEmails) })
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(emptyResponse) })
      }
    }
  )
}

async function navigateToNoiseLabel(page: Page) {
  await page.getByTestId('nav-inbox').click()
  const noiseTab = page.locator('.header-tab').filter({ hasText: /^(Bruit|Noise)$/ }).first()
  await noiseTab.waitFor({ state: 'visible', timeout: 10000 })
  await noiseTab.click()
  await page.locator('.noise-banner').waitFor({ state: 'visible', timeout: 10000 })
}

// ===========================================================================
// TESTS — Toggles ON : bannière affiche le message "auto-suppression active"
// ===========================================================================

test.describe('Auto-cleanup ON — bannières affichent le message actif', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupMocks(page, ALL_ON)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('spam : bannière affiche "automatiquement supprimés après 30 jours"', async ({ page }) => {
    await app.navigateToSpam()
    const banner = page.locator('.spam-banner')
    await expect(banner).toBeVisible({ timeout: 10000 })
    await expect(banner).toContainText(/30 jours|30 days/, { timeout: 5000 })
    await expect(banner).not.toContainText(/paramètres|settings/i)
  })

  test('corbeille : bannière affiche "automatiquement supprimés après 30 jours"', async ({ page }) => {
    await app.navigateToTrash()
    const banner = page.locator('.trash-banner')
    await expect(banner).toBeVisible({ timeout: 10000 })
    await expect(banner).toContainText(/30 jours|30 days/, { timeout: 5000 })
    await expect(banner).not.toContainText(/paramètres|settings/i)
  })

  test('bruit : bannière affiche "corbeille après 30 jours"', async ({ page }) => {
    await navigateToNoiseLabel(page)
    const banner = page.locator('.noise-banner')
    await expect(banner).toBeVisible({ timeout: 10000 })
    await expect(banner).toContainText(/30 jours|30 days/, { timeout: 5000 })
    await expect(banner).not.toContainText(/paramètres|settings/i)
  })

  test('brouillons : bannière affiche "supprimés après 7 jours"', async ({ page }) => {
    await app.navigateToDrafts()
    const banner = page.locator('.drafts-banner')
    await expect(banner).toBeVisible({ timeout: 10000 })
    await expect(banner).toContainText(/7 jours|7 days/, { timeout: 5000 })
    await expect(banner).not.toContainText(/paramètres|settings/i)
  })
})

// ===========================================================================
// TESTS — Toggles OFF : bannière affiche le message "paramètres"
// ===========================================================================

test.describe('Auto-cleanup OFF — bannières affichent la suggestion paramètres', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupMocks(page, ALL_OFF)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('spam : bannière affiche "paramètres" au lieu de "30 jours"', async ({ page }) => {
    await app.navigateToSpam()
    const banner = page.locator('.spam-banner')
    await expect(banner).toBeVisible({ timeout: 10000 })
    await expect(banner).toContainText(/paramètres|settings/i, { timeout: 5000 })
    await expect(banner).not.toContainText(/automatiquement|automatically/i)
  })

  test('corbeille : bannière affiche "paramètres" au lieu de "30 jours"', async ({ page }) => {
    await app.navigateToTrash()
    const banner = page.locator('.trash-banner')
    await expect(banner).toBeVisible({ timeout: 10000 })
    await expect(banner).toContainText(/paramètres|settings/i, { timeout: 5000 })
    await expect(banner).not.toContainText(/automatiquement|automatically/i)
  })

  test('bruit : bannière affiche "paramètres" au lieu de "30 jours"', async ({ page }) => {
    await navigateToNoiseLabel(page)
    const banner = page.locator('.noise-banner')
    await expect(banner).toBeVisible({ timeout: 10000 })
    await expect(banner).toContainText(/paramètres|settings/i, { timeout: 5000 })
    await expect(banner).not.toContainText(/30 jours|30 days/)
  })

  test('brouillons : bannière affiche "paramètres" au lieu de "7 jours"', async ({ page }) => {
    await app.navigateToDrafts()
    const banner = page.locator('.drafts-banner')
    await expect(banner).toBeVisible({ timeout: 10000 })
    await expect(banner).toContainText(/paramètres|settings/i, { timeout: 5000 })
    await expect(banner).not.toContainText(/7 jours|7 days/)
  })
})

// ===========================================================================
// TESTS — Bouton nettoyage manuel fonctionne quel que soit le toggle
// ===========================================================================

test.describe('Nettoyage manuel — fonctionne même quand toggle est OFF', () => {
  test('spam OFF : le bouton nettoyer est présent et appelle l\'API', async ({ page }) => {
    await setupMocks(page, ALL_OFF)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToSpam()

    let apiCalled = false
    await page.route(`${API}/api/emails/empty-spam`, (route) => {
      apiCalled = true
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, deleted_count: 2 }) })
    })

    const btn = page.locator('.spam-empty-btn')
    await expect(btn).toBeVisible({ timeout: 10000 })
    await expect(btn).toBeEnabled()
    await btn.click()

    // Spam uses confirmation dialog
    const confirmBtn = page.locator('[data-testid="confirm-btn"]')
    if (await confirmBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await confirmBtn.click()
    }

    await expect.poll(() => apiCalled, { timeout: 5000 }).toBe(true)
  })

  test('corbeille OFF : le bouton nettoyer est présent et appelle l\'API', async ({ page }) => {
    await setupMocks(page, ALL_OFF)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToTrash()

    let apiCalled = false
    await page.route(`${API}/api/emails/empty-trash`, (route) => {
      apiCalled = true
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, deleted_count: 2 }) })
    })

    const btn = page.locator('.trash-empty-btn')
    await expect(btn).toBeVisible({ timeout: 10000 })
    await expect(btn).toBeEnabled()
    await btn.click()

    // Trash uses confirmation dialog
    const confirmBtn = page.locator('[data-testid="confirm-btn"]')
    if (await confirmBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await confirmBtn.click()
    }

    await expect.poll(() => apiCalled, { timeout: 5000 }).toBe(true)
  })

  test('bruit OFF : le bouton nettoyer est présent et appelle l\'API', async ({ page }) => {
    await setupMocks(page, ALL_OFF)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await navigateToNoiseLabel(page)

    let apiCalled = false
    await page.route(`${API}/api/emails/clean-noise`, (route) => {
      apiCalled = true
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, archived_count: 2, deleted_count: 0 }) })
    })

    // Wait for noise emails to load
    await expect(page.locator('[data-testid="email-item"]').first()).toBeVisible({ timeout: 10000 })

    const btn = page.locator('.noise-clean-btn')
    await expect(btn).toBeEnabled({ timeout: 5000 })
    await btn.click()

    await expect.poll(() => apiCalled, { timeout: 5000 }).toBe(true)
  })

  test('brouillons OFF : le bouton nettoyer est présent et appelle l\'API', async ({ page }) => {
    await setupMocks(page, ALL_OFF)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToDrafts()

    let apiCalled = false
    await page.route(
      (url) => (url.origin === API || url.origin === 'http://localhost:5050') && url.pathname.includes('/purge-all'),
      (route) => {
        apiCalled = true
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, deleted_count: 1 }) })
      }
    )

    const btn = page.locator('.drafts-cleanup-btn')
    await expect(btn).toBeVisible({ timeout: 10000 })
    await expect(btn).toBeEnabled()
    await btn.click()

    await expect.poll(() => apiCalled, { timeout: 5000 }).toBe(true)
  })
})

// ===========================================================================
// TESTS — Toggles ON : nettoyage manuel fonctionne aussi
// ===========================================================================

test.describe('Nettoyage manuel — fonctionne quand toggle est ON', () => {
  test('spam ON : le bouton appelle l\'API normalement', async ({ page }) => {
    await setupMocks(page, ALL_ON)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToSpam()

    let apiCalled = false
    await page.route(`${API}/api/emails/empty-spam`, (route) => {
      apiCalled = true
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, deleted_count: 2 }) })
    })

    const btn = page.locator('.spam-empty-btn')
    await expect(btn).toBeVisible({ timeout: 10000 })
    await btn.click()

    const confirmBtn = page.locator('[data-testid="confirm-btn"]')
    if (await confirmBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await confirmBtn.click()
    }

    await expect.poll(() => apiCalled, { timeout: 5000 }).toBe(true)
  })

  test('corbeille ON : le bouton appelle l\'API normalement', async ({ page }) => {
    await setupMocks(page, ALL_ON)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToTrash()

    let apiCalled = false
    await page.route(`${API}/api/emails/empty-trash`, (route) => {
      apiCalled = true
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, deleted_count: 2 }) })
    })

    const btn = page.locator('.trash-empty-btn')
    await expect(btn).toBeVisible({ timeout: 10000 })
    await btn.click()

    const confirmBtn = page.locator('[data-testid="confirm-btn"]')
    if (await confirmBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await confirmBtn.click()
    }

    await expect.poll(() => apiCalled, { timeout: 5000 }).toBe(true)
  })

  test('bruit ON : le bouton appelle l\'API normalement', async ({ page }) => {
    await setupMocks(page, ALL_ON)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await navigateToNoiseLabel(page)

    let apiCalled = false
    await page.route(`${API}/api/emails/clean-noise`, (route) => {
      apiCalled = true
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, archived_count: 2, deleted_count: 0 }) })
    })

    // Wait for noise emails to load
    await expect(page.locator('[data-testid="email-item"]').first()).toBeVisible({ timeout: 10000 })

    const btn = page.locator('.noise-clean-btn')
    await expect(btn).toBeEnabled({ timeout: 5000 })
    await btn.click()

    await expect.poll(() => apiCalled, { timeout: 5000 }).toBe(true)
  })

  test('brouillons ON : le bouton appelle l\'API normalement', async ({ page }) => {
    await setupMocks(page, ALL_ON)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToDrafts()

    let apiCalled = false
    await page.route(
      (url) => (url.origin === API || url.origin === 'http://localhost:5050') && url.pathname.includes('/purge-all'),
      (route) => {
        apiCalled = true
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, deleted_count: 1 }) })
      }
    )

    const btn = page.locator('.drafts-cleanup-btn')
    await expect(btn).toBeVisible({ timeout: 10000 })
    await btn.click()

    await expect.poll(() => apiCalled, { timeout: 5000 }).toBe(true)
  })
})
