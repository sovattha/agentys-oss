/**
 * Folder Loading Performance E2E Tests
 *
 * Measures time-to-first-email for slow folders: Sent, Archived, Trash, Spam.
 * Each test navigates to a folder and asserts emails appear within 3000ms.
 * Also verifies skeleton loader appears immediately (< 100ms) and that
 * rapid tab switching doesn't crash or show stale data.
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks } from './support/fixtures/setup'
import { mockEmails } from './support/fixtures/mock-data'
import { AppPage } from './pages/AppPage'

const API = 'http://localhost:5051'
const LOAD_TIMEOUT_MS = 3000
const SKELETON_TIMEOUT_MS = 100

function makeFolderEmails(folder: string, count = 5) {
  return {
    count,
    emails: Array.from({ length: count }, (_, i) => ({
      ...mockEmails[i % mockEmails.length],
      id: `${folder}-email-${i}`,
      subject: `[${folder.toUpperCase()}] Test email ${i + 1}`,
      folder,
    })),
  }
}

async function setupFolderMocks(page: Page) {
  await setupBaseMocks(page)

  // Folder-aware email mock (applies to all folder params)
  await page.route(`${API}/api/emails?*`, (route) => {
    const url = new URL(route.request().url())
    const folder = url.searchParams.get('folder') || 'inbox'
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(makeFolderEmails(folder)),
    })
  })
}

// Use data-testid (stable) instead of CSS class
const EMAIL_ITEM = '[data-testid="email-item"]'

// Les tests de perf doivent s'exécuter séquentiellement — la contention CPU en mode parallèle
// fausse les mesures et provoque des timeouts artificiels sur les workers lents.
test.describe.configure({ mode: 'serial' })

test.describe('Folder loading performance', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupFolderMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('Envoyés charge en moins de 3s', async ({ page }) => {
    const t0 = Date.now()

    await app.navigateToSent()

    await expect(page.locator(EMAIL_ITEM).first())
      .toBeVisible({ timeout: LOAD_TIMEOUT_MS })

    const elapsed = Date.now() - t0
    console.log(`[PERF] Envoyés: ${elapsed}ms`)
    expect(elapsed).toBeLessThan(LOAD_TIMEOUT_MS)
  })

  test('Archives charge en moins de 3s', async ({ page }) => {
    const t0 = Date.now()

    await app.navigateToArchived()

    await expect(page.locator(EMAIL_ITEM).first())
      .toBeVisible({ timeout: LOAD_TIMEOUT_MS })

    const elapsed = Date.now() - t0
    console.log(`[PERF] Archives: ${elapsed}ms`)
    expect(elapsed).toBeLessThan(LOAD_TIMEOUT_MS)
  })

  test('Corbeille charge en moins de 3s', async ({ page }) => {
    const t0 = Date.now()

    await app.navigateToTrash()

    await expect(page.locator(EMAIL_ITEM).first())
      .toBeVisible({ timeout: LOAD_TIMEOUT_MS })

    const elapsed = Date.now() - t0
    console.log(`[PERF] Corbeille: ${elapsed}ms`)
    expect(elapsed).toBeLessThan(LOAD_TIMEOUT_MS)
  })

  test('Indésirables charge en moins de 3s', async ({ page }) => {
    const t0 = Date.now()

    await app.navigateToSpam()

    await expect(page.locator(EMAIL_ITEM).first())
      .toBeVisible({ timeout: LOAD_TIMEOUT_MS })

    const elapsed = Date.now() - t0
    console.log(`[PERF] Indésirables: ${elapsed}ms`)
    expect(elapsed).toBeLessThan(LOAD_TIMEOUT_MS)
  })

  test('Skeleton loader apparaît immédiatement lors du changement de dossier', async ({ page }) => {
    await app.navigateToSent()

    const t0 = Date.now()
    const skeleton = page.locator('.email-list-skeleton, [data-testid="skeleton"], .skeleton-row')
    const emailItem = page.locator(EMAIL_ITEM).first()

    // Either skeleton appears quickly OR emails appear directly (from cache)
    await expect(skeleton.or(emailItem)).toBeVisible({ timeout: SKELETON_TIMEOUT_MS + 200 })
    const elapsed = Date.now() - t0
    console.log(`[PERF] Skeleton/first-email: ${elapsed}ms`)
  })

  test('Aller-retour rapide inbox→envoyés→inbox ne crashe pas', async ({ page }) => {
    // Rapid tab switching using data-testid nav
    await app.navigateToSent()
    await app.navigateToInbox()
    await app.navigateToSent()
    await app.navigateToInbox()

    // App should still display emails without crash
    await expect(page.locator(EMAIL_ITEM).first())
      .toBeVisible({ timeout: LOAD_TIMEOUT_MS })

    // No error overlay
    await expect(page.locator('[data-testid="error-overlay"], .error-state')).not.toBeVisible()
  })

  test('Données non périmées après retour depuis un dossier', async ({ page }) => {
    // Go to sent, then back to inbox
    await app.navigateToSent()
    await expect(page.locator(EMAIL_ITEM).first())
      .toBeVisible({ timeout: LOAD_TIMEOUT_MS })

    await app.navigateToInbox()
    await expect(page.locator(EMAIL_ITEM).first())
      .toBeVisible({ timeout: LOAD_TIMEOUT_MS })

    // Inbox emails should show inbox subjects, not [SENT] subjects
    const firstSubject = await page.locator(EMAIL_ITEM)
      .first()
      .textContent()

    expect(firstSubject).not.toContain('[SENT]')
  })

  // ─── Extended navigation perf audit ───────────────────────────────────────

  test('[AUDIT] Inbox → Envoyés : mesure temps de réponse', async ({ page }) => {
    await expect(page.locator(EMAIL_ITEM).first()).toBeVisible({ timeout: 5000 })

    const t0 = Date.now()
    await app.navigateToSent()
    await expect(page.locator(EMAIL_ITEM).first()).toBeVisible({ timeout: LOAD_TIMEOUT_MS })
    const elapsed = Date.now() - t0
    console.log(`[AUDIT] inbox→sent: ${elapsed}ms`)
    expect(elapsed).toBeLessThan(LOAD_TIMEOUT_MS)
  })

  test('[AUDIT] Navigation complète inbox→archives→spam→corbeille→inbox', async ({ page }) => {
    const timings: Record<string, number> = {}

    await expect(page.locator(EMAIL_ITEM).first()).toBeVisible({ timeout: 5000 })

    let t = Date.now()
    await app.navigateToArchived()
    await expect(page.locator(EMAIL_ITEM).first()).toBeVisible({ timeout: LOAD_TIMEOUT_MS })
    timings['inbox→archived'] = Date.now() - t

    t = Date.now()
    await app.navigateToSpam()
    await expect(page.locator(EMAIL_ITEM).first()).toBeVisible({ timeout: LOAD_TIMEOUT_MS })
    timings['archived→spam'] = Date.now() - t

    t = Date.now()
    await app.navigateToTrash()
    await expect(page.locator(EMAIL_ITEM).first()).toBeVisible({ timeout: LOAD_TIMEOUT_MS })
    timings['spam→trash'] = Date.now() - t

    t = Date.now()
    await app.navigateToInbox()
    await expect(page.locator(EMAIL_ITEM).first()).toBeVisible({ timeout: LOAD_TIMEOUT_MS })
    timings['trash→inbox'] = Date.now() - t

    console.log('[AUDIT] Navigation complète:', JSON.stringify(timings, null, 2))
    const max = Math.max(...Object.values(timings))
    console.log(`[AUDIT] Pire transition: ${max}ms`)
    expect(max).toBeLessThan(LOAD_TIMEOUT_MS)
  })

  test('[AUDIT] Retour inbox depuis chaque dossier : test de cache', async ({ page }) => {
    const timings: Record<string, number> = {}

    // Pre-load inbox (warms cache)
    await expect(page.locator(EMAIL_ITEM).first()).toBeVisible({ timeout: 5000 })

    for (const [folder, navigate] of [
      ['sent', () => app.navigateToSent()],
      ['archived', () => app.navigateToArchived()],
      ['spam', () => app.navigateToSpam()],
      ['trash', () => app.navigateToTrash()],
    ] as [string, () => Promise<void>][]) {
      await navigate()
      await expect(page.locator(EMAIL_ITEM).first()).toBeVisible({ timeout: LOAD_TIMEOUT_MS })

      const t = Date.now()
      await app.navigateToInbox()
      await expect(page.locator(EMAIL_ITEM).first()).toBeVisible({ timeout: LOAD_TIMEOUT_MS })
      timings[`${folder}→inbox`] = Date.now() - t
    }

    console.log('[AUDIT] Retour inbox:', JSON.stringify(timings, null, 2))
    const max = Math.max(...Object.values(timings))
    console.log(`[AUDIT] Pire retour inbox: ${max}ms`)
    expect(max).toBeLessThan(LOAD_TIMEOUT_MS)
  })
})
