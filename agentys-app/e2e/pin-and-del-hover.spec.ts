/**
 * Pin / Unpin + Del hover delete — Regression tests
 *
 * Bug 1 — Unpin:
 *   - pinned-header had height 0 → no visible "Épinglés" section
 *   - no pin icon on pinned rows → unpin not discoverable
 *
 * Bug 2 — Del hover desyncs selectedEmailIdRef:
 *   - per-item keydown handler deleted email but never updated App's ref
 *   - second Del press targeted null (global handler found nothing)
 *
 * Fixes verified:
 *   - the pinned-section header takes no visible space (height 0)
 *   - pinned rows carry the `.pinned` class; unpin is offered via the context menu
 *     (the old hover `.pin-active-btn` was removed in commit 5c4a9e1a)
 *   - Delete key handled exclusively by global App handler (getHoveredEmail() first)
 */

import { test, expect, Page, Route } from '@playwright/test'
import { setupBaseMocks } from './support/fixtures/setup'
import { mockEmails } from './support/fixtures/mock-data'
import { AppPage } from './pages/AppPage'

// The e2e app runs under `yarn dev` (Vite), so config.ts resolves API_URL to ''
// and every /api/* request hits the page origin — http://localhost:1420. Per-spec
// mocks must cover that origin too: registering only on 127.0.0.1:5050 leaves the
// app's real requests falling through to the generic setupBaseMocks routes (static
// list / catch-all), so the stateful delete/archive handlers below never run and
// an optimistically-removed email is resurrected by the next refetch.
const API = 'http://127.0.0.1:5050'
const API_LOCALHOST = 'http://localhost:5050'
const API_VITE = 'http://localhost:1420'
const EMAIL_ITEM = '[data-testid="email-item"]'

/** Register a route handler on every origin the app may address. */
async function routeAll(page: Page, path: string, handler: (route: Route) => void) {
  await page.route(`${API}${path}`, handler)
  await page.route(`${API_LOCALHOST}${path}`, handler)
  await page.route(`${API_VITE}${path}`, handler)
}

// ─── Email fixtures ───────────────────────────────────────────────────────────

const PINNED_EMAIL = {
  ...mockEmails[0],
  id: 'pin-test-001',
  subject: 'Email épinglé test',
  is_read: false,
  conversation_id: 'pin-conv-1',
}

const EMAIL_A = {
  ...mockEmails[0],
  id: 'del-test-001',
  subject: 'Email Del A',
  is_read: false,
  conversation_id: 'del-conv-1',
}

const EMAIL_B = {
  ...mockEmails[0],
  id: 'del-test-002',
  subject: 'Email Del B',
  is_read: false,
  conversation_id: 'del-conv-2',
}

const EMAIL_C = {
  ...mockEmails[0],
  id: 'del-test-003',
  subject: 'Email Del C',
  is_read: false,
  conversation_id: 'del-conv-3',
}

function inbox(...emails: typeof mockEmails) {
  return { count: emails.length, emails, has_more: false, source: 'mock' }
}

/**
 * Fulfill an /api/emails request honoring the `offset`/`limit` query params.
 * EmailList.loadMore ends infinite-scroll on `response.emails.length === 0` — it
 * never reads `has_more` — so a mock that returns the full set for every offset
 * triggers an unbounded loadMore storm whose in-flight `[A,B]` responses keep
 * re-appending optimistically-deleted rows (the source of the hover Del/E
 * flakiness). Slicing by offset makes pagination stop after the first empty page.
 */
function fulfillEmailPage(route: Route, all: typeof mockEmails) {
  const params = new URL(route.request().url()).searchParams
  const offset = Number(params.get('offset') ?? '0')
  const limit = Number(params.get('limit') ?? '50')
  route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(inbox(...all.slice(offset, offset + limit))),
  })
}

// ─── Setup helpers ────────────────────────────────────────────────────────────

/** Setup with one pinned email. localStorage key = 'agentys_pinned'. */
async function setupPinMocks(page: Page) {
  await page.addInitScript(() => {
    if ('indexedDB' in window) indexedDB.deleteDatabase('agentys_cache')
    // Correct key used by usePinned.ts
    localStorage.setItem('agentys_pinned', JSON.stringify(['pin-test-001']))
  })

  await setupBaseMocks(page, {
    emailsResponse: inbox(PINNED_EMAIL),
  })

  // Override emails route to always return the pinned email
  await routeAll(page, '/api/emails?*', (route) => fulfillEmailPage(route, [PINNED_EMAIL]))
}

/** Setup with three regular emails; delete endpoint is stateful. */
async function setupDelMocks3(page: Page) {
  const deleted = new Set<string>()

  await page.addInitScript(() => {
    if ('indexedDB' in window) indexedDB.deleteDatabase('agentys_cache')
  })

  await setupBaseMocks(page, {
    emailsResponse: inbox(EMAIL_A, EMAIL_B, EMAIL_C),
  })

  await routeAll(page, '/api/emails?*', (route) =>
    fulfillEmailPage(route, [EMAIL_A, EMAIL_B, EMAIL_C].filter(e => !deleted.has(e.id))))

  for (const email of [EMAIL_A, EMAIL_B, EMAIL_C]) {
    await routeAll(page, `/api/emails/${email.id}/delete`, (route) => {
      deleted.add(email.id)
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, message: 'deleted' }),
      })
    })
  }
}

/** Setup with two regular emails; delete endpoint is stateful. */
async function setupDelMocks(page: Page) {
  const deleted = new Set<string>()

  await page.addInitScript(() => {
    if ('indexedDB' in window) indexedDB.deleteDatabase('agentys_cache')
  })

  await setupBaseMocks(page, {
    emailsResponse: inbox(EMAIL_A, EMAIL_B),
  })

  // Stateful email list — deleted emails are excluded from subsequent fetches
  await routeAll(page, '/api/emails?*', (route) =>
    fulfillEmailPage(route, [EMAIL_A, EMAIL_B].filter(e => !deleted.has(e.id))))

  // Delete endpoint — marks email as deleted for subsequent fetches
  for (const email of [EMAIL_A, EMAIL_B]) {
    await routeAll(page, `/api/emails/${email.id}/delete`, (route) => {
      deleted.add(email.id)
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, message: 'deleted' }),
      })
    })
  }
}

/** Setup with two regular emails; archive endpoint is stateful. */
async function setupArchiveMocks(page: Page) {
  const archived = new Set<string>()

  await page.addInitScript(() => {
    if ('indexedDB' in window) indexedDB.deleteDatabase('agentys_cache')
  })

  await setupBaseMocks(page, {
    emailsResponse: inbox(EMAIL_A, EMAIL_B),
  })

  // Stateful email list — archived emails are excluded from inbox
  await routeAll(page, '/api/emails?*', (route) =>
    fulfillEmailPage(route, [EMAIL_A, EMAIL_B].filter(e => !archived.has(e.id))))

  // Archive endpoint — marks email as archived
  for (const email of [EMAIL_A, EMAIL_B]) {
    await routeAll(page, `/api/emails/${email.id}/archive`, (route) => {
      archived.add(email.id)
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, message: 'archived' }),
      })
    })
  }
}

/** Setup with three regular emails; archive endpoint is stateful (for rapid E). */
async function setupArchiveMocks3(page: Page) {
  const archived = new Set<string>()

  await page.addInitScript(() => {
    if ('indexedDB' in window) indexedDB.deleteDatabase('agentys_cache')
  })

  await setupBaseMocks(page, {
    emailsResponse: inbox(EMAIL_A, EMAIL_B, EMAIL_C),
  })

  await routeAll(page, '/api/emails?*', (route) =>
    fulfillEmailPage(route, [EMAIL_A, EMAIL_B, EMAIL_C].filter(e => !archived.has(e.id))))

  for (const email of [EMAIL_A, EMAIL_B, EMAIL_C]) {
    await routeAll(page, `/api/emails/${email.id}/archive`, (route) => {
      archived.add(email.id)
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, message: 'archived' }),
      })
    })
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// Bug 1 — Pinned section header + unpin button
// ═════════════════════════════════════════════════════════════════════════════

test.describe('Bug 1 — Pinned section header + unpin button', () => {
  test('l\'email épinglé apparaît en tête de liste', async ({ page }) => {
    await setupPinMocks(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    // Wait for email list to render — pinned email must be present
    const item = page.locator(EMAIL_ITEM).filter({ hasText: 'Email épinglé test' }).first()
    await expect(item).toBeVisible({ timeout: 5000 })
  })

  test('le header épinglé n\'est pas affiché (hauteur 0)', async ({ page }) => {
    await setupPinMocks(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    const item = page.locator(EMAIL_ITEM).first()
    await expect(item).toBeVisible({ timeout: 5000 })

    // Header is intentionally hidden (height 0, not in the visible flow)
    const pinnedHeader = page.locator('.email-pinned-header')
    const count = await pinnedHeader.count()
    if (count > 0) {
      const box = await pinnedHeader.boundingBox()
      // If present in DOM, must not take visible space
      expect(!box || box.height === 0).toBeTruthy()
    }
  })

  test('un email épinglé porte la classe .pinned sur sa rangée', async ({ page }) => {
    await setupPinMocks(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    const pinnedItem = page.locator(EMAIL_ITEM).filter({ hasText: 'Email épinglé test' }).first()
    await expect(pinnedItem).toBeVisible({ timeout: 5000 })

    // The hover `.pin-active-btn` was replaced by a context-menu unpin (commit
    // 5c4a9e1a). The pinned state is now surfaced as a `.pinned` class on the row.
    await expect(pinnedItem).toHaveClass(/pinned/, { timeout: 3000 })
  })

  test('un email non épinglé ne porte pas la classe .pinned', async ({ page }) => {
    await page.addInitScript(() => {
      if ('indexedDB' in window) indexedDB.deleteDatabase('agentys_cache')
      localStorage.removeItem('agentys_pinned')
    })
    await setupBaseMocks(page, { emailsResponse: inbox(EMAIL_A) })
    await routeAll(page, '/api/emails?*', (route) => fulfillEmailPage(route, [EMAIL_A]))

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    const item = page.locator(EMAIL_ITEM).first()
    await expect(item).toBeVisible({ timeout: 5000 })

    // Counterpart to the pinned-row test: a non-pinned row must not carry .pinned.
    await expect(item).not.toHaveClass(/pinned/)
  })

  test('right-click sur email épinglé propose "Unpin" dans le menu contextuel', async ({ page }) => {
    await setupPinMocks(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    const pinnedItem = page.locator(EMAIL_ITEM).filter({ hasText: 'Email épinglé test' }).first()
    await expect(pinnedItem).toBeVisible({ timeout: 5000 })

    await pinnedItem.click({ button: 'right', force: true })

    const contextMenu = page.locator('.email-context-menu')
    await expect(contextMenu).toBeVisible({ timeout: 2000 })

    // Context menu should include an unpin/pin option (the text depends on isPinned → t('unpin'))
    const pinMenuItem = contextMenu.locator('button').filter({ hasText: /pin|épingle/i })
    await expect(pinMenuItem.first()).toBeVisible({ timeout: 2000 })
  })
})

// ═════════════════════════════════════════════════════════════════════════════
// Unpin via context menu — end-to-end assertion
// ═════════════════════════════════════════════════════════════════════════════

test.describe('Unpin via context menu', () => {
  test('désépingler via le menu contextuel retire l\'email des épinglés', async ({ page }) => {
    const consoleErrors: string[] = []
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text())
    })

    await setupPinMocks(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    const pinnedItem = page.locator(EMAIL_ITEM).filter({ hasText: 'Email épinglé test' }).first()
    await expect(pinnedItem).toBeVisible({ timeout: 5000 })

    // Verify the email has .pinned class before unpinning
    await expect(pinnedItem).toHaveClass(/pinned/, { timeout: 3000 })

    // Right-click to open context menu
    await pinnedItem.click({ button: 'right', force: true })
    const contextMenu = page.locator('.email-context-menu')
    await expect(contextMenu).toBeVisible({ timeout: 2000 })

    // Click the unpin button
    const unpinBtn = contextMenu.locator('button').filter({ hasText: /désépingl|unpin/i })
    await expect(unpinBtn.first()).toBeVisible({ timeout: 2000 })
    await unpinBtn.first().click()

    // Context menu should close
    await expect(contextMenu).not.toBeVisible({ timeout: 2000 })

    // Assert: localStorage agentys_pinned should now be []
    const pinnedStorage = await page.evaluate(() => {
      const raw = localStorage.getItem('agentys_pinned')
      return raw ? JSON.parse(raw) : null
    })
    expect(pinnedStorage).toEqual([])

    // Assert: the email row should no longer have .pinned class
    await expect(pinnedItem).not.toHaveClass(/pinned/, { timeout: 3000 })

    // Assert: no [data-testid="email-item"].pinned visible
    const pinnedRows = page.locator('[data-testid="email-item"].pinned')
    await expect(pinnedRows).toHaveCount(0, { timeout: 2000 })

    // Surface any JS errors
    expect(consoleErrors).toEqual([])
  })
})

// ═════════════════════════════════════════════════════════════════════════════
// Bug 2 — Del key hover: selection state stays in sync
// ═════════════════════════════════════════════════════════════════════════════

test.describe('Bug 2 — Del hover : sélection reste synchronisée', () => {
  test('Del sur email survolé supprime l\'email (premier appui)', async ({ page }) => {
    await setupDelMocks(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    const items = page.locator(EMAIL_ITEM)
    await expect(items).toHaveCount(2, { timeout: 5000 })

    const emailA = items.filter({ hasText: 'Email Del A' }).first()
    await emailA.hover({ force: true })
    await page.waitForLoadState('domcontentloaded')
    await page.keyboard.press('Delete')

    await expect(emailA).not.toBeVisible({ timeout: 3000 })
  })

  test('Del fonctionne deux fois de suite sans désynchronisation', async ({ page }) => {
    await setupDelMocks(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    const items = page.locator(EMAIL_ITEM)
    await expect(items).toHaveCount(2, { timeout: 5000 })

    const emailA = items.filter({ hasText: 'Email Del A' }).first()
    const emailB = items.filter({ hasText: 'Email Del B' }).first()

    // First Del — hover email A
    await emailA.hover({ force: true })
    await page.waitForLoadState('domcontentloaded')
    await page.keyboard.press('Delete')
    await expect(emailA).not.toBeVisible({ timeout: 3000 })

    // Second Del — hover email B (previously broken: App's ref was null after first)
    await emailB.hover({ force: true })
    await page.waitForLoadState('domcontentloaded')
    await page.keyboard.press('Delete')
    await expect(emailB).not.toBeVisible({ timeout: 3000 })

    await expect(items).toHaveCount(0, { timeout: 2000 })
  })

  test('Del rapide — 2ème appui immédiat (<260ms) supprime le bon email', async ({ page }) => {
    // Regression: handleOptimisticDelete has a 260ms animation delay before removing the
    // email from state. During that window, emailRef.current still points to the animating
    // email (already in pendingOps), so a second immediate Del was silently ignored.
    // Fix: getEmailIdUnderCursor() via elementFromPoint resolves the correct target.
    await setupDelMocks3(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    const items = page.locator(EMAIL_ITEM)
    await expect(items).toHaveCount(3, { timeout: 5000 })

    const emailA = items.filter({ hasText: 'Email Del A' }).first()
    await emailA.hover({ force: true })
    await page.waitForLoadState('domcontentloaded')

    // Two Del presses in rapid succession (no waiting between them)
    await page.keyboard.press('Delete')
    await page.keyboard.press('Delete') // fired before 260ms animation completes

    // Both A and B must be gone eventually
    await expect(items.filter({ hasText: 'Email Del A' })).not.toBeVisible({ timeout: 3000 })
    await expect(items.filter({ hasText: 'Email Del B' })).not.toBeVisible({ timeout: 3000 })
    // C must survive
    await expect(items.filter({ hasText: 'Email Del C' })).toBeVisible({ timeout: 1000 })
  })

  test('Del rapide — 3 appuis consécutifs suppriment 3 emails', async ({ page }) => {
    await setupDelMocks3(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    const items = page.locator(EMAIL_ITEM)
    await expect(items).toHaveCount(3, { timeout: 5000 })

    const emailA = items.filter({ hasText: 'Email Del A' }).first()
    await emailA.hover({ force: true })
    await page.waitForLoadState('domcontentloaded')

    await page.keyboard.press('Delete')
    await page.keyboard.press('Delete')
    await page.keyboard.press('Delete')

    await expect(items).toHaveCount(0, { timeout: 4000 })
  })

  test('Del via clavier (J+Del) supprime l\'email sélectionné', async ({ page }) => {
    await setupDelMocks(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    const items = page.locator(EMAIL_ITEM)
    await expect(items).toHaveCount(2, { timeout: 5000 })

    // Click the list area to give focus, then J to keyboard-select first email
    await items.first().click()
    await page.waitForLoadState('domcontentloaded')
    await page.keyboard.press('Delete')

    await expect(items).toHaveCount(1, { timeout: 3000 })
  })

  test('survol prend priorité sur sélection clavier pour Del', async ({ page }) => {
    await setupDelMocks(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    const items = page.locator(EMAIL_ITEM)
    await expect(items).toHaveCount(2, { timeout: 5000 })

    // Select email A via click
    const emailA = items.filter({ hasText: 'Email Del A' }).first()
    await emailA.click()
    await page.waitForLoadState('domcontentloaded')

    // Then hover email B → Del should delete B (hovered), not A
    const emailB = items.filter({ hasText: 'Email Del B' }).first()
    await emailB.hover({ force: true })
    await page.waitForLoadState('domcontentloaded')
    await page.keyboard.press('Delete')

    await expect(emailB).not.toBeVisible({ timeout: 3000 })
    await expect(emailA).toBeVisible({ timeout: 1000 })
  })

  test('Del en survol ne doit PAS ouvrir le panneau de détail', async ({ page }) => {
    // Regression: before the fix, handleShortcutDelete called handleEmailSelect(next)
    // even when no email was keyboard-selected, opening the detail panel unexpectedly.
    await setupDelMocks(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    const items = page.locator(EMAIL_ITEM)
    await expect(items).toHaveCount(2, { timeout: 5000 })

    // Hover only — no click / keyboard selection
    const emailA = items.filter({ hasText: 'Email Del A' }).first()
    await emailA.hover({ force: true })
    await page.waitForLoadState('domcontentloaded')
    await page.keyboard.press('Delete')

    // Email should be removed
    await expect(emailA).not.toBeVisible({ timeout: 3000 })

    // Detail panel must NOT have opened
    const detailPanel = page.locator('.email-detail-panel, [data-testid="email-detail"]')
    await expect(detailPanel).toHaveCount(0)
  })
})

// ═════════════════════════════════════════════════════════════════════════════
// E key — Archive on hover and keyboard selection
// ═════════════════════════════════════════════════════════════════════════════

test.describe('E key — Archiver au survol et par sélection clavier', () => {
  test('E sur email survolé archive l\'email', async ({ page }) => {
    await setupArchiveMocks(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    const items = page.locator(EMAIL_ITEM)
    await expect(items).toHaveCount(2, { timeout: 5000 })

    const emailA = items.filter({ hasText: 'Email Del A' }).first()
    await emailA.hover({ force: true })
    await page.waitForLoadState('domcontentloaded')
    await page.keyboard.press('e')

    await expect(emailA).not.toBeVisible({ timeout: 3000 })
    // B should remain
    await expect(items.filter({ hasText: 'Email Del B' })).toBeVisible({ timeout: 1000 })
  })

  test('E fonctionne deux fois de suite en survol', async ({ page }) => {
    await setupArchiveMocks(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    const items = page.locator(EMAIL_ITEM)
    await expect(items).toHaveCount(2, { timeout: 5000 })

    const emailA = items.filter({ hasText: 'Email Del A' }).first()
    const emailB = items.filter({ hasText: 'Email Del B' }).first()

    await emailA.hover({ force: true })
    await page.waitForLoadState('domcontentloaded')
    await page.keyboard.press('e')
    await expect(emailA).not.toBeVisible({ timeout: 3000 })

    await emailB.hover({ force: true })
    await page.waitForLoadState('domcontentloaded')
    await page.keyboard.press('e')
    await expect(emailB).not.toBeVisible({ timeout: 3000 })

    await expect(items).toHaveCount(0, { timeout: 2000 })
  })

  test('E rapide — 2ème appui immédiat (<260ms) archive le bon email', async ({ page }) => {
    // Regression (#914): handleOptimisticArchive has a 260ms slide-out before the row
    // leaves state. During that window the still-animating row sits under the cursor;
    // archive used to never mark it pending-removal, so getEmailIdUnderCursor() re-hit
    // it and pendingOps deduped the 2nd press to a no-op — only the first email archived.
    // Fix mirrors delete: markDeletePending + setLastPendingDeleteId so the next row wins.
    await setupArchiveMocks3(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    const items = page.locator(EMAIL_ITEM)
    await expect(items).toHaveCount(3, { timeout: 5000 })

    const emailA = items.filter({ hasText: 'Email Del A' }).first()
    await emailA.hover({ force: true })
    await page.waitForLoadState('domcontentloaded')

    // Two E presses in rapid succession (2nd fires before the 260ms animation completes)
    await page.keyboard.press('e')
    await page.keyboard.press('e')

    await expect(items.filter({ hasText: 'Email Del A' })).not.toBeVisible({ timeout: 3000 })
    await expect(items.filter({ hasText: 'Email Del B' })).not.toBeVisible({ timeout: 3000 })
    // C must survive
    await expect(items.filter({ hasText: 'Email Del C' })).toBeVisible({ timeout: 1000 })
  })

  test('E rapide — 3 appuis consécutifs archivent 3 emails', async ({ page }) => {
    await setupArchiveMocks3(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    const items = page.locator(EMAIL_ITEM)
    await expect(items).toHaveCount(3, { timeout: 5000 })

    const emailA = items.filter({ hasText: 'Email Del A' }).first()
    await emailA.hover({ force: true })
    await page.waitForLoadState('domcontentloaded')

    await page.keyboard.press('e')
    await page.keyboard.press('e')
    await page.keyboard.press('e')

    await expect(items).toHaveCount(0, { timeout: 4000 })
  })

  test('E via clavier (click + E) archive l\'email sélectionné', async ({ page }) => {
    await setupArchiveMocks(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    const items = page.locator(EMAIL_ITEM)
    await expect(items).toHaveCount(2, { timeout: 5000 })

    // Click to select, then E to archive
    await items.first().click()
    await page.waitForLoadState('domcontentloaded')
    await page.keyboard.press('e')

    await expect(items).toHaveCount(1, { timeout: 3000 })
  })

  test('E en survol ne doit PAS ouvrir le panneau de détail', async ({ page }) => {
    await setupArchiveMocks(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    const items = page.locator(EMAIL_ITEM)
    await expect(items).toHaveCount(2, { timeout: 5000 })

    // Hover only — no click / keyboard selection
    const emailA = items.filter({ hasText: 'Email Del A' }).first()
    await emailA.hover({ force: true })
    await page.waitForLoadState('domcontentloaded')
    await page.keyboard.press('e')

    await expect(emailA).not.toBeVisible({ timeout: 3000 })

    // Detail panel must NOT have opened
    const detailPanel = page.locator('.email-detail-panel, [data-testid="email-detail"]')
    await expect(detailPanel).toHaveCount(0)
  })

  test('survol prend priorité sur sélection clavier pour E', async ({ page }) => {
    await setupArchiveMocks(page)
    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    const items = page.locator(EMAIL_ITEM)
    await expect(items).toHaveCount(2, { timeout: 5000 })

    // Select email A via click
    const emailA = items.filter({ hasText: 'Email Del A' }).first()
    await emailA.click()
    await page.waitForLoadState('domcontentloaded')

    // Hover email B → E should archive B (hovered), not A
    const emailB = items.filter({ hasText: 'Email Del B' }).first()
    await emailB.hover({ force: true })
    await page.waitForLoadState('domcontentloaded')
    await page.keyboard.press('e')

    await expect(emailB).not.toBeVisible({ timeout: 3000 })
    await expect(emailA).toBeVisible({ timeout: 1000 })
  })
})
