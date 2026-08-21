/**
 * Visual Audit E2E — Comprehensive screenshots of every major view.
 * Run: npx playwright test e2e/visual-audit.spec.ts --headed
 * Screenshots saved to: e2e/screenshots/
 */

import { test, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'
import { mockEmails, mockEmailDetails, mockEmailThread } from './support/fixtures/mock-data'

const API = 'http://127.0.0.1:5050'

// Rich mock data for realistic screenshots
async function setupRichMocks(page: Page) {
  await setupBaseMocks(page, {
    emailsResponse: { count: mockEmails.length, emails: mockEmails },
  })

  // Email detail
  await page.route((url) => url.origin === API && /\/api\/emails\/[^/]+$/.test(url.pathname), (route) => {
    const id = route.request().url().split('/api/emails/')[1]?.split('?')[0]
    const detail = (mockEmailDetails as Record<string, unknown>)[id] || {
      ...mockEmails[0],
      id,
      body: '<p>Corps de l\'email de test.</p>',
      to: ['vous@example.com'],
      cc: [],
      attachments: [],
    }
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(detail) })
  })

  // Thread
  await page.route((url) => url.origin === API && url.pathname.includes('/thread'), (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ messages: mockEmailThread['conv-2'] || [] }),
    })
  })

  // Pending drafts with realistic data
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts'), (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          drafts: [
            {
              id: 'pd-1',
              email_id: 'email-5',
              subject: 'Re: Demande de devis urgent',
              sender: 'jean.lefevre@client.com',
              sender_name: 'Jean Lefèvre',
              draft_body: '<p>Bonjour M. Lefèvre, voici notre devis...</p>',
              status: 'ready',
              classification: { tier: 'STANDARD', reason: 'Business email requiring full response' },
              created_at: new Date().toISOString(),
              smart_suggestions: ['Oui, je vous envoie ça', 'Merci, nous y travaillons'],
            },
          ],
          pending_count: 1,
        }),
      })
    } else {
      route.continue()
    }
  })

  // Labels with realistic data
  await page.route((url) => url.origin === API && url.pathname === '/api/labels', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        labels: [
          { name: 'Action', color: '#dc2626', description: 'Emails nécessitant une action', is_default: true, is_favorite: true, created_at: '2026-01-01', rules: [] },
          { name: 'Waiting', color: '#eab308', description: 'Emails en attente', is_default: true, is_favorite: true, created_at: '2026-01-01', rules: [] },
          { name: 'FYI', color: '#3b82f6', description: 'Pour information', is_default: true, is_favorite: true, created_at: '2026-01-01', rules: [] },
          { name: 'Noise', color: '#6b7280', description: 'Bruit', is_default: true, is_favorite: false, created_at: '2026-01-01', rules: [] },
          { name: 'Projet Alpha', color: '#22c55e', description: 'Tous les emails projet Alpha', is_default: false, is_favorite: true, is_project: true, created_at: '2026-02-01', rules: [] },
        ],
        counts: { Action: 3, Waiting: 2, FYI: 4, Noise: 1, 'Projet Alpha': 2 },
      }),
    })
  })

  // Settings
  await page.route(`${API}/api/settings`, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        auto_archive: false,
        auto_followup: true,
        hide_noise: false,
        language: 'fr',
        theme: 'light',
      }),
    })
  })

  // Learning/style
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/learning'), (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ categories: [] }),
    })
  })

  // Contacts
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/contacts'), (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { email: 'marie.dupont@example.com', name: 'Marie Dupont', frequency: 15 },
        { email: 'pierre.martin@example.com', name: 'Pierre Martin', frequency: 10 },
      ]),
    })
  })
}

function ssPath(name: string) {
  return `e2e/screenshots/${name}.png`
}

test.describe('Visual Audit — Full App', () => {
  test.beforeEach(async ({ page }) => {
    await setupRichMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  // ═══════════════════════════════════════════════════════════════
  // 1. INBOX & SIDEBAR
  // ═══════════════════════════════════════════════════════════════
  test('01 — Inbox view (main)', async ({ page }) => {
    await page.waitForLoadState('domcontentloaded')
    await page.screenshot({ path: ssPath('01-inbox-main'), fullPage: true })
  })

  test('02 — Sidebar navigation', async ({ page }) => {
    const sidebar = page.locator('.sidebar, [data-testid="sidebar"], nav').first()
    await sidebar.screenshot({ path: ssPath('02-sidebar') })
  })

  // ═══════════════════════════════════════════════════════════════
  // 2. EMAIL DETAIL
  // ═══════════════════════════════════════════════════════════════
  test('03 — Email detail modal', async ({ page }) => {
    const firstEmail = page.locator('.email-row, [data-testid^="email-item"]').first()
    if (await firstEmail.isVisible()) {
      await firstEmail.click()
      await page.waitForLoadState('domcontentloaded')
      await page.screenshot({ path: ssPath('03-email-detail'), fullPage: true })
    }
  })

  // ═══════════════════════════════════════════════════════════════
  // 3. COMPOSE / NEW MESSAGE
  // ═══════════════════════════════════════════════════════════════
  test('04 — New message modal', async ({ page }) => {
    // Try keyboard shortcut first, then button
    await page.keyboard.press('Meta+n')

    const modal = page.locator('.nm-modal, [data-testid="new-message-modal"]').first()
    if (!await modal.isVisible({ timeout: 1000 }).catch(() => false)) {
      const btn = page.locator('[data-testid="nav-compose"], [aria-label*="nouveau"], [aria-label*="Nouveau"]').first()
      if (await btn.isVisible()) await btn.click()
    }

    await page.screenshot({ path: ssPath('04-new-message'), fullPage: true })
  })

  // ═══════════════════════════════════════════════════════════════
  // 4. SETTINGS
  // ═══════════════════════════════════════════════════════════════
  test('05 — Settings modal', async ({ page }) => {
    const settingsBtn = page.locator('[data-testid="nav-settings"]')
    if (await settingsBtn.isVisible()) {
      await settingsBtn.click()
      await page.waitForLoadState('domcontentloaded')
      await page.screenshot({ path: ssPath('05-settings'), fullPage: true })

      // Scroll through settings tabs if they exist
      const tabs = page.locator('.settings-sidebar-item, .settings-tab')
      const count = await tabs.count()
      for (let i = 1; i < Math.min(count, 6); i++) {
        await tabs.nth(i).click()
        await page.waitForLoadState('domcontentloaded')
        await page.screenshot({ path: ssPath(`05-settings-tab-${i}`), fullPage: true })
      }
    }
  })

  // ═══════════════════════════════════════════════════════════════
  // 5. FOLDERS: Sent, Archives, Trash, Spam
  // ═══════════════════════════════════════════════════════════════
  test('06 — Sent folder', async ({ page }) => {
    const sent = page.locator('[data-testid="nav-sent"]')
    if (await sent.isVisible()) {
      await sent.click()
      await page.waitForLoadState('domcontentloaded')
      await page.screenshot({ path: ssPath('06-sent-folder'), fullPage: true })
    }
  })

  test('07 — Archives folder', async ({ page }) => {
    const archives = page.locator('[data-testid="nav-archives"], [data-testid="nav-archive"]')
    if (await archives.isVisible().catch(() => false)) {
      await archives.click()
      await page.waitForLoadState('domcontentloaded')
      await page.screenshot({ path: ssPath('07-archives-folder'), fullPage: true })
    }
  })

  test('08 — Trash folder', async ({ page }) => {
    const trash = page.locator('[data-testid="nav-trash"]')
    if (await trash.isVisible().catch(() => false)) {
      await trash.click()
      await page.waitForLoadState('domcontentloaded')
      await page.screenshot({ path: ssPath('08-trash-folder'), fullPage: true })
    }
  })

  test('09 — Spam folder', async ({ page }) => {
    const spam = page.locator('[data-testid="nav-spam"]')
    if (await spam.isVisible().catch(() => false)) {
      await spam.click()
      await page.waitForLoadState('domcontentloaded')
      await page.screenshot({ path: ssPath('09-spam-folder'), fullPage: true })
    }
  })

  // ═══════════════════════════════════════════════════════════════
  // 6. PENDING DRAFTS
  // ═══════════════════════════════════════════════════════════════
  test('10 — Pending drafts list', async ({ page }) => {
    const draftsNav = page.locator('[data-testid="nav-drafts"], [data-testid="nav-pending"]')
    if (await draftsNav.isVisible().catch(() => false)) {
      await draftsNav.click()
      await page.waitForLoadState('domcontentloaded')
      await page.screenshot({ path: ssPath('10-pending-drafts'), fullPage: true })
    }
  })

  // ═══════════════════════════════════════════════════════════════
  // 7. SEARCH
  // ═══════════════════════════════════════════════════════════════
  test('11 — Search panel', async ({ page }) => {
    const searchBtn = page.locator('[data-testid="nav-search"], [data-testid="search-trigger"], .search-input, input[placeholder*="echerch"]').first()
    if (await searchBtn.isVisible().catch(() => false)) {
      await searchBtn.click()
      await page.waitForLoadState('domcontentloaded')
      await page.screenshot({ path: ssPath('11-search-panel'), fullPage: true })

      // Type a query
      const input = page.locator('input[type="search"], input[placeholder*="echerch"], .search-input input').first()
      if (await input.isVisible().catch(() => false)) {
        await input.fill('rapport')
        await page.waitForLoadState('domcontentloaded')
        await page.screenshot({ path: ssPath('11-search-results'), fullPage: true })
      }
    }
  })

  // ═══════════════════════════════════════════════════════════════
  // 8. CALENDAR
  // ═══════════════════════════════════════════════════════════════
  test('12 — Calendar view', async ({ page }) => {
    const calBtn = page.locator('[data-testid="nav-calendar"]')
    if (await calBtn.isVisible().catch(() => false)) {
      await calBtn.click()
      await page.waitForLoadState('domcontentloaded')
      await page.screenshot({ path: ssPath('12-calendar'), fullPage: true })
    }
  })

  // ═══════════════════════════════════════════════════════════════
  // 9. LABEL LIBRARY
  // ═══════════════════════════════════════════════════════════════
  test('13 — Label library', async ({ page }) => {
    const labelBtn = page.locator('[data-testid="nav-labels"], [data-testid="open-label-library"]')
    if (await labelBtn.isVisible().catch(() => false)) {
      await labelBtn.click()
      await page.waitForLoadState('domcontentloaded')
      await page.screenshot({ path: ssPath('13-label-library'), fullPage: true })
    }
  })

  // ═══════════════════════════════════════════════════════════════
  // 10. COMMAND PALETTE
  // ═══════════════════════════════════════════════════════════════
  test('14 — Command palette', async ({ page }) => {
    await page.keyboard.press('Meta+k')
    const palette = page.locator('.command-palette, [data-testid="command-palette"]').first()
    if (await palette.isVisible().catch(() => false)) {
      await page.screenshot({ path: ssPath('14-command-palette'), fullPage: true })
    }
  })

  // ═══════════════════════════════════════════════════════════════
  // 11. KEYBOARD SHORTCUTS HELP
  // ═══════════════════════════════════════════════════════════════
  test('15 — Shortcuts help', async ({ page }) => {
    await page.keyboard.press('?')
    await page.waitForLoadState('domcontentloaded')
    await page.screenshot({ path: ssPath('15-shortcuts-help'), fullPage: true })
  })

  // ═══════════════════════════════════════════════════════════════
  // 12. SUPPORT PANEL
  // ═══════════════════════════════════════════════════════════════
  test('16 — Support panel', async ({ page }) => {
    const supportBtn = page.locator('[data-testid="nav-support"], [data-testid="open-support"]')
    if (await supportBtn.isVisible().catch(() => false)) {
      await supportBtn.click()
      await page.waitForLoadState('domcontentloaded')
      await page.screenshot({ path: ssPath('16-support-panel'), fullPage: true })
    }
  })

  // ═══════════════════════════════════════════════════════════════
  // 13. RESPONSIVE — Narrow viewport
  // ═══════════════════════════════════════════════════════════════
  test('17 — Narrow viewport (mobile-like)', async ({ page }) => {
    await page.setViewportSize({ width: 480, height: 800 })
    await page.waitForLoadState('domcontentloaded')
    await page.screenshot({ path: ssPath('17-narrow-viewport'), fullPage: true })
  })

  // ═══════════════════════════════════════════════════════════════
  // 14. EMPTY STATES
  // ═══════════════════════════════════════════════════════════════
  test('18 — Empty inbox state', async ({ page }) => {
    // Re-mock with empty emails
    await page.route(`${API}/api/emails?*`, (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ count: 0, emails: [] }),
      })
    })
    await page.route(`${API}/api/emails`, (route) => {
      if (route.request().url().includes('?')) return
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ count: 0, emails: [] }),
      })
    })
    await page.route(`${API}/api/init`, (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          emails: { emails: [], has_more: false, source: 'mock' },
          label_counts: { counts: {}, total: 0 },
          pending_drafts: { drafts: [], pending_count: 0 },
          accounts: [{ id: 1, email: 'test@example.com', status: 'active' }],
        }),
      })
    })
    await page.reload()
    await waitForAppReady(page)
    await page.screenshot({ path: ssPath('18-empty-inbox'), fullPage: true })
  })

  // ═══════════════════════════════════════════════════════════════
  // 15. CONTEXT MENU (right-click email)
  // ═══════════════════════════════════════════════════════════════
  test('19 — Context menu on email', async ({ page }) => {
    const firstEmail = page.locator('.email-row, [data-testid^="email-item"]').first()
    if (await firstEmail.isVisible()) {
      await firstEmail.click({ button: 'right' })
      await page.waitForLoadState('domcontentloaded')
      await page.screenshot({ path: ssPath('19-context-menu'), fullPage: true })
    }
  })
})
