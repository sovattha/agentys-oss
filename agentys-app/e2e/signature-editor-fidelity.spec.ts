/**
 * Signature editor — imported provider HTML must render faithfully.
 *
 * Regression guard for the "signature importée de Hotmail n'est pas
 * identique" bug (2026-06-09, Karine):
 *
 * 1. The app-wide `a` rule (index.css) paints every anchor in the teal
 *    accent at font-weight 500 with no underline. An Outlook signature whose
 *    mailto anchor carries no inline color (Outlook autolink often wraps only
 *    PART of the address) showed up as a green "info@i" fragment in the
 *    editor. `.sig-editor a` / `.sig-preview a` now revert to standard
 *    browser link rendering.
 *
 * 2. `.sig-editor` used `white-space: pre-wrap`, so the raw newlines Outlook
 *    puts between block tags each rendered as a phantom empty line — the
 *    imported signature looked double-spaced vs the original.
 *
 * This MUST be an e2e test: the CSS cascade (global `a` rule vs component
 * rules) and white-space layout only exist in a real browser.
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'
const API_LOCALHOST = 'http://localhost:5050'
const API_VITE = 'http://localhost:1420'

// Outlook-shaped signature: raw newlines between the block divs (exactly what
// the sent-items extractor returns) and a mailto anchor with NO inline color
// that wraps only part of the address (Outlook autolink artifact).
const SIGNATURE_HTML =
  '<div class="sig-test-name">Karine Morel, ND</div>\n' +
  '<div class="sig-test-title">Co-fondatrice Institut Vitale</div>\n' +
  '<div class="sig-test-mail"><a href="mailto:info@institutvitale.com">info@i</a>nstitutvitale.com</div>'

async function setupSignatureAccount(page: Page) {
  await setupBaseMocks(page)
  const body = JSON.stringify({
    current_account_id: '1',
    accounts: [{
      id: '1',
      email: 'karine@example.com',
      provider: 'outlook',
      status: 'active',
      signature: 'Karine Morel, ND',
      signature_html: SIGNATURE_HTML,
      has_signature: true,
    }],
  })
  const handler = (route: import('@playwright/test').Route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body })
  await page.route(
    (url) =>
      url.pathname === '/api/accounts' &&
      (url.origin === API || url.origin === API_LOCALHOST || url.origin === API_VITE),
    handler,
  )
  // Bibliothèque multi-signatures : le modal ouvre désormais sur une LISTE —
  // l'éditeur s'atteint en cliquant l'entrée seedée.
  const libraryBody = JSON.stringify({
    signatures: [{
      id: 'sig_seed',
      name: 'Signature 1',
      html: SIGNATURE_HTML,
      text: 'Karine Morel, ND',
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
  await page.locator('.settings-link-btn').filter({ hasText: 'Signature' }).click()
  // Vue liste d'abord : entrer dans l'éditeur via l'entrée seedée.
  await page.locator('[data-testid="sig-list-item"]').first().click()
  await page.locator('.sig-editor').waitFor({ state: 'visible', timeout: 10000 })
  await page.locator('.sig-editor .sig-test-name').waitFor({ state: 'visible', timeout: 10000 })
}

test.describe('Signature editor — provider HTML renders faithfully', () => {
  test.beforeEach(async ({ page }) => {
    await setupSignatureAccount(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openSignatureEditor(page)
  })

  test('signature mailto link is not skinned with the app accent', async ({ page }) => {
    const link = page.locator('.sig-editor a')
    await expect(link).toHaveCount(1)

    const { linkColor, accentColor, fontWeight, decoration } = await link.evaluate((el) => {
      const cs = getComputedStyle(el)
      // Resolve the accent token against the same element so both colors are
      // in the same computed format (rgb(...)).
      const probe = document.createElement('span')
      probe.style.color = 'var(--accent-primary)'
      el.appendChild(probe)
      const accent = getComputedStyle(probe).color
      probe.remove()
      return {
        linkColor: cs.color,
        accentColor: accent,
        fontWeight: cs.fontWeight,
        decoration: cs.textDecorationLine,
      }
    })

    expect(linkColor, 'anchor must not inherit the app accent (teal) skin').not.toBe(accentColor)
    expect(fontWeight, 'anchor must not get the app-wide 500 weight').not.toBe('500')
    expect(decoration, 'anchor keeps standard email-client underline').toContain('underline')
  })

  test('newlines between block tags do not render as phantom blank lines', async ({ page }) => {
    const nameBox = await page.locator('.sig-editor .sig-test-name').boundingBox()
    const titleBox = await page.locator('.sig-editor .sig-test-title').boundingBox()
    const mailBox = await page.locator('.sig-editor .sig-test-mail').boundingBox()
    expect(nameBox).not.toBeNull()
    expect(titleBox).not.toBeNull()
    expect(mailBox).not.toBeNull()

    // Editor: 13.5px font × 1.65 line-height ≈ 22.3px per line. Consecutive
    // lines must sit one line apart; pre-wrap rendered the inter-tag \n as an
    // extra empty line, doubling the gap to ~45px.
    const lineGap1 = titleBox!.y - nameBox!.y
    const lineGap2 = mailBox!.y - titleBox!.y
    expect(lineGap1, `name→title gap ${lineGap1.toFixed(1)}px — a phantom blank line doubles it`).toBeLessThan(32)
    expect(lineGap2, `title→mail gap ${lineGap2.toFixed(1)}px — a phantom blank line doubles it`).toBeLessThan(32)
  })
})
