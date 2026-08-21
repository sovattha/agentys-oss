/**
 * E2E — Brouillon vide directement éditable (PendingDraftDetail)
 *
 * Historique :
 *   - Régression initiale : cliquer "Régénérer" sur un brouillon vide appelait
 *     l'API avec instructions="" → 400 "instructions is required" → textarea
 *     verrouillé. Un correctif intermédiaire faisait ouvrir un RegenerateModal.
 *   - Fix 2026-06-23 (signalé par l'utilisateur) : l'ancien état "Le brouillon
 *     est vide / Régénérer" REMPLAÇAIT l'éditeur et empêchait d'écrire. On rend
 *     désormais directement le DraftEditor éditable quand le corps est vide.
 *
 * Nouveau contrat (ce que ce spec garde vert) :
 *   1. Corps vide → l'éditeur (DraftEditor) est rendu et éditable, PAS l'ancien
 *      état bloquant `.draft-empty-state` / `.draft-empty-regen-btn`.
 *   2. L'utilisateur peut taper directement dans la zone du brouillon.
 *   3. Aucune bannière "instructions is required" au chargement.
 *   4. Aucun appel /regenerate (et a fortiori aucun avec instructions vides) sur
 *      le simple chargement + saisie d'un brouillon vide.
 *   5. La régénération reste accessible via la barre d'outils (bouton ✨
 *      "générer depuis les notes", data-testid="pdd-magic-generate").
 */

import { test, expect, Page } from '@playwright/test'
import { mockEmailDetails } from './support/fixtures/mock-data'
import { isApiRoute, setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

// ── Fixtures ──────────────────────────────────────────────────────────────────

const mockDraftEmpty = {
  id: 'draft-empty',
  email_id: 'email-1',
  email_subject: 'Rapport trimestriel Q4 2025',
  email_sender: 'marie.dupont@example.com',
  email_sender_name: 'Marie Dupont',
  email_body: '<p>Bonjour, veuillez trouver ci-joint le rapport.</p>',
  draft_subject: 'Re: Rapport trimestriel Q4 2025',
  draft_body: '',   // ← corps vide : doit rendre l'éditeur directement éditable
  draft_v1: '',
  status: 'pending',
  classification: 'action',
  routing_tier: 'STANDARD',
  critique: '',
  smart_suggestions: [],
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
}

// ── Helpers ───────────────────────────────────────────────────────────────────

async function setupMocks(page: Page) {
  await setupBaseMocks(page)

  // Emails list + detail
  await page.route(
    (url) => isApiRoute(url) && url.pathname.match(/^\/api\/emails\/email-\d+$/) !== null,
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockEmailDetails['email-1']) })
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname.match(/\/api\/emails\/[^/]+\/read$/) !== null,
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname.match(/\/api\/emails\/[^/]+\/thread$/) !== null,
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 1, emails: [] }) })
  )

  // Pending drafts
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/pending-drafts',
    (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({ drafts: [mockDraftEmpty], pending_count: 1 }),
        })
      } else { route.continue() }
    }
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname.startsWith('/api/pending-drafts/by-email'),
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDraftEmpty) })
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname.match(/^\/api\/pending-drafts\/draft-empty$/) !== null,
    (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDraftEmpty) })
      } else if (route.request().method() === 'DELETE') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, draft_id: 'draft-empty' }) })
      } else if (route.request().method() === 'PUT' || route.request().method() === 'PATCH') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, draft_id: 'draft-empty' }) })
      } else { route.continue() }
    }
  )

  // Misc
  await page.route(
    (url) => isApiRoute(url) && url.pathname.startsWith('/api/contacts'),
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname.startsWith('/api/snippets'),
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ snippets: [], total: 0 }) })
  )
}

async function openEmptyDraft(page: Page) {
  await page.locator('[data-testid="nav-drafts"]').click()
  const draftItem = page.locator('.draft-item').first()
  await expect(draftItem).toBeVisible({ timeout: 10000 })
  await draftItem.click()
  await expect(
    page.locator('.pending-draft-detail, .pdd-draft-zone, .draft-card').first()
  ).toBeVisible({ timeout: 10000 })
}

const editor = (page: Page) =>
  page.locator('[data-testid="draft-body"] .draft-editor-content').first()

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe('Brouillon vide — éditeur directement éditable', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openEmptyDraft(page)
  })

  test('1. le corps vide rend l\'éditeur (pas l\'ancien état bloquant)', async ({ page }) => {
    // L'éditeur éditable est présent…
    await expect(editor(page)).toBeVisible({ timeout: 8000 })
    // …et l'ancien état "Le brouillon est vide / Régénérer" a disparu.
    await expect(page.locator('.draft-empty-state')).toHaveCount(0)
    await expect(page.locator('.draft-empty-regen-btn')).toHaveCount(0)
  })

  test('2. aucune bannière "instructions is required" au chargement', async ({ page }) => {
    await expect(page.locator('text=instructions is required')).not.toBeVisible({ timeout: 3000 })
    await expect(page.locator('.rc-error, .rc-error-banner, .error-banner').first()).not.toBeVisible({ timeout: 3000 })
  })

  test('3. l\'utilisateur peut écrire directement dans la zone du brouillon', async ({ page }) => {
    const body = editor(page)
    await expect(body).toBeVisible({ timeout: 8000 })
    await body.click()
    await page.keyboard.type('Bonjour Marie, merci pour votre rapport.')
    await expect(body).toContainText('Bonjour Marie, merci pour votre rapport.')
  })

  test('4. charger + écrire sur un brouillon vide n\'appelle jamais /regenerate', async ({ page }) => {
    const regenerateCalls: string[] = []
    page.on('request', (req) => {
      if (req.url().includes('/regenerate') && req.method() === 'POST') {
        regenerateCalls.push(req.url())
      }
    })

    const body = editor(page)
    await body.click()
    await page.keyboard.type('Réponse écrite à la main.')
    await page.waitForTimeout(500)

    expect(regenerateCalls).toHaveLength(0)
  })

  test('5. la régénération reste accessible via la barre d\'outils', async ({ page }) => {
    // Le bouton ✨ "générer depuis les notes" est présent et actionnable même
    // quand le corps est vide — la régénération n\'est plus imposée, juste offerte.
    const magicBtn = page.locator('[data-testid="pdd-magic-generate"]').first()
    await expect(magicBtn).toBeVisible({ timeout: 8000 })
    await expect(magicBtn).toBeEnabled()
  })
})
