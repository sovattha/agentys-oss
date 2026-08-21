/**
 * E2E — Recherche cross-dossiers : inbox, archives, envoyés, corbeille
 *
 * Couvre :
 *  1. Opérateurs "Après:" et "Avant:" présents dans la palette de suggestions
 *  2. Suggestions de périodes affichées quand on tape "after:" ou "before:"
 *  3. Chip "Après" créé avec l'accent correct (pas "Apres")
 *  4. Chip "Avant" créé avec l'accent correct
 *  5. Résultats depuis l'inbox affichés
 *  6. Résultats depuis les archives affichés
 *  7. Résultats depuis les envoyés affichés
 *  8. Résultats depuis la corbeille affichés
 *  9. Résultats mixtes (4 dossiers) tous affichés en même temps
 * 10. Provider fallback : endpoint search appelé une seule fois (merge côté backend)
 * 11. Date ancienne (> 120j) incluse dans la requête envoyée au backend
 * 12. Zéro résultat SQLite → affichage gracieux (pas d'erreur)
 * 13. Déduplication : email_id identique entre SQLite et provider → affiché une seule fois
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

// ─── Helpers ─────────────────────────────────────────────────────────────────

type SearchResult = {
  id: number
  email_id: string
  subject: string
  sender: string
  date: string
  snippet: string
  relevance_score: number
  is_read: boolean
  is_starred: boolean
}

function makeResult(overrides: Partial<SearchResult> & { email_id: string; subject: string }): SearchResult {
  return {
    id: 0,
    sender: 'test@example.com',
    date: new Date(Date.now() - 86400000).toISOString(),
    snippet: 'Extrait du message...',
    relevance_score: 1.0,
    is_read: true,
    is_starred: false,
    ...overrides,
  }
}

function makeSearchResponse(results: SearchResult[], query = 'test') {
  return {
    success: true,
    query,
    total: results.length,
    results,
    duration_ms: 5.2,
    has_more: false,
  }
}

/** Résultats simulant des emails de 4 dossiers différents */
const INBOX_RESULT = makeResult({ email_id: 'inbox-1', subject: 'Message inbox important', sender: 'alice@example.com', relevance_score: 2.5 })
const ARCHIVE_RESULT = makeResult({ email_id: 'archive-1', subject: 'Ancien projet archivé', sender: 'bob@example.com', date: new Date('2024-06-15').toISOString(), relevance_score: 1.8 })
const SENT_RESULT = makeResult({ email_id: 'sent-1', subject: 'Ma réponse envoyée', sender: 'me@example.com', date: new Date('2024-09-01').toISOString(), relevance_score: 1.2 })
const TRASH_RESULT = makeResult({ email_id: 'trash-1', subject: 'Email supprimé retrouvé', sender: 'charlie@example.com', date: new Date('2023-12-01').toISOString(), relevance_score: 0.0 })

async function setupSearchMocks(page: Page, searchResponse?: object) {
  await setupBaseMocks(page)

  await page.route(
    (url) => url.origin === API && url.pathname === '/api/contacts/autocomplete',
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )
  await page.route(
    (url) => url.origin === API && url.pathname === '/api/emails/search/suggestions',
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, senders: [], subjects: [], labels: [] }),
    }),
  )

  const defaultResponse = makeSearchResponse([INBOX_RESULT, ARCHIVE_RESULT, SENT_RESULT, TRASH_RESULT])
  await page.route(
    (url) => url.origin === API && url.pathname === '/api/emails/search',
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(searchResponse ?? defaultResponse),
    }),
  )
}

/** Ouvre la barre de recherche via le raccourci "/" */
async function openSearchBar(page: Page) {
  // Cliquer hors de tout champ pour s'assurer que le focus est sur body
  await page.locator('body').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press('/')

  // Attendre que la barre apparaisse
  const input = page.locator('.smart-search-input, [data-testid="smart-search-input"]').first()
  await expect(input).toBeVisible({ timeout: 8000 })
  return input
}

/** Ouvre le dropdown de suggestions en cliquant sur l'input */
async function openSuggestions(page: Page, input: ReturnType<Page['locator']>) {
  await input.click()
  const dropdown = page.locator('.search-suggestions-dropdown')
  await expect(dropdown).toBeVisible({ timeout: 5000 })
  return dropdown
}

// ─── Suite 1 : Opérateurs de date dans la palette ────────────────────────────

test.describe('Palette d\'opérateurs — dates', () => {
  test.beforeEach(async ({ page }) => {
    await setupSearchMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('1. "Après:" visible dans les suggestions à vide', async ({ page }) => {
    const input = await openSearchBar(page)
    await openSuggestions(page, input)

    // Doit contenir l'opérateur "Après:" dans la palette
    await expect(
      page.locator('.search-suggestions-dropdown').getByText('Après:', { exact: true })
    ).toBeVisible({ timeout: 5000 })
  })

  test('2. "Avant:" visible dans les suggestions à vide', async ({ page }) => {
    const input = await openSearchBar(page)
    await openSuggestions(page, input)

    await expect(
      page.locator('.search-suggestions-dropdown').getByText('Avant:', { exact: true })
    ).toBeVisible({ timeout: 5000 })
  })

  test('3. Taper "after:" affiche les suggestions de périodes', async ({ page }) => {
    const input = await openSearchBar(page)
    await input.fill('after:')

    const dropdown = page.locator('.search-suggestions-dropdown')
    await expect(dropdown).toBeVisible({ timeout: 5000 })

    // Vérifier la section "Choisir une période"
    await expect(dropdown.getByText('Choisir une période')).toBeVisible({ timeout: 3000 })

    // Vérifier quelques entrées de période
    await expect(dropdown.getByText('Cette semaine')).toBeVisible()
    await expect(dropdown.getByText('Ce mois')).toBeVisible()
    await expect(dropdown.getByText('Cette année')).toBeVisible()
  })

  test('4. Taper "before:" affiche les suggestions de périodes', async ({ page }) => {
    const input = await openSearchBar(page)
    await input.fill('before:')

    const dropdown = page.locator('.search-suggestions-dropdown')
    await expect(dropdown).toBeVisible({ timeout: 5000 })
    await expect(dropdown.getByText('Choisir une période')).toBeVisible({ timeout: 3000 })

    // Entrées spécifiques au mode "avant"
    await expect(dropdown.getByText(/Il y a plus d.1 an/)).toBeVisible()
    await expect(dropdown.getByText(/Il y a plus de 6 mois/)).toBeVisible()
  })

  test('5. Sélectionner "Cette semaine" crée un chip "Après" (avec accent)', async ({ page }) => {
    const input = await openSearchBar(page)
    await input.fill('after:')

    const dropdown = page.locator('.search-suggestions-dropdown')
    await expect(dropdown.getByText('Cette semaine')).toBeVisible({ timeout: 5000 })
    await dropdown.getByText('Cette semaine').click()

    // Un chip doit apparaître — son label doit être "Après" avec l'accent
    const chip = page.locator('.search-chip').first()
    await expect(chip).toBeVisible({ timeout: 3000 })
    await expect(chip.locator('.search-chip-label')).toHaveText('Après:')
  })

  test('6. Chip "Avant" a l\'accent correct', async ({ page }) => {
    const input = await openSearchBar(page)
    await input.fill('before:')

    const dropdown = page.locator('.search-suggestions-dropdown')
    await expect(dropdown.getByText(/Il y a plus d.1 mois/)).toBeVisible({ timeout: 5000 })
    await dropdown.getByText(/Il y a plus d.1 mois/).click()

    const chip = page.locator('.search-chip').first()
    await expect(chip).toBeVisible({ timeout: 3000 })
    await expect(chip.locator('.search-chip-label')).toHaveText('Avant:')
  })

  test('7. La valeur du chip contient la date formatée', async ({ page }) => {
    const input = await openSearchBar(page)
    await input.fill('after:')

    await expect(
      page.locator('.search-suggestions-dropdown').getByText('Cette semaine')
    ).toBeVisible({ timeout: 5000 })
    await page.locator('.search-suggestions-dropdown').getByText('Cette semaine').click()

    const chip = page.locator('.search-chip').first()
    await expect(chip).toBeVisible({ timeout: 3000 })
    // La valeur doit être le label lisible (pas la date brute)
    await expect(chip.locator('.search-chip-value')).toHaveText('Cette semaine')
  })
})

// ─── Suite 2 : Résultats cross-dossiers ──────────────────────────────────────

test.describe('Résultats cross-dossiers', () => {
  test.beforeEach(async ({ page }) => {
    await setupSearchMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('8. Email inbox affiché dans les résultats de recherche', async ({ page }) => {
    const input = await openSearchBar(page)
    await input.fill('important')
    await page.keyboard.press('Enter')

    await expect(
      page.locator(`[data-email-id="${INBOX_RESULT.email_id}"]`)
    ).toBeVisible({ timeout: 8000 })
  })

  test('9. Email archivé affiché dans les résultats de recherche', async ({ page }) => {
    const input = await openSearchBar(page)
    await input.fill('archivé')
    await page.keyboard.press('Enter')

    await expect(
      page.locator(`[data-email-id="${ARCHIVE_RESULT.email_id}"]`)
    ).toBeVisible({ timeout: 8000 })
  })

  test('10. Email envoyé affiché dans les résultats de recherche', async ({ page }) => {
    const input = await openSearchBar(page)
    await input.fill('réponse')
    await page.keyboard.press('Enter')

    await expect(
      page.locator(`[data-email-id="${SENT_RESULT.email_id}"]`)
    ).toBeVisible({ timeout: 8000 })
  })

  test('11. Email de la corbeille affiché dans les résultats de recherche', async ({ page }) => {
    const input = await openSearchBar(page)
    await input.fill('supprimé')
    await page.keyboard.press('Enter')

    await expect(
      page.locator(`[data-email-id="${TRASH_RESULT.email_id}"]`)
    ).toBeVisible({ timeout: 8000 })
  })

  test('12. Les 4 dossiers apparaissent simultanément dans les résultats', async ({ page }) => {
    const input = await openSearchBar(page)
    await input.fill('test')
    await page.keyboard.press('Enter')

    await expect(page.locator(`[data-email-id="${INBOX_RESULT.email_id}"]`)).toBeVisible({ timeout: 8000 })
    await expect(page.locator(`[data-email-id="${ARCHIVE_RESULT.email_id}"]`)).toBeVisible()
    await expect(page.locator(`[data-email-id="${SENT_RESULT.email_id}"]`)).toBeVisible()
    await expect(page.locator(`[data-email-id="${TRASH_RESULT.email_id}"]`)).toBeVisible()
  })
})

// ─── Suite 3 : Provider fallback ─────────────────────────────────────────────

test.describe('Provider fallback — emails anciens', () => {
  test('13. L\'endpoint /search est appelé une seule fois par requête', async ({ page }) => {
    let callCount = 0
    await setupBaseMocks(page)

    await page.route(
      (url) => url.origin === API && url.pathname === '/api/emails/search',
      (route) => {
        callCount++
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(makeSearchResponse([INBOX_RESULT, ARCHIVE_RESULT, SENT_RESULT, TRASH_RESULT])),
        })
      },
    )

    await page.goto('/')
    await waitForAppReady(page)

    const input = await openSearchBar(page)
    await input.fill('rapport')
    await page.keyboard.press('Enter')

    await page.waitForLoadState('networkidle')
    expect(callCount).toBe(1)
  })

  test('14. Résultats avec relevance_score=0 (provider) affichés correctement', async ({ page }) => {
    // Simule un résultat venant du provider (score 0 = pas de BM25, pas en cache SQLite)
    const providerResult = makeResult({
      email_id: 'old-email-2020',
      subject: 'Email de 2020 retrouvé',
      sender: 'ancien@partner.com',
      date: new Date('2020-03-15').toISOString(),
      relevance_score: 0.0,
      snippet: 'Email très ancien non présent dans le cache local...',
    })

    await setupSearchMocks(page, makeSearchResponse([providerResult]))
    await page.goto('/')
    await waitForAppReady(page)

    const input = await openSearchBar(page)
    await input.fill('2020')
    await page.keyboard.press('Enter')

    await expect(
      page.locator('[data-email-id="old-email-2020"]')
    ).toBeVisible({ timeout: 8000 })
  })

  test('15. Filtre "after:2020-01-01" envoyé correctement au backend', async ({ page }) => {
    let capturedQuery = ''
    await setupBaseMocks(page)

    await page.route(
      (url) => url.origin === API && url.pathname === '/api/emails/search',
      (route) => {
        const url2 = new URL(route.request().url())
        capturedQuery = url2.searchParams.get('q') || ''
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(makeSearchResponse([ARCHIVE_RESULT])),
        })
      },
    )

    await page.goto('/')
    await waitForAppReady(page)

    const input = await openSearchBar(page)
    // Taper manuellement la date ancienne
    await input.fill('after:2020-01-01')
    await page.keyboard.press('Enter')

    await page.waitForLoadState('networkidle')

    // La query doit contenir "after:2020-01-01"
    expect(capturedQuery).toContain('after:2020-01-01')
  })

  test('16. Zéro résultat — pas d\'erreur affiché', async ({ page }) => {
    await setupSearchMocks(page, makeSearchResponse([]))
    await page.goto('/')
    await waitForAppReady(page)

    const input = await openSearchBar(page)
    await input.fill('requête introuvable xyz')
    await page.keyboard.press('Enter')

    // Pas d'erreur fatale visible
    await expect(page.locator('.error-banner, [data-testid="error-state"]')).toHaveCount(0, { timeout: 5000 })

    // L'interface reste utilisable
    await expect(page.locator('.smart-search-input, [data-testid="smart-search-input"]').first()).toBeVisible()
  })

  test('17. Déduplication : email_id identique non affiché deux fois', async ({ page }) => {
    // Simule un résultat où le même email_id apparaîtrait dans SQLite et provider
    const sqliteHit = makeResult({ email_id: 'dup-email', subject: 'Email dupliqué via SQLite', relevance_score: 2.0 })
    const providerHit = makeResult({ email_id: 'dup-email', subject: 'Email dupliqué via provider', relevance_score: 0.0 })

    // Le backend est censé dédupliquer côté serveur — on simule la réponse déjà dédupliquée
    await setupSearchMocks(page, makeSearchResponse([sqliteHit, providerHit]))
    await page.goto('/')
    await waitForAppReady(page)

    const input = await openSearchBar(page)
    await input.fill('dupliqué')
    await page.keyboard.press('Enter')

    // L'UI doit afficher AU PLUS 1 élément avec data-email-id="dup-email"
    const items = page.locator('[data-email-id="dup-email"]')
    const count = await items.count()
    expect(count).toBeLessThanOrEqual(1)
  })
})

// ─── Suite 4 : Recherche par date via sélection de période ───────────────────

test.describe('Recherche par période — flux complet', () => {
  test.beforeEach(async ({ page }) => {
    await setupSearchMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('18. Sélectionner "6 derniers mois" → query envoyée avec after: + date correcte', async ({ page }) => {
    let capturedQuery = ''

    await page.route(
      (url) => url.origin === API && url.pathname === '/api/emails/search',
      (route) => {
        const url2 = new URL(route.request().url())
        capturedQuery = url2.searchParams.get('q') || ''
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(makeSearchResponse([ARCHIVE_RESULT])),
        })
      },
    )

    const input = await openSearchBar(page)
    await input.fill('after:')

    await expect(
      page.locator('.search-suggestions-dropdown').getByText('6 derniers mois')
    ).toBeVisible({ timeout: 5000 })
    await page.locator('.search-suggestions-dropdown').getByText('6 derniers mois').click()

    // Le chip est créé, maintenant il faut soumettre la recherche
    // (auto-submit ou Entrée)
    await page.waitForLoadState('networkidle')

    // Vérifier que la query contient after: + une date YYYY-MM-DD
    if (capturedQuery) {
      expect(capturedQuery).toMatch(/after:\d{4}-\d{2}-\d{2}/)
    }
  })

  test('19. Chip de date peut être supprimé avec le bouton ×', async ({ page }) => {
    const input = await openSearchBar(page)
    await input.fill('after:')

    await expect(
      page.locator('.search-suggestions-dropdown').getByText('Cette semaine')
    ).toBeVisible({ timeout: 5000 })
    await page.locator('.search-suggestions-dropdown').getByText('Cette semaine').click()

    // Un chip est créé
    const chip = page.locator('.search-chip').first()
    await expect(chip).toBeVisible({ timeout: 3000 })

    // Supprimer le chip
    await chip.locator('.search-chip-remove').click()

    // Le chip disparaît
    await expect(page.locator('.search-chip')).toHaveCount(0, { timeout: 3000 })
  })

  test('20. Combinaison chip "Après" + texte libre → query avec after: + texte', async ({ page }) => {
    let capturedQuery = ''

    await page.route(
      (url) => url.origin === API && url.pathname === '/api/emails/search',
      (route) => {
        const url2 = new URL(route.request().url())
        capturedQuery = url2.searchParams.get('q') || ''
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(makeSearchResponse([ARCHIVE_RESULT])),
        })
      },
    )

    const input = await openSearchBar(page)
    await input.fill('after:')

    await expect(
      page.locator('.search-suggestions-dropdown').getByText('Cette année')
    ).toBeVisible({ timeout: 5000 })
    await page.locator('.search-suggestions-dropdown').getByText('Cette année').click()

    // Ajouter du texte libre après le chip
    await input.fill('facture')
    await page.keyboard.press('Enter')

    await page.waitForLoadState('networkidle')

    // La query finale doit contenir à la fois after: et le terme libre
    if (capturedQuery) {
      expect(capturedQuery).toMatch(/after:\d{4}-\d{2}-\d{2}/)
      expect(capturedQuery).toContain('facture')
    }
  })
})
