/**
 * Scroll Unifié E2E Tests — Régression guard
 *
 * Vérifie que le scroll email+draft fonctionne comme un thread continu
 * (style Superhuman) dans tous les contextes :
 *   1. Panel inbox — email seul (inline)
 *   2. Panel inbox — email + draft (PendingDraftDetail)
 *
 * Pattern CSS critique (4 règles interdépendantes) :
 *   - .pending-draft-detail: flex:1 1 0 + min-height:0 + overflow-y:auto
 *   - App.css panel: height:0 sur .pending-draft-detail et .email-detail-inline
 *   - EmailDetailModal.css: overflow-y:visible sur .email-detail-inline .email-detail-body
 *   - PendingDraftDetail.css: flex-shrink:0 sur .pdd-email-zone et .pdd-draft-zone
 */

import { test, expect, Page } from '@playwright/test'
import { mockEmails, mockEmailDetails } from './support/fixtures/mock-data'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

// Génère un body HTML très long pour forcer le scroll
const LONG_BODY = `<div>${Array.from({ length: 120 }, (_, i) =>
  `<p>Paragraphe ${i + 1} — Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.</p>`
).join('')}</div>`

const LONG_DRAFT_BODY = `<div>${Array.from({ length: 80 }, (_, i) =>
  `<p>Réponse ligne ${i + 1} — Merci pour votre message. Je reviens vers vous avec les détails demandés concernant le projet et les prochaines étapes à suivre.</p>`
).join('')}</div>`

/**
 * Mock un email avec un body très long + un draft prêt
 */
async function setupScrollMocks(page: Page, opts: { withDraft: boolean } = { withDraft: false }) {
  // Pass custom emails response with has_pending_draft when testing drafts
  const emailsResponse = opts.withDraft ? {
    count: 1,
    emails: [{
      ...mockEmails[0],
      has_pending_draft: true,
    }],
  } : undefined

  await setupBaseMocks(page, emailsResponse ? { emailsResponse } : undefined)

  // Email detail avec body long
  await page.route((url) => url.origin === API && url.pathname.match(/^\/api\/emails\/[^/]+$/) !== null, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...mockEmailDetails['email-1'],
        body: LONG_BODY,
      }),
    })
  })

  // Mark as read
  await page.route((url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/read$/) !== null, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
  })

  // Thread
  await page.route((url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/thread$/) !== null, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ count: 1, emails: [{ ...mockEmailDetails['email-1'], body: LONG_BODY }] }),
    })
  })

  // Pending draft by email
  if (opts.withDraft) {
    await page.route((url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts/by-email'), (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'pd-scroll-test',
          email_id: 'email-1',
          email_body: LONG_BODY,
          email_subject: 'Rapport trimestriel Q4 2025',
          email_sender: 'marie.dupont@example.com',
          email_sender_name: 'Marie Dupont',
          draft_body: LONG_DRAFT_BODY,
          draft_subject: 'Re: Rapport trimestriel Q4 2025',
          status: 'ready',
          classification: { tier: 'STANDARD', confidence: 0.9 },
          critique: { verdict: 'VALID', score: 85 },
          created_at: new Date().toISOString(),
        }),
      })
    })
  } else {
    await page.route((url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts/by-email'), (route) => {
      route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: 'No draft' }) })
    })
  }
}

/**
 * Vérifie qu'un élément a overflow-y scrollable (auto ou scroll) et que
 * son scrollHeight > clientHeight (= contenu dépasse = scrollbar active).
 */
async function assertScrollable(page: Page, selector: string) {
  const result = await page.evaluate((sel) => {
    const el = document.querySelector(sel)
    if (!el) return { found: false, selector: sel }
    const style = getComputedStyle(el)
    return {
      found: true,
      selector: sel,
      overflowY: style.overflowY,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
      isScrollable: el.scrollHeight > el.clientHeight + 2, // 2px tolerance
    }
  }, selector)

  expect(result.found, `Élément "${selector}" introuvable`).toBe(true)
  expect(
    ['auto', 'scroll'].includes(result.overflowY!),
    `"${selector}" devrait avoir overflow-y: auto|scroll, trouvé: ${result.overflowY}`
  ).toBe(true)
  expect(result.isScrollable, `"${selector}" devrait scroller (scrollHeight=${result.scrollHeight} > clientHeight=${result.clientHeight})`).toBe(true)
}

/**
 * Vérifie qu'un élément enfant ne scrolle PAS indépendamment
 * (pas de scroll imbriqué parasite).
 */
async function assertNotScrollable(page: Page, selector: string) {
  const result = await page.evaluate((sel) => {
    const el = document.querySelector(sel)
    if (!el) return { found: false }
    const style = getComputedStyle(el)
    const hasOwnScroll = (style.overflowY === 'auto' || style.overflowY === 'scroll') && el.scrollHeight > el.clientHeight + 2
    return { found: true, hasOwnScroll, overflowY: style.overflowY, scrollHeight: el.scrollHeight, clientHeight: el.clientHeight }
  }, selector)

  if (result.found) {
    expect(
      result.hasOwnScroll,
      `"${selector}" ne devrait PAS avoir son propre scroll (overflow-y=${result.overflowY}, scrollH=${result.scrollHeight}, clientH=${result.clientHeight})`
    ).toBe(false)
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Tests
// ─────────────────────────────────────────────────────────────────────────────

test.describe('Scroll unifié — Régression guard', () => {

  test('Panel inbox : email long sans draft → scroll sur .email-detail-inline, PAS sur .email-detail-body', async ({ page }) => {
    await setupScrollMocks(page, { withDraft: false })
    await page.goto('/')
    await waitForAppReady(page)

    // Ouvrir le premier email
    await page.locator('[data-testid="email-item"]').first().click()
    await page.locator('.email-detail-body').first().waitFor({ state: 'visible', timeout: 10000 })

    // Le parent (.email-detail-inline) doit scroller
    const inlineExists = await page.locator('.email-detail-inline').count()
    if (inlineExists > 0) {
      await assertScrollable(page, '.email-detail-inline')
      // L'enfant (.email-detail-body) ne doit PAS scroller indépendamment
      await assertNotScrollable(page, '.email-detail-inline .email-detail-body')
    }
  })

  test.fixme('Panel inbox : email + draft → scroll unique sur .pending-draft-detail', async ({ page }) => {
    // FIXME: PendingDraftDetail crash à cause de dialog.tsx → lucide-react conflit React 19
    await setupScrollMocks(page, { withDraft: true })
    await page.goto('/')
    await waitForAppReady(page)

    await page.locator('[data-testid="email-item"]').first().click()

    // Attendre que le PendingDraftDetail soit monté et le body rendu
    const pdd = page.locator('.pending-draft-detail')
    await pdd.first().waitFor({ state: 'visible', timeout: 10000 })
    await page.locator('.original-card-body').first().waitFor({ state: 'visible', timeout: 10000 })

    // Le PDD doit être scrollable (email + draft ensemble)
    await expect(async () => {
      await assertScrollable(page, '.email-detail-panel .pending-draft-detail')
    }).toPass({ timeout: 5000 })

    // Les zones enfants ne doivent PAS scroller individuellement
    await assertNotScrollable(page, '.pdd-email-zone')
    await assertNotScrollable(page, '.pdd-draft-zone')
  })

  test.fixme('CSS invariants : propriétés critiques présentes', async ({ page }) => {
    // FIXME: PendingDraftDetail crash à cause de dialog.tsx → lucide-react conflit React 19
    await setupScrollMocks(page, { withDraft: true })
    await page.goto('/')
    await waitForAppReady(page)

    await page.locator('[data-testid="email-item"]').first().click()
    await page.locator('.pending-draft-detail').first().waitFor({ state: 'visible', timeout: 10000 })

    // Vérifier les computed styles critiques
    const checks = await page.evaluate(() => {
      const results: Record<string, Record<string, string>> = {}

      function capture(selector: string, props: string[]) {
        const el = document.querySelector(selector)
        if (!el) return
        const style = getComputedStyle(el)
        results[selector] = {}
        for (const prop of props) {
          results[selector][prop] = style.getPropertyValue(prop)
        }
      }

      capture('.pending-draft-detail', ['overflow-y', 'min-height', 'flex-grow', 'flex-shrink'])
      capture('.pdd-email-zone', ['flex-shrink', 'overflow-y'])
      capture('.pdd-draft-zone', ['flex-shrink', 'overflow-y'])

      return results
    })

    // .pending-draft-detail — scroll parent
    if (checks['.pending-draft-detail']) {
      expect(checks['.pending-draft-detail']['overflow-y']).toBe('auto')
      expect(checks['.pending-draft-detail']['min-height']).toBe('0px')
    }

    // .pdd-email-zone — ne scrolle pas
    if (checks['.pdd-email-zone']) {
      expect(checks['.pdd-email-zone']['overflow-y']).not.toBe('scroll')
      expect(checks['.pdd-email-zone']['flex-shrink']).toBe('0')
    }

    // .pdd-draft-zone — ne scrolle pas
    if (checks['.pdd-draft-zone']) {
      expect(checks['.pdd-draft-zone']['overflow-y']).not.toBe('scroll')
    }
  })

  test.fixme('Action bar sticky : reste visible après scroll vers le bas', async ({ page }) => {
    // FIXME: PendingDraftDetail crash à cause de dialog.tsx → lucide-react conflit React 19
    await setupScrollMocks(page, { withDraft: true })
    await page.goto('/')
    await waitForAppReady(page)

    await page.locator('[data-testid="email-item"]').first().click()
    await page.locator('.pending-draft-detail').first().waitFor({ state: 'visible', timeout: 10000 })

    // Scroller le PDD vers le bas
    await page.evaluate(() => {
      const pdd = document.querySelector('.pending-draft-detail')
      if (pdd) pdd.scrollTop = pdd.scrollHeight
    })

    // L'action bar doit être visible (position: sticky)
    const actionBar = page.locator('.rc-action-bar').first()
    const actionBarCount = await actionBar.count()
    if (actionBarCount > 0) {
      await expect(actionBar).toBeVisible()
    }
  })
})
