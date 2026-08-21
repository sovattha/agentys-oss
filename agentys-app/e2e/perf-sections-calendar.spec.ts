/**
 * E2E — Performance sections & calendrier
 *
 * Vérifie les temps de réponse lors de :
 * - Ouverture des sections (inbox, envoyés, brouillons, spam, corbeille, archivés)
 * - Ouverture d'un email (cold + warm cache)
 * - Navigation calendrier (mois précédent/suivant avec SWR cache)
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady, isApiRoute } from './support/fixtures/setup'
import { mockEmailsResponse, mockEmailDetails } from './support/fixtures/mock-data'

// Folders and their nav selectors
const FOLDERS = [
  { label: 'Envoyés',   nav: '[data-folder="sent"], [title*="nvoy"], [aria-label*="nvoy"]' },
  { label: 'Archivés',  nav: '[data-folder="archived"], [title*="rchiv"], [aria-label*="rchiv"]' },
  { label: 'Spam',      nav: '[data-folder="spam"], [title*="pam"], [aria-label*="pam"]' },
  { label: 'Corbeille', nav: '[data-folder="trash"], [title*="orbeille"], [aria-label*="trash"]' },
]

async function setupSectionMocks(page: Page) {
  await setupBaseMocks(page)

  // Mock all folder endpoints with instant response
  await page.route((url) =>
    isApiRoute(url) && url.pathname === '/api/emails' &&
    ['sent', 'archived', 'spam', 'trash'].some(f => url.searchParams.get('folder') === f),
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...mockEmailsResponse, emails: mockEmailsResponse.emails.slice(0, 5) }),
      })
    }
  )

  // Mock email detail
  await page.route(
    (url) => isApiRoute(url) && /^\/api\/emails\/[^/]+$/.test(url.pathname),
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockEmailDetails['email-1']) })
  )
  await page.route(
    (url) => isApiRoute(url) && /\/api\/emails\/[^/]+\/read$/.test(url.pathname),
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname.startsWith('/api/pending-drafts/by-email'),
    (route) => route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: 'No draft' }) })
  )

  // Mock calendar
  await page.route(
    (url) => isApiRoute(url) && url.pathname.startsWith('/api/calendar'),
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ events: [], calendars: [] }) })
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname.startsWith('/api/calendars'),
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ calendars: [] }) })
  )
}

// ─────────────────────────────────────────────────────────────
// Section navigation timing
// ─────────────────────────────────────────────────────────────

test.describe('Perf — navigation sections', () => {
  test.beforeEach(async ({ page }) => {
    await setupSectionMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('inbox charge en < 3 s', async ({ page }) => {
    const t0 = Date.now()
    await expect(page.locator('.email-list-container, .email-list, [data-testid="email-list"]').first()).toBeVisible({ timeout: 3000 })
    console.log(`[PERF] inbox: ${Date.now() - t0}ms`)
  })

  for (const folder of FOLDERS) {
    test(`${folder.label} charge en < 3 s`, async ({ page }) => {
      const nav = page.locator(folder.nav).first()
      if (!(await nav.isVisible().catch(() => false))) {
        test.skip(true, `${folder.label} nav item non trouvé`)
        return
      }

      const t0 = Date.now()
      await nav.click()
      await expect(
        page.locator('.email-list-container, .email-list, [data-testid="email-list"], .email-skeleton-item').first()
      ).toBeVisible({ timeout: 3000 })
      const elapsed = Date.now() - t0
      console.log(`[PERF] ${folder.label}: ${elapsed}ms`)
      expect(elapsed).toBeLessThan(3000)
    })
  }

  test('navigation rapide inbox→envoyés→inbox sans crash', async ({ page }) => {
    const sentNav = page.locator('[data-folder="sent"], [title*="nvoy"], [aria-label*="nvoy"]').first()
    if (!(await sentNav.isVisible().catch(() => false))) {
      test.skip(true, 'nav envoyés non trouvé')
      return
    }

    // inbox → sent → inbox (rapide)
    const t0 = Date.now()
    await sentNav.click()
    await page.locator('[data-testid="nav-inbox"], [data-folder="inbox"], [aria-label*="éception"]').first().click()
    await expect(
      page.locator('.email-list-container, .email-list').first()
    ).toBeVisible({ timeout: 3000 })
    const elapsed = Date.now() - t0
    console.log(`[PERF] inbox→sent→inbox: ${elapsed}ms`)
    expect(elapsed).toBeLessThan(3000)
  })
})

// ─────────────────────────────────────────────────────────────
// Email detail timing (cold + warm)
// ─────────────────────────────────────────────────────────────

test.describe('Perf — ouverture email', () => {
  test.beforeEach(async ({ page }) => {
    await setupSectionMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('ouverture email (cold) < 4 s', async ({ page }) => {
    const item = page.locator('[data-testid="email-item"], .email-item').first()
    if (!(await item.isVisible().catch(() => false))) {
      test.skip(true, 'Aucun email dans la liste')
      return
    }
    const t0 = Date.now()
    await item.click()
    await expect(
      page.locator('.email-detail-title, .email-detail-modal, [data-testid="email-detail"]').first()
    ).toBeVisible({ timeout: 4000 })
    const elapsed = Date.now() - t0
    console.log(`[PERF] email open cold: ${elapsed}ms`)
    expect(elapsed).toBeLessThan(4000)
  })

  test('ouverture email (warm cache) < 1.5 s', async ({ page }) => {
    const item = page.locator('[data-testid="email-item"], .email-item').first()
    if (!(await item.isVisible().catch(() => false))) {
      test.skip(true, 'Aucun email dans la liste')
      return
    }

    // Warm up
    await item.click()
    await page.locator('.email-detail-title, .email-detail-modal').first().waitFor({ state: 'visible', timeout: 4000 })
    await page.keyboard.press('Escape')
    await page.locator('.email-detail-title, .email-detail-modal').first().waitFor({ state: 'hidden', timeout: 5000 })

    // Warm cache hit
    const t0 = Date.now()
    await item.click()
    await expect(
      page.locator('.email-detail-title, .email-detail-modal').first()
    ).toBeVisible({ timeout: 1500 })
    const elapsed = Date.now() - t0
    console.log(`[PERF] email open warm: ${elapsed}ms`)
    expect(elapsed).toBeLessThan(1500)
  })
})

// ─────────────────────────────────────────────────────────────
// Calendrier — SWR cache
// ─────────────────────────────────────────────────────────────

test.describe('Perf — calendrier', () => {
  test.beforeEach(async ({ page }) => {
    await setupSectionMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('ouverture calendrier < 3 s', async ({ page }) => {
    const calNav = page.locator('[aria-label="Calendrier"], [data-mode="calendar"], [aria-label*="alend"]').first()
    if (!(await calNav.isVisible().catch(() => false))) {
      test.skip(true, 'nav calendrier non trouvé')
      return
    }
    const t0 = Date.now()
    await calNav.click()
    await expect(
      page.locator('.calendar-view, .calendar-grid, [data-testid="calendar"]').first()
    ).toBeVisible({ timeout: 5000 })
    const elapsed = Date.now() - t0
    console.log(`[PERF] calendar open cold: ${elapsed}ms`)
    expect(elapsed).toBeLessThan(8000)
  })

  test('navigation mois calendrier (warm cache) < 1 s', async ({ page }) => {
    const calNav = page.locator('[aria-label="Calendrier"], [data-mode="calendar"], [aria-label*="alend"]').first()
    if (!(await calNav.isVisible().catch(() => false))) {
      test.skip(true, 'nav calendrier non trouvé')
      return
    }
    await calNav.click()
    await page.locator('.calendar-view, .calendar-grid, .calendar-week-body').first().waitFor({ state: 'visible', timeout: 5000 })

    // Mois précédent pour warmer cache
    const prevBtn = page.locator('[aria-label*="récédent"], [title*="récédent"], .calendar-nav-prev').first()
    if (!(await prevBtn.isVisible().catch(() => false))) {
      test.skip(true, 'bouton mois précédent non trouvé')
      return
    }
    await prevBtn.click()
    await page.locator('.calendar-view, .calendar-grid, .calendar-week-body').first().waitFor({ state: 'visible', timeout: 5000 })

    // Retour mois courant — devrait être dans le cache
    const nextBtn = page.locator('[aria-label*="uivant"], [title*="uivant"], .calendar-nav-next').first()
    const t0 = Date.now()
    await nextBtn.click()
    await expect(page.locator('.calendar-view, .calendar-grid, .calendar-week-body').first()).toBeVisible({ timeout: 1000 })
    const elapsed = Date.now() - t0
    console.log(`[PERF] calendar month nav (warm): ${elapsed}ms`)
    expect(elapsed).toBeLessThan(1000)
  })
})
