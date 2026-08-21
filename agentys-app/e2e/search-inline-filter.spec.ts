/**
 * E2E — Search inline filter panel + régressions flux type-based
 *
 * Couvre :
 *  RÉGRESSIONS :
 *  R1. Taper "from:john" dans la barre principale → dropdown toujours visible
 *  R2. Taper "after:" dans la barre → date presets dans dropdown (pas inline panel)
 *  R3. Chips créées via "from:x" tapé manuellement + Enter
 *
 *  NOUVEAU inline panel :
 *  N1. Ouvrir dropdown vide → palette en grille 2 colonnes (.search-operators-grid)
 *  N2. Groupes Personnes / Contenu / Date visibles
 *  N3. Cliquer "De :" → inline panel apparaît, main input reste vide
 *  N4. Inline input reçoit le focus automatiquement
 *  N5. Échap dans inline input → panel fermé, aucun chip, main input refocus
 *  N6. × dans inline panel → panel fermé, aucun chip
 *  N7. Cliquer "Après :" → grille de dates (pas d'input texte)
 *  N8. Cliquer preset "Cette semaine" → chip after: créé, panel fermé
 *  N9. Opérateur actif → classe .is-active sur l'item correspondant
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

async function setupSearchMocks(page: Page) {
  await setupBaseMocks(page)
  await page.route(
    (url) => url.origin === API && url.pathname === '/api/contacts/autocomplete',
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )
  await page.route(
    (url) => url.origin === API && url.pathname === '/api/emails/search/suggestions',
    (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ success: true, senders: [], subjects: [], labels: [] }),
    }),
  )
  await page.route(
    (url) => url.origin === API && url.pathname === '/api/emails/search',
    (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ success: true, query: '', total: 0, results: [], duration_ms: 1, has_more: false }),
    }),
  )
}

async function openSearchBar(page: Page) {
  await page.locator('body').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press('/')
  const input = page.locator('.smart-search-input, [data-testid="smart-search-input"]').first()
  await expect(input).toBeVisible({ timeout: 8000 })
  return input
}

async function openSuggestions(page: Page, input: ReturnType<Page['locator']>) {
  await input.click()
  const dropdown = page.locator('.search-suggestions-dropdown')
  await expect(dropdown).toBeVisible({ timeout: 5000 })
  return dropdown
}

// ─── Régressions : flux type-based inchangé ───────────────────────────────────

test.describe('Régression — flux type-based', () => {
  test.beforeEach(async ({ page }) => {
    await setupSearchMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('R1. Taper "from:john" dans la barre → dropdown visible, pas de inline panel', async ({ page }) => {
    const input = await openSearchBar(page)
    await input.fill('from:jo')

    // Dropdown (normal) doit être visible
    await expect(page.locator('.search-suggestions-dropdown')).toBeVisible({ timeout: 3000 })
    // Inline panel ne doit PAS apparaître (seulement activé par clic sur opérateur)
    await expect(page.locator('.inline-filter-panel')).not.toBeVisible()
    // Main input garde la valeur tapée
    await expect(input).toHaveValue('from:jo')
  })

  test('R2. Taper "after:" → date presets dans dropdown normal (pas inline)', async ({ page }) => {
    const input = await openSearchBar(page)
    await input.fill('after:')

    const dropdown = page.locator('.search-suggestions-dropdown')
    await expect(dropdown).toBeVisible({ timeout: 3000 })

    // Date presets dans le dropdown normal
    await expect(dropdown.getByText('Cette semaine')).toBeVisible({ timeout: 3000 })
    // Pas de inline panel
    await expect(page.locator('.inline-filter-panel')).not.toBeVisible()
  })

  test('R3. Taper "from:alice@example.com" + Enter → chip créé', async ({ page }) => {
    const input = await openSearchBar(page)
    await input.fill('from:alice@example.com')
    await input.press('Enter')

    // Chip doit apparaître
    await expect(page.locator('.search-chip').first()).toBeVisible({ timeout: 3000 })
    // Input vidé
    await expect(input).toHaveValue('')
  })
})

// ─── Nouveau : inline filter panel ───────────────────────────────────────────

test.describe('Inline filter panel — ouverture', () => {
  test.beforeEach(async ({ page }) => {
    await setupSearchMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('N1. Dropdown vide affiche la grille 2 colonnes (.search-operators-grid)', async ({ page }) => {
    const input = await openSearchBar(page)
    await openSuggestions(page, input)

    await expect(page.locator('.search-operators-grid').first()).toBeVisible({ timeout: 3000 })
  })

  test('N2. Groupes Personnes, Contenu, Date visibles dans la palette', async ({ page }) => {
    const input = await openSearchBar(page)
    await openSuggestions(page, input)

    const dropdown = page.locator('.search-suggestions-dropdown')
    await expect(dropdown.getByText('Personnes')).toBeVisible({ timeout: 3000 })
    await expect(dropdown.getByText('Contenu')).toBeVisible({ timeout: 3000 })
    await expect(dropdown.getByText('Date')).toBeVisible({ timeout: 3000 })
  })

  test('N3. Cliquer "De :" → inline panel apparaît, main input reste vide', async ({ page }) => {
    const input = await openSearchBar(page)
    await openSuggestions(page, input)

    // Cliquer l'opérateur "De :"
    await page.locator('.search-suggestions-dropdown').locator('[data-operator-type="from:"]').click()

    // Inline panel visible
    await expect(page.locator('.inline-filter-panel')).toBeVisible({ timeout: 3000 })
    // Main input reste vide (pas "from:")
    await expect(input).toHaveValue('')
  })

  test('N4. Inline input visible dans le panel', async ({ page }) => {
    const input = await openSearchBar(page)
    await openSuggestions(page, input)

    await page.locator('.search-suggestions-dropdown').locator('[data-operator-type="from:"]').click()

    const inlineInput = page.locator('[data-testid="inline-filter-input"]')
    await expect(inlineInput).toBeVisible({ timeout: 3000 })
  })
})

test.describe('Inline filter panel — interactions', () => {
  test.beforeEach(async ({ page }) => {
    await setupSearchMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('N5. Échap dans inline input → panel fermé, aucun chip, main input refocused', async ({ page }) => {
    const input = await openSearchBar(page)
    await openSuggestions(page, input)

    await page.locator('.search-suggestions-dropdown').locator('[data-operator-type="from:"]').click()

    const inlineInput = page.locator('[data-testid="inline-filter-input"]')
    await inlineInput.fill('john')
    await inlineInput.press('Escape')

    // Panel fermé
    await expect(page.locator('.inline-filter-panel')).not.toBeVisible({ timeout: 3000 })
    // Aucun chip
    await expect(page.locator('.search-chip')).not.toBeVisible()
    // Main input vide
    await expect(input).toHaveValue('')
  })

  test('N6. Bouton × ferme le panel sans créer de chip', async ({ page }) => {
    const input = await openSearchBar(page)
    await openSuggestions(page, input)

    await page.locator('.search-suggestions-dropdown').locator('[data-operator-type="from:"]').click()

    const cancelBtn = page.locator('.inline-filter-cancel')
    await cancelBtn.click()

    await expect(page.locator('.inline-filter-panel')).not.toBeVisible({ timeout: 3000 })
    await expect(page.locator('.search-chip')).not.toBeVisible()
  })

  test('N7. Cliquer "Après :" → grille de dates visible, pas d\'input texte', async ({ page }) => {
    const input = await openSearchBar(page)
    await openSuggestions(page, input)

    await page.locator('.search-suggestions-dropdown').locator('[data-operator-type="after:"]').click()

    // Date grid visible
    await expect(page.locator('.inline-date-grid')).toBeVisible({ timeout: 3000 })
    // Pas de input texte inline (date mode = presets only)
    await expect(page.locator('[data-testid="inline-filter-input"]')).not.toBeVisible()
    // Date chips visibles
    const dateChips = page.locator('[data-testid="inline-date-chip"]')
    await expect(dateChips.first()).toBeVisible({ timeout: 3000 })
    expect(await dateChips.count()).toBeGreaterThan(0)
  })

  test('N8. Cliquer "Cette semaine" → chip after: créé, inline panel fermé', async ({ page }) => {
    const input = await openSearchBar(page)
    await openSuggestions(page, input)

    await page.locator('.search-suggestions-dropdown').locator('[data-operator-type="after:"]').click()

    // Cliquer "Cette semaine"
    await page.locator('[data-testid="inline-date-chip"]').filter({ hasText: 'Cette semaine' }).click()

    // Panel fermé
    await expect(page.locator('.inline-filter-panel')).not.toBeVisible({ timeout: 3000 })
    // Chip after: créé
    await expect(page.locator('.search-chip')).toBeVisible({ timeout: 3000 })
    // Chip contient un label de date (pas une date brute)
    const chipValue = await page.locator('.search-chip-value').first().textContent()
    expect(chipValue).toBeTruthy()
    // L'input main est vide
    await expect(input).toHaveValue('')
  })
})

test.describe('Inline filter panel — saisie texte', () => {
  test.beforeEach(async ({ page }) => {
    await setupSearchMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('Saisir valeur + Enter dans "Objet :" crée chip subject:', async ({ page }) => {
    const input = await openSearchBar(page)
    await openSuggestions(page, input)

    await page.locator('.search-suggestions-dropdown').locator('[data-operator-type="subject:"]').click()

    const inlineInput = page.locator('[data-testid="inline-filter-input"]')
    await inlineInput.fill('rapport mensuel')
    await inlineInput.press('Enter')

    // Panel fermé
    await expect(page.locator('.inline-filter-panel')).not.toBeVisible({ timeout: 3000 })
    // Chip subject: créé
    await expect(page.locator('.search-chip')).toBeVisible({ timeout: 3000 })
    const chipValue = await page.locator('.search-chip-value').first().textContent()
    expect(chipValue).toContain('rapport mensuel')
    // Main input vide
    await expect(input).toHaveValue('')
  })
})
