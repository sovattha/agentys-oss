/**
 * ConnectionBanner — « reconnecting… » doit être vrai.
 *
 * Avant : la bannière n'armait aucune sonde ; elle ne disparaissait que si une
 * AUTRE requête réussissait par hasard. Sur un écran sans polling actif elle
 * restait affichée pour toujours, même backend revenu.
 *
 * Maintenant : useConnectionHealth sonde /api/ping (backoff 2s → 30s) tant que
 * la bannière est visible, et se ferme seule dès que le ping répond 200.
 */

import { test, expect } from '@playwright/test'
import { isApiRoute, setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

test.describe('ConnectionBanner — reconnexion automatique', () => {
  test('la bannière se ferme seule quand le backend redevient joignable', async ({ page }) => {
    await setupBaseMocks(page, {
      emailsResponse: { emails: [], has_more: false, source: 'mock' },
    })

    // Ping contrôlable : up au boot (l'app doit se charger), down ensuite.
    let pingUp = true
    await page.route(
      (url) => isApiRoute(url) && url.pathname === '/api/ping',
      (route) => route.fulfill({
        status: pingUp ? 200 : 503,
        contentType: 'application/json',
        body: pingUp ? JSON.stringify({ status: 'ok', version: 'e2e' }) : JSON.stringify({ error: 'down' }),
      }),
    )

    await page.goto('/')
    await waitForAppReady(page)

    // Panne : le backend tombe, la couche api signale deux échecs.
    pingUp = false
    await page.evaluate(() => {
      window.dispatchEvent(new Event('api:connection-lost'))
      window.dispatchEvent(new Event('api:connection-lost'))
    })
    const banner = page.locator('[data-testid="connection-banner"]')
    await expect(banner).toBeVisible({ timeout: 3_000 })

    // Backend toujours down : la sonde échoue, la bannière reste affichée.
    await page.waitForTimeout(3_000)
    await expect(banner).toBeVisible()

    // Le backend revient : la prochaine sonde (backoff ≤ 8s) doit fermer la
    // bannière SANS clic sur Retry.
    pingUp = true
    await expect(banner).toBeHidden({ timeout: 15_000 })
  })
})
