/**
 * Quick Steps — Settings panel E2E coverage.
 *
 * Targets the user-visible contract:
 *   1. Empty state shows the Quick Start templates rail (suggestions only;
 *      no defaults are persisted server-side until the user picks one).
 *   2. Creating a step via "+ Nouveau" surfaces the editor, saves to
 *      POST /api/quicksteps, and lands the new card in the list.
 *   3. Editing flips PATCH /api/quicksteps/<id>; deleting calls DELETE
 *      and removes the card.
 *   4. Shortcut collision returns 400 + UI surfaces a non-fatal error.
 *
 * Execution-time behaviour (chip bar, hotkeys, confirmation modal) is
 * covered by the Python integration tests under tests/quicksteps/ and
 * tests/api/test_quicksteps_routes.py — the surface is too plumbing-
 * heavy to drive realistically through a mocked Playwright run.
 */

import { test, expect, Page, Route } from '@playwright/test'
import { setupBaseMocks, waitForAppReady, isApiRoute } from './support/fixtures/setup'

interface MockStep {
  id: string
  name: string
  icon: string | null
  shortcut: string | null
  enabled: boolean
  confirmBeforeRun: boolean
  actions: Array<{ type: string; payload?: Record<string, unknown> }>
}

function uuid(): string {
  // RFC4122-shaped placeholder — backend validation only checks the format.
  return 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'.replace(/[a8]/g, (c) =>
    c === '8'
      ? (8 + Math.floor(Math.random() * 4)).toString(16)
      : Math.floor(Math.random() * 16).toString(16),
  )
}

interface MockState {
  steps: Map<string, MockStep>
  shortcutConflict: boolean
  postedBodies: unknown[]
  patchedBodies: unknown[]
  deletedIds: string[]
}

async function setupQuickStepsMocks(
  page: Page,
  initialSteps: MockStep[] = [],
): Promise<MockState> {
  const state: MockState = {
    steps: new Map(initialSteps.map((s) => [s.id, s])),
    shortcutConflict: false,
    postedBodies: [],
    patchedBodies: [],
    deletedIds: [],
  }

  // isApiRoute couvre AUSSI le proxy Vite (localhost:1420) — l'app en dev
  // fait des fetch relatifs /api/* ; sans cette origine les mocks étaient
  // ratés et le panneau restait sur la vue découverte (rail de templates).
  const matchListOrCreate = (url: URL) =>
    isApiRoute(url) && url.pathname === '/api/quicksteps'
  const matchItem = (url: URL) =>
    isApiRoute(url) &&
    /^\/api\/quicksteps\/[^/]+$/.test(url.pathname) &&
    !url.pathname.endsWith('/execute')

  await page.route(matchListOrCreate, (route: Route) => {
    const method = route.request().method()
    if (method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ quick_steps: Array.from(state.steps.values()) }),
      })
    }
    if (method === 'POST') {
      const body = JSON.parse(route.request().postData() || '{}')
      state.postedBodies.push(body)
      if (state.shortcutConflict) {
        return route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({
            error: "Shortcut '1' is already used",
            code: 'SHORTCUT_CONFLICT',
          }),
        })
      }
      const stored: MockStep = {
        id: body.id ?? uuid(),
        name: body.name ?? 'Untitled',
        icon: body.icon ?? null,
        shortcut: body.shortcut ?? null,
        enabled: body.enabled ?? true,
        confirmBeforeRun: body.confirmBeforeRun ?? false,
        actions: body.actions ?? [],
      }
      state.steps.set(stored.id, stored)
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(stored),
      })
    }
    return route.fallback()
  })

  await page.route(matchItem, (route: Route) => {
    const method = route.request().method()
    const url = new URL(route.request().url())
    const id = url.pathname.split('/').pop()!
    if (method === 'PATCH') {
      const body = JSON.parse(route.request().postData() || '{}')
      state.patchedBodies.push({ id, body })
      const existing = state.steps.get(id)
      if (!existing) {
        return route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'Quick Step not found' }),
        })
      }
      const merged: MockStep = { ...existing, ...body, id }
      state.steps.set(id, merged)
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(merged),
      })
    }
    if (method === 'DELETE') {
      state.deletedIds.push(id)
      state.steps.delete(id)
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      })
    }
    return route.fallback()
  })

  return state
}

async function openQuickStepsPanel(page: Page) {
  await page.locator('[data-testid="nav-settings"]').click()
  await expect(page.locator('[data-testid="settings-modal"]')).toBeVisible({
    timeout: 5000,
  })
  // Quick Actions vit désormais dans la section AUTOMATISATION, sous le
  // libellé « Actions rapides » (i18n quicksteps_section_label) — link
  // button qui ouvre sa propre modale.
  const sidebarItem = page
    .locator('.settings-sidebar-item')
    .filter({ hasText: /Automatisation/i })
  await sidebarItem.click()
  await page
    .locator('.settings-link-btn')
    .filter({ hasText: /Actions rapides/i })
    .click()
  await expect(page.locator('.quick-actions-modal')).toBeVisible({ timeout: 5000 })
  await expect(page.locator('.quicksteps-panel')).toBeVisible({ timeout: 5000 })
}

test.describe('Quick Steps settings panel', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
  })

  test('empty state renders the Quick Start templates rail', async ({ page }) => {
    await setupQuickStepsMocks(page, [])
    await page.goto('/')
    await waitForAppReady(page)
    await openQuickStepsPanel(page)

    // L'état vide rend .quicksteps-empty avec les cartes templates
    // (.quicksteps-template) + la carte « Nouvelle » (--blank) — l'ancien
    // rail .quicksteps-rail__card n'existe plus dans la modale.
    await expect(page.locator('.quicksteps-empty')).toBeVisible()
    expect(await page.locator('.quicksteps-template').count()).toBeGreaterThanOrEqual(2)
    await expect(
      page.locator('.quicksteps-template', { hasText: 'Répondre + Transférer' }),
    ).toBeVisible()
    // No saved cards yet — scopé à la modale : la section Automatisation
    // derrière rend des QuickStepCard « embedded » (règles découvrables)
    // qui ne sont pas des quick steps sauvegardés.
    await expect(page.locator('.quick-actions-modal .quickstep-card')).toHaveCount(0)
  })

  test('"+ Nouveau" creates a Quick Step via POST /api/quicksteps', async ({ page }) => {
    const state = await setupQuickStepsMocks(page, [])
    await page.goto('/')
    await waitForAppReady(page)
    await openQuickStepsPanel(page)

    // État vide → la création « from scratch » passe par la carte
    // .quicksteps-template--blank du rail (le bouton __primary n'existe
    // que dans l'en-tête de la liste non vide).
    await page.locator('.quicksteps-template--blank').click()
    await expect(page.locator('.quickstep-editor')).toBeVisible()

    await page
      .locator('.quickstep-editor__field input[type="text"]').first()
      .fill('Triage rapide')

    // Save — default action chain is [archive] which the validator accepts.
    // (Le bouton vit dans .quickstep-editor__actions-row, type=submit —
    // l'ancien .quickstep-editor__head-actions .primary n'existe plus.)
    await page
      .locator('.quickstep-editor__actions-row button[type="submit"]')
      .click()

    await expect(page.locator('.quickstep-editor')).toHaveCount(0)
    await expect(page.locator('.quickstep-card', { hasText: 'Triage rapide' })).toBeVisible()
    expect(state.postedBodies).toHaveLength(1)
    expect((state.postedBodies[0] as MockStep).name).toBe('Triage rapide')
  })

  test('shortcut conflict surfaces inline without losing the editor', async ({ page }) => {
    const state = await setupQuickStepsMocks(page, [])
    state.shortcutConflict = true
    await page.goto('/')
    await waitForAppReady(page)
    await openQuickStepsPanel(page)

    await page.locator('.quicksteps-template--blank').click()
    await page
      .locator('.quickstep-editor__field input[type="text"]').first()
      .fill('Conflit')
    await page
      .locator('.quickstep-editor__actions-row button[type="submit"]')
      .click()

    // Editor stays open and surfaces the server error (inline dans
    // l'éditeur — .quickstep-editor__error — depuis le refactor éditeur).
    await expect(page.locator('.quickstep-editor')).toBeVisible()
    const errorBox = page.locator('.quickstep-editor__error, .quicksteps-panel__error')
    await expect(errorBox.first()).toBeVisible()
    await expect(errorBox.first()).toContainText(/Shortcut/i)
  })

  test('editing flips PATCH /api/quicksteps/<id>', async ({ page }) => {
    const existing: MockStep = {
      id: 'aaaaaaaa-1111-4111-8111-111111111111',
      name: 'Old name',
      icon: null,
      shortcut: null,
      enabled: true,
      confirmBeforeRun: false,
      actions: [{ type: 'archive' }],
    }
    const state = await setupQuickStepsMocks(page, [existing])
    await page.goto('/')
    await waitForAppReady(page)
    await openQuickStepsPanel(page)

    await expect(page.locator('.quickstep-card', { hasText: 'Old name' })).toBeVisible()
    // Plus de bouton « Modifier » — la carte entière est cliquable (onEdit
    // sur l'article, voir QuickStepsManager.QuickStepCard).
    await page.locator('.quickstep-card', { hasText: 'Old name' }).click()
    await expect(page.locator('.quickstep-editor')).toBeVisible()
    const nameInput = page.locator('.quickstep-editor__field input[type="text"]').first()
    await nameInput.fill('New name')
    await page
      .locator('.quickstep-editor__actions-row button[type="submit"]')
      .click()
    await expect(page.locator('.quickstep-editor')).toHaveCount(0)
    await expect(page.locator('.quickstep-card', { hasText: 'New name' })).toBeVisible()

    expect(state.patchedBodies).toHaveLength(1)
    expect((state.patchedBodies[0] as { body: MockStep }).body.name).toBe('New name')
  })

  test('delete removes the card and calls DELETE', async ({ page }) => {
    const existing: MockStep = {
      id: 'aaaaaaaa-2222-4222-8222-222222222222',
      name: 'To delete',
      icon: null,
      shortcut: null,
      enabled: true,
      confirmBeforeRun: false,
      actions: [{ type: 'archive' }],
    }
    const state = await setupQuickStepsMocks(page, [existing])
    await page.goto('/')
    await waitForAppReady(page)
    await openQuickStepsPanel(page)

    // La confirmation est une modale custom (ConfirmationDialog), plus un
    // window.confirm natif — cliquer le bouton confirm-btn.
    await page
      .locator('.quickstep-card', { hasText: 'To delete' })
      .locator('button.danger')
      .click()
    await page.locator('[data-testid="confirmation-dialog"] [data-testid="confirm-btn"]').click()

    await expect(page.locator('.quickstep-card', { hasText: 'To delete' })).toHaveCount(0)
    expect(state.deletedIds).toEqual([existing.id])
  })
})
