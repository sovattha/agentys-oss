/**
 * Auto-Reply Toggle — Regression Test
 *
 * Reproduit le bug : le toggle "Activer les réponses automatiques" ne s'activait
 * pas au clic dans le modal AutoReplyModal (label-checkbox delegation silencieuse
 * dans le webview Tauri).
 *
 * Fix appliqué : onClick explicite sur le <label> avec e.preventDefault() +
 * appel direct de toggleAutoReply(), bypassing le mécanisme natif.
 *
 * Ce test vérifie :
 *   1. Le modal s'ouvre depuis le bouton Settings → Compte
 *   2. Le toggle principal est OFF par défaut
 *   3. Un clic sur le toggle l'active visuellement (checked + body interactif)
 *   4. Un deuxième clic le désactive
 *   5. Le toggle "Transfert automatique" fonctionne aussi
 *   6. Cliquer hors du modal le ferme
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'
const API_LOCALHOST = 'http://localhost:5050'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function mockSettings(page: Page, overrides: Record<string, unknown> = {}) {
  const body = JSON.stringify({
    auto_reply_enabled: false,
    auto_reply_message: '',
    auto_reply_start: '',
    auto_reply_end: '',
    auto_transfer_enabled: false,
    auto_transfer_email: '',
    ...overrides,
  })
  const handler = (route: import('@playwright/test').Route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body })

  await page.route(`${API}/api/settings`, handler)
  await page.route(`${API_LOCALHOST}/api/settings`, handler)
  // PATCH settings → 200 OK
  await page.route(`${API}/api/settings`, (route) => {
    if (route.request().method() === 'PATCH') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) })
    } else {
      route.fallback()
    }
  })
}

/** Ouvre Settings → section Compte → clique le bouton Réponses automatiques */
async function openAutoReplyModal(page: Page) {
  // Ouvrir les settings
  await page.locator('[data-testid="nav-settings"]').click()
  await expect(page.locator('[data-testid="settings-modal"]')).toBeVisible()

  // Aller dans la section Compte (première section par défaut, mais on clique explicitement)
  const compteTab = page.locator('.settings-sidebar-item', { hasText: 'Compte' })
  await compteTab.click()

  // Cliquer le bouton "Réponses automatiques"
  await page.locator('.settings-link-btn', { hasText: /[Rr][ée]ponses automatiques/ }).click()

  // Attendre le modal
  await expect(page.locator('.autoreply-modal')).toBeVisible()
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('AutoReply Toggle', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
    await mockSettings(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('le modal s\'ouvre et le toggle est OFF par défaut', async ({ page }) => {
    await openAutoReplyModal(page)

    const toggle = page.locator('.autoreply-modal .autoreply-toggle').first()
    const checkbox = toggle.locator('input[type="checkbox"]')

    await expect(toggle).toBeVisible()
    await expect(checkbox).not.toBeChecked()

    // Le body sous le toggle doit être désactivé (pointer-events none + opacity)
    const body = page.locator('.autoreply-body')
    await expect(body).toHaveAttribute('data-disabled', 'true')
  })

  test('cliquer le toggle l\'active (ON)', async ({ page }) => {
    await openAutoReplyModal(page)

    const toggle = page.locator('.autoreply-modal .autoreply-toggle').first()
    const checkbox = toggle.locator('input[type="checkbox"]')
    const switchEl = toggle.locator('.settings-switch')

    // Clic sur le switch visuel
    await switchEl.click()

    // Le checkbox doit être coché
    await expect(checkbox).toBeChecked()

    // Le body doit être activé (data-disabled="false")
    const body = page.locator('.autoreply-body')
    await expect(body).toHaveAttribute('data-disabled', 'false')
  })

  test('double clic toggle : ON puis OFF', async ({ page }) => {
    await openAutoReplyModal(page)

    const toggle = page.locator('.autoreply-modal .autoreply-toggle').first()
    const checkbox = toggle.locator('input[type="checkbox"]')
    const switchEl = toggle.locator('.settings-switch')

    // Premier clic → ON
    await switchEl.click()
    await expect(checkbox).toBeChecked()

    // Deuxième clic → OFF
    await switchEl.click()
    await expect(checkbox).not.toBeChecked()
    await expect(page.locator('.autoreply-body')).toHaveAttribute('data-disabled', 'true')
  })

  test('cliquer le label (pas juste le switch) active aussi le toggle', async ({ page }) => {
    await openAutoReplyModal(page)

    const toggle = page.locator('.autoreply-modal .autoreply-toggle').first()
    const checkbox = toggle.locator('input[type="checkbox"]')

    // Clic sur le label complet (zone texte)
    await toggle.click()
    await expect(checkbox).toBeChecked()
  })

  test('le toggle Transfert automatique fonctionne quand auto-reply est ON', async ({ page }) => {
    await openAutoReplyModal(page)

    // Activer d'abord le toggle principal
    await page.locator('.autoreply-modal .autoreply-toggle').first().locator('.settings-switch').click()
    await expect(page.locator('.autoreply-body')).toHaveAttribute('data-disabled', 'false')

    // Toggle transfert (second toggle, à l'intérieur du body)
    const transferToggle = page.locator('.autoreply-body .autoreply-toggle')
    const transferCheckbox = transferToggle.locator('input[type="checkbox"]')

    await expect(transferCheckbox).not.toBeChecked()
    await transferToggle.locator('.settings-switch').click()
    await expect(transferCheckbox).toBeChecked()
  })

  test('cliquer hors du modal le ferme', async ({ page }) => {
    await openAutoReplyModal(page)

    // Cliquer sur l'overlay (fond)
    await page.locator('.autoreply-overlay').click({ position: { x: 5, y: 5 } })

    await expect(page.locator('.autoreply-modal')).not.toBeVisible()
  })

  test('le switch s\'affiche en vert (accent) quand activé', async ({ page }) => {
    await openAutoReplyModal(page)

    const switchEl = page.locator('.autoreply-modal .autoreply-toggle').first().locator('.settings-switch')

    // Avant clic : couleur non-accent
    const colorBefore = await switchEl.evaluate((el) =>
      window.getComputedStyle(el).backgroundColor
    )

    await switchEl.click()

    // Après clic : couleur doit avoir changé (le toggle est ON = couleur accent)
    const colorAfter = await switchEl.evaluate((el) =>
      window.getComputedStyle(el).backgroundColor
    )

    expect(colorBefore).not.toBe(colorAfter)
  })
})
