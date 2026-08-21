/**
 * Issue #187 — Regression: sliders Formalité et Niveau d'émotion doivent
 * avoir disparu de l'onglet "Style d'écriture par défaut".
 *
 * Le ton est désormais inféré automatiquement depuis l'outbox via
 * StyleInferenceService + affiché read-only par StyleObservedFromOutbox.
 */

import { test, expect } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

test.describe('Issue #187 — sliders explicites retirés', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('StyleSettingsSection ne contient plus les boutons Formalité/Émotion', async ({ page }) => {
    // Les sliders legacy utilisaient `button.style-emotion-option`. Sur toute
    // la page, plus aucun bouton avec les valeurs slider ne doit être rendu.
    // Playwright attend implicitement jusqu'à 5s — si un chunk lazy-chargé
    // rend les sliders plus tard, l'assertion capture la régression.
    const sliderButtons = page.locator(
      'button.style-emotion-option:is(:has-text("formel"), :has-text("decontracte"), :has-text("professionnel"), :has-text("neutre"), :has-text("chaleureux"), :has-text("legerement_positif"))'
    )
    await expect(sliderButtons).toHaveCount(0)

    // Labels slider legacy (sur un contrôle actif, pas un texte d'aide ailleurs)
    await expect(
      page.locator('label.pillar-field-label:has-text("Niveau d\'émotion")')
    ).toHaveCount(0)
    await expect(
      page.locator('label.pillar-field-label:has-text("Formalité")')
    ).toHaveCount(0)
  })
})
