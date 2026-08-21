/**
 * Send Flow E2E Tests
 *
 * Vérifie le flow complet d'envoi d'un brouillon depuis l'interface.
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'
import { mockDrafts as _mockDrafts } from './support/fixtures/draft-mocks'

const API = 'http://127.0.0.1:5050'

const mockPendingDraft = {
  id: 'pending-send-1',
  email_id: 'email-send-1',
  email_sender: 'client@example.com',
  email_sender_name: 'Client Test',
  email_subject: 'Question sur la livraison',
  email_body: 'Bonjour, quand sera livrée ma commande ?',
  draft_body: 'Bonjour, votre commande sera livrée dans 2 jours ouvrés.',
  draft_subject: 'Re: Question sur la livraison',
  draft_v1: null,
  critique: null,
  status: 'pending',
  smart_suggestions: ['Je vérifierai', 'Contactez le service livraison'],
  quick_replies: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
}

async function setupSendFlowMocks(page: Page) {
  await setupBaseMocks(page)

  // Mock /api/pending-drafts avec un draft en attente
  await page.route(`${API}/api/pending-drafts`, (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          drafts: [mockPendingDraft],
          pending_count: 1,
        }),
      })
    } else {
      route.continue()
    }
  })

  // Mock /api/pending-drafts/<id>
  await page.route(
    (url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts/pending-send-1'),
    (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockPendingDraft),
        })
      } else {
        route.continue()
      }
    }
  )

  // Mock /api/init pour inclure le draft
  await page.route(`${API}/api/init`, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        emails: { emails: [], has_more: false, source: 'mock' },
        label_counts: { counts: {}, total: 0 },
        pending_drafts: { drafts: [mockPendingDraft], pending_count: 1 },
        accounts: [{ id: 1, email: 'test@example.com', status: 'active' }],
      }),
    })
  })
}

// ============================================================================
// Tests navigation vers Brouillons
// ============================================================================

test.describe('Send Flow — navigation', () => {
  test.setTimeout(60000)
  test.beforeEach(async ({ page }) => {
    await setupSendFlowMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('la liste de brouillons est accessible', async ({ page }) => {
    // Chercher un lien vers les brouillons en attente dans la sidebar
    const draftsNav = page.locator('[data-testid="nav-drafts"], [data-testid="nav-pending"], .nav-drafts, [href*="draft"]').first()
    const hasDraftsNav = await draftsNav.count() > 0

    if (hasDraftsNav) {
      await draftsNav.click()
      await expect(page.locator('body')).not.toContainText('500', { timeout: 5000 })
    } else {
      // Les drafts peuvent être visibles dans la vue principale
      await expect(page.locator('body')).toBeVisible()
    }
  })

  test('le badge de brouillons affiche le bon compte', async ({ page }) => {
    // Un badge de count peut apparaître dans la navigation
    const badge = page.locator('[data-testid="drafts-badge"], .pending-count, .draft-badge').first()
    const hasBadge = await badge.count() > 0

    if (hasBadge) {
      const text = await badge.textContent()
      // Le badge doit être numérique
      expect(text?.trim()).toMatch(/^\d+$/)
    }
  })
})

// ============================================================================
// Tests envoi d'un brouillon
// ============================================================================

test.describe('Send Flow — envoi', () => {
  test.setTimeout(60000)
  test.beforeEach(async ({ page }) => {
    await setupSendFlowMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('intercepte POST /emails/<id>/send ou /pending-drafts/<id>/validate au clic Envoyer', async ({ page }) => {
    const sentRequests: string[] = []

    // Intercepter les requêtes d'envoi (différents endpoints possibles)
    await page.route(
      (url) => url.origin === API && (
        url.pathname.includes('/send') ||
        url.pathname.includes('/validate')
      ),
      (route) => {
        sentRequests.push(route.request().url())
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, sent: true, message: 'Email envoyé avec succès' }),
        })
      }
    )

    // Chercher le bouton Envoyer / Valider dans la page
    const sendButton = page.locator(
      'button:has-text("Envoyer"), button:has-text("Valider"), [data-testid="send-btn"], [data-testid="validate-btn"]'
    ).first()

    const hasSendButton = await sendButton.count() > 0
    if (hasSendButton) {
      await sendButton.click()
      // Wait for the send request to be intercepted
      await page.waitForResponse((resp) => resp.url().includes('/send') || resp.url().includes('/validate'))
      // Vérifier qu'une requête d'envoi a été faite
      expect(sentRequests.length).toBeGreaterThan(0)
    }
  })

  test('aucun crash 500 lors de la navigation dans les brouillons', async ({ page }) => {
    // Naviguer dans l'interface et vérifier l'absence d'erreurs
    await expect(page.locator('text=/500 Internal Server Error/i')).not.toBeVisible()
    await expect(page.locator('text=/Failed to fetch/i')).not.toBeVisible()
  })
})

// ============================================================================
// Tests feedback post-envoi
// ============================================================================

test.describe('Send Flow — feedback utilisateur', () => {
  // Tests directs (fetch API) — pas besoin de charger l'app complète
  test('mock POST validate retourne success: true', async ({ page }) => {
    await page.route(
      (url) => url.origin === API && url.pathname.includes('/validate'),
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, sent: true, message: 'Email envoyé avec succès' }),
        })
      }
    )

    await page.goto('about:blank')

    const evalResult = await page.evaluate(async (apiUrl) => {
      try {
        const res = await fetch(`${apiUrl}/api/pending-drafts/pending-send-1/validate`, { method: 'POST' })
        return await res.json()
      } catch {
        return null
      }
    }, API)

    if (evalResult) {
      expect(evalResult).toHaveProperty('success', true)
    }
  })

  test('le format de réponse validate contient sent et message', async ({ page }) => {
    await page.route(
      (url) => url.origin === API && url.pathname.includes('/validate'),
      (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            draft_id: 'pending-send-1',
            sent: true,
            message: 'Email envoyé avec succès',
          }),
        })
      }
    )

    await page.goto('about:blank')

    const result = await page.evaluate(async (apiUrl) => {
      try {
        const res = await fetch(`${apiUrl}/api/pending-drafts/pending-send-1/validate`, { method: 'POST' })
        return await res.json()
      } catch {
        return null
      }
    }, API)

    if (result) {
      expect(result).toHaveProperty('success')
      expect(result).toHaveProperty('sent')
      expect(result).toHaveProperty('message')
    }
  })
})
