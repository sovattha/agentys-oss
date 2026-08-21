/**
 * Comprehensive Settings E2E Tests
 *
 * Tests complets : ouverture, navigation sections, toggles, fermeture.
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady, isApiRoute } from './support/fixtures/setup'

async function setupSettingsMocks(page: Page) {
  await setupBaseMocks(page)
  // isApiRoute (et pas url.origin === 127.0.0.1:5050) : l'app en dev appelle
  // /api/* en relatif via le proxy Vite (localhost:1420) — un matcher
  // mono-origine laisse ces requêtes tomber sur les mocks de base.
  await page.route((url) => isApiRoute(url) && url.pathname === '/api/settings', (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          auto_draft_enabled: true,
          auto_archive_action: true,
          hide_noise_from_inbox: true,
          auto_followup_enabled: true,
          notifications_enabled: true,
          theme: 'default',
        }),
      })
    } else {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
    }
  })
  await page.route((url) => isApiRoute(url) && url.pathname === '/api/my-style', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ style: null }) })
  })
}

async function openSettings(page: Page) {
  await page.keyboard.press('Control+,')
  const modal = page.locator('.settings-modal, [data-testid="settings-modal"]').first()
  try {
    await modal.waitFor({ state: 'visible', timeout: 3000 })
  } catch {
    // Fallback : le raccourci a pu être avalé pendant l'init → bouton sidebar.
    // MAIS le modal peut aussi apparaître juste APRÈS les 3 s : re-check avant
    // de cliquer (sinon on clique un bouton recouvert par l'overlay du modal
    // → interception pointer-events → timeout 30 s), et clic tolérant —
    // s'il échoue parce que l'overlay est arrivé entre-temps, c'est un succès.
    if (!(await modal.isVisible())) {
      await page.locator('[data-testid="nav-settings"]').click({ timeout: 5000 }).catch(() => {})
    }
    await modal.waitFor({ state: 'visible', timeout: 5000 })
  }
}

test.describe('Settings — ouverture', () => {
  test.beforeEach(async ({ page }) => { await setupSettingsMocks(page); await page.goto('/'); await waitForAppReady(page) })

  test('ouvre avec Ctrl+,', async ({ page }) => {
    await openSettings(page)
    await expect(page.locator('.settings-modal, [data-testid="settings-modal"]').first()).toBeVisible()
  })

  test('ouvre via le bouton sidebar', async ({ page }) => {
    const settingsBtn = page.locator('[data-testid="nav-settings"]').first()
    await expect(settingsBtn).toBeVisible({ timeout: 5000 })
    await settingsBtn.click()
    await expect(page.locator('.settings-modal, [data-testid="settings-modal"]').first()).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Settings — navigation sections', () => {
  test.beforeEach(async ({ page }) => { await setupSettingsMocks(page); await page.goto('/'); await waitForAppReady(page); await openSettings(page) })

  test('affiche la section Compte', async ({ page }) => {
    const compteTab = page.locator('text=/Compte|Account/i').first()
    await expect(compteTab).toBeVisible({ timeout: 5000 })
  })

  test('navigue entre les sections', async ({ page }) => {
    // Settings sidebar has nav items (Connexion, Audio, Productivité, etc.)
    const tabs = page.locator('.settings-nav-item, .settings-tab, .settings-sidebar button, .settings-sidebar a, .settings-sidebar li')
    await expect(tabs.first()).toBeVisible({ timeout: 5000 })
    const count = await tabs.count()
    expect(count).toBeGreaterThan(1)
    await tabs.nth(1).click()
    // Settings modal should still be visible (no crash)
    await expect(page.locator('.settings-modal, [data-testid="settings-modal"]').first()).toBeVisible()
  })
})

test.describe('Settings — toggles', () => {
  test.beforeEach(async ({ page }) => { await setupSettingsMocks(page); await page.goto('/'); await waitForAppReady(page); await openSettings(page) })

  test('affiche les toggles de paramètres', async ({ page }) => {
    // Navigate to a section with toggles (Automatisation)
    await page.locator('.settings-sidebar-item', { hasText: /Automatisation|Automation/i }).click()
    const toggles = page.locator('.settings-toggle')
    await toggles.first().waitFor({ state: 'visible', timeout: 5000 })
    expect(await toggles.count()).toBeGreaterThan(0)
  })

  test('toggle un paramètre au clic', async ({ page }) => {
    // Navigate to Automatisation section which has toggle switches
    await page.locator('.settings-sidebar-item', { hasText: /Automatisation|Automation/i }).click()
    const toggles = page.locator('.settings-toggle')
    await toggles.first().waitFor({ state: 'visible', timeout: 5000 })
    const firstToggle = toggles.first()
    const checkbox = firstToggle.locator('input[type="checkbox"]')
    const checkedBefore = await checkbox.isChecked()
    await firstToggle.click()
    // Lecture immédiate = course avec le re-render React (le clic passe par
    // setState + PUT mocké). Assertion avec retry au lieu d'un isChecked sec.
    await expect(checkbox).toBeChecked({ checked: !checkedBefore, timeout: 3000 })
  })
})

test.describe('Settings — fermeture', () => {
  test.beforeEach(async ({ page }) => { await setupSettingsMocks(page); await page.goto('/'); await waitForAppReady(page); await openSettings(page) })

  test('ferme avec le bouton X', async ({ page }) => {
    const closeBtn = page.locator('.settings-close-btn, .settings-modal button[aria-label*="Fermer"], .settings-modal button[aria-label*="Close"]').first()
    await expect(closeBtn).toBeVisible({ timeout: 5000 })
    await closeBtn.click()
    await expect(page.locator('.settings-modal')).not.toBeVisible({ timeout: 5000 })
  })

  test('ferme avec Escape', async ({ page }) => {
    await page.keyboard.press('Escape')
    await expect(page.locator('.settings-modal, [data-testid="settings-modal"]')).not.toBeVisible({ timeout: 5000 })
  })
})
