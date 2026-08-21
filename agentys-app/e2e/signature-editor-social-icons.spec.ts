/**
 * Signature editor — Gmail-style social icons must render in a horizontal row.
 *
 * Regression guard for the "signature shows badly in Settings" bug (2026-06):
 * Tailwind Preflight resets <img>/<svg> to `display: block`, which stacks the
 * social icons (Facebook / Instagram / web) vertically instead of letting them
 * flow in a row inside their container. Every signature surface reverts this to
 * `display: inline` in index.css — but `.sig-editor` (the Settings → Signature
 * modal editor) had been left off that list AND carried its own explicit
 * `display: block`, so the editor preview stacked the icons even though the
 * actual sent email (.nm-signature-footer) rendered them correctly.
 *
 * This MUST be an e2e test: Tailwind Preflight and the CSS cascade are only
 * applied in a real browser, so jsdom/vitest can't observe the bug.
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'
const API_LOCALHOST = 'http://localhost:5050'
// In dev, API_URL='' (config.ts) → the app calls relative /api/* through the
// Vite proxy on localhost:1420. Must intercept this origin too, not just :5050.
const API_VITE = 'http://localhost:1420'

// 1×1 transparent PNG — loads instantly with no network, scales to the inline
// width/height so each icon gets a real layout box.
const PX =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='

// The three icons live on ONE line: a newline between them would break onto
// separate lines under the editor's `white-space: pre-wrap`, confounding the
// "are they stacked?" check. So we never want the row to depend on display.
const SOCIAL_ROW =
  '<div class="sig-test-socials">' +
  `<a href="https://facebook.com/x"><img class="sig-test-icon" alt="Facebook" src="${PX}" style="width:24px;height:24px"></a>` +
  `<a href="https://instagram.com/x"><img class="sig-test-icon" alt="Instagram" src="${PX}" style="width:24px;height:24px"></a>` +
  `<a href="https://example.com"><img class="sig-test-icon" alt="Web" src="${PX}" style="width:24px;height:24px"></a>` +
  '</div>'

// Gmail-style signature: photo-left / text-right two-column table, then the
// inline social-icon row beneath the text (mirrors Karine's real signature).
const SIGNATURE_HTML =
  '<table cellpadding="0" cellspacing="0" border="0"><tr>' +
  `<td style="vertical-align:top;padding-right:12px"><img alt="photo" src="${PX}" style="width:64px;height:64px"></td>` +
  '<td style="vertical-align:top">' +
  '<div><strong>Karine Morel</strong></div>' +
  '<div>www.example.com</div>' +
  SOCIAL_ROW +
  '</td></tr></table>'

async function setupSignatureAccount(page: Page) {
  await setupBaseMocks(page)
  const body = JSON.stringify({
    current_account_id: '1',
    accounts: [{
      id: '1',
      email: 'karine@example.com',
      provider: 'gmail',
      status: 'active',
      signature: 'Karine Morel',
      signature_html: SIGNATURE_HTML,
      has_signature: true,
    }],
  })
  const handler = (route: import('@playwright/test').Route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body })
  // SignatureModal loads via fetchAccounts() → GET /api/accounts. Registered
  // AFTER setupBaseMocks so it wins (Playwright routes are LIFO). Covers all
  // three origins because dev proxies relative /api/* through localhost:1420.
  await page.route(
    (url) =>
      url.pathname === '/api/accounts' &&
      (url.origin === API || url.origin === API_LOCALHOST || url.origin === API_VITE),
    handler,
  )
  // Bibliothèque multi-signatures : le modal ouvre désormais sur une LISTE
  // (GET /api/accounts/<id>/signatures, seedée côté backend depuis la
  // signature legacy du compte) — l'éditeur s'atteint en cliquant l'entrée.
  const libraryBody = JSON.stringify({
    signatures: [{
      id: 'sig_seed',
      name: 'Signature 1',
      html: SIGNATURE_HTML,
      text: 'Karine Morel',
      is_default: true,
    }],
    default_id: 'sig_seed',
  })
  await page.route(
    (url) =>
      url.pathname === '/api/accounts/1/signatures' &&
      (url.origin === API || url.origin === API_LOCALHOST || url.origin === API_VITE),
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: libraryBody }),
  )
}

async function openSignatureEditor(page: Page) {
  await page.locator('[data-testid="nav-settings"]').click()
  await page.locator('[data-testid="settings-modal"]').waitFor({ state: 'visible', timeout: 10000 })
  // Default Settings section is "compte" → the Signature link is visible.
  await page.locator('.settings-link-btn').filter({ hasText: 'Signature' }).click()
  // Vue liste d'abord : entrer dans l'éditeur via l'entrée seedée.
  await page.locator('[data-testid="sig-list-item"]').first().click()
  await page.locator('.sig-editor').waitFor({ state: 'visible', timeout: 10000 })
  // Editor content is injected in an effect once the account load resolves.
  await page.locator('.sig-editor img.sig-test-icon').first().waitFor({ state: 'visible', timeout: 10000 })
}

test.describe('Signature editor — social icons render in a row (not stacked)', () => {
  test.beforeEach(async ({ page }) => {
    await setupSignatureAccount(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openSignatureEditor(page)
  })

  test('social icons are not display:block (Tailwind Preflight reverted)', async ({ page }) => {
    const icons = page.locator('.sig-editor img.sig-test-icon')
    await expect(icons).toHaveCount(3)
    for (let i = 0; i < 3; i++) {
      const display = await icons.nth(i).evaluate((el) => getComputedStyle(el).display)
      expect(display, `icon ${i} should not be block — block stacks the icon row vertically`).not.toBe('block')
    }
  })

  test('the three social icons share one horizontal row', async ({ page }) => {
    const icons = page.locator('.sig-editor img.sig-test-icon')
    const boxes: { x: number; y: number; width: number; height: number }[] = []
    for (let i = 0; i < 3; i++) {
      const b = await icons.nth(i).boundingBox()
      expect(b, `icon ${i} should have a layout box`).not.toBeNull()
      boxes.push(b!)
    }

    // Same row → vertical positions cluster within less than one icon height.
    // Stacked (display:block) would put each icon ~24px+ below the previous.
    const ys = boxes.map((b) => b.y)
    const verticalSpread = Math.max(...ys) - Math.min(...ys)
    expect(
      verticalSpread,
      `icons span ${verticalSpread.toFixed(1)}px vertically — a row should be ~0, stacked would be ≥24px`,
    ).toBeLessThan(12)

    // Laid left-to-right.
    expect(boxes[1].x, 'icon 2 should sit to the right of icon 1').toBeGreaterThan(boxes[0].x)
    expect(boxes[2].x, 'icon 3 should sit to the right of icon 2').toBeGreaterThan(boxes[1].x)
  })
})
