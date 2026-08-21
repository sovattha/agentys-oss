/**
 * Performance Audit E2E — Chargement des 7 scénarios clés
 *
 * Mesure les temps de chargement pour :
 * 1. Inbox (liste)
 * 2. Envoyés (liste)
 * 3. Indésirables / Spam (liste)
 * 4. Supprimé / Trash (liste)
 * 5. Archivés (liste)
 * 6. Ouvrir un email depuis Envoyés (cold → warm cache)
 * 7. Nouveau message depuis l'inbox (ouverture modale Compose)
 *
 * Tous les tests utilisent des mocks — aucun backend réel requis.
 * Tests en mode serial pour des mesures de perf fiables.
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks } from './support/fixtures/setup'
import { mockEmails, mockEmailDetails } from './support/fixtures/mock-data'
import { AppPage } from './pages/AppPage'

const API = 'http://127.0.0.1:5050'

// Seuils de performance
const FOLDER_LOAD_MS  = 3000  // liste dossier < 3 s
const EMAIL_DETAIL_MS = 3000  // ouverture email envoyé cold < 3 s
const WARM_DETAIL_MS  = 2000  // ouverture email envoyé warm < 2 s
const COMPOSE_OPEN_MS = 2000  // modale Nouveau message < 2 s

// Sélecteurs stables
const EMAIL_ITEM    = '[data-testid="email-item"]'
const EMAIL_DETAIL  = '[data-testid="email-detail"], .email-detail-modal, .email-detail-panel'
const COMPOSE_MODAL = '[data-testid="compose-modal"], .new-message-modal, .compose-modal'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function makeFolderEmails(folder: string, count = 8) {
  return {
    count,
    emails: Array.from({ length: count }, (_, i) => ({
      ...mockEmails[i % mockEmails.length],
      id: folder === 'sent' ? `sent:sent-email-${i}` : `${folder}-email-${i}`,
      subject: `[${folder.toUpperCase()}] Email de test ${i + 1}`,
      folder,
    })),
    has_more: false,
    source: 'mock',
  }
}

function logPerf(label: string, ms: number, threshold: number) {
  const status = ms < threshold ? '[OK]' : '⚠ SLOW'
  console.log(`[PERF] ${label}: ${ms}ms ${status}`)
}

async function setupAuditMocks(page: Page) {
  await setupBaseMocks(page)

  // Route folder-aware — prioritaire sur le mock générique de setupBaseMocks (LIFO)
  await page.route(`${API}/api/emails?*`, (route) => {
    const url = new URL(route.request().url())
    const folder = url.searchParams.get('folder') || 'inbox'
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(makeFolderEmails(folder)),
    })
  })

  // Détail de l'email envoyé (cold + warm)
  await page.route(
    (url) => url.origin === API && url.pathname === '/api/emails/sent:sent-email-0',
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockEmailDetails['email-1']),
      })
    }
  )

  // Routes auxiliaires pour le détail
  await page.route(
    (url) => url.origin === API && url.pathname.startsWith('/api/emails/sent:') && url.pathname.endsWith('/read'),
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  )
  await page.route(
    (url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts/by-email/sent:'),
    (route) => route.fulfill({ status: 404, contentType: 'application/json', body: '{"error": "not found"}' })
  )
  await page.route(`${API}/api/contacts`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  )
}

// ─── Mode serial — évite la contention CPU qui fausse les mesures ─────────────
test.describe.configure({ mode: 'serial' })

// ═══════════════════════════════════════════════════════════════════════════════
// BLOC 1 — Chargement des dossiers (scénarios 1–5)
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('[AUDIT PERF] Chargement des dossiers', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupAuditMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('[1] Inbox charge en moins de 3s', async ({ page }) => {
    // L'inbox est déjà chargée au waitForReady — on mesure depuis la navigation explicite
    await app.navigateToSent() // quitter d'abord
    await expect(page.locator(EMAIL_ITEM).first()).toBeVisible({ timeout: FOLDER_LOAD_MS })

    const t0 = Date.now()
    await app.navigateToInbox()
    await expect(page.locator(EMAIL_ITEM).first()).toBeVisible({ timeout: FOLDER_LOAD_MS })
    const elapsed = Date.now() - t0

    logPerf('Inbox', elapsed, FOLDER_LOAD_MS)
    expect(elapsed).toBeLessThan(FOLDER_LOAD_MS)
  })

  test('[2] Envoyés charge en moins de 3s', async ({ page }) => {
    const t0 = Date.now()
    await app.navigateToSent()
    await expect(page.locator(EMAIL_ITEM).first()).toBeVisible({ timeout: FOLDER_LOAD_MS })
    const elapsed = Date.now() - t0

    logPerf('Envoyés', elapsed, FOLDER_LOAD_MS)
    expect(elapsed).toBeLessThan(FOLDER_LOAD_MS)
  })

  test('[3] Indésirables charge en moins de 3s', async ({ page }) => {
    const t0 = Date.now()
    await app.navigateToSpam()
    await expect(page.locator(EMAIL_ITEM).first()).toBeVisible({ timeout: FOLDER_LOAD_MS })
    const elapsed = Date.now() - t0

    logPerf('Indésirables', elapsed, FOLDER_LOAD_MS)
    expect(elapsed).toBeLessThan(FOLDER_LOAD_MS)
  })

  test('[4] Supprimé charge en moins de 3s', async ({ page }) => {
    const t0 = Date.now()
    await app.navigateToTrash()
    await expect(page.locator(EMAIL_ITEM).first()).toBeVisible({ timeout: FOLDER_LOAD_MS })
    const elapsed = Date.now() - t0

    logPerf('Supprimé', elapsed, FOLDER_LOAD_MS)
    expect(elapsed).toBeLessThan(FOLDER_LOAD_MS)
  })

  test('[5] Archivés charge en moins de 3s', async ({ page }) => {
    const t0 = Date.now()
    await app.navigateToArchived()
    await expect(page.locator(EMAIL_ITEM).first()).toBeVisible({ timeout: FOLDER_LOAD_MS })
    const elapsed = Date.now() - t0

    logPerf('Archivés', elapsed, FOLDER_LOAD_MS)
    expect(elapsed).toBeLessThan(FOLDER_LOAD_MS)
  })
})

// ═══════════════════════════════════════════════════════════════════════════════
// BLOC 2 — Ouverture email envoyé (scénarios 6a/6b : cold + warm cache)
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('[AUDIT PERF] Email envoyé — cold et warm cache', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupAuditMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    // Naviguer vers Envoyés et attendre la liste
    await app.navigateToSent()
    await expect(page.locator(EMAIL_ITEM).first()).toBeVisible({ timeout: FOLDER_LOAD_MS })
  })

  test('[6a] Ouverture email envoyé (cold) en moins de 3s', async ({ page }) => {
    const t0 = Date.now()
    await page.locator(EMAIL_ITEM).first().click()
    await expect(page.locator(EMAIL_DETAIL)).toBeVisible({ timeout: EMAIL_DETAIL_MS })
    const elapsed = Date.now() - t0

    logPerf('Email envoyé (cold)', elapsed, EMAIL_DETAIL_MS)
    expect(elapsed).toBeLessThan(EMAIL_DETAIL_MS)
  })

  test('[6b] Ouverture email envoyé (warm cache) en moins de 2s', async ({ page }) => {
    // Cold open — pré-chauffe le cache
    await page.locator(EMAIL_ITEM).first().click()
    await expect(page.locator(EMAIL_DETAIL)).toBeVisible({ timeout: EMAIL_DETAIL_MS })

    // Fermer le panneau de détail
    const closeBtn = page.locator(
      '[data-testid="close-email-detail"], [data-testid="email-detail-close"], .close-btn, button[aria-label="Fermer"]'
    ).first()
    await expect(closeBtn).toBeVisible({ timeout: 5000 })
    await closeBtn.click()
    await expect(page.locator(EMAIL_DETAIL)).not.toBeVisible({ timeout: 2000 })

    // Warm open — mesure
    const t0 = Date.now()
    await page.locator(EMAIL_ITEM).first().click()
    await expect(page.locator(EMAIL_DETAIL)).toBeVisible({ timeout: WARM_DETAIL_MS })
    const elapsed = Date.now() - t0

    logPerf('Email envoyé (warm)', elapsed, WARM_DETAIL_MS)
    expect(elapsed).toBeLessThan(WARM_DETAIL_MS)
  })
})

// ═══════════════════════════════════════════════════════════════════════════════
// BLOC 3 — Nouveau message (scénario 7)
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('[AUDIT PERF] Nouveau message', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupAuditMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('[7] Modale Nouveau message s\'ouvre en moins de 2s', async ({ page }) => {
    const t0 = Date.now()
    await app.openCompose()
    await expect(page.locator(COMPOSE_MODAL)).toBeVisible({ timeout: COMPOSE_OPEN_MS })
    const elapsed = Date.now() - t0

    logPerf('Nouveau message', elapsed, COMPOSE_OPEN_MS)
    expect(elapsed).toBeLessThan(COMPOSE_OPEN_MS)
  })
})
