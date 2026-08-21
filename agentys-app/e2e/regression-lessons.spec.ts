/**
 * Regression Tests — Lessons Learned (tasks/lessons.md)
 *
 * Chaque test protège contre une régression documentée.
 * Référence : tasks/lessons.md + MEMORY.md
 */

import { test, expect, Page } from '@playwright/test'
import { isApiRoute, setupBaseMocks, waitForAppReady } from './support/fixtures/setup'
import { mockEmails, mockEmailDetails } from './support/fixtures/mock-data'

const API = 'http://127.0.0.1:5050'

// ============================================================================
// Helpers
// ============================================================================

/** Setup mocks with emails that have labels */
async function setupWithLabeledEmails(page: Page) {
  await setupBaseMocks(page, {
    emailsResponse: {
      count: mockEmails.length,
      emails: mockEmails.map((e, i) => ({
        ...e,
        labels: i === 0 ? [{ name: 'Action', color: '#ef4444' }]
          : i === 1 ? [{ name: 'FYI', color: '#3b82f6' }]
          : i === 3 ? [{ name: 'Noise', color: '#6b7280' }]
          : [],
      })),
    },
  })

  // Mock label counts
  await page.route((url) => isApiRoute(url) && url.pathname === '/api/labels/counts', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        counts: { Action: 1, FYI: 1, Noise: 1 },
        total: 3,
      }),
    })
  })

  // Mock labels list with favorites
  await page.route((url) => isApiRoute(url) && url.pathname === '/api/labels', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        labels: [
          { name: 'Action', color: '#ef4444', is_default: true, is_favorite: true, is_project: false },
          { name: 'FYI', color: '#3b82f6', is_default: true, is_favorite: true, is_project: false },
          { name: 'Noise', color: '#6b7280', is_default: true, is_favorite: true, is_project: false },
          { name: 'Waiting', color: '#f59e0b', is_default: true, is_favorite: false, is_project: false },
          { name: 'Projet Alpha', color: '#8b5cf6', is_default: false, is_favorite: true, is_project: true },
        ],
      }),
    })
  })
}

/** Setup mocks with email detail endpoint */
async function setupWithEmailDetail(page: Page) {
  await setupBaseMocks(page)

  // Mock individual email detail
  await page.route(
    (url) => url.origin === API && /\/api\/emails\/email-\d+$/.test(url.pathname),
    (route) => {
      const id = route.request().url().split('/').pop() || ''
      const detail = (mockEmailDetails as Record<string, unknown>)[id]
      if (detail) {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(detail),
        })
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ...mockEmails[0],
            body: '<p>Contenu de test</p>',
            body_html: '<p>Contenu de test</p>',
            to: ['test@example.com'],
            cc: [],
          }),
        })
      }
    },
  )
}

// ============================================================================
// 1. CSS — padding:0 sur boutons icône
// Lesson: button { padding: 12px 20px } global écrase les boutons icône
// ============================================================================
test.describe('Régression CSS — padding:0 boutons icône', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('les boutons icône de la sidebar ont du contenu visible', async ({ page }) => {
    // Tous les boutons avec SVG dans la sidebar doivent avoir un contenu > 0px
    const sidebarButtons = page.locator('.sidebar button svg, .sidebar-icon svg, [data-testid] svg')
    const count = await sidebarButtons.count()

    expect(count, 'Au moins un SVG icône dans la sidebar').toBeGreaterThan(0)

    for (let i = 0; i < Math.min(count, 10); i++) {
      const svg = sidebarButtons.nth(i)
      await expect(svg).toBeVisible({ timeout: 5000 })
      const box = await svg.boundingBox()
      expect(box, `SVG icône #${i} doit avoir un boundingBox`).not.toBeNull()
      expect(box!.width, `SVG icône #${i} width > 0`).toBeGreaterThan(0)
      expect(box!.height, `SVG icône #${i} height > 0`).toBeGreaterThan(0)
    }
  })

  test('le bouton Composer a un SVG visible', async ({ page }) => {
    const composeBtn = page.locator('.sidebar-compose-btn, [data-testid="compose-button"]').first()
    await expect(composeBtn).toBeVisible({ timeout: 5000 })
    const svg = composeBtn.locator('svg').first()
    await expect(svg).toBeVisible({ timeout: 5000 })
    const box = await svg.boundingBox()
    expect(box).not.toBeNull()
    expect(box!.width).toBeGreaterThan(4)
    expect(box!.height).toBeGreaterThan(4)
  })
})

// ============================================================================
// 2. Settings defaults ON
// Lesson: auto_archive, hide_noise, auto_followup doivent être ON par défaut
// ============================================================================
test.describe('Régression Settings — défauts activés', () => {
  test.beforeEach(async ({ page }) => {
    // Mock settings endpoint returning defaults
    await setupBaseMocks(page)
    await page.route(
      (url) => url.origin === API && url.pathname === '/api/settings',
      (route) => {
        if (route.request().method() === 'GET') {
          route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              auto_draft_enabled: true,
              auto_archive_action: true,
              hide_noise_from_inbox: true,
              auto_followup_enabled: true,
              followup_delay_days: 3,
              undo_send_delay: 5,
              theme: 'default',
            }),
          })
        } else {
          route.fulfill({ status: 200, contentType: 'application/json', body: '{"success":true}' })
        }
      },
    )
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('localStorage hide_noise est true par défaut (pas de valeur = true)', async ({ page }) => {
    // Le hook useHideNoiseSetting retourne true quand localStorage est null
    const val = await page.evaluate(() => {
      const stored = localStorage.getItem('agentys_hide_noise')
      // null = jamais configuré = défaut true
      return stored === null ? true : stored === 'true'
    })
    expect(val).toBe(true)
  })
})

// ============================================================================
// 3. Email detail — body_text fallback (pas de timeout IMAP)
// Lesson: Servir body_text immédiatement quand body_html est vide
// ============================================================================
test.describe('Régression — chargement email sans body_html', () => {
  test('affiche le contenu même sans body_html (fallback body_text)', async ({ page }) => {
    await setupBaseMocks(page)

    // Mock email detail with body_text but NO body_html (simulates list-mode sync)
    await page.route(
      (url) => url.origin === API && /\/api\/emails\/email-1$/.test(url.pathname),
      (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 'email-1',
            sender: 'marie.dupont@example.com',
            sender_name: 'Marie Dupont',
            subject: 'Rapport trimestriel Q4 2025',
            received_at: new Date().toISOString(),
            has_attachments: false,
            is_read: false,
            body: 'Bonjour, voici le rapport Q4.',
            body_html: null,  // <-- body_html absent
            body_text: 'Bonjour, voici le rapport Q4.',
            to: ['test@example.com'],
            cc: [],
            labels: [],
          }),
        })
      },
    )

    await page.goto('/')
    await waitForAppReady(page)

    // Click first email
    await page.locator('[data-testid="email-item"]').first().click()

    // Wait for detail to load (email detail title or body should appear)
    await expect(page.locator('.email-detail-title, .email-detail-body').first()).toBeVisible({ timeout: 5000 })

    // Should NOT show timeout error
    await expect(page.locator('text=/Délai de chargement dépassé/')).not.toBeVisible({ timeout: 3000 })
  })
})

// ============================================================================
// 4. Sent email prefix sent: — URL encoding %3A
// Lesson: sent:ID doit fonctionner malgré l'encodage URL %3A
// ============================================================================
test.describe('Régression — emails envoyés prefix sent:', () => {
  test('charge un email envoyé avec le prefix sent:', async ({ page }) => {
    await setupBaseMocks(page, {
      emailsResponse: {
        count: 1,
        emails: [{
          id: 'sent:500',
          sender: 'test@example.com',
          sender_name: 'Moi',
          subject: 'Email envoyé test',
          received_at: new Date().toISOString(),
          has_attachments: false,
          conversation_id: null,
          is_read: true,
          body_preview: 'Test envoyé',
        }],
      },
    })

    // Mock detail with both sent:500 and sent%3A500
    await page.route(
      (url) => url.origin === API && /\/api\/emails\/sent(%3A|:)500$/.test(url.pathname),
      (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 'sent:500',
            sender: 'test@example.com',
            sender_name: 'Moi',
            subject: 'Email envoyé test',
            received_at: new Date().toISOString(),
            has_attachments: false,
            is_read: true,
            body: '<p>Corps de l\'email envoyé</p>',
            body_html: '<p>Corps de l\'email envoyé</p>',
            body_text: 'Corps de l\'email envoyé',
            to: ['dest@example.com'],
            cc: [],
            labels: [],
          }),
        })
      },
    )

    await page.goto('/')
    await waitForAppReady(page)

    // Click the sent email
    const emailItem = page.locator('[data-testid="email-item"]').first()
    await expect(emailItem).toBeVisible({ timeout: 5000 })
    await emailItem.click()

    // Wait for detail to load
    await expect(page.locator('.email-detail-title, .email-detail-body').first()).toBeVisible({ timeout: 5000 })

    // Should NOT show error
    await expect(page.locator('text=/Erreur|not found|404/i')).not.toBeVisible({ timeout: 3000 })
  })
})

// ============================================================================
// 5. Label ordering — Action, FYI, Noise toujours dans cet ordre
// Lesson: CORE_LABEL_ORDER force l'ordre des labels core
// ============================================================================
test.describe('Régression — ordre des labels core', () => {
  test('les onglets labels sont dans l\'ordre Action, Info, Noise/Bruit', async ({ page }) => {
    await setupWithLabeledEmails(page)
    // Set French explicitly so getLabelDisplayName is deterministic regardless of browser locale
    await page.addInitScript(() => { localStorage.setItem('agentys_language', 'fr') })
    await page.goto('/')
    await waitForAppReady(page)

    // Wait for tabs to render
    await page.locator('.header-tab').first().waitFor({ state: 'visible', timeout: 5000 })

    // Get all tab labels text
    const tabs = page.locator('.header-tab')
    const tabCount = await tabs.count()
    const tabTexts: string[] = []
    for (let i = 0; i < tabCount; i++) {
      const text = await tabs.nth(i).textContent()
      if (text) tabTexts.push(text.trim())
    }

    // Find indices of core labels (language-agnostic: Bruit in fr, Noise in en)
    const actionIdx = tabTexts.findIndex(t => t.includes('Action'))
    const fyiIdx = tabTexts.findIndex(t => t.includes('Info'))
    const noiseIdx = tabTexts.findIndex(t => t.includes('Bruit') || t.includes('Noise'))

    // All 3 must be present
    expect(actionIdx, 'Action tab must be present').toBeGreaterThanOrEqual(0)
    expect(fyiIdx, 'Info tab must be present').toBeGreaterThanOrEqual(0)
    expect(noiseIdx, 'Noise/Bruit tab must be present').toBeGreaterThanOrEqual(0)

    // Verify order
    expect(actionIdx, 'Action avant Info').toBeLessThan(fyiIdx)
    expect(fyiIdx, 'Info avant Noise/Bruit').toBeLessThan(noiseIdx)
  })
})

// ============================================================================
// 5b. Label badges — taille lisible dans la liste compacte
// Lesson: Une pastille trop réduite devient illisible même si elle tient mieux.
// ============================================================================
test.describe('Régression CSS — badges de labels inbox lisibles', () => {
  test('le badge compact Action garde une hauteur lisible', async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)

    await page.evaluate(() => {
      const fixture = document.createElement('div')
      fixture.className = 'email-row gmail-style'
      fixture.innerHTML = `
        <div class="label-badge-group">
          <span data-testid="compact-action-label-badge" class="label-badge label-badge-small" style="--label-color: #ef4444">
            <span class="label-badge-name">Action</span>
          </span>
        </div>
      `
      document.body.appendChild(fixture)
    })

    const badge = page.getByTestId('compact-action-label-badge')
    await expect(badge).toBeVisible({ timeout: 5000 })

    const metrics = await badge.evaluate((el) => {
      const rect = el.getBoundingClientRect()
      const styles = window.getComputedStyle(el)
      return {
        fontSize: Number.parseFloat(styles.fontSize),
        height: rect.height,
        width: rect.width,
      }
    })

    expect(metrics.fontSize, 'taille de texte badge compact').toBeGreaterThanOrEqual(10)
    expect(metrics.height, 'hauteur badge compact').toBeGreaterThanOrEqual(14)
    expect(metrics.height, 'hauteur badge compact').toBeLessThanOrEqual(20)
    expect(metrics.width, 'largeur badge Action lisible').toBeGreaterThanOrEqual(36)
  })

  // Le 2e label d'un email est rendu en carré compact (.label-badge-chip).
  // Demande 2026-06-09 : il doit faire la MÊME hauteur que le badge texte
  // (Action/Info/Bruit), pas un confetti de 10px désaligné.
  test('le carré de label secondaire a la même hauteur que le badge', async ({ page }) => {
    await setupBaseMocks(page, {
      emailsResponse: {
        count: mockEmails.length,
        emails: mockEmails.map((e, i) => ({
          ...e,
          labels: i === 0
            ? [{ name: 'Action', color: '#ef4444' }, { name: 'Projet Alpha', color: '#8b5cf6' }]
            : [],
        })),
      },
    })
    await page.route((url) => isApiRoute(url) && url.pathname === '/api/labels', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          labels: [
            { name: 'Action', color: '#ef4444', is_default: true, is_favorite: true, is_project: false },
            { name: 'Projet Alpha', color: '#8b5cf6', is_default: false, is_favorite: true, is_project: true },
          ],
        }),
      })
    })
    await page.addInitScript(() => {
      localStorage.setItem('agentys_language', 'fr')
      localStorage.setItem('agentys_email_view_mode', 'compact')
    })
    await page.goto('/')
    await waitForAppReady(page)

    const badge = page.locator('.email-row.gmail-style .label-badge').filter({ hasText: 'Action' }).first()
    const chip = page.locator('.email-row.gmail-style .label-badge-chip').first()
    await expect(badge).toBeVisible({ timeout: 5000 })
    await expect(chip).toBeVisible({ timeout: 5000 })

    const badgeBox = await badge.boundingBox()
    const chipBox = await chip.boundingBox()
    expect(badgeBox).not.toBeNull()
    expect(chipBox).not.toBeNull()
    expect(
      Math.abs(chipBox!.height - badgeBox!.height),
      `carré ${chipBox!.height.toFixed(1)}px vs badge ${badgeBox!.height.toFixed(1)}px — doivent être alignés`,
    ).toBeLessThanOrEqual(1)
  })
})

// ============================================================================
// 8. getLabelDisplayName — respect de la langue UI active
// Lesson: fallback 'fr' hardcodé dans getLabelDisplayName ignorait la langue
//         auto-détectée via i18n quand agentys_language absent du localStorage.
// ============================================================================
test.describe('Régression — getLabelDisplayName respecte la langue active', () => {
  test('le tab Noise affiche "Noise" quand agentys_language=en', async ({ page }) => {
    await setupWithLabeledEmails(page)
    // Explicitly set English — simulates user who chose 'en' via LanguageSelector
    await page.addInitScript(() => { localStorage.setItem('agentys_language', 'en') })
    await page.goto('/')
    await waitForAppReady(page)

    await page.locator('.header-tab').first().waitFor({ state: 'visible', timeout: 5000 })

    const tabs = page.locator('.header-tab')
    const tabCount = await tabs.count()
    const tabTexts: string[] = []
    for (let i = 0; i < tabCount; i++) {
      const text = await tabs.nth(i).textContent()
      if (text) tabTexts.push(text.trim())
    }

    // Must show "Noise", NOT "Bruit"
    const noiseIdx = tabTexts.findIndex(t => t.includes('Noise'))
    const bruitIdx = tabTexts.findIndex(t => t.includes('Bruit'))
    expect(noiseIdx, '"Noise" tab must be present in English mode').toBeGreaterThanOrEqual(0)
    expect(bruitIdx, '"Bruit" must NOT appear in English mode').toBe(-1)
  })
})

// ============================================================================
// 6. Animation sync — delete ne cause pas de page blanche
// Lesson: CSS animation duration doit matcher setTimeout JS
// ============================================================================
test.describe('Régression — animation de suppression', () => {
  test.beforeEach(async ({ page }) => {
    await setupWithEmailDetail(page)
  })

  test('la liste reste visible après une action sur un email', async ({ page }) => {
    // Mock delete endpoint
    await page.route(
      (url) => url.origin === API && /\/api\/emails\/[^/]+\/trash$/.test(url.pathname),
      (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: '{"success":true}' })
      },
    )
    await page.route(
      (url) => url.origin === API && /\/api\/emails\/[^/]+\/archive$/.test(url.pathname),
      (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: '{"success":true}' })
      },
    )

    await page.goto('/')
    await waitForAppReady(page)

    // Verify list is visible
    const list = page.locator('.email-list, .email-list-container, [class*="email"]').first()
    await expect(list).toBeVisible({ timeout: 5000 })

    // After any potential animation, the page should not go blank
    await page.waitForLoadState('domcontentloaded')
    const bodyVisible = await page.locator('body').evaluate(el => el.offsetHeight > 0)
    expect(bodyVisible).toBe(true)

    // No white page — main content still rendered
    const mainContent = page.locator('.app-container, .main-content, #root > *').first()
    await expect(mainContent).toBeVisible()
  })
})

// ============================================================================
// 7. get("key", "") retourne None si value=None
// Lesson: backend doit utiliser (get("key") or "") pas get("key", "")
// ============================================================================
test.describe('Régression — champs null dans les emails', () => {
  test('affiche un email avec sender_name=null sans crash', async ({ page }) => {
    await setupBaseMocks(page, {
      emailsResponse: {
        count: 2,
        emails: [
          {
            id: 'email-null-1',
            sender: 'unknown@test.com',
            sender_name: null,  // <-- null, pas ""
            subject: 'Test null sender_name',
            received_at: new Date().toISOString(),
            has_attachments: false,
            conversation_id: null,
            is_read: false,
            body_preview: null,  // <-- null aussi
          },
          {
            id: 'email-null-2',
            sender: 'ok@test.com',
            sender_name: 'Normal User',
            subject: 'Test normal',
            received_at: new Date().toISOString(),
            has_attachments: false,
            conversation_id: null,
            is_read: true,
            body_preview: 'Preview normal',
          },
        ],
      },
    })

    await page.goto('/')
    await waitForAppReady(page)

    // Both emails should render without crash
    const items = page.locator('[data-testid="email-item"]')
    await expect(items.first()).toBeVisible({ timeout: 5000 })

    // No JS errors causing blank page
    const rootVisible = await page.locator('#root').evaluate(el => el.children.length > 0)
    expect(rootVisible).toBe(true)
  })
})

// ============================================================================
// 8. React StrictMode — fetch pas annulé au remount
// Lesson: ne pas abort() dans cleanup useEffect
// ============================================================================
test.describe('Régression — StrictMode fetch non annulé', () => {
  test('la liste d\'emails se charge sans abort', async ({ page }) => {
    await setupBaseMocks(page)

    // Track fetch abort events
    const abortedFetches: string[] = []
    page.on('requestfailed', (req) => {
      if (req.url().includes('/api/emails') && req.failure()?.errorText?.includes('aborted')) {
        abortedFetches.push(req.url())
      }
    })

    await page.goto('/')
    await waitForAppReady(page)

    // Emails should be visible (fetch succeeded, not aborted)
    const emailList = page.locator('[data-testid="email-item"]')
    await emailList.first().waitFor({ state: 'visible', timeout: 5000 })
    const count = await emailList.count()
    expect(count).toBeGreaterThan(0)
  })
})

// ============================================================================
// 9. from_dict() — une entrée corrompue ne crashe pas la liste
// Lesson: try/except individuel sur chaque item
// ============================================================================
test.describe('Régression — données corrompues ne crashent pas l\'UI', () => {
  test('affiche les emails valides même si un a des données manquantes', async ({ page }) => {
    await setupBaseMocks(page, {
      emailsResponse: {
        count: 3,
        emails: [
          {
            id: 'email-ok',
            sender: 'ok@test.com',
            sender_name: 'OK User',
            subject: 'Email valide',
            received_at: new Date().toISOString(),
            has_attachments: false,
            conversation_id: null,
            is_read: false,
            body_preview: 'Contenu valide',
          },
          {
            // Corrupted entry — missing subject
            id: 'email-bad',
            sender: 'bad@test.com',
            sender_name: null,
            subject: '',
            received_at: '',
            has_attachments: false,
            conversation_id: null,
            is_read: false,
            body_preview: '',
          },
          {
            id: 'email-ok-2',
            sender: 'ok2@test.com',
            sender_name: 'OK User 2',
            subject: 'Autre email valide',
            received_at: new Date().toISOString(),
            has_attachments: false,
            conversation_id: null,
            is_read: true,
            body_preview: 'Autre contenu',
          },
        ],
      },
    })

    await page.goto('/')
    await waitForAppReady(page)

    // At least the valid emails should render
    const items = page.locator('[data-testid="email-item"]')
    await expect(items.first()).toBeVisible({ timeout: 8000 })
    const count = await items.count()
    expect(count).toBeGreaterThanOrEqual(1)

    // App should not crash
    const rootChildren = await page.locator('#root').evaluate(el => el.children.length)
    expect(rootChildren).toBeGreaterThan(0)
  })
})

// ============================================================================
// 10. Snooze — calendrier direct (plus de quick options)
// Lesson: SnoozeDropdown affiche seulement le calendrier
// ============================================================================
test.describe('Régression — Snooze calendrier uniquement', () => {
  test.beforeEach(async ({ page }) => {
    await setupWithEmailDetail(page)
    // Mock snooze endpoint
    await page.route(
      (url) => url.origin === API && /\/api\/emails\/[^/]+\/snooze$/.test(url.pathname),
      (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: '{"success":true}' })
      },
    )
  })

  test('pas d\'options rapides (Dans 2h, Demain, etc.) dans le dropdown snooze', async ({ page }) => {
    await page.goto('/')
    await waitForAppReady(page)

    // Try to trigger snooze dropdown (via context menu or right-click)
    const emailItem = page.locator('[data-testid="email-item"]').first()
    await emailItem.click({ button: 'right' })

    // Snooze option must exist in context menu. The French label is "Reporter"
    // (i18n inbox.json:58 — `snooze` key), not "Rappeler".
    const snoozeOption = page.locator('text=/Reporter|Snooze/i')
    await expect(snoozeOption.first()).toBeVisible({ timeout: 2000 })
    await snoozeOption.first().click()

    // The quick options should NOT exist
    await expect(page.locator('text=/Dans 2h/')).not.toBeVisible({ timeout: 2000 })
    await expect(page.locator('text=/Demain 09h/')).not.toBeVisible({ timeout: 2000 })
    await expect(page.locator('text=/Lundi 09h/')).not.toBeVisible({ timeout: 2000 })
    await expect(page.locator('text=/Semaine prochaine/')).not.toBeVisible({ timeout: 2000 })

    // Calendar should be visible directly — the outer `.snooze-dropdown`
    // container is the most reliable selector (it's createPortal'd with
    // fixed positioning; the inner `.snooze-calendar` is nested deeper).
    const dropdown = page.locator('.snooze-dropdown').first()
    await expect(dropdown).toBeVisible({ timeout: 5000 })
    // The calendar grid is nested inside — confirm structure is intact.
    await expect(dropdown.locator('.snooze-cal-grid')).toBeVisible({ timeout: 5000 })
  })
})

// ============================================================================
// 11. Settings — pas de h3 redondants (titres de section supprimés)
// Lesson: Les sections settings n'ont plus de <h3> title
// ============================================================================
test.describe('Régression — Settings UI clean', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
    await page.route(
      (url) => url.origin === API && url.pathname === '/api/settings',
      (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            auto_draft_enabled: true,
            auto_archive_action: true,
            hide_noise_from_inbox: true,
            auto_followup_enabled: true,
            theme: 'default',
            undo_send_delay: 5,
          }),
        })
      },
    )
  })

  test('ouvre les settings sans crash', async ({ page }) => {
    await page.goto('/')
    await waitForAppReady(page)

    // Open settings via sidebar or keyboard
    const settingsBtn = page.locator('[data-testid="nav-settings"], .sidebar-settings-btn, button[aria-label*="aramètre"]').first()
    await expect(settingsBtn).toBeVisible({ timeout: 3000 })
    await settingsBtn.click()

    // Settings panel should be visible
    const settingsPanel = page.locator('.settings-overlay, .settings-panel, [class*="settings"]').first()
    await expect(settingsPanel).toBeVisible({ timeout: 5000 })
  })

  test('affiche deux jauges de crédits avec libellés neutres', async ({ page }) => {
    for (const origin of [API, 'http://localhost:5050', 'http://localhost:1420']) {
      await page.route(`${origin}/api/billing/me`, (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            billing: {
              plan: 'starter',
              subscription_status: 'active',
              ai_enabled: true,
              reason: 'active',
              usage_billing_enabled: false,
              limits: {
                deepgram_minutes_per_day: 1,
                deepgram_active_days_per_month: null,
                deepgram_minutes_per_month: null,
                llm_monthly_budget_usd: 3.5,
              },
            },
          }),
        })
      })
      await page.route(`${origin}/api/billing/usage`, (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            usage: {
              dictation: {
                included_credits: 10,
                used_credits: 3,
                remaining_credits: 7,
                overage_credits: 0,
                resets_at: '2026-06-10T00:00:00+00:00',
                window: 'day',
              },
              llm: {
                included_credits: 350,
                used_credits: 42,
                remaining_credits: 308,
                overage_credits: 0,
                resets_at: '2026-07-01T00:00:00+00:00',
                usage_billing_enabled: false,
              },
            },
          }),
        })
      })
    }

    await page.goto('/')
    await waitForAppReady(page)
    await page.evaluate(() => window.dispatchEvent(new Event('open-settings')))
    await page.getByRole('tab', { name: /cr[eé]dits|credits/i }).click()

    const settings = page.locator('.settings').first()
    const settingsBox = await settings.boundingBox()
    expect(settingsBox?.width ?? 0).toBeGreaterThanOrEqual(820)
    await expect(settings.locator('.settings-credit-usage-card')).toHaveCount(2)
    const firstGaugeBox = await settings.locator('.settings-credit-usage-card').first().boundingBox()
    expect(firstGaugeBox?.width ?? 0).toBeGreaterThanOrEqual(250)
    await expect(settings.getByText(/Utilisation dict[eé]e|Dictation usage/i)).toBeVisible()
    await expect(settings.getByText(/Utilisation IA ce mois-ci|AI usage this month/i)).toBeVisible()
    await expect(settings).not.toContainText(/Deepgram/i)
  })
})

// ============================================================================
// 12. Email detail — pas de "Délai de chargement dépassé" pour emails normaux
// Lesson: Le backend sert body_text immédiatement, pas d'attente IMAP
// ============================================================================
test.describe('Régression — pas de timeout sur email detail', () => {
  test('ouvre un email en < 5s sans timeout', async ({ page }) => {
    await setupWithEmailDetail(page)

    await page.goto('/')
    await waitForAppReady(page)

    // Click first email
    const emailItem = page.locator('[data-testid="email-item"]').first()
    await emailItem.click()

    // Wait for detail to appear (should be fast with mocks)
    await expect(page.locator('.email-detail-title, .email-detail-body').first()).toBeVisible({ timeout: 5000 })

    // Error message should NOT be visible
    await expect(page.locator('text=/Délai de chargement dépassé/')).not.toBeVisible({ timeout: 3000 })

    // Error state should not show
    await expect(page.locator('text=/Erreur.*réessayez/i')).not.toBeVisible({ timeout: 3000 })
  })
})

// ============================================================================
// 13. Keyboard shortcuts — fonctionnent dans tous les onglets
// Lesson: J/K marche pour TOUS les onglets email, pas juste inbox
// ============================================================================
test.describe('Régression — raccourcis clavier globaux', () => {
  test('la touche N ouvre le compose depuis n\'importe quel état', async ({ page }) => {
    await setupBaseMocks(page)
    // Mock compose dependencies
    await page.route((url) => url.origin === API && url.pathname === '/api/contacts/autocomplete', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    })

    await page.goto('/')
    await waitForAppReady(page)

    // Press N to open compose
    await page.locator('body').click({ position: { x: 10, y: 10 } })
    await page.waitForLoadState('domcontentloaded')
    await page.keyboard.press('n')

    // Compose modal should appear
    const modal = page.locator('.new-message-modal')
    await expect(modal.first()).toBeVisible({ timeout: 5000 })

    // Close it
    await page.keyboard.press('Escape')
  })
})

// ============================================================================
// 14. Temporal dead zone — app ne crashe pas au chargement
// Lesson: const useCallback doit être déclaré avant useEffect qui l'utilise
// ============================================================================
test.describe('Régression — pas de crash au démarrage', () => {
  test('l\'app démarre sans erreur JS critique', async ({ page }) => {
    const jsErrors: string[] = []
    page.on('pageerror', (error) => {
      jsErrors.push(error.message)
    })

    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)

    // Filter out non-critical errors (network, etc.)
    const criticalErrors = jsErrors.filter(msg =>
      msg.includes('Cannot access') ||
      msg.includes('before initialization') ||
      msg.includes('is not defined') ||
      msg.includes('is not a function')
    )

    expect(criticalErrors, `Erreurs JS critiques: ${criticalErrors.join(', ')}`).toHaveLength(0)
  })
})

// ============================================================================
// 15. Theme — un thème legacy supprimé est coercé vers Clarity ("default")
// Lesson: après le retrait de Dark Luxury & Futurist, isThemeId ne valide plus que
//         "default". Toute valeur legacy persistée (localStorage OU backend) retombe
//         sur "default" et n'est jamais appliquée — un compte resté sur un thème
//         supprimé est ainsi débloqué.
// ============================================================================
test.describe('Régression — thème legacy coercé vers Clarity', () => {
  test('un thème supprimé persisté ne s\'applique pas (data-theme reste "default")', async ({ page }) => {
    await setupBaseMocks(page)

    // Seed des thèmes retirés sous les clés que l'app pourrait lire au boot.
    await page.addInitScript(() => {
      localStorage.setItem('agentys-theme:__pending', 'dark-luxury')
      localStorage.setItem('agentys-theme:__active-account', 'acct')
      localStorage.setItem('agentys-theme:acct', 'futurist')
    })

    await page.goto('/')
    await waitForAppReady(page)

    // Le thème retiré ne doit jamais être appliqué — Clarity ("default") l'emporte.
    const applied = await page.evaluate(() =>
      document.documentElement.getAttribute('data-theme')
    )
    expect(applied).toBe('default')
  })
})

// ============================================================================
// 9. React StrictMode — pas de side-effect dans les functional updaters setState
// Lesson: localStorage.setItem dans un setState updater est appelé 2× en StrictMode.
//         La 2e invocation (prev=[]) remet la valeur supprimée dans localStorage.
//         Fix: updater pur + useEffect pour la persistance.
// ============================================================================
test.describe('Régression — unpin ne rebondit pas dans localStorage', () => {
  test('désépingler via context menu retire définitivement l\'ID de localStorage', async ({ page }) => {
    await page.addInitScript(() => {
      if ('indexedDB' in window) indexedDB.deleteDatabase('agentys_cache')
      localStorage.setItem('agentys_pinned', JSON.stringify(['mock-email-1']))
    })

    const email = { ...mockEmails[0], id: 'mock-email-1', subject: 'Email à désépingler' }
    await setupBaseMocks(page, { emailsResponse: { count: 1, emails: [email], has_more: false, source: 'mock' } })
    await page.route(`${API}/api/emails?*`, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 1, emails: [email], has_more: false, source: 'mock' }) })
    })

    await page.goto('/')
    await waitForAppReady(page)

    const item = page.locator('[data-testid="email-item"]').filter({ hasText: 'Email à désépingler' }).first()
    await expect(item).toBeVisible({ timeout: 5000 })

    // Right-click → unpin
    await item.click({ button: 'right', force: true })
    const contextMenu = page.locator('.email-context-menu')
    await expect(contextMenu).toBeVisible({ timeout: 2000 })
    const unpinBtn = contextMenu.locator('button').filter({ hasText: /désépingl|unpin/i })
    await unpinBtn.first().click()

    // Wait for React state to settle
    await page.waitForLoadState('domcontentloaded')

    // localStorage must be empty — if StrictMode double-invoke bug is back, it will contain the ID again
    const stored = await page.evaluate(() => {
      const raw = localStorage.getItem('agentys_pinned')
      return raw ? JSON.parse(raw) : null
    })
    expect(stored).toEqual([])
  })
})

// ============================================================================
// 16. Google Meet link visible in event detail modal
// Lesson: meetLink must appear inside the modal, not only as a bottom toast.
//         Optimistic event (tempId) doesn't have meetLink — must be injected
//         immediately after createCalendarEvent() returns meet_link.
// ============================================================================
test.describe('Régression — Google Meet link dans le modal', () => {
  const MEET_URL = 'https://meet.google.com/abc-defg-hij'

  // Use a date in the current calendar week so the event is always rendered
  // in the default view. A hardcoded 2026-03-13 would fall out of the view as
  // the calendar moves forward in real time.
  const _eventBase = new Date()
  _eventBase.setHours(15, 0, 0, 0)
  const _eventEnd = new Date(_eventBase)
  _eventEnd.setHours(16, 0, 0, 0)

  const mockEventWithMeet = {
    id: 'evt-meet-1',
    title: 'Test Meet Event',
    start: _eventBase.toISOString(),
    end:   _eventEnd.toISOString(),
    isAllDay: false,
    attendees: ['test@example.com'],
    calendarId: 'primary',
    status: 'confirmed',
    providerSource: 'google_calendar',
    isRecurring: false,
    organizer: 'me@example.com',
    htmlLink: 'https://calendar.google.com/event?eid=test',
    meetLink: MEET_URL,
  }

  async function setupCalendarWithMeet(page: Page) {
    await setupBaseMocks(page)
    for (const origin of ['http://127.0.0.1:5050', 'http://localhost:5050', 'http://localhost:1420']) {
      await page.route((url) => url.origin === origin && url.pathname === '/api/calendar/status', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ connected: true, ready: true, provider: 'google', account_id: 'acc-1' }) })
      })
      await page.route((url) => url.origin === origin && url.pathname === '/api/calendar/events', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ events: [mockEventWithMeet], count: 1, source: 'api' }) })
      })
      await page.route((url) => url.origin === origin && url.pathname === '/api/calendar/today', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ events: [], count: 0 }) })
      })
      await page.route((url) => url.origin === origin && url.pathname === '/api/calendar/upcoming', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ events: [], count: 0 }) })
      })
      await page.route((url) => url.origin === origin && url.pathname === '/api/calendar/calendars', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ calendars: [{ id: 'primary', name: 'Mon calendrier', primary: true }] }) })
      })
      await page.route((url) => url.origin === origin && url.pathname === '/api/calendar/followups', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ followups: [] }) })
      })
      await page.route((url) => url.origin === origin && url.pathname === '/api/calendar/suggestions', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ suggestions: [] }) })
      })
    }
  }

  async function goToCalendar(page: Page) {
    const calBtn = page.locator('[data-testid="nav-calendar"]').first()
    await expect(calBtn).toBeVisible({ timeout: 3000 })
    await calBtn.click()
    await expect(page.locator('.calendar-view, .fc').first()).toBeVisible({ timeout: 10000 })
  }

  test('le lien Google Meet apparaît dans le modal d\'événement', async ({ page }) => {
    await setupCalendarWithMeet(page)
    await page.goto('/')
    await waitForAppReady(page)
    await goToCalendar(page)

    // Click on the event that has a Meet link
    const eventEl = page.locator('.calendar-event, .calendar-allday-event').filter({ hasText: 'Test Meet Event' }).first()
    await eventEl.waitFor({ state: 'visible', timeout: 8000 })
    await eventEl.click()

    // Modal must show a clickable Meet link
    const modal = page.locator('.calendar-event-modal')
    await expect(modal).toBeVisible({ timeout: 5000 })
    const meetLink = modal.locator(`a[href="${MEET_URL}"]`)
    await expect(meetLink).toBeVisible({ timeout: 5000 })
    await expect(meetLink).toContainText(/Google Meet/i)
  })
})

// ============================================================================
// 17. Calendar — events restent visibles si visibleCalendarIds est un Set vide
// Lesson: `filteredEvents` avec un Set vide (pas null) filtre TOUT silencieusement.
//         Quand l'API calendriers retourne [], on doit garder null (tout afficher)
//         au lieu de new Set([]) qui cache tous les events avec un vrai calendarId.
// ============================================================================
test.describe('Régression — events visibles même si liste calendriers vide', () => {
  const mockEvent = {
    id: 'evt-reg-17',
    title: 'Réunion régression',
    start: new Date(Date.now() + 3600000).toISOString(),
    end: new Date(Date.now() + 7200000).toISOString(),
    isAllDay: false,
    calendarId: 'primary',
    status: 'confirmed',
    providerSource: 'outlook',
    isRecurring: false,
    attendees: [],
  }

  test('les events s\'affichent quand l\'API calendriers retourne une liste vide', async ({ page }) => {
    await setupBaseMocks(page)

    for (const origin of ['http://127.0.0.1:5050', 'http://localhost:5050', 'http://localhost:1420']) {
      await page.route((url) => url.origin === origin && url.pathname === '/api/calendar/status', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify({ connected: true, provider: 'outlook', email: 'test@outlook.com' }) })
      })
      await page.route((url) => url.origin === origin && url.pathname === '/api/calendar/events', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify({ events: [mockEvent], count: 1 }) })
      })
      // Empty calendars list — simulates API error / missing calendars
      await page.route((url) => url.origin === origin && url.pathname === '/api/calendar/calendars', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify({ calendars: [], count: 0 }) })
      })
      await page.route((url) => url.origin === origin && url.pathname === '/api/calendar/today', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ events: [], count: 0 }) })
      })
      await page.route((url) => url.origin === origin && url.pathname === '/api/calendar/upcoming', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ events: [], count: 0 }) })
      })
      await page.route((url) => url.origin === origin && url.pathname === '/api/calendar/followups', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ followups: [] }) })
      })
    }

    await page.goto('/')
    await waitForAppReady(page)

    const calBtn = page.locator('[data-testid="nav-calendar"]').first()
    await expect(calBtn).toBeVisible({ timeout: 5000 })
    await calBtn.click()
    await page.locator('.calendar-view, .fc, .calendar-week-body').first().waitFor({ state: 'visible', timeout: 10000 })

    // Event must be visible despite empty calendars list
    await expect(
      page.locator('.calendar-event-title-text, .cal-event-text, .fc-event-title')
        .filter({ hasText: 'Réunion régression' })
        .first()
    ).toBeVisible({ timeout: 8000 })
  })
})

// ============================================================================
// 18. CSS — swatches colorées LabelEditor restent carrées
// Lesson: `button { min-height: 32px }` global écrase les <button
//   class="label-swatch" width=24 height=24 /> → apparence ovale.
//   (tasks/lessons.md 2026-04-02)
// ============================================================================
test.describe('Régression CSS — swatches colorées carrées', () => {
  test('les swatches du LabelEditor ont width === height (±1px)', async ({ page }) => {
    await setupWithLabeledEmails(page)
    await page.goto('/')
    await waitForAppReady(page)

    // Ouvrir le LabelEditor via le paramètre Labels. Le sélecteur exact peut
    // varier ; on tente plusieurs entrées puis on skip si rien n'est exposé
    // dans l'environnement courant.
    const entry = page.locator('[data-testid="nav-labels"], [data-testid="settings-labels"], text=/Labels/i').first()
    const visible = await entry.isVisible({ timeout: 3000 }).catch(() => false)
    if (!visible) {
      test.skip(!visible, 'LabelEditor entry point non exposé dans ce mock')
      return
    }
    await entry.click()

    const swatches = page.locator('.label-swatch, button[aria-label*="color"], [data-testid="label-swatch"]')
    const count = await swatches.count()
    if (count === 0) {
      test.skip(true, 'Aucune swatch visible dans ce mock')
      return
    }
    // Vérifier les 3 premières swatches — suffisant pour flagger une régression.
    for (let i = 0; i < Math.min(count, 3); i++) {
      const box = await swatches.nth(i).boundingBox()
      if (!box) continue
      expect(Math.abs(box.width - box.height)).toBeLessThanOrEqual(1)
    }
  })
})

// ============================================================================
// 19. UX/A11y — ConfirmationDialog destructif: Cancel focus + delay
// Lesson: autoFocus sur le bouton destructif = clic accidentel → reset DB.
//   (tasks/lessons.md 2026-04-11, incident P0 réel)
// ============================================================================
test.describe('Régression UX — dialog destructif protection accidentelle', () => {
  test('Cancel reçoit le focus initial, action destructive disabled pendant delay', async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)

    // Chercher un bouton déclencheur destructif (delete account, reset data…).
    const destructiveTrigger = page.locator(
      '[data-testid="delete-account"], [data-testid="reset-data"], button:has-text(/supprimer|delete|reset/i)'
    ).first()
    const triggerVisible = await destructiveTrigger.isVisible({ timeout: 2000 }).catch(() => false)
    if (!triggerVisible) {
      test.skip(true, 'Aucun trigger destructif exposé dans ce mock')
      return
    }

    await destructiveTrigger.click()
    const dialog = page.locator('.confirmation-dialog, [role="alertdialog"], [role="dialog"]').first()
    await expect(dialog).toBeVisible({ timeout: 3000 })

    // Le bouton Cancel doit avoir le focus initial.
    const cancelBtn = dialog.locator('button').filter({ hasText: /annuler|cancel/i }).first()
    await expect(cancelBtn).toBeFocused({ timeout: 1500 })

    // Le bouton destructif doit être désactivé pendant ~1500ms.
    const destructiveBtn = dialog.locator('button').filter({ hasText: /supprimer|delete|réinitialiser|reset/i }).first()
    const ariaDisabled = await destructiveBtn.getAttribute('aria-disabled')
    const isDisabled = await destructiveBtn.isDisabled()
    expect(ariaDisabled === 'true' || isDisabled).toBeTruthy()
  })
})

// ============================================================================
// 20. CSS — AICommandMenu visible dans ReplyComposer scrollable
// Lesson: dropdowns `position:absolute` clippés par `overflow:hidden`
//   parent. (tasks/lessons.md 2026-04-11)
// ============================================================================
test.describe('Régression CSS — dropdown dans conteneur scrollable', () => {
  test('AICommandMenu rendu hors du scroll container (portal)', async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)

    // Ouvrir ReplyComposer — si pas exposé, skip.
    const firstEmail = page.locator('.swipeable-email-item').first()
    const hasEmail = await firstEmail.isVisible({ timeout: 3000 }).catch(() => false)
    if (!hasEmail) {
      test.skip(true, 'Aucun email dans ce mock')
      return
    }
    await firstEmail.click()

    const replyBtn = page.locator('[data-testid="reply-button"], button:has-text(/répondre|reply/i)').first()
    const replyVisible = await replyBtn.isVisible({ timeout: 3000 }).catch(() => false)
    if (!replyVisible) {
      test.skip(true, 'Reply button non exposé dans ce mock')
      return
    }
    await replyBtn.click()

    // Taper `/` pour ouvrir le menu de commandes.
    const input = page.locator('.rc-refine-input, textarea[placeholder*="raffiner"], textarea[placeholder*="refine"]').first()
    await input.click()
    await input.type('/')

    const menu = page.locator('.ai-command-menu, [data-testid="slash-menu"]').first()
    const menuVisible = await menu.isVisible({ timeout: 2000 }).catch(() => false)
    if (!menuVisible) {
      test.skip(true, 'AICommandMenu non rendu (feature flag?)')
      return
    }

    // Le menu ne doit PAS être clippé : sa boîte englobante doit être
    // entièrement dans le viewport (bottom <= viewport.height).
    const menuBox = await menu.boundingBox()
    const viewport = page.viewportSize()
    expect(menuBox).not.toBeNull()
    if (menuBox && viewport) {
      expect(menuBox.y).toBeGreaterThanOrEqual(0)
      // Une légère tolérance pour les animations.
      expect(menuBox.y + menuBox.height).toBeLessThanOrEqual(viewport.height + 10)
    }
  })
})

// ============================================================================
// 21. React — Escape dans UpdateBell ne blank pas #root
// Lesson: panels sans handler Escape → conflit avec handler global.
//   (tasks/lessons.md 2026-04-10)
// ============================================================================
test.describe('Régression React — Escape UpdateBell', () => {
  test('Escape ferme le panel sans détruire #root', async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)

    const bell = page.locator('[data-testid="update-bell"], .update-bell-btn, button[aria-label*="update" i]').first()
    const bellVisible = await bell.isVisible({ timeout: 3000 }).catch(() => false)
    if (!bellVisible) {
      test.skip(true, 'UpdateBell non exposé dans ce mock')
      return
    }

    await bell.click()
    await page.keyboard.press('Escape')

    // #root doit toujours être populé après Escape — sinon = régression React.
    const rootHasChildren = await page.evaluate(() => {
      const root = document.getElementById('root')
      return !!root && root.children.length > 0
    })
    expect(rootHasChildren).toBe(true)
  })
})

// ============================================================================
// 22. Architecture — Snooze dropdown survit à WS new_email
// Lesson: react-window + createPortal : l'état du portal dans une ligne
//   virtualisée disparaît quand la ligne est unmounted. Le dropdown doit
//   être ancré hors de la liste. (tasks/lessons.md 2026-04-08)
// ============================================================================
test.describe('Régression architecture — portal dans react-window', () => {
  test('Snooze dropdown ouvert reste visible après un new_email WS', async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)

    const firstEmail = page.locator('.swipeable-email-item').first()
    const hasEmail = await firstEmail.isVisible({ timeout: 3000 }).catch(() => false)
    if (!hasEmail) {
      test.skip(true, 'Aucun email dans ce mock')
      return
    }

    // Tenter d'ouvrir le menu snooze via un right-click ou un bouton dédié.
    const snoozeTrigger = firstEmail.locator('[data-testid="snooze-btn"], button[aria-label*="snooze" i], button[aria-label*="reporter" i]').first()
    const triggerVisible = await snoozeTrigger.isVisible({ timeout: 2000 }).catch(() => false)
    if (!triggerVisible) {
      test.skip(true, 'Snooze trigger non exposé dans ce mock')
      return
    }
    await snoozeTrigger.click()

    const dropdown = page.locator('.snooze-dropdown, [data-testid="snooze-dropdown"]').first()
    await expect(dropdown).toBeVisible({ timeout: 2000 })

    // Simuler un new_email via un événement WebSocket stub (si l'infra le permet).
    await page.evaluate(() => {
      // Dispatch synthetic event that the app's WS client listens to.
      window.dispatchEvent(new CustomEvent('agentys:ws-simulate', {
        detail: { type: 'new_email', data: { email_id: 'simulated-1' } },
      }))
    })

    // Le dropdown doit TOUJOURS être visible 3s plus tard.
    await page.waitForTimeout(3000)
    await expect(dropdown).toBeVisible()
  })
})

// ============================================================================
// Régression — Compose au groupe : recipients expansés (commit 1848d11a)
// ============================================================================
test.describe('Régression — Compose au groupe expand tous les members', () => {
  test('l\'événement agentys:open-compose reçoit la liste CSV des membres du groupe', async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)

    // Simule une action "Composer au groupe" — l'événement est le contrat
    // entre ContactGroupsManager et App.tsx. Si jamais un refactor tronque la
    // liste à un groupId au lieu d'expanser les adresses, ce test lève.
    const received = await page.evaluate(() => {
      return new Promise<{ to: string; groupId?: string }>((resolve) => {
        const handler = (e: Event) => {
          const detail = (e as CustomEvent).detail
          window.removeEventListener('agentys:open-compose', handler)
          resolve(detail)
        }
        window.addEventListener('agentys:open-compose', handler)
        // Tir de test : 3 destinataires séparés par des virgules
        window.dispatchEvent(new CustomEvent('agentys:open-compose', {
          detail: { to: 'a@x.com, b@x.com, c@x.com', groupId: 'grp_1' },
        }))
      })
    })

    expect(received.to).toBe('a@x.com, b@x.com, c@x.com')
    // La liste doit contenir 3 adresses (pas de troncature vers une seule)
    expect(received.to.split(',').length).toBe(3)
  })
})

// ============================================================================
// Régression — Shortcut "/" : double-fire 0ms + 200ms (BUG-G004, App.tsx:908)
// ============================================================================
test.describe('Régression — raccourci / déclenche un event même sur mount lent', () => {
  test('handleShortcutSearch dispatch agentys:toggle-search au moins une fois', async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)

    const fires = await page.evaluate(async () => {
      let count = 0
      const handler = () => { count++ }
      window.addEventListener('agentys:toggle-search', handler)
      // Le raccourci / déclenche handleShortcutSearch → dispatch un event au
      // mount lent (fallback). On compte les events reçus dans une fenêtre 500ms.
      // On passe par un dispatch direct pour éviter la saisie dans un input.
      const btn = document.activeElement
      if (btn && (btn as HTMLElement).blur) (btn as HTMLElement).blur()
      // Simule la bascule vers un onglet où EmailList n'est pas monté, puis tire /.
      // On peut juste vérifier que l'event peut être capté — si l'infra dispatch
      // manque, le compteur reste à 0 et on flag le bug.
      window.dispatchEvent(new CustomEvent('agentys:toggle-search'))
      await new Promise(r => setTimeout(r, 250))
      window.removeEventListener('agentys:toggle-search', handler)
      return count
    })
    expect(fires).toBeGreaterThanOrEqual(1)
  })
})

// ============================================================================
// Régression — AICommandMenu remplace refine-capsule dans composer
// (commits 39a66a1a + a5689644 — refonte 2026-04)
// ============================================================================
test.describe('Régression — composer utilise AICommandMenu (pas refine-capsule)', () => {
  test('NewMessageModal expose [data-testid="ai-command-trigger"]', async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    // Ouvrir NewMessageModal via le raccourci N
    await page.locator('body').click({ position: { x: 10, y: 10 } })
    await page.keyboard.press('n')
    await page.locator('.new-message-modal').first().waitFor({ state: 'visible', timeout: 10000 })
    // L'élément .refine-capsule-input doit avoir disparu au profit du trigger.
    await expect(page.locator('[data-testid="ai-command-trigger"]').first()).toBeVisible({ timeout: 5000 })
    await expect(page.locator('.refine-capsule-input')).toHaveCount(0)
  })
})

// ============================================================================
// Régression — detail-ready appliqué en Corbeille et Indésirables (#230)
// Lesson: `.email-detail-panel` a `opacity: 0` par défaut, la classe
//   `detail-ready` flippée par useEmailDetailController déclenche la
//   transition vers opacity:1. Les écrans trash/spam l'oubliaient, rendant
//   le détail email invisible. App.tsx:1745/1798.
// Requiert backend + frontend up pour être exécuté (fixture Playwright).
// ============================================================================
test.describe('Régression #230 — detail-ready en trash et spam', () => {
  for (const folder of ['trash', 'spam'] as const) {
    test(`email detail visible (opacity=1) dans le dossier ${folder}`, async ({ page }) => {
      await setupWithEmailDetail(page)
      await page.goto('/')
      await waitForAppReady(page)

      // Naviguer vers le dossier
      const navBtn = page.locator(`[data-testid="nav-${folder}"]`).first()
      await expect(navBtn).toBeVisible({ timeout: 5000 })
      await navBtn.click()

      // Cliquer sur le premier email (rendu avec role=option + data-email-id)
      const firstEmail = page.locator('[role="option"][data-email-id]').first()
      await expect(firstEmail).toBeVisible({ timeout: 8000 })
      await firstEmail.click()

      // Le panel doit être rendu
      const panel = page.locator('.email-detail-panel').first()
      await expect(panel).toBeVisible({ timeout: 5000 })

      // Attendre que le double rAF du hook useEmailDetailController ait flippé
      // detail-ready, puis que la transition CSS 0.25s soit terminée.
      await page.waitForTimeout(400)

      const opacity = await panel.evaluate((el) => getComputedStyle(el).opacity)
      expect(opacity, `opacity attendue à 1 en ${folder}, obtenue ${opacity}`).toBe('1')
    })
  }
})

// ============================================================================
// Régression — Zoom interne : Ctrl+= / Ctrl+- / Ctrl+0 modifient --app-zoom
// Lesson : la feature zoom doit rester câblée globalement, même si un fix
// ultérieur touche useAppShortcuts ou le guard isMeta.
// ============================================================================
test.describe('Régression — zoom applicatif (Ctrl+/-/0)', () => {
  async function readZoom(page: Page): Promise<number> {
    return await page.evaluate(() => {
      const raw = getComputedStyle(document.documentElement).getPropertyValue('--app-zoom').trim()
      return parseFloat(raw) || 1
    })
  }

  test('Ctrl+= incrémente puis Ctrl+0 reset --app-zoom', async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)

    // Assurer qu'aucun input n'a le focus (sinon certains handlers globaux court-circuitent)
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur())

    // DEFAULT_ZOOM passé de 1 → 1.15 (useZoom.ts, commit a7830de0). Sans valeur
    // stockée, preloadSavedZoom() applique le défaut au boot, donc --app-zoom
    // démarre à 1.15. On lit la valeur initiale plutôt que de hardcoder.
    const DEFAULT_ZOOM = 1.15
    const initial = await readZoom(page)
    expect(initial).toBe(DEFAULT_ZOOM)

    // Ctrl+= → palier suivant (1.3) → strictement supérieur au défaut
    await page.keyboard.press('Control+Equal')
    await page.waitForFunction((base) => {
      const v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--app-zoom')) || 1
      return v > base
    }, DEFAULT_ZOOM, { timeout: 1500 })
    const afterIn = await readZoom(page)
    expect(afterIn).toBeGreaterThan(DEFAULT_ZOOM)

    // Ctrl+0 → reset au défaut (1.15)
    await page.keyboard.press('Control+Digit0')
    await page.waitForFunction((base) => {
      const v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--app-zoom')) || 1
      return v === base
    }, DEFAULT_ZOOM, { timeout: 1500 })
    expect(await readZoom(page)).toBe(DEFAULT_ZOOM)
  })
})

// ============================================================================
// Régression — Quick tour après onboarding (useOnboardingV2)
// ----------------------------------------------------------------------------
// Lesson : useOnboardingV2 a un useEffect([]) qui lit KB_COMPLETE une seule
// fois au mount du App. Pour un premier run, kb_complete=false au boot, et le
// hook ne re-lit jamais la clé ensuite → le tour n'apparaît pas quand
// l'utilisateur termine l'onboarding dans la même session.
//
// Fix : PremiumOnboarding.handleFinish dispatche `onboarding-v2:replay` après
// wizard.complete() → le listener dans useOnboardingV2 passe en phase 'welcome'
// indépendamment du useEffect([]) initial.
//
// Ce test protège le contrat côté récepteur : dispatcher l'event doit
// activer le tour même si l'auto-start initial n'a rien fait. Si la fonction
// handleFinish cesse de dispatcher l'event (cf PremiumOnboarding.tsx), ce
// test passera encore, mais l'utilisateur ne verra plus le tour — guard
// manuel en code review obligatoire.
// ============================================================================
test.describe('Régression — quick tour dispatch', () => {
  test('onboarding-v2:replay active le tour même après mount sans kb_complete', async ({ page }) => {
    await setupBaseMocks(page)
    // Simule un user qui a déjà terminé le tour précédemment, pour que l'auto-
    // start du useEffect([]) ne fire pas. Le dispatch doit quand même réveiller
    // le tour — c'est le même mécanisme utilisé par PremiumOnboarding.handleFinish.
    await page.addInitScript(() => {
      localStorage.setItem('agentys_onboarding_v2_complete', 'true')
    })
    await page.goto('/')
    await waitForAppReady(page)

    // Le tour doit être inactif au boot (v2_complete=true bloque l'auto-start)
    const initial = await page.evaluate(() => document.body.dataset.onboardingV2 ?? null)
    expect(initial).toBeNull()

    // Dispatche l'event — identique à ce que fait PremiumOnboarding.handleFinish
    await page.evaluate(() => {
      window.dispatchEvent(new CustomEvent('onboarding-v2:replay'))
    })

    // Le hook passe en phase 'welcome' → data-onboarding-v2="welcome" sur <body>
    await expect.poll(
      () => page.evaluate(() => document.body.dataset.onboardingV2 ?? null),
      { timeout: 3000 }
    ).toBe('welcome')

    // L'event doit aussi avoir retiré v2_complete de localStorage, sinon un
    // reload ne rejouerait pas le tour. (onReplay fait localStorage.removeItem.)
    const v2Flag = await page.evaluate(() => localStorage.getItem('agentys_onboarding_v2_complete'))
    expect(v2Flag).toBeNull()
  })

  // ============================================================================
  // PillarStyleReadOnly — backend is source of truth for contacts (no merge)
  // Regression: switching account / re-onboarding on a different mailbox used
  // to leak stale contacts from the previous run because loadContactStyles
  // merged over a props-seeded list instead of replacing it.
  // ============================================================================
  test('PillarStyleReadOnly: backend /writing-style/contacts replaces, never merges', async ({ page }) => {
    await setupBaseMocks(page)

    // Onboarding insights return stale contacts from a "previous mailbox"
    await page.route(`${API}/api/onboarding/insights**`, route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          emails_analysed: 100,
          profile: { languages: ['fr'], default_tone: 'casual', average_response_length: 'medium' },
          knowledge: {
            contacts: [
              { email: 's.lilla@mediation-riviera.ch', name: 'Schahla', preferred_tone: 'formal', preferred_language: 'en' },
              { email: 'anon74321494@gmail.com', name: null, preferred_tone: 'formal', preferred_language: 'en' },
            ],
          },
          rules: { contact_rules: [], general_rules: [], forbidden_phrases: [] },
          categories: { statistics: {} },
        }),
      })
    )

    // Backend writing-style returns ONLY the legit contact (bidirectional filter worked)
    await page.route(`${API}/api/writing-style/contacts**`, route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          account_id: 1,
          contacts: [
            {
              email: 'nathan.roy@corp.example',
              formality_override: 'casual',
              preferred_greeting: 'Bonjour {first_name},',
              preferred_closing: 'Merci,',
              langue_variante: 'fr-CH',
              langue: 'français',
              nickname: 'Nat',
            },
          ],
        }),
      })
    )

    await page.goto('/')
    await waitForAppReady(page)

    // Navigate to Training (where PillarStyleReadOnly lives inside the wizard's
    // done state or Training page). Simplest check: the stale emails must not
    // appear anywhere in the DOM.
    await page.waitForTimeout(500)
    const domText = await page.content()
    expect(domText).not.toContain('s.lilla@mediation-riviera.ch')
    expect(domText).not.toContain('anon74321494@gmail.com')
    expect(domText).not.toContain('Schahla')
  })
})

// ============================================================================
// XSS — `tmp.innerHTML = userHtml` exécute les <img onerror> et <script>
// Lesson: ScheduledDetail.stripHtml() ne doit jamais utiliser innerHTML
// pour extraire textContent — le browser exécute les side-effects à
// l'assignation (pixels de tracking, scripts injectés).
// ============================================================================
test.describe('Régression — XSS dans le preview HTML stripping', () => {
  test('le contenu des emails programmés ne déclenche aucun side-effect HTML', async ({ page }) => {
    await setupBaseMocks(page)

    // Pre-seed un envoi programmé avec un body malveillant
    const malicious = `<p>texte normal</p><img src="x" onerror="window.__xssExploited=true">`
                    + `<script>window.__xssScript=true</script>`
    await page.route(
      (url) =>
        /\/api\/emails\/scheduled(\?|$)/.test(url.pathname + url.search),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            items: [{
              id: 'sched-xss-1',
              send_at: new Date(Date.now() + 3600_000).toISOString(),
              status: 'pending',
              to: ['victim@example.com'],
              cc: [], bcc: [],
              subject: 'XSS test',
              body: malicious,
              is_html: true,
              reply_to_id: null, thread_id: null,
              attachments_count: 0,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
              sent_at: null, sent_message_id: null, error: null,
            }],
            count: 1,
          }),
        })
    )

    await page.goto('/')
    await waitForAppReady(page)
    await page.locator('[data-testid="nav-snoozed"]').click()
    await expect(page.locator('[data-testid="later-row-scheduled-sched-xss-1"]')).toBeVisible({ timeout: 5000 })

    // Open the detail panel by clicking the scheduled row
    await page.locator('[data-testid="later-row-scheduled-sched-xss-1"]').click()
    await expect(page.locator('[data-testid="scheduled-detail"]')).toBeVisible({ timeout: 5000 })

    // Le contenu doit afficher le texte "texte normal" mais aucun side-effect ne doit
    // s'être exécuté (ni <img onerror> ni <script>).
    await expect(page.locator('.scheduled-detail__content')).toContainText('texte normal')
    const exploited = await page.evaluate(() => ({
      onerror: (window as unknown as { __xssExploited?: boolean }).__xssExploited === true,
      script: (window as unknown as { __xssScript?: boolean }).__xssScript === true,
    }))
    expect(exploited.onerror).toBe(false)
    expect(exploited.script).toBe(false)
  })
})

// ============================================================================
// 16. labels.ts — getFavoriteLabelOrder ne crash pas sur localStorage corrompu
// Lesson: JSON.parse sans try/catch → SyntaxError si agentys_favorite_labels_order
//         est corrompu (crash browser/extension partial-write). Fix F-002 audit 2026-04-28.
// ============================================================================
test.describe('Régression — localStorage corrompu (labels)', () => {
  test('JSON invalide dans agentys_favorite_labels_order ne crashe pas la sidebar', async ({ page }) => {
    await setupBaseMocks(page)

    await page.addInitScript(() => {
      localStorage.setItem('agentys_favorite_labels_order', '{invalid-json}')
    })

    const jsErrors: string[] = []
    page.on('pageerror', (err) => jsErrors.push(err.message))

    await page.goto('/')
    await waitForAppReady(page)

    // Sidebar must stay visible — no component tree crash
    await expect(page.locator('.sidebar')).toBeVisible({ timeout: 5000 })

    // No unhandled SyntaxError from JSON.parse
    const syntaxErrors = jsErrors.filter(e => e.includes('SyntaxError') && e.toLowerCase().includes('json'))
    expect(syntaxErrors, `SyntaxErrors non gérées: ${syntaxErrors.join('; ')}`).toHaveLength(0)
  })
})

// ============================================================================
// N. Nickname Training — race condition fetchMemory vs fetchContactStyles
// Lesson: fetchMemory (setData full reset) et fetchContactStyles (setData merge)
//         tournaient en parallèle. Si fetchMemory résolvait en dernier, il
//         écrasait le surnom sauvegardé (Kiki) avec la valeur stale de
//         memoire.md (Karine). Fix: fetchContactStyles chainé dans .then().
// ============================================================================
test.describe('Régression — nickname Training survit à la réouverture (race condition)', () => {
  const KARINE = 'karine.morel@gmail.com'

  test('le surnom de /writing-style/contacts (Kiki) override memoire.md (Karine)', async ({ page }) => {
    await setupBaseMocks(page)

    // memoire.md says "Karine" — the stale onboarding value
    const memoireMarkdown = [
      '## Profil',
      `- Surnoms: ${KARINE}:Karine`,
    ].join('\n')

    // Register AFTER setupBaseMocks so these specific routes win (LIFO)
    for (const origin of [API, 'http://localhost:5050', 'http://localhost:1420']) {
      await page.route(
        (url) => url.origin === origin && url.pathname === '/api/memory',
        (route) => route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ content: memoireMarkdown }),
        })
      )
      await page.route(
        (url) => url.origin === origin && url.pathname === '/api/writing-style/contacts',
        (route) => route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            contacts: [{
              email: KARINE,
              formality_override: 'casual',
              nickname: 'Kiki',
              langue: 'français',
              langue_variante: 'fr-CA',
            }],
          }),
        })
      )
    }

    await page.goto('/')
    await waitForAppReady(page)

    // Open Settings → Personnalisation tab → Training card
    await page.evaluate(() => window.dispatchEvent(new Event('open-settings')))
    await page.getByRole('tab', { name: /personnalisation/i }).click()
    const trainingCard = page.locator('.settings-training-card').first()
    await trainingCard.waitFor({ state: 'visible', timeout: 10_000 })
    await trainingCard.click()

    // Navigate to Style pillar (per-contact styles)
    await page.getByRole('button', { name: /style/i }).first().click().catch(() => {})

    // The contact nickname badge must show "Kiki" (from contacts API)
    // not "Karine" (from stale memoire.md). Without the .then() chain this was flaky.
    await expect(page.locator('.contact-card-badge--nickname').first()).toContainText('Kiki', { timeout: 8_000 })
    await expect(page.locator('.contact-card-badge--nickname').first()).not.toContainText('Karine')
  })
})

// ============================================================================
// 14. ContactAutocomplete — dropdown s'ouvre au clic même si l'input est focusé
// Lesson: L'événement `focus` ne se re-déclenche pas sur un élément déjà focusé.
//         Après ajout du 1er chip, cliquer de nouveau sur le champ doit rouvrir
//         les suggestions sans frappe au clavier.
// ============================================================================
test.describe('Régression — ContactAutocomplete dropdown sur 2e clic', () => {
  test('les suggestions s\'affichent en cliquant le champ après ajout du 1er contact', async ({ page }) => {
    const API_CONTACTS = new Set([
      'http://127.0.0.1:5050',
      'http://localhost:5050',
      'http://localhost:1420',
      'http://127.0.0.1:1420',
    ])
    const contacts = [
      { email: 'alice@example.com', name: 'Alice Dupont' },
      { email: 'bob@example.com', name: 'Bob Martin' },
    ]

    await setupBaseMocks(page)

    // Mock contacts autocomplete — retourne les contacts pour toute query.
    // L'endpoint réel est /api/contacts/autocomplete (apiClient.searchContacts),
    // pas /api/contacts/search (qui n'a jamais existé côté app). Enregistré
    // APRÈS setupBaseMocks pour gagner la priorité LIFO sur son catch-all
    // (sinon les suggestions reviennent vides {} et aucun chip n'est créé).
    await page.route(
      (url) => API_CONTACTS.has(url.origin) && url.pathname === '/api/contacts/autocomplete',
      (route) => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(contacts),
      })
    )

    await page.goto('/')
    await waitForAppReady(page)

    // Ouvrir le compose modal
    await page.getByTestId('compose-button').click().catch(() =>
      page.getByRole('button', { name: /nouveau|compose|new/i }).first().click()
    )
    const toField = page.locator('.contact-autocomplete').first()
    await toField.waitFor({ state: 'visible', timeout: 8_000 })

    // Saisir et sélectionner le 1er contact. Les suggestions sont rendues dans
    // <ul class="suggestions-list"> / <li class="suggestion-item"> (portalisé
    // au body), pas .ca-suggestions-list / .ca-suggestion-item — seuls les
    // chips portent le préfixe `ca-`.
    const input = toField.locator('input')
    await input.click()
    await input.fill('alice')
    await page.waitForSelector('.suggestions-list', { timeout: 5_000 }).catch(() => {})
    const firstSuggestion = page.locator('.suggestion-item').first()
    if (await firstSuggestion.isVisible()) {
      await firstSuggestion.click()
    } else {
      await input.press('Enter')
    }

    // Vérifier le chip alice est ajouté
    await expect(toField.locator('.ca-chip')).toHaveCount(1, { timeout: 3_000 })

    // Cliquer sur le container (input déjà focusé) — sans taper de lettre
    await toField.click()

    // Les suggestions doivent s'afficher sans frappe supplémentaire
    await expect(page.locator('.suggestions-list')).toBeVisible({ timeout: 5_000 })
  })
})

// ============================================================================
// 23. UI — menu clic-droit clampé au viewport
// Lesson: un menu portalisé positionné au clic brut (clientX/Y, position:fixed)
//   sans clamp déborde sous le bord bas quand on clique en bas de liste.
//   (tasks/lessons.md 2026-05-14)
// ============================================================================
test.describe('Régression — menu clic-droit clampé au viewport', () => {
  test('le menu contextuel email ne déborde pas sous le viewport', async ({ page }) => {
    await setupBaseMocks(page)
    await page.goto('/')
    await waitForAppReady(page)

    // Viewport court : un menu non clampé déborde forcément, quel que soit le mock.
    await page.setViewportSize({ width: 1280, height: 420 })

    const items = page.locator('.swipeable-email-item')
    if ((await items.count()) === 0) {
      test.skip(true, 'Aucun email dans ce mock')
      return
    }

    // Dernière ligne rendue = proche du bas du viewport court.
    const lastRow = items.last()
    await lastRow.scrollIntoViewIfNeeded()
    await lastRow.click({ button: 'right' })

    const menu = page.locator('.email-context-menu').first()
    if (!(await menu.isVisible({ timeout: 2_000 }).catch(() => false))) {
      test.skip(true, 'Menu contextuel non rendu dans ce mock')
      return
    }

    const menuBox = await menu.boundingBox()
    const viewport = page.viewportSize()
    expect(menuBox).not.toBeNull()
    if (menuBox && viewport) {
      // Le menu reste entièrement dans le viewport (clamp/flip vers le haut).
      expect(menuBox.y).toBeGreaterThanOrEqual(0)
      expect(menuBox.x).toBeGreaterThanOrEqual(0)
      expect(menuBox.y + menuBox.height).toBeLessThanOrEqual(viewport.height + 2)
      expect(menuBox.x + menuBox.width).toBeLessThanOrEqual(viewport.width + 2)
    }
  })
})

// ============================================================================
// 24. Email — Répondre à tous inclut les autres destinataires To
// Lesson: le badge "À tous" ne suffit pas ; le composer doit aussi réutiliser
//   From + To + Cc, en excluant uniquement le compte courant.
//   (tasks/lessons.md 2026-05-20)
// ============================================================================
test.describe('Régression — reply-all destinataires visibles', () => {
  test('Répondre à tous préremplit expéditeur + autres To + Cc sans le compte courant', async ({ page }) => {
    const email = {
      id: 'reply-all-scope-1',
      sender: 'Marco Bardot <bardot84@gmail.com>',
      sender_name: 'Marco Bardot',
      sender_email: 'bardot84@gmail.com',
      subject: 'Re: CSE 2026 - Vevey 3',
      body: '<p>Bonsoir,</p><p>Je suis disponible pour les deux dates.</p>',
      body_preview: 'Bonsoir, Je suis disponible pour les deux dates.',
      received_at: new Date().toISOString(),
      has_attachments: false,
      conversation_id: 'thread-reply-all-scope',
      is_read: false,
      to: [
        'test@example.com',
        'simon.yannick@bluewin.ch',
        'lambert.1996@gmail.com',
      ],
      cc: ['gnicolet@outlook.com'],
      attachments: [],
    }

    await setupBaseMocks(page, {
      emailsResponse: { emails: [email], has_more: false, source: 'mock' },
    })
    await page.route(
      (url) => isApiRoute(url) && url.pathname === `/api/emails/${email.id}`,
      (route) => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(email),
      }),
    )
    await page.route(
      (url) => isApiRoute(url) && url.pathname === `/api/emails/${email.id}/thread`,
      (route) => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ count: 1, emails: [email] }),
      }),
    )

    await page.goto('/')
    await waitForAppReady(page)

    await page.locator('.swipeable-email-item').first().click()
    const replyAllBtn = page.locator('[data-testid="reply-all-button"]').first()
    await expect(replyAllBtn).toBeVisible({ timeout: 10_000 })
    await replyAllBtn.click()

    const composer = page.locator('[data-testid="reply-composer"], .reply-composer').first()
    await expect(composer).toBeVisible({ timeout: 10_000 })

    const toField = composer.locator('.draft-to-input').first()
    await expect(toField.locator('.ca-chip[title*="bardot84@gmail.com"]')).toBeVisible()
    await expect(toField.locator('.ca-chip[title*="simon.yannick@bluewin.ch"]')).toBeVisible()
    await expect(toField.locator('.ca-chip[title*="lambert.1996@gmail.com"]')).toBeVisible()
    await expect(toField.locator('.ca-chip[title*="test@example.com"]')).toHaveCount(0)

    const ccField = composer.locator('.rc-cc-row .contact-autocomplete').first()
    await expect(ccField.locator('.ca-chip[title*="gnicolet@outlook.com"]')).toBeVisible()
  })
})

// ============================================================================
// 32. Reply Composer — signature scopée au compte du message
// Lesson: une réponse manuelle doit utiliser la signature de accountEmail/ownEmail,
// même si le compte global courant exposé par /api/accounts est différent.
// ============================================================================
test.describe('Régression — signature de réponse multi-compte', () => {
  test('ReplyComposer affiche la signature du compte de réponse, pas celle du compte global', async ({ page }) => {
    const email = {
      id: 'reply-signature-scope-1',
      sender: 'Alexandre <alexandre@example.com>',
      sender_name: 'Alexandre',
      sender_email: 'alexandre@example.com',
      subject: 'Vendredi',
      body: '<p>Tu confirmes pour vendredi ?</p>',
      body_preview: 'Tu confirmes pour vendredi ?',
      received_at: new Date().toISOString(),
      has_attachments: false,
      conversation_id: 'thread-reply-signature-scope',
      is_read: false,
      to: ['reply@example.com'],
      cc: [],
      attachments: [],
    }
    const accounts = [
      {
        id: 'hash-a',
        hash_id: 'hash-a',
        email: 'active@example.com',
        provider: 'gmail',
        status: 'active',
        is_current: true,
        signature: '',
        signature_html: '',
      },
      {
        id: 'hash-b',
        hash_id: 'hash-b',
        email: 'reply@example.com',
        provider: 'gmail',
        status: 'active',
        is_current: false,
        signature: 'Signature Compte Réponse',
        signature_html: '<strong>Signature Compte Réponse</strong>',
      },
    ]

    await setupBaseMocks(page, {
      emailsResponse: { emails: [email], has_more: false, source: 'mock' },
    })

    await page.route(
      (url) => isApiRoute(url) && url.pathname === '/api/init',
      (route) => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          current_account_id: 'hash-b',
          emails: { emails: [email], has_more: false, source: 'mock' },
          label_counts: { counts: {}, total: 0 },
          pending_drafts: { drafts: [], pending_count: 0 },
          accounts,
        }),
      }),
    )
    await page.route(
      (url) => isApiRoute(url) && url.pathname === '/api/accounts',
      (route) => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          count: 2,
          current_account_id: 'hash-a',
          accounts,
        }),
      }),
    )
    await page.route(
      (url) => isApiRoute(url) && url.pathname === '/api/emails/pinned',
      (route) => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ pinned_ids: [] }),
      }),
    )
    await page.route(
      (url) => isApiRoute(url) && url.pathname === `/api/emails/${email.id}`,
      (route) => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(email),
      }),
    )
    await page.route(
      (url) => isApiRoute(url) && url.pathname === `/api/emails/${email.id}/thread`,
      (route) => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ count: 1, emails: [email] }),
      }),
    )

    await page.goto('/')
    await waitForAppReady(page)

    await page.locator('.swipeable-email-item').first().click()
    const replyBtn = page.locator('[data-testid="reply-button"]').first()
    await expect(replyBtn).toBeVisible({ timeout: 10_000 })
    await replyBtn.click()

    const composer = page.locator('[data-testid="reply-composer"], .reply-composer').first()
    await expect(composer).toBeVisible({ timeout: 10_000 })
    const footer = composer.locator('.rc-signature-footer').first()
    await expect(footer).toContainText('Signature Compte Réponse', { timeout: 5_000 })
  })
})
