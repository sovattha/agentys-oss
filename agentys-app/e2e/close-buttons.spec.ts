/**
 * Close / Icon Buttons — Visibility & Regression E2E Tests
 *
 * Root cause fixed: global `button { padding: 12px 20px; box-sizing: border-box }`
 * was crushing icon content to 0px on any button with fixed width+height but no
 * explicit `padding: 0`. This file guards against regressions.
 *
 * Assertions per button:
 *   1. padding = 0px (content area not crushed)
 *   2. color is not transparent / not white-on-white
 *   3. clicking closes the modal
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'
import { mockEmailDetails } from './support/fixtures/mock-data'

const API = 'http://127.0.0.1:5050'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Inject a minimal modal into the DOM for CSS-only tests (modals that require
 * complex app state to open naturally).
 */
async function injectModal(
  page: Page,
  opts: {
    overlayClass: string
    modalClass: string
    headerClass: string
    btnClass: string
    btnContent?: string
    /** extra inline style on the modal */
    modalStyle?: string
  },
) {
  const { overlayClass, modalClass, headerClass, btnClass, btnContent = '×', modalStyle = '' } = opts
  await page.evaluate(
    ({ overlayClass, modalClass, headerClass, btnClass, btnContent, modalStyle }) => {
      const overlay = document.createElement('div')
      overlay.className = overlayClass
      overlay.style.cssText =
        'position:fixed;inset:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:9999'

      const modal = document.createElement('div')
      modal.className = modalClass
      modal.style.cssText = `background:white;border-radius:12px;min-width:280px;overflow:hidden;${modalStyle}`

      const header = document.createElement('div')
      header.className = headerClass
      header.style.cssText =
        'display:flex;justify-content:space-between;align-items:center;padding:16px 20px'

      const title = document.createElement('h2')
      title.textContent = 'Test modal'
      title.style.margin = '0'

      const closeBtn = document.createElement('button')
      closeBtn.className = btnClass
      closeBtn.innerHTML = btnContent
      closeBtn.addEventListener('click', () => overlay.remove())

      header.appendChild(title)
      header.appendChild(closeBtn)
      modal.appendChild(header)
      overlay.appendChild(modal)
      document.body.appendChild(overlay)
    },
    { overlayClass, modalClass, headerClass, btnClass, btnContent, modalStyle },
  )
}

/**
 * Core assertion: the button must have:
 * - padding: 0px (not crushed by global button rule)
 * - a non-white, non-transparent computed color
 * - clicking removes the modal from view
 */
async function assertIconButton(page: Page, btnSelector: string, modalLocator: import('@playwright/test').Locator) {
  const btn = page.locator(btnSelector).first()
  await expect(btn).toBeVisible({ timeout: 5000 })

  // 1. Padding must be 0 — global `button { padding: 12px 20px }` must be overridden
  const padding = await btn.evaluate((el) => {
    const s = window.getComputedStyle(el)
    return {
      top: s.paddingTop,
      right: s.paddingRight,
      bottom: s.paddingBottom,
      left: s.paddingLeft,
    }
  })
  expect(padding.top, `${btnSelector} paddingTop must be 0`).toBe('0px')
  expect(padding.bottom, `${btnSelector} paddingBottom must be 0`).toBe('0px')

  // 2. Color must be visible (not white, not fully transparent)
  const color = await btn.evaluate((el) => window.getComputedStyle(el).color)
  // color is something like "rgb(55, 65, 81)" — must not be white rgb(255,255,255)
  expect(color, `${btnSelector} color must not be white`).not.toBe('rgb(255, 255, 255)')
  expect(color, `${btnSelector} color must not be rgba(0,0,0,0)`).not.toBe('rgba(0, 0, 0, 0)')

  // 3. Click closes the modal
  await btn.click()
  await expect(modalLocator).not.toBeVisible({ timeout: 2000 })
}

// ---------------------------------------------------------------------------
// Mock helpers
// ---------------------------------------------------------------------------

async function setupEmailDetailMocks(page: Page) {
  await setupBaseMocks(page)

  await page.route(
    (url) => url.origin === API && url.pathname.match(/^\/api\/emails\/[^/]+$/) !== null,
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockEmailDetails['email-1']),
      }),
  )
  await page.route(
    (url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/read$/) !== null,
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"success":true}' }),
  )
  await page.route(
    (url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/thread$/) !== null,
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ count: 1, emails: [mockEmailDetails['email-1']] }),
      }),
  )
  await page.route(
    (url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts/by-email'),
    (route) => route.fulfill({ status: 404, contentType: 'application/json', body: '{"error":"No draft"}' }),
  )
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('Boutons icônes — padding:0 + couleur visible (régression)', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('SignatureModal .sig-close — padding:0, couleur visible, ferme', async ({ page }) => {
    await injectModal(page, {
      overlayClass: 'sig-overlay-test',
      modalClass: 'sig-modal',
      headerClass: 'sig-header',
      btnClass: 'sig-close',
    })
    await assertIconButton(page, '.sig-close', page.locator('.sig-modal').first())
  })

  test('SendConfirmationModal .send-confirmation-modal-close — padding:0, couleur visible, ferme', async ({ page }) => {
    await injectModal(page, {
      overlayClass: 'scm-overlay-test',
      modalClass: 'send-confirmation-modal',
      headerClass: 'send-confirmation-modal-header',
      btnClass: 'send-confirmation-modal-close',
    })
    await assertIconButton(
      page,
      '.send-confirmation-modal-close',
      page.locator('.send-confirmation-modal').first(),
    )
  })

  test('RegenerateModal .regenerate-modal-close — padding, couleur visible, ferme', async ({ page }) => {
    await injectModal(page, {
      overlayClass: 'regen-overlay-test',
      modalClass: 'regenerate-modal',
      headerClass: 'regenerate-modal-header',
      btnClass: 'regenerate-modal-close',
    })
    await assertIconButton(
      page,
      '.regenerate-modal-close',
      page.locator('.regenerate-modal').first(),
    )
  })

  test('AutoReplyModal .autoreply-close — padding:0, couleur visible, ferme', async ({ page }) => {
    await injectModal(page, {
      overlayClass: 'ar-overlay-test',
      modalClass: 'autoreply-modal',
      headerClass: 'autoreply-modal-header',
      btnClass: 'autoreply-close',
    })
    await assertIconButton(page, '.autoreply-close', page.locator('.autoreply-modal').first())
  })

  test('ShareSnippetDialog .share-dialog-close — padding, couleur visible, ferme', async ({ page }) => {
    await injectModal(page, {
      overlayClass: 'sd-overlay-test',
      modalClass: 'share-dialog',
      headerClass: 'share-dialog-header',
      btnClass: 'share-dialog-close',
    })
    await assertIconButton(page, '.share-dialog-close', page.locator('.share-dialog').first())
  })

  test('SpecialtyDetailModal .spdm-close — padding:0, couleur visible, ferme', async ({ page }) => {
    await injectModal(page, {
      overlayClass: 'spdm-overlay-test',
      modalClass: 'spdm-modal',
      headerClass: 'spdm-header',
      btnClass: 'spdm-close',
    })
    await assertIconButton(page, '.spdm-close', page.locator('.spdm-modal').first())
  })
})

test.describe('Boutons icônes — flux naturels', () => {
  test('EmailDetailModal .email-detail-close — padding:0, couleur visible, ferme', async ({ page }) => {
    await setupEmailDetailMocks(page)
    await page.goto('/')
    await waitForAppReady(page)

    await page.locator('[data-testid="email-item"]').first().click()
    // Inline mode renders .email-detail-inline (not .email-detail-content)
    const modal = page.locator('.email-detail-inline, .email-detail-content').first()
    await expect(modal).toBeVisible({ timeout: 10000 })

    await assertIconButton(page, '.email-detail-close', modal)
  })
})

test.describe('CSS global — audit régression padding boutons icônes', () => {
  /**
   * This test injects all known icon-button classes and verifies padding is 0.
   * Catches any future button that regresses back to the global padding:12px 20px.
   */
  test('Tous les boutons icônes connus ont padding: 0px', async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)

    // Inject one button per class into a test container
    const classes = [
      'sig-close',
      'autoreply-close',
      'clean-inbox-close',
      'regenerate-modal-close',
      'send-confirmation-modal-close',
      'email-detail-close',
      'share-dialog-close',
      'ssc-close',
      'spdm-close',
      'close-button',
      'df2-exit-btn',
      'newsletters-close',
      'subscriptions-close',
      'recap-close',
      'ash-close',
      'calendar-close-btn',
      'cg-close-btn',
      'fdp-nav',
      'snippet-icon-btn',
      'snippet-nav-btn',
      'gmail-header-btn',
      'gmail-icon-btn',
    ]

    await page.evaluate((classes) => {
      const container = document.createElement('div')
      container.id = 'padding-audit-container'
      container.style.cssText = 'position:fixed;top:-9999px;left:-9999px;'
      classes.forEach((cls) => {
        const btn = document.createElement('button')
        btn.className = cls
        btn.textContent = '×'
        container.appendChild(btn)
      })
      document.body.appendChild(container)
    }, classes)

    const results = await page.evaluate((classes) => {
      return classes.map((cls) => {
        const btn = document.querySelector(`#padding-audit-container .${cls}`) as HTMLElement | null
        if (!btn) return { cls, found: false, paddingTop: null, paddingBottom: null }
        const s = window.getComputedStyle(btn)
        return { cls, found: true, paddingTop: s.paddingTop, paddingBottom: s.paddingBottom }
      })
    }, classes)

    const failures = results.filter(
      (r) => !r.found || r.paddingTop !== '0px' || r.paddingBottom !== '0px',
    )

    if (failures.length > 0) {
      const msg = failures
        .map((f) => `  .${f.cls}: found=${f.found} paddingTop=${f.paddingTop} paddingBottom=${f.paddingBottom}`)
        .join('\n')
      throw new Error(`Boutons icônes avec padding non-zéro (contenu écrasé) :\n${msg}`)
    }
  })
})
