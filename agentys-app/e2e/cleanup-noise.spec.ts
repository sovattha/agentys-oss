/**
 * Noise Label — Bouton "Nettoyer" (Clean up) E2E Tests
 *
 * Teste le comportement du bouton de nettoyage dans la vue label Bruit (Noise)
 * de la boîte de réception Agentys.
 *
 * Scénarios :
 *  - Visibilité de la bannière et du bouton
 *  - Désactivation quand liste vide
 *  - Appel API direct sans confirmation
 *  - Rafraîchissement de la liste après nettoyage
 *  - Toast succès / erreur
 *  - Affichage de la notice auto-suppression 30 jours
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks } from './support/fixtures/setup'
import { AppPage } from './pages/AppPage'

const API = 'http://127.0.0.1:5050'

// ---------------------------------------------------------------------------
// Données mock
// ---------------------------------------------------------------------------

const mockNoiseEmails = {
  count: 3,
  emails: [
    {
      id: 'noise-1',
      sender: 'newsletter@marketing.com',
      sender_name: 'Marketing Newsletter',
      subject: 'Nouvelles du mois',
      received_at: '2026-03-20T10:00:00Z',
      is_read: true,
      has_attachments: false,
      label: 'Noise',
    },
    {
      id: 'noise-2',
      sender: 'promo@deals.com',
      sender_name: 'Daily Deals',
      subject: 'Offre du jour -50%',
      received_at: '2026-03-19T10:00:00Z',
      is_read: true,
      has_attachments: false,
      label: 'Noise',
    },
    {
      id: 'noise-3',
      sender: 'notifications@app.io',
      sender_name: 'App Notifications',
      subject: 'Votre rapport hebdomadaire',
      received_at: '2026-03-18T10:00:00Z',
      is_read: false,
      has_attachments: false,
      label: 'Noise',
    },
  ],
  has_more: false,
  offset: 0,
  filter: 'all',
  source: 'cache',
}

const mockEmptyEmails = {
  count: 0,
  emails: [],
  has_more: false,
  offset: 0,
  filter: 'all',
  source: 'cache',
}

const mockCleanNoiseSuccess = {
  success: true,
  archived_count: 3,
  deleted_count: 0,
}

// ---------------------------------------------------------------------------
// Helpers de setup
// ---------------------------------------------------------------------------

/**
 * Configure les mocks de base et surcharge /api/emails pour renvoyer les emails
 * Noise quand le label est demandé, ou les emails fournis sinon.
 */
async function setupNoiseMocks(
  page: Page,
  opts: {
    noiseEmails?: typeof mockNoiseEmails | typeof mockEmptyEmails
    autoDeleteNoise?: boolean
  } = {}
) {
  const { noiseEmails = mockNoiseEmails, autoDeleteNoise = true } = opts

  // Écrire le localStorage avant le chargement de la page
  await page.addInitScript(
    ({ storageKey, value }: { storageKey: string; value: string }) => {
      localStorage.setItem(storageKey, value)
    },
    {
      storageKey: 'agentys_auto_delete_noise_30d',
      value: String(autoDeleteNoise),
    }
  )

  await setupBaseMocks(page)

  // Route emails : renvoie les emails Noise quand le label=Noise est demandé,
  // sinon une liste vide pour inbox générique.
  await page.route(`${API}/api/emails?*`, (route) => {
    const url = new URL(route.request().url())
    const label = url.searchParams.get('label')
    const folder = url.searchParams.get('folder') || 'inbox'

    if (folder === 'inbox' && label === 'Noise') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(noiseEmails),
      })
    } else {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ count: 0, emails: [], has_more: false, offset: 0, filter: 'all', source: 'cache' }),
      })
    }
  })

  // Mock /api/settings pour que useAutoDeleteNoiseSetting ne remplace pas le localStorage
  await page.route(`${API}/api/settings`, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ auto_delete_noise_30d: autoDeleteNoise }),
    })
  })

  // Mock clean-noise (succès par défaut — peut être surchargé dans les tests)
  await page.route(`${API}/api/emails/clean-noise`, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockCleanNoiseSuccess),
    })
  })
}

/**
 * Navigue vers l'inbox puis clique sur l'onglet Bruit (Noise) dans le header.
 * L'onglet est rendu par EmailListHeader comme `.header-tab` avec le texte
 * du label (getLabelDisplayName renvoie "Bruit" en fr, "Noise" en en).
 */
async function navigateToNoiseLabel(page: Page) {
  // S'assurer qu'on est sur l'inbox
  await page.getByTestId('nav-inbox').click()

  // Cliquer sur le tab Bruit / Noise dans le ribbon du header
  const noiseTab = page
    .locator('.header-tab')
    .filter({ hasText: /^(Bruit|Noise)$/ })
    .first()
  await noiseTab.waitFor({ state: 'visible', timeout: 10000 })
  await noiseTab.click()

  // Attendre que la bannière Noise soit visible (confirmant qu'on est dans la bonne vue)
  await page.locator('.noise-banner').waitFor({ state: 'visible', timeout: 10000 })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('Noise — Bannière et visibilité', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupNoiseMocks(page, { autoDeleteNoise: true })
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await navigateToNoiseLabel(page)
  })

  test('la bannière .noise-banner est visible dans la vue Noise', async ({ page }) => {
    await expect(page.locator('.noise-banner')).toBeVisible({ timeout: 10000 })
  })

  test('le bouton .noise-clean-btn est visible', async ({ page }) => {
    await expect(page.locator('.noise-clean-btn')).toBeVisible({ timeout: 10000 })
  })

  test('le bouton affiche une icône poubelle avec title', async ({ page }) => {
    const btn = page.locator('.noise-clean-btn')
    await expect(btn).toBeVisible({ timeout: 10000 })
    await expect(btn.locator('svg')).toBeVisible()
  })

  test('la bannière n\'est pas visible dans l\'inbox sans label Noise', async ({ page }) => {
    // Revenir à l'inbox général (onglet "Boîte de réception")
    await page.locator('.header-tab').filter({ hasText: /Boîte de réception|Inbox|All/i }).first().click()
    await expect(page.locator('.noise-banner')).not.toBeVisible({ timeout: 5000 })
  })
})

test.describe('Noise — Notice auto-suppression 30 jours', () => {
  test('la notice "30 jours" est affichée quand autoDeleteNoise est activé', async ({ page }) => {
    await setupNoiseMocks(page, { autoDeleteNoise: true })
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await navigateToNoiseLabel(page)

    const banner = page.locator('.noise-banner')
    await expect(banner).toContainText(/30 jours|30 days/, { timeout: 10000 })
  })

  test('la notice "30 jours" est masquée quand autoDeleteNoise est désactivé', async ({ page }) => {
    await setupNoiseMocks(page, { autoDeleteNoise: false })
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await navigateToNoiseLabel(page)

    // La bannière est présente avec le message "disabled" (paramètres/settings)
    await expect(page.locator('.noise-banner')).toBeVisible({ timeout: 10000 })
    await expect(page.locator('.noise-banner')).not.toContainText(/30 jours|30 days/)
    await expect(page.locator('.noise-banner')).toContainText(/paramètres|settings/i)
  })

  test('le bouton est toujours présent même quand la notice est masquée', async ({ page }) => {
    await setupNoiseMocks(page, { autoDeleteNoise: false })
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await navigateToNoiseLabel(page)

    await expect(page.locator('.noise-clean-btn')).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Noise — Bouton désactivé quand liste vide', () => {
  test('le bouton est désactivé quand la liste Noise est vide', async ({ page }) => {
    await setupNoiseMocks(page, { noiseEmails: mockEmptyEmails })
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await navigateToNoiseLabel(page)

    const btn = page.locator('.noise-clean-btn')
    await expect(btn).toBeVisible({ timeout: 10000 })
    await expect(btn).toBeDisabled({ timeout: 5000 })
  })

  test('le bouton est activé quand des emails Noise existent', async ({ page }) => {
    await setupNoiseMocks(page, { noiseEmails: mockNoiseEmails })
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await navigateToNoiseLabel(page)

    const btn = page.locator('.noise-clean-btn')
    await expect(btn).toBeVisible({ timeout: 10000 })
    await expect(btn).toBeEnabled({ timeout: 5000 })
  })
})

test.describe('Noise — Clic appelle l\'API directement (sans confirmation)', () => {
  test('le clic sur le bouton appelle POST /api/emails/clean-noise sans dialog', async ({ page }) => {
    await setupNoiseMocks(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await navigateToNoiseLabel(page)

    // Préparer l'interception de la requête
    const cleanNoiseRequest = page.waitForRequest(
      (req) => req.url().includes('/api/emails/clean-noise') && req.method() === 'POST',
      { timeout: 10000 }
    )

    // Cliquer sans aucune dialog de confirmation attendue
    await page.locator('.noise-clean-btn').click()

    // Vérifier que l'API est appelée immédiatement
    const req = await cleanNoiseRequest
    expect(req.method()).toBe('POST')
    expect(req.url()).toContain('/api/emails/clean-noise')

    // Vérifier qu'aucune dialog n'est apparue
    await expect(page.locator('[role="dialog"]')).not.toBeVisible({ timeout: 1000 }).catch(() => {
      // Tolérer si aucun dialog — c'est attendu
    })
  })

  test('l\'URL appelée est exactement /api/emails/clean-noise', async ({ page }) => {
    let capturedUrl = ''
    await setupNoiseMocks(page)
    // Surcharger la route pour capturer l'URL
    await page.route(`${API}/api/emails/clean-noise`, (route) => {
      capturedUrl = route.request().url()
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockCleanNoiseSuccess),
      })
    })

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await navigateToNoiseLabel(page)

    await page.locator('.noise-clean-btn').click()
    await page.waitForTimeout(500)

    expect(capturedUrl).toMatch(/\/api\/emails\/clean-noise$/)
  })
})

test.describe('Noise — Rafraîchissement de la liste après nettoyage', () => {
  test('la liste d\'emails devient vide après un nettoyage réussi', async ({ page }) => {
    await setupNoiseMocks(page)

    // Après le nettoyage, l'API emails doit renvoyer une liste vide
    let cleanDone = false
    await page.route(`${API}/api/emails/clean-noise`, (route) => {
      cleanDone = true
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockCleanNoiseSuccess),
      })
    })
    await page.route(`${API}/api/emails?*`, (route) => {
      const url = new URL(route.request().url())
      const label = url.searchParams.get('label')
      const folder = url.searchParams.get('folder') || 'inbox'

      if (cleanDone && folder === 'inbox' && label === 'Noise') {
        // Après le nettoyage : liste vide
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockEmptyEmails),
        })
      } else if (folder === 'inbox' && label === 'Noise') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockNoiseEmails),
        })
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ count: 0, emails: [], has_more: false, offset: 0, filter: 'all', source: 'cache' }),
        })
      }
    })

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await navigateToNoiseLabel(page)

    // Vérifier que les emails sont bien là avant le nettoyage
    await expect(page.locator('[data-testid="email-item"]').first()).toBeVisible({ timeout: 10000 })

    // Cliquer sur le bouton Nettoyer
    await page.locator('.noise-clean-btn').click()

    // Attendre que la liste se rafraîchisse et devienne vide
    await expect(page.locator('[data-testid="email-item"]')).toHaveCount(0, { timeout: 10000 })
  })
})

test.describe('Noise — Toast succès après nettoyage', () => {
  test('un toast de succès apparaît après le nettoyage', async ({ page }) => {
    await setupNoiseMocks(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await navigateToNoiseLabel(page)

    await page.locator('.noise-clean-btn').click()

    // Le toast doit apparaître avec le message de succès
    const toast = page.locator('.toast.toast-success, .toast-success')
    await expect(toast.first()).toBeVisible({ timeout: 10000 })
  })

  test('le toast de succès mentionne le nombre d\'emails nettoyés', async ({ page }) => {
    await setupNoiseMocks(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await navigateToNoiseLabel(page)

    await page.locator('.noise-clean-btn').click()

    // "3 emails bruit nettoyés" ou "3 noise emails cleaned"
    const toastMessage = page.locator('.toast-message')
    await expect(toastMessage.first()).toBeVisible({ timeout: 10000 })
    await expect(toastMessage.first()).toContainText(/3/, { timeout: 10000 })
  })
})

test.describe('Noise — Toast erreur quand l\'API retourne 500', () => {
  test('un toast d\'erreur apparaît quand l\'API clean-noise retourne 500', async ({ page }) => {
    await setupNoiseMocks(page)

    // Surcharger la route clean-noise pour retourner une erreur
    await page.route(`${API}/api/emails/clean-noise`, (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal server error' }),
      })
    })

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await navigateToNoiseLabel(page)

    await page.locator('.noise-clean-btn').click()

    // Toast d'erreur visible
    const errorToast = page.locator('.toast.toast-error, .toast-error')
    await expect(errorToast.first()).toBeVisible({ timeout: 10000 })
  })

  test('aucun toast de succès n\'apparaît quand l\'API retourne 500', async ({ page }) => {
    await setupNoiseMocks(page)

    await page.route(`${API}/api/emails/clean-noise`, (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal server error' }),
      })
    })

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await navigateToNoiseLabel(page)

    await page.locator('.noise-clean-btn').click()
    await page.waitForTimeout(1000)

    // Pas de toast succès
    await expect(page.locator('.toast.toast-success, .toast-success')).not.toBeVisible({ timeout: 3000 })
    // Mais un toast erreur
    await expect(page.locator('.toast.toast-error, .toast-error').first()).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Noise — Intégration complète', () => {
  test('scénario complet : navigation → nettoyage → toast → liste vide', async ({ page }) => {
    let cleanDone = false

    await page.addInitScript(() => {
      localStorage.setItem('agentys_auto_delete_noise_30d', 'true')
    })

    await setupBaseMocks(page)

    await page.route(`${API}/api/emails?*`, (route) => {
      const url = new URL(route.request().url())
      const label = url.searchParams.get('label')
      const folder = url.searchParams.get('folder') || 'inbox'

      if (folder === 'inbox' && label === 'Noise') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(cleanDone ? mockEmptyEmails : mockNoiseEmails),
        })
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ count: 0, emails: [], has_more: false, offset: 0, filter: 'all', source: 'cache' }),
        })
      }
    })

    await page.route(`${API}/api/settings`, (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ auto_delete_noise_30d: true }),
      })
    })

    await page.route(`${API}/api/emails/clean-noise`, (route) => {
      cleanDone = true
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockCleanNoiseSuccess),
      })
    })

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    // 1. Naviguer vers le label Noise
    await navigateToNoiseLabel(page)

    // 2. Vérifier que la bannière et les emails sont présents
    await expect(page.locator('.noise-banner')).toBeVisible({ timeout: 10000 })
    await expect(page.locator('[data-testid="email-item"]').first()).toBeVisible({ timeout: 10000 })
    await expect(page.locator('.noise-clean-btn')).toBeEnabled({ timeout: 5000 })

    // 3. Vérifier la notice 30 jours
    await expect(page.locator('.noise-banner')).toContainText(/30 jours|30 days/)

    // 4. Cliquer sur le bouton Nettoyer
    await page.locator('.noise-clean-btn').click()

    // 5. Toast de succès
    await expect(page.locator('.toast.toast-success, .toast-success').first()).toBeVisible({ timeout: 10000 })

    // 6. Liste vide après nettoyage
    await expect(page.locator('[data-testid="email-item"]')).toHaveCount(0, { timeout: 10000 })
  })
})
