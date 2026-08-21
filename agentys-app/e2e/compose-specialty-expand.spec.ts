/**
 * Specialty Expand E2E Tests — Ctrl+Shift+G
 *
 * Tests the specialty-aware two-call flow (Sonnet plan → Haiku draft) triggered
 * by Ctrl+Shift+G in NewMessageModal. Covers:
 *  - Badge renders on a full match, with category, risk color and sources tooltip
 *  - Footnote "---\nSources : …" is present in the generated body
 *  - no_active_specialty warning surfaces as a warning banner
 *  - specialty_unavailable (spec deleted but still listed in settings) → error banner
 *  - Standard Ctrl+G (without Shift) does NOT trigger expert mode
 *
 * Historique : le scénario "no_match" a été retiré — Ctrl+Shift+G force
 * maintenant l'application de la spécialité active, même si les mots-clés ne
 * matchent pas (demande utilisateur explicite = condition suffisante).
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

type RefineResponseKind = 'match' | 'specialty_unavailable' | 'no_active' | 'standard'

function makeRefineHandler(kind: RefineResponseKind) {
  return (route: import('@playwright/test').Route) => {
    const body = route.request().postDataJSON() || {}
    const useSpecialty = !!body.use_specialty

    if (!useSpecialty) {
      // Standard mode — never include specialty_info.
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          refined_text: 'Bonjour,\n\nTexte raffiné standard.\n\nCordialement,',
        }),
      })
      return
    }

    if (kind === 'no_active') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          refined_text: 'Bonjour,\n\nTexte raffiné sans expertise.\n\nCordialement,',
          specialty_info: { warning: 'no_active_specialty' },
        }),
      })
      return
    }

    if (kind === 'specialty_unavailable') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          refined_text: 'Bonjour,\n\nTexte raffiné standard.\n\nCordialement,',
          specialty_info: { warning: 'specialty_unavailable' },
        }),
      })
      return
    }

    // 'match' — full specialty_info with applied_sources + plan_preview.
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        refined_text:
          'Bonjour Marc,\n\n' +
          'Concernant le vice de pyrite découvert après la vente, ' +
          'je te recommande de consulter rapidement un notaire ou un avocat.\n\n' +
          'Cordialement,\n\n' +
          '---\n' +
          'Sources : CCQ art. 1726-1733, CCQ art. 1729',
        specialty_info: {
          specialty_id: 'real-estate-qc',
          specialty_name: 'Immobilier Québec',
          category: 'vice_cache',
          expert_ids: ['legal', 'construction'],
          expert_names: ['Juridique immobilier', 'Construction et inspection'],
          risk_level: 'medium',
          confidence: 0.8,
          keyword_hits: 4,
          applied_sources: ['CCQ art. 1726-1733', 'CCQ art. 1729'],
          plan_preview: '## Points clés\n- Vice caché\n\n## Cadre légal\n- CCQ art. 1726-1733',
        },
      }),
    })
  }
}

async function setupMocks(page: Page, kind: RefineResponseKind) {
  await setupBaseMocks(page)

  await page.route(
    (url) => url.origin === API && url.pathname === '/api/refine-text',
    makeRefineHandler(kind),
  )

  await page.route(
    (url) => url.origin === API && url.pathname.startsWith('/api/snippets'),
    (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ snippets: [], total: 0 }),
    }),
  )

  await page.route(
    (url) => url.origin === API && url.pathname === '/api/contacts/autocomplete',
    (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify([]),
    }),
  )
}

async function openNewMessageAndType(page: Page, notes: string) {
  await page.locator('body').click({ position: { x: 10, y: 10 } })
  await page.keyboard.press('n')
  await page.locator('.new-message-modal').first().waitFor({ state: 'visible', timeout: 10000 })
  // Body editor (TipTap) — click into it then type.
  const editor = page.locator('.nm-body-wrapper .ProseMirror').first()
  await editor.click()
  await page.keyboard.type(notes)
}

test.describe('Specialty expand — Ctrl+Shift+G', () => {
  test('match: affiche le badge avec catégorie, sources, et footnote dans le corps', async ({ page }) => {
    await setupMocks(page, 'match')
    await page.goto('/')
    await waitForAppReady(page)
    await openNewMessageAndType(page, 'Mon client a découvert un vice de pyrite après achat')

    await page.keyboard.press('Control+Shift+KeyG')

    const badge = page.locator('.specialty-badge').first()
    await expect(badge).toBeVisible({ timeout: 10000 })
    await expect(badge).toContainText('Immobilier Québec')
    await expect(badge).toContainText('vice cache')
    await expect(badge.locator('.specialty-badge__sources')).toContainText('2 sources')
    // Risk-level coloring applied via modifier class
    await expect(badge).toHaveClass(/specialty-badge--medium/)

    // Sources footnote inside the editor body
    const editor = page.locator('.nm-body-wrapper .ProseMirror').first()
    await expect(editor).toContainText('CCQ art. 1726-1733')
    await expect(editor).toContainText('Sources :')
  })

  test('specialty_unavailable: affiche un banner error, pas de badge', async ({ page }) => {
    await setupMocks(page, 'specialty_unavailable')
    await page.goto('/')
    await waitForAppReady(page)
    await openNewMessageAndType(page, 'Salut, tu veux aller au ciné demain ?')

    await page.keyboard.press('Control+Shift+KeyG')

    const msg = page.locator('.specialty-message--error').first()
    await expect(msg).toBeVisible({ timeout: 10000 })
    await expect(msg).toContainText('Spécialité introuvable')
    await expect(page.locator('.specialty-badge')).toHaveCount(0)
  })

  test('no_active_specialty: affiche un banner warning pointant vers Paramètres', async ({ page }) => {
    await setupMocks(page, 'no_active')
    await page.goto('/')
    await waitForAppReady(page)
    await openNewMessageAndType(page, 'Question sur la CCQ')

    await page.keyboard.press('Control+Shift+KeyG')

    const msg = page.locator('.specialty-message--warning').first()
    await expect(msg).toBeVisible({ timeout: 10000 })
    await expect(msg).toContainText('Aucune spécialité activée')
    await expect(page.locator('.specialty-badge')).toHaveCount(0)
  })

  test('Ctrl+G standard ne déclenche pas le mode expert (pas de specialty_info)', async ({ page }) => {
    await setupMocks(page, 'standard')
    await page.goto('/')
    await waitForAppReady(page)
    await openNewMessageAndType(page, 'Quelques notes rapides')

    await page.keyboard.press('Control+KeyG')

    // Give the app a moment to settle; then confirm nothing specialty-related rendered.
    await page.waitForTimeout(500)
    await expect(page.locator('.specialty-badge')).toHaveCount(0)
    await expect(page.locator('.specialty-message')).toHaveCount(0)
  })
})
