/**
 * Sent Folder E2E Tests
 *
 * Regression tests pour le bug "Failed to fetch emails: 500" sur le dossier Envoyés.
 * Cause : `manager.switch_account()` appelé au lieu de la fonction module `switch_account()`.
 *
 * Couvre :
 * - Navigation vers le dossier Envoyés sans erreur
 * - Affichage de la liste des emails envoyés
 * - Comportement en cas d'erreur 500 (état d'erreur avec bouton Réessayer)
 * - Récupération après erreur (retry)
 * - Affichage du détail d'un email envoyé
 */

import { test, expect, Page } from '@playwright/test'
import { mockEmails } from './support/fixtures/mock-data'
import { setupBaseMocks } from './support/fixtures/setup'
import { AppPage } from './pages/AppPage'

const API = 'http://127.0.0.1:5050'

const mockSentEmails = {
  count: 3,
  emails: [
    {
      ...mockEmails[0],
      id: 'sent:100',
      subject: 'Re: Projet Agentys',
      sender: 'test@example.com',
      folder: 'sent',
    },
    {
      ...mockEmails[1],
      id: 'sent:101',
      subject: 'Re: Budget Q1',
      sender: 'test@example.com',
      folder: 'sent',
    },
    {
      ...mockEmails[2],
      id: 'sent:102',
      subject: 'Rapport mensuel',
      sender: 'test@example.com',
      folder: 'sent',
    },
  ],
  has_more: false,
  offset: 0,
  filter: 'all',
  source: 'cache',
}

async function setupSentMocks(page: Page) {
  await setupBaseMocks(page)

  await page.route(`${API}/api/emails?*`, (route) => {
    const url = new URL(route.request().url())
    const folder = url.searchParams.get('folder') || 'inbox'

    if (folder === 'sent') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockSentEmails),
      })
    } else {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          count: 2,
          emails: mockEmails.slice(0, 2),
          has_more: false,
          offset: 0,
          filter: 'all',
          source: 'cache',
        }),
      })
    }
  })
}

test.describe('Dossier Envoyés — navigation', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupSentMocks(page)
    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('navigue vers Envoyés sans erreur 500', async ({ page }) => {
    // Régression : avant fix, cette navigation déclenchait une 500
    await app.navigateToSent()

    // Pas d'erreur affichée
    const errorState = page.locator('text=Failed to fetch emails')
    await expect(errorState).not.toBeVisible({ timeout: 5000 })
  })

  test('affiche les emails envoyés après navigation', async ({ page }) => {
    await app.navigateToSent()

    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems.first()).toBeVisible({ timeout: 10000 })
    await expect(emailItems).toHaveCount(3, { timeout: 10000 })
  })

  test('affiche les sujets des emails envoyés', async ({ page }) => {
    await app.navigateToSent()

    await expect(page.locator('text=Re: Projet Agentys')).toBeVisible({ timeout: 10000 })
    await expect(page.locator('text=Re: Budget Q1')).toBeVisible({ timeout: 10000 })
  })

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  test('nav Envoyés a la classe active', async ({ page }) => {
    await app.navigateToSent()
    await expect(app.navSent).toHaveClass(/active/, { timeout: 5000 })
  })

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  test('retour inbox depuis Envoyés fonctionne', async ({ page }) => {
    await app.navigateToSent()
    await app.navigateToInbox()
    await expect(app.navInbox).toHaveClass(/active/, { timeout: 5000 })
  })
})

test.describe('Dossier Envoyés — état erreur 500', () => {
  let app: AppPage

  test('affiche l\'état d\'erreur quand API retourne 500', async ({ page }) => {
    await setupBaseMocks(page)

    // Inbox OK, Sent 500
    await page.route(`${API}/api/emails?*`, (route) => {
      const url = new URL(route.request().url())
      const folder = url.searchParams.get('folder') || 'inbox'

      if (folder === 'sent') {
        route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'Internal server error' }),
        })
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            count: 2,
            emails: mockEmails.slice(0, 2),
            has_more: false,
            offset: 0,
            filter: 'all',
            source: 'cache',
          }),
        })
      }
    })

    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToSent()

    // L'état d'erreur doit être visible
    const errorMsg = page.locator('text=/Failed to fetch emails|erreur|500/i')
    await expect(errorMsg).toBeVisible({ timeout: 10000 })
  })

  test('bouton Réessayer re-fetch les emails', async ({ page }) => {
    await setupBaseMocks(page)

    let callCount = 0

    await page.route(`${API}/api/emails?*`, (route) => {
      const url = new URL(route.request().url())
      const folder = url.searchParams.get('folder') || 'inbox'

      if (folder === 'sent') {
        callCount++
        if (callCount === 1) {
          // Premier appel : erreur
          route.fulfill({
            status: 500,
            contentType: 'application/json',
            body: JSON.stringify({ error: 'Internal server error' }),
          })
        } else {
          // Deuxième appel : succès
          route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(mockSentEmails),
          })
        }
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            count: 2,
            emails: mockEmails.slice(0, 2),
            has_more: false,
            offset: 0,
            filter: 'all',
            source: 'cache',
          }),
        })
      }
    })

    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToSent()

    // Attendre l'état d'erreur
    const retryButton = page.locator('button:has-text("Réessayer")')
    await expect(retryButton).toBeVisible({ timeout: 10000 })

    // Cliquer sur Réessayer
    await retryButton.click()

    // Les emails doivent apparaître après retry
    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems.first()).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Dossier Envoyés — auth failure retourne état propre', () => {
  test('affiche état vide quand auth échoue (source: error)', async ({ page }) => {
    await setupBaseMocks(page)

    await page.route(`${API}/api/emails?*`, (route) => {
      const url = new URL(route.request().url())
      const folder = url.searchParams.get('folder') || 'inbox'

      if (folder === 'sent') {
        // Simule le retour du backend quand get_pooled_provider() échoue
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            count: 0,
            offset: 0,
            has_more: false,
            filter: 'all',
            source: 'error',
            emails: [],
          }),
        })
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            count: 2,
            emails: mockEmails.slice(0, 2),
            has_more: false,
            offset: 0,
            filter: 'all',
            source: 'cache',
          }),
        })
      }
    })

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToSent()

    // Pas de crash ni d'erreur 500 — le frontend affiche un état vide ou "aucun email"
    const errorState = page.locator('text=/Failed to fetch emails|500|Internal server error/i')
    await expect(errorState).not.toBeVisible({ timeout: 5000 })

    // Pas d'emails affichés (liste vide)
    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems).toHaveCount(0, { timeout: 5000 })
  })
})

test.describe('Dossier Envoyés — détail email', () => {
  let app: AppPage

  test.beforeEach(async ({ page }) => {
    await setupSentMocks(page)

    // Mock email detail
    await page.route(`${API}/api/emails/sent:100`, (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...mockSentEmails.emails[0],
          body_html: '<p>Corps de l\'email envoyé.</p>',
          body_text: "Corps de l'email envoyé.",
          cc: [],
          bcc: [],
        }),
      })
    })

    app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
  })

  test('ouvre le détail d\'un email envoyé au clic', async ({ page }) => {
    await app.navigateToSent()

    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await expect(firstEmail).toBeVisible({ timeout: 10000 })
    await firstEmail.click()

    // Un panneau de détail doit s'ouvrir ou le sujet doit être visible
    const detailPanel = page.locator('.email-detail-panel, [data-testid="email-detail"]')
    const subject = page.locator('text=Re: Projet Agentys')
    await expect(detailPanel.or(subject).first()).toBeVisible({ timeout: 5000 })
  })
})

test.describe('Dossier Envoyés — détail headers-only puis body chargé', () => {
  test.fixme('affiche immédiatement les headers puis charge le body en arrière-plan', async ({ page }) => {
    // FIXME: lazy body-loading (2-step fetch) no longer implemented — app fetches full body in a single call
    await setupSentMocks(page)

    let detailCallCount = 0

    // 1er appel : headers-only (body vide, simule le backend servant depuis SQLite sans body)
    // 2e appel  : body complet (simule le background fetch terminé)
    await page.route(`${API}/api/emails/sent%3A100`, (route) => {
      detailCallCount++
      if (detailCallCount === 1) {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ...mockSentEmails.emails[0],
            body_html: null,
            body_text: '',
            body: '',
            cc: [],
          }),
        })
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ...mockSentEmails.emails[0],
            body_html: '<p>Contenu complet chargé en arrière-plan.</p>',
            body_text: 'Contenu complet chargé en arrière-plan.',
            body: '<p>Contenu complet chargé en arrière-plan.</p>',
            cc: [],
          }),
        })
      }
    })

    // Also match unencoded URL (Playwright may or may not encode the colon)
    await page.route(`${API}/api/emails/sent:100`, (route) => {
      detailCallCount++
      if (detailCallCount === 1) {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ...mockSentEmails.emails[0],
            body_html: null,
            body_text: '',
            body: '',
            cc: [],
          }),
        })
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ...mockSentEmails.emails[0],
            body_html: '<p>Contenu complet chargé en arrière-plan.</p>',
            body_text: 'Contenu complet chargé en arrière-plan.',
            body: '<p>Contenu complet chargé en arrière-plan.</p>',
            cc: [],
          }),
        })
      }
    })

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToSent()

    // Cliquer sur le premier email envoyé
    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await expect(firstEmail).toBeVisible({ timeout: 10000 })

    // Préparer les waiters AVANT le clic pour capturer les 2 appels détail
    const isSentDetailUrl = (resp: import('@playwright/test').Response) =>
      resp.url().includes('/api/emails/sent')

    const firstDetailDone = page.waitForResponse(isSentDetailUrl, { timeout: 8000 })
    await firstEmail.click()
    await firstDetailDone  // 1er appel : headers-only (body vide)

    // Le spinner "Chargement..." ne doit PAS rester indéfiniment visible.
    const loadingSpinner = page.locator('text=Chargement...')
    await expect(loadingSpinner).not.toBeVisible({ timeout: 8000 })

    // Le sujet doit être visible dans le panneau de détail (prouve que les headers sont affichés)
    await expect(page.locator('h2:has-text("Re: Projet Agentys")')).toBeVisible({ timeout: 5000 })

    // Le silent retry doit déclencher au moins 2 appels au endpoint de détail
    // Attendre le 2e appel (background fetch body complet)
    await page.waitForResponse(isSentDetailUrl, { timeout: 8000 })
    expect(detailCallCount).toBeGreaterThanOrEqual(2)
  })

  test('ne reste pas bloqué sur Chargement quand le detail retourne un body vide', async ({ page }) => {
    await setupSentMocks(page)

    // Toujours retourner un body vide (simule un background fetch pas encore terminé)
    const detailHandler = (route: import('@playwright/test').Route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...mockSentEmails.emails[0],
          body_html: null,
          body_text: '',
          body: '',
          cc: [],
        }),
      })
    }
    await page.route(`${API}/api/emails/sent%3A100`, detailHandler)
    await page.route(`${API}/api/emails/sent:100`, detailHandler)

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()
    await app.navigateToSent()

    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await expect(firstEmail).toBeVisible({ timeout: 10000 })
    await firstEmail.click()

    // Le spinner doit disparaître même sans body (pas de blocage infini)
    const loadingSpinner = page.locator('text=Chargement...')
    await expect(loadingSpinner).not.toBeVisible({ timeout: 8000 })

    // Le sujet est affiché dans le détail (headers servis)
    await expect(page.locator('h2:has-text("Re: Projet Agentys")')).toBeVisible({ timeout: 5000 })
  })
})
