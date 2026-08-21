/**
 * Search / SmartSearchBar E2E Tests
 */

import { test, expect, Page } from '@playwright/test'
import { mockEmails } from './support/fixtures/mock-data'
import { isApiRoute, setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

async function setupSearchMocks(page: Page) {
  await setupBaseMocks(page)
  await page.route((url) => url.origin === API && url.pathname === '/api/contacts/autocomplete', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  })
  await page.route((url) => url.origin === API && url.pathname === '/api/emails/search', (route) => {
    const url2 = new URL(route.request().url())
    const q = url2.searchParams.get('q') || ''
    const results = mockEmails.filter(e => e.subject.toLowerCase().includes(q.toLowerCase())).slice(0, 3)
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: results.length, emails: results, has_more: false }) })
  })
}

async function openSearch(page: Page) {
  // Click search icon/bar to open
  const searchBar = page.locator('.smart-search-bar, [data-testid="smart-search-bar"]').first()
  if (await searchBar.isVisible()) {
    await searchBar.click()
    return
  }
  // Fallback: press / shortcut
  await page.locator('body').click({ position: { x: 10, y: 10 } })
  await page.keyboard.press('/')
}

test.describe('Search — ouverture et saisie', () => {
  test.beforeEach(async ({ page }) => { await setupSearchMocks(page); await page.goto('/'); await waitForAppReady(page) })

  test('affiche la barre de recherche', async ({ page }) => {
    await openSearch(page)
    await expect(page.locator('.smart-search-bar, [data-testid="smart-search-bar"], .smart-search-input').first()).toBeVisible({ timeout: 10000 })
  })

  test('le champ de recherche est focusable', async ({ page }) => {
    await openSearch(page)
    const input = page.locator('.smart-search-input, [data-testid="smart-search-input"]').first()
    await expect(input).toBeVisible({ timeout: 10000 })
  })

  test('saisie de texte dans le champ', async ({ page }) => {
    await openSearch(page)
    const input = page.locator('.smart-search-input, [data-testid="smart-search-input"]').first()
    await input.fill('rapport')
    await expect(input).toHaveValue('rapport', { timeout: 5000 })
  })

  test('affiche le bouton clear après saisie', async ({ page }) => {
    await openSearch(page)
    const input = page.locator('.smart-search-input, [data-testid="smart-search-input"]').first()
    await input.fill('test')
    await expect(page.locator('.smart-search-clear').first()).toBeVisible({ timeout: 5000 })
  })

  test('le bouton clear efface le texte', async ({ page }) => {
    await openSearch(page)
    const input = page.locator('.smart-search-input, [data-testid="smart-search-input"]').first()
    await input.fill('test')
    await page.locator('.smart-search-clear').first().click()
    await expect(input).toHaveValue('', { timeout: 5000 })
  })
})

test.describe('Search — suggestions', () => {
  test.beforeEach(async ({ page }) => { await setupSearchMocks(page); await page.goto('/'); await waitForAppReady(page) })

  test('affiche le dropdown de suggestions au focus', async ({ page }) => {
    await openSearch(page)
    const input = page.locator('.smart-search-input, [data-testid="smart-search-input"]').first()
    await input.click()
    // Le dropdown peut s'afficher avec les recherches récentes ou les suggestions
    await expect(page.locator('.search-suggestions-dropdown').first()).toBeVisible({ timeout: 10000 })
  })

  test('Escape ferme les suggestions', async ({ page }) => {
    await openSearch(page)
    const input = page.locator('.smart-search-input, [data-testid="smart-search-input"]').first()
    await input.click()
    const dropdown = page.locator('.search-suggestions-dropdown')
    await expect(dropdown).toBeVisible({ timeout: 3000 })
    await page.keyboard.press('Escape')
    await expect(dropdown).not.toBeVisible({ timeout: 5000 })
  })
})

test.describe('Search — icône et recherche sauvegardée', () => {
  test.beforeEach(async ({ page }) => { await setupSearchMocks(page); await page.goto('/'); await waitForAppReady(page) })

  test('affiche l\'icône de recherche', async ({ page }) => {
    await openSearch(page)
    // Icône peut être dans la barre ou dans le bouton d'ouverture
    const icon = page.locator('.smart-search-icon, .smart-search-bar svg, [data-testid="smart-search-bar"] svg').first()
    await expect(icon).toBeVisible({ timeout: 5000 })
  })

  test('affiche le bouton sauvegarder après saisie', async ({ page }) => {
    await openSearch(page)
    const input = page.locator('.smart-search-input, [data-testid="smart-search-input"]').first()
    await input.fill('test query')
    await page.keyboard.press('Enter')
    await page.waitForLoadState('domcontentloaded')
    const saveBtn = page.locator('.smart-search-save')
    // Le bouton save doit apparaître après une recherche active
    await expect(saveBtn.first()).toBeVisible({ timeout: 5000 })
  })
})

test.describe('Search — refresh pendant recherche', () => {
  test('conserve les résultats filtrés quand un refresh de draft recharge la liste', async ({ page }) => {
    const searchedEmail = {
      ...mockEmails[0],
      id: 'searched-email',
      sender: 'cours.universite@example.com',
      sender_name: 'Cryptoformation Université',
      subject: 'Feedback calendrier',
      body_preview: 'Retour sur les fonctionnalités du calendrier',
    }
    const inboxEmails = mockEmails.filter((email) => email.id !== searchedEmail.id)
    let emailsCalls = 0

    await setupBaseMocks(page, {
      emailsResponse: { count: inboxEmails.length, emails: inboxEmails, source: 'mock' },
    })
    await page.route(
      (url) => isApiRoute(url) && url.pathname === '/api/settings',
      (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            deep_work_enabled: false,
            deep_work_emails_enabled: false,
            deep_work_work_enabled: false,
            deep_work_check_slots: [],
            deep_work_personal_blocks: [],
            deep_work_weekdays: [],
            deep_work_vip_contacts: [],
          }),
        })
      },
    )
    await page.route(
      (url) => isApiRoute(url) && url.pathname === '/api/emails',
      (route) => {
        emailsCalls += 1
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ count: inboxEmails.length, emails: inboxEmails, source: 'mock' }),
        })
      },
    )
    await page.route(
      (url) => isApiRoute(url) && url.pathname === '/api/emails/search',
      (route) => {
        const url2 = new URL(route.request().url())
        const query = url2.searchParams.get('q') || ''
        const results = query.includes('cours.universite')
          ? [{
              id: 1,
              email_id: searchedEmail.id,
              subject: searchedEmail.subject,
              sender: searchedEmail.sender,
              date: searchedEmail.received_at,
              snippet: searchedEmail.body_preview,
              relevance_score: 1,
              is_read: searchedEmail.is_read,
              is_starred: false,
            }]
          : []
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            query,
            total: results.length,
            results,
            duration_ms: 1,
            has_more: false,
          }),
        })
      },
    )

    await page.goto('/')
    await waitForAppReady(page)

    await page.locator('[data-testid="email-list-container"]').getByRole('button', { name: /Search|Rechercher/i }).click()
    const input = page.locator('.smart-search-input, [data-testid="smart-search-input"]').first()
    await expect(input).toBeVisible({ timeout: 8000 })
    await input.fill('from:cours.universite')
    await Promise.all([
      page.waitForResponse((response) => response.url().includes('/api/emails/search?')),
      input.press('Enter'),
    ])

    const feedbackSubject = page.locator('[data-testid="email-subject"]').filter({ hasText: 'Feedback calendrier' })
    const nonMatchingSubject = page.locator('[data-testid="email-subject"]').filter({ hasText: 'Rapport trimestriel Q4 2025' })
    await expect(feedbackSubject).toBeVisible({ timeout: 5000 })
    await expect(nonMatchingSubject).toHaveCount(0)

    const callsBeforeRefresh = emailsCalls
    await page.evaluate(() => {
      window.dispatchEvent(new CustomEvent('agentys:pending-draft-stale'))
    })
    await expect
      .poll(() => emailsCalls, { timeout: 5000 })
      .toBeGreaterThan(callsBeforeRefresh)

    await expect(feedbackSubject).toBeVisible()
    await expect(nonMatchingSubject).toHaveCount(0)
  })
})
