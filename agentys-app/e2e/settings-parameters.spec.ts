/**
 * Settings Parameters E2E Tests
 *
 * Tests every settings section, toggle, modal, and sub-panel
 * to verify all parameters load correctly and respond to user interaction.
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'
const API_LOCALHOST = 'http://localhost:5050'

// Full settings mock matching DEFAULT_SETTINGS from backend
const FULL_SETTINGS = {
  operation_mode: 'controlled',
  polling_interval_minutes: 5,
  notifications_enabled: true,
  working_hours_only: false,
  working_hours_start: '09:00',
  working_hours_end: '18:00',
  auto_draft_enabled: true,
  auto_archive_action: true,
  auto_empty_trash_30d: true,
  auto_empty_spam_30d: true,
  hide_noise_from_inbox: true,
  theme: 'default',
  ui_sounds_enabled: false,
  undo_send_delay: 5,
  auto_reply_enabled: false,
  auto_reply_message: '',
  auto_reply_start: '',
  auto_reply_end: '',
  auto_transfer_enabled: false,
  auto_transfer_email: '',
  auto_followup_enabled: true,
  followup_delay_days: 3,
  batch_enabled: true,
  batch_active_hours_start: '07:00',
  batch_active_hours_end: '20:00',
  batch_weekend_all_day: true,
  batch_activity_timeout_min: 15,
  monthly_recap_email_enabled: true,
  monthly_recap_email_sent_month: '',
  monthly_recap_banner_month: '',
  monthly_recap_banner_dismissed: false,
  deep_work_enabled: false,
  deep_work_emails_enabled: true,
  deep_work_work_enabled: true,
  deep_work_check_slots: [
    { start: '08:00', duration: 30 },
    { start: '12:30', duration: 30 },
    { start: '17:30', duration: 30 },
  ],
  deep_work_vip_contacts: [],
  deep_work_weekdays: [1, 2, 3, 4, 5],
  deep_work_personal_blocks: [],
  active_specialties: [],
  specialty_activations: {},
  booking_url: '',
}

const ACCOUNT_MOCK = {
  count: 1,
  current_account_id: 'acc_1',
  accounts: [{
    id: 'acc_1',
    name: 'Test',
    email: 'test@example.com',
    provider: 'gmail',
    status: 'active',
    is_current: true,
    last_sync: null,
    signature: 'Mon nom\nMon titre',
    signature_html: '<div>Mon nom</div><div>Mon titre</div>',
  }],
}

/** Captured PATCH requests for settings verification */
let settingsPatchCalls: { body: unknown }[] = []

async function setupAllMocks(page: Page) {
  settingsPatchCalls = []
  await setupBaseMocks(page)

  // Override accounts mock with signature data
  const accountHandler = (route: import('@playwright/test').Route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/accounts') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(ACCOUNT_MOCK),
      })
    } else {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
    }
  }
  await page.route(`${API}/api/accounts`, accountHandler)
  await page.route(`${API_LOCALHOST}/api/accounts`, accountHandler)

  // Settings GET/PATCH
  const settingsHandler = (route: import('@playwright/test').Route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(FULL_SETTINGS),
      })
    } else if (route.request().method() === 'PATCH') {
      try {
        settingsPatchCalls.push({ body: JSON.parse(route.request().postData() || '{}') })
      } catch { /* ignore */ }
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
    } else {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
    }
  }
  await page.route((url) => (url.origin === API || url.origin === API_LOCALHOST) && url.pathname === '/api/settings', settingsHandler)

  // My-style mock
  await page.route((url) => (url.origin === API || url.origin === API_LOCALHOST) && url.pathname === '/api/my-style', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ style: null }) })
  })

  // Blocked senders mock (actual path: /api/senders/blocked)
  await page.route((url) => (url.origin === API || url.origin === API_LOCALHOST) && url.pathname === '/api/senders/blocked', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ blocked_senders: ['spam@evil.com', 'phish@bad.org'] }) })
  })

  // Spammed senders mock
  await page.route((url) => (url.origin === API || url.origin === API_LOCALHOST) && url.pathname === '/api/senders/spammed', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ spammed_senders: ['newsletter@spam.net'], spammed_domains: ['junkmail.com'] }) })
  })

  // Unblock / Unspam POST mocks
  await page.route((url) => (url.origin === API || url.origin === API_LOCALHOST) && url.pathname === '/api/senders/unblock', (route) => {
    if (route.request().method() === 'POST') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, blocked_senders: ['phish@bad.org'] }) })
    } else { route.fallback() }
  })
  await page.route((url) => (url.origin === API || url.origin === API_LOCALHOST) && url.pathname === '/api/senders/unspam', (route) => {
    if (route.request().method() === 'POST') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, spammed_senders: [], spammed_domains: [] }) })
    } else { route.fallback() }
  })

  // Contact groups mock
  await page.route((url) => (url.origin === API || url.origin === API_LOCALHOST) && url.pathname.startsWith('/api/contact-groups'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ groups: [], total: 0 }) })
  })

  // Newsletters mock
  await page.route((url) => (url.origin === API || url.origin === API_LOCALHOST) && url.pathname.startsWith('/api/newsletters'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ newsletters: [] }) })
  })

  // Agent catalog mock
  await page.route((url) => (url.origin === API || url.origin === API_LOCALHOST) && url.pathname.startsWith('/api/agents'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  })

  // Wizard LLM settings
  await page.route((url) => (url.origin === API || url.origin === API_LOCALHOST) && url.pathname === '/api/wizard/llm-settings', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ provider: 'claude', model: 'claude-sonnet-4-5-20250514', api_key_set: true }),
    })
  })

  // Specialties mock
  await page.route((url) => (url.origin === API || url.origin === API_LOCALHOST) && url.pathname.startsWith('/api/specialties'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ specialties: [] }) })
  })
}

async function openSettings(page: Page) {
  const settingsBtn = page.locator('[data-testid="nav-settings"]').first()
  if (await settingsBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await settingsBtn.click()
  } else {
    await page.keyboard.press('Control+,')
  }
  await page.locator('.settings').first().waitFor({ state: 'visible', timeout: 10000 })
}

async function clickSidebarItem(page: Page, index: number) {
  const items = page.locator('.settings-sidebar-item')
  await items.nth(index).click()
  await page.waitForTimeout(300)
}

// Section indices (from Settings.tsx sidebar items order):
// 0 = Compte, 1 = Personnalisation, 2 = Outils, 3 = Productivité, 4 = Automatisation, 5 = Général

// ============================================================================
// SECTION: Compte (index 0)
// ============================================================================

test.describe('Settings > Compte', () => {
  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openSettings(page)
  })

  test('affiche les liens du compte', async ({ page }) => {
    // Compte section is the default. 4 base links: User account, Signature,
    // Auto-replies, Blocked senders. (Monthly recap is gated on ENABLE_MONTHLY_RECAP.)
    const links = page.locator('.settings-link-btn')
    await links.first().waitFor({ state: 'visible', timeout: 5000 })
    const count = await links.count()
    expect(count).toBeGreaterThanOrEqual(4)
  })

  test('signature lien visible', async ({ page }) => {
    const signatureBtn = page.locator('.settings-link-btn').filter({ hasText: /Signature/i }).first()
    await expect(signatureBtn).toBeVisible({ timeout: 5000 })
  })

  test('réponses automatiques lien visible', async ({ page }) => {
    // French: "Réponses automatiques"
    const autoReplyBtn = page.locator('.settings-link-btn').filter({ hasText: /[Rr][eé]ponse/i }).first()
    await expect(autoReplyBtn).toBeVisible({ timeout: 5000 })
  })

  test('expéditeurs bloqués lien visible', async ({ page }) => {
    // French: "Expéditeurs bloqués"
    const blockedBtn = page.locator('.settings-link-btn').filter({ hasText: /bloqu|exp[eé]diteur/i }).first()
    await expect(blockedBtn).toBeVisible({ timeout: 5000 })
  })

  test('signature modal charge sans erreur', async ({ page }) => {
    const signatureBtn = page.locator('.settings-link-btn').filter({ hasText: /Signature/i }).first()
    await signatureBtn.click()

    // Signature modal should open
    const sigModal = page.locator('.sig-modal').first()
    await expect(sigModal).toBeVisible({ timeout: 5000 })

    // Should NOT show error
    await page.waitForTimeout(1500)
    const errorEl = page.locator('#sig-error, .sig-error')
    await expect(errorEl).not.toBeVisible()

    // Editor should be visible
    await expect(page.locator('.sig-editor')).toBeVisible()

    // Import button visible
    await expect(page.locator('.sig-import-btn')).toBeVisible()

    // Save button visible — the footer Save is now the shared <Button> (shadcn,
    // data-slot="button") inside .sig-footer-right, not a .sig-btn-save class.
    await expect(page.locator('.sig-footer-right button')).toBeVisible()
  })

  test('signature modal charge la signature existante', async ({ page }) => {
    const signatureBtn = page.locator('.settings-link-btn').filter({ hasText: /Signature/i }).first()
    await signatureBtn.click()

    const sigModal = page.locator('.sig-modal').first()
    await expect(sigModal).toBeVisible({ timeout: 5000 })
    await page.waitForTimeout(1000)

    const editor = page.locator('.sig-editor')
    const text = await editor.textContent()
    expect(text).toContain('Mon nom')
  })

  test('signature modal se ferme avec Back', async ({ page }) => {
    await page.locator('.settings-link-btn').filter({ hasText: /Signature/i }).first().click()
    const sigModal = page.locator('.sig-modal').first()
    await expect(sigModal).toBeVisible({ timeout: 5000 })
    await page.locator('.sig-back').click()
    await expect(sigModal).not.toBeVisible({ timeout: 3000 })
  })

  test('signature modal se ferme avec X', async ({ page }) => {
    await page.locator('.settings-link-btn').filter({ hasText: /Signature/i }).first().click()
    const sigModal = page.locator('.sig-modal').first()
    await expect(sigModal).toBeVisible({ timeout: 5000 })
    await page.locator('.sig-close').click()
    await expect(sigModal).not.toBeVisible({ timeout: 3000 })
  })

  test('auto-reply modal ouvre', async ({ page }) => {
    await page.locator('.settings-link-btn').filter({ hasText: /[Rr][eé]ponse/i }).first().click()
    // AutoReplyModal should appear
    await page.waitForTimeout(1000)
    const autoReplyModal = page.locator('.autoreply-modal').first()
    await expect(autoReplyModal).toBeVisible({ timeout: 5000 })
  })

  test('blocked senders modal ouvre', async ({ page }) => {
    await page.locator('.settings-link-btn').filter({ hasText: /bloqu|exp[eé]diteur/i }).first().click()
    await page.waitForTimeout(1000)
    // Should display a modal overlay with blocked senders
    const modal = page.locator('.settings-modal-overlay').first()
    await expect(modal).toBeVisible({ timeout: 5000 })
  })

  // Spammed-senders (indésirables) management was removed from Settings. The
  // Compte section only renders 4 links (User account, Signature, Auto-replies,
  // Blocked senders) and BlockedSendersModal handles blocked senders only — no
  // spam/unspam UI. The /senders/spammed + /senders/unspam APIs still exist but
  // are no longer surfaced anywhere in Settings.tsx. Skip until/unless a
  // spammed-senders entry-point is re-added.
  test.skip('spammed senders modal ouvre', async ({ page }) => {
    await page.locator('.settings-link-btn').filter({ hasText: /spam|ind[eé]sirable/i }).first().click()
    await page.waitForTimeout(1000)
    const modal = page.locator('.settings-modal-overlay').first()
    await expect(modal).toBeVisible({ timeout: 5000 })
  })

  // Monthly Recap link is gated on ENABLE_MONTHLY_RECAP (= false in Settings.tsx).
  // Skip until the feature is re-enabled; the link is intentionally not rendered.
  test.skip('monthly recap lien visible', async ({ page }) => {
    const recapBtn = page.locator('.settings-link-btn').filter({ hasText: /r[eé]sum[eé]|recap/i }).first()
    await expect(recapBtn).toBeVisible({ timeout: 5000 })
  })

  test('auto-reply modal toggle visible et cliquable', async ({ page }) => {
    await page.locator('.settings-link-btn').filter({ hasText: /[Rr][eé]ponse/i }).first().click()
    const modal = page.locator('.autoreply-modal').first()
    await expect(modal).toBeVisible({ timeout: 5000 })
    const toggle = modal.locator('.autoreply-toggle').first()
    await expect(toggle).toBeVisible()
    // Click toggle — sends PATCH to backend
    settingsPatchCalls = []
    await toggle.click()
    await page.waitForTimeout(1000)
    expect(settingsPatchCalls.length).toBeGreaterThan(0)
  })

  test('auto-reply modal textarea editable', async ({ page }) => {
    await page.locator('.settings-link-btn').filter({ hasText: /[Rr][eé]ponse/i }).first().click()
    const modal = page.locator('.autoreply-modal').first()
    await expect(modal).toBeVisible({ timeout: 5000 })
    // The message field was refactored from a <textarea> to the shared
    // RichTextEditor (contenteditable .rte-editor). The body is disabled
    // (pointer-events:none via .autoreply-body[data-disabled]) until auto-reply
    // is enabled, so first flip the toggle (optimistic local state), then type.
    // `.fill()` doesn't work on contenteditable — use keyboard.type.
    await modal.locator('.autoreply-toggle').first().click()
    const editor = modal.locator('.rte-editor').first()
    await expect(editor).toBeVisible()
    await editor.click()
    await page.keyboard.type('Je suis absent du bureau.')
    await expect(editor).toContainText('absent')
  })

  test('auto-reply modal se ferme avec save', async ({ page }) => {
    await page.locator('.settings-link-btn').filter({ hasText: /[Rr][eé]ponse/i }).first().click()
    const modal = page.locator('.autoreply-modal').first()
    await expect(modal).toBeVisible({ timeout: 5000 })
    const saveBtn = modal.locator('button').filter({ hasText: /sauvegarder|enregistrer|save/i }).first()
    await expect(saveBtn).toBeVisible({ timeout: 2000 })
    await saveBtn.click()
    await expect(modal).not.toBeVisible({ timeout: 5000 })
  })

  test('auto-reply modal se ferme avec back', async ({ page }) => {
    await page.locator('.settings-link-btn').filter({ hasText: /[Rr][eé]ponse/i }).first().click()
    const modal = page.locator('.autoreply-modal').first()
    await expect(modal).toBeVisible({ timeout: 5000 })
    const backBtn = modal.locator('.autoreply-back, .autoreply-close').first()
    await backBtn.click()
    await expect(modal).not.toBeVisible({ timeout: 5000 })
  })

  test('blocked senders affiche la liste', async ({ page }) => {
    await page.locator('.settings-link-btn').filter({ hasText: /bloqu|exp[eé]diteur/i }).first().click()
    const modal = page.locator('.settings-modal-overlay').first()
    await expect(modal).toBeVisible({ timeout: 5000 })
    await expect(page.locator('text=spam@evil.com')).toBeVisible({ timeout: 5000 })
  })

  test('blocked senders unblock envoie API', async ({ page }) => {
    await page.locator('.settings-link-btn').filter({ hasText: /bloqu|exp[eé]diteur/i }).first().click()
    const modal = page.locator('.settings-modal-overlay').first()
    await expect(modal).toBeVisible({ timeout: 5000 })
    await expect(page.locator('text=spam@evil.com')).toBeVisible({ timeout: 5000 })

    const requestPromise = page.waitForRequest(
      (req) => req.url().includes('/api/senders/unblock') && req.method() === 'POST',
      { timeout: 5000 }
    )
    // Click unblock button next to spam@evil.com
    const row = page.locator('li').filter({ hasText: 'spam@evil.com' })
    await row.locator('button').click()
    const request = await requestPromise
    expect(request.postDataJSON()).toHaveProperty('email', 'spam@evil.com')
  })

  // See note above — spammed-senders UI removed from Settings.
  test.skip('spammed senders affiche senders et domains', async ({ page }) => {
    await page.locator('.settings-link-btn').filter({ hasText: /spam|ind[eé]sirable/i }).first().click()
    const modal = page.locator('.settings-modal-overlay').first()
    await expect(modal).toBeVisible({ timeout: 5000 })
    await expect(page.locator('text=newsletter@spam.net')).toBeVisible({ timeout: 5000 })
    await expect(page.locator('text=/junkmail\\.com/i')).toBeVisible({ timeout: 5000 })
  })

  // See note above — spammed-senders UI removed from Settings.
  test.skip('spammed senders unspam envoie API', async ({ page }) => {
    await page.locator('.settings-link-btn').filter({ hasText: /spam|ind[eé]sirable/i }).first().click()
    const modal = page.locator('.settings-modal-overlay').first()
    await expect(modal).toBeVisible({ timeout: 5000 })
    await expect(page.locator('text=newsletter@spam.net')).toBeVisible({ timeout: 5000 })

    const requestPromise = page.waitForRequest(
      (req) => req.url().includes('/api/senders/unspam') && req.method() === 'POST',
      { timeout: 5000 }
    )
    const row = page.locator('li').filter({ hasText: 'newsletter@spam.net' })
    await row.locator('button').click()
    await requestPromise
  })
})

// ============================================================================
// SECTION: Personnalisation (index 1)
// ============================================================================

test.describe('Settings > IA', () => {
  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openSettings(page)
    await clickSidebarItem(page, 1)
  })

  test('affiche les cartes IA', async ({ page }) => {
    const trainingCard = page.locator('.settings-training-card').first()
    await expect(trainingCard).toBeVisible({ timeout: 5000 })
  })

  test('affiche la carte Agents', async ({ page }) => {
    const cards = page.locator('.settings-training-card')
    await cards.first().waitFor({ state: 'visible', timeout: 5000 })
    const count = await cards.count()
    expect(count).toBeGreaterThanOrEqual(2)
  })

  // The IA section was trimmed to two cards: AI Training and AI Dictation
  // (STT keyterms). The Specialties/Skills card is gated off
  // (ENABLE_SKILLS_CARD = false) and the Agents Showcase + Marketplace surfaces
  // were removed entirely — no AgentsShowcase/Marketplace component remains and
  // the .ash-*/.am-* classes are dead CSS. Skip the showcase/marketplace tests
  // until those surfaces come back.
  test.skip('au moins 3 cartes (training, agents, marketplace)', async ({ page }) => {
    const cards = page.locator('.settings-training-card')
    await cards.first().waitFor({ state: 'visible', timeout: 5000 })
    expect(await cards.count()).toBeGreaterThanOrEqual(3)
  })

  test.skip('agents showcase modal ouvre', async ({ page }) => {
    // Cards order: 0=Training, 1=Specialties, 2=Agents, 3=Marketplace
    const agentsCard = page.locator('.settings-training-card').nth(2)
    await agentsCard.click()
    await expect(page.locator('.ash-overlay').first()).toBeVisible({ timeout: 5000 })
    await expect(page.locator('.ash-modal').first()).toBeVisible({ timeout: 5000 })
  })

  test.skip('agents showcase affiche 7+ cartes', async ({ page }) => {
    await page.locator('.settings-training-card').nth(2).click()
    await expect(page.locator('.ash-modal').first()).toBeVisible({ timeout: 5000 })
    const cards = page.locator('.ash-card')
    await cards.first().waitFor({ state: 'visible', timeout: 5000 })
    expect(await cards.count()).toBeGreaterThanOrEqual(7)
  })

  test.skip('agents showcase se ferme', async ({ page }) => {
    await page.locator('.settings-training-card').nth(2).click()
    const overlay = page.locator('.ash-overlay').first()
    await expect(overlay).toBeVisible({ timeout: 5000 })
    await page.locator('.ash-close').click()
    await expect(overlay).not.toBeVisible({ timeout: 3000 })
  })

  test.skip('marketplace modal ouvre', async ({ page }) => {
    // Cards order: 0=Training, 1=Specialties, 2=Agents, 3=Marketplace
    const cards = page.locator('.settings-training-card')
    await cards.first().waitFor({ state: 'visible', timeout: 5000 })
    const marketplaceCard = cards.nth(3)
    await marketplaceCard.click()
    await page.waitForTimeout(500)
    // Marketplace renders as .am-overlay or another overlay
    const overlay = page.locator('.am-overlay, .settings-modal-overlay, [class*="marketplace"]').first()
    await expect(overlay).toBeVisible({ timeout: 5000 })
  })
})

// ============================================================================
// SECTION: Outils (index 2)
// ============================================================================

test.describe('Settings > Outils', () => {
  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openSettings(page)
    await clickSidebarItem(page, 2)
  })

  test('affiche les liens d\'organisation', async ({ page }) => {
    // French: "Étiquettes", "Fragments", "Groupes de contacts"
    const links = page.locator('.settings-link-btn')
    await links.first().waitFor({ state: 'visible', timeout: 5000 })
    const count = await links.count()
    expect(count).toBeGreaterThanOrEqual(3)
  })

  test('affiche les liens de messagerie', async ({ page }) => {
    // French: "Abonnements payants", "Infolettres"
    const subsBtn = page.locator('.settings-link-btn').filter({ hasText: /abonn|subscri|infolettre|newsletter/i }).first()
    await expect(subsBtn).toBeVisible({ timeout: 5000 })
  })

  test('contact groups modal ouvre', async ({ page }) => {
    await page.locator('.settings-link-btn').filter({ hasText: /groupe|contact/i }).first().click()
    await page.waitForTimeout(500)
    await expect(page.locator('.cg-overlay').first()).toBeVisible({ timeout: 5000 })
    await expect(page.locator('.cg-modal').first()).toBeVisible()
  })

  test('contact groups add btn visible', async ({ page }) => {
    await page.locator('.settings-link-btn').filter({ hasText: /groupe|contact/i }).first().click()
    await expect(page.locator('.cg-modal').first()).toBeVisible({ timeout: 5000 })
    await expect(page.locator('.ghost-add-row').first()).toBeVisible({ timeout: 3000 })
  })

  test('clean inbox modal ouvre', async ({ page }) => {
    await page.locator('.settings-link-btn').filter({ hasText: /propre|clean|nettoy/i }).first().click()
    await page.waitForTimeout(500)
    // Radix Dialog or custom modal
    const modal = page.locator('.clean-inbox-modal, [role="dialog"]').first()
    await expect(modal).toBeVisible({ timeout: 5000 })
  })

  test('newsletters modal ouvre', async ({ page }) => {
    await page.locator('.settings-link-btn').filter({ hasText: /infolettre|newsletter/i }).first().click()
    await page.waitForTimeout(500)
    const modal = page.locator('.newsletters-modal, [role="dialog"]').first()
    await expect(modal).toBeVisible({ timeout: 5000 })
  })

  test('labels link ferme settings', async ({ page }) => {
    await page.locator('.settings-link-btn').filter({ hasText: /[eé]tiquette|label/i }).first().click()
    // Settings should close (onClose called before onOpenLabelLibrary)
    await expect(page.locator('.settings').first()).not.toBeVisible({ timeout: 5000 })
  })

  test('snippets link ferme settings', async ({ page }) => {
    await page.locator('.settings-link-btn').filter({ hasText: /fragment|snippet/i }).first().click()
    await expect(page.locator('.settings').first()).not.toBeVisible({ timeout: 5000 })
  })
})

// ============================================================================
// SECTION: Productivité (index 3)
// ============================================================================

test.describe('Settings > Productivite', () => {
  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openSettings(page)
    await clickSidebarItem(page, 3)
  })

  test('affiche les liens productivite', async ({ page }) => {
    // French: "Boîte propre", "Mode concentration", "Ne pas déranger", "Raccourcis clavier"
    const links = page.locator('.settings-link-btn')
    await links.first().waitFor({ state: 'visible', timeout: 5000 })
    const count = await links.count()
    expect(count).toBeGreaterThanOrEqual(3)
  })

  test('focus mode link visible', async ({ page }) => {
    const btn = page.locator('.settings-link-btn').filter({ hasText: /concentration|focus|deep.*work/i }).first()
    await expect(btn).toBeVisible({ timeout: 5000 })
  })

  // "Ne pas déranger" (DND) is no longer a Productivité link. The section now
  // exposes: Mode concentration (Deep Work), Raccourcis clavier, Rappels de
  // réunions, Lien de rendez-vous. No DND/do-not-disturb entry-point exists in
  // Settings.tsx anymore. Skip until/unless it is re-added.
  test.skip('DND link visible', async ({ page }) => {
    const btn = page.locator('.settings-link-btn').filter({ hasText: /d[eé]ranger|dnd|do.*not.*disturb/i }).first()
    await expect(btn).toBeVisible({ timeout: 5000 })
  })

  test('shortcuts link visible', async ({ page }) => {
    const btn = page.locator('.settings-link-btn').filter({ hasText: /raccourcis|shortcut/i }).first()
    await expect(btn).toBeVisible({ timeout: 5000 })
  })
})

// ============================================================================
// SECTION: Automatisation (index 4) — all toggles
// ============================================================================

test.describe('Settings > Automatisation', () => {
  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openSettings(page)
    await clickSidebarItem(page, 4)
  })

  test('affiche tous les toggles d\'automatisation', async ({ page }) => {
    const toggles = page.locator('.settings-toggle')
    await toggles.first().waitFor({ state: 'visible', timeout: 5000 })
    // The Automation section now has exactly 3 `.settings-toggle` switches under
    // "Suppression automatique": Corbeille 30j (auto_empty_trash_30d),
    // Indésirables 30j (auto_empty_spam_30d), Noise 30j (auto_delete_noise_30d).
    // The former auto-draft / auto-archive / hide-noise toggles were removed or
    // moved: hide-noise → Général, auto-archive → a Quick Step ("Archive after
    // reply"), and auto-draft was retired. The "Règles automatiques" block above
    // uses .quickstep-card__toggle (a different class), not .settings-toggle.
    const count = await toggles.count()
    expect(count).toBeGreaterThanOrEqual(3)
  })

  test('toggle 1 (brouillons auto) fonctionne', async ({ page }) => {
    // "Brouillons auto pour les emails Action"
    const toggle = page.locator('.settings-toggle').nth(0)
    await expect(toggle).toBeVisible({ timeout: 5000 })
    const checkbox = toggle.locator('input[type="checkbox"]')
    const before = await checkbox.isChecked()
    await toggle.click()
    await page.waitForTimeout(500)
    expect(await checkbox.isChecked()).not.toBe(before)
  })

  test('toggle 2 (auto-archiver) fonctionne', async ({ page }) => {
    // "Auto-archiver après réponse"
    const toggle = page.locator('.settings-toggle').nth(1)
    await expect(toggle).toBeVisible({ timeout: 5000 })
    const checkbox = toggle.locator('input[type="checkbox"]')
    const before = await checkbox.isChecked()
    await toggle.click()
    await page.waitForTimeout(500)
    expect(await checkbox.isChecked()).not.toBe(before)
  })

  test('toggle 3 (masquer noise) fonctionne', async ({ page }) => {
    // "Masquer le Noise"
    const toggle = page.locator('.settings-toggle').nth(2)
    await expect(toggle).toBeVisible({ timeout: 5000 })
    const checkbox = toggle.locator('input[type="checkbox"]')
    const before = await checkbox.isChecked()
    await toggle.click()
    await page.waitForTimeout(500)
    expect(await checkbox.isChecked()).not.toBe(before)
  })

  // Only 3 `.settings-toggle` switches remain (indices 0/1/2 = Corbeille,
  // Indésirables, Noise — already covered by "toggle 1/2/3" above). Indices 3/4
  // no longer exist, and the "Brouillons après 7 jours" toggle was removed from
  // this section (drafts cleanup is a Quick Step now). Skip the stale indices.
  test.skip('toggle 4 (corbeille 30j) fonctionne', async ({ page }) => {
    // "Corbeille après 30 jours"
    const toggle = page.locator('.settings-toggle').nth(3)
    await expect(toggle).toBeVisible({ timeout: 5000 })
    const checkbox = toggle.locator('input[type="checkbox"]')
    const before = await checkbox.isChecked()
    await toggle.click()
    await page.waitForTimeout(500)
    expect(await checkbox.isChecked()).not.toBe(before)
  })

  test.skip('toggle 5 (indésirables 30j) fonctionne', async ({ page }) => {
    // "Indésirables après 30 jours"
    const toggle = page.locator('.settings-toggle').nth(4)
    await expect(toggle).toBeVisible({ timeout: 5000 })
    const checkbox = toggle.locator('input[type="checkbox"]')
    const before = await checkbox.isChecked()
    await toggle.click()
    await page.waitForTimeout(500)
    expect(await checkbox.isChecked()).not.toBe(before)
  })

  test.skip('toggle 6 (brouillons 7j) fonctionne', async ({ page }) => {
    // "Brouillons après 7 jours"
    const toggle = page.locator('.settings-toggle').nth(5)
    await expect(toggle).toBeVisible({ timeout: 5000 })
    const checkbox = toggle.locator('input[type="checkbox"]')
    const before = await checkbox.isChecked()
    await toggle.click()
    await page.waitForTimeout(500)
    expect(await checkbox.isChecked()).not.toBe(before)
  })

  test('toggle envoie PATCH au backend', async ({ page }) => {
    settingsPatchCalls = []
    const toggle = page.locator('.settings-toggle').first()
    await toggle.click()
    await page.waitForTimeout(1000)
    expect(settingsPatchCalls.length).toBeGreaterThan(0)
  })

  test('sous-titres de section visibles', async ({ page }) => {
    const subtitles = page.locator('h4.settings-subtitle')
    await subtitles.first().waitFor({ state: 'visible', timeout: 5000 })
    expect(await subtitles.count()).toBeGreaterThanOrEqual(2)
  })

  test('toggle PATCH envoie le bon field name', async ({ page }) => {
    settingsPatchCalls = []
    // Toggle 0 is now "Corbeille après 30 jours" → useAutoEmptyTrashSetting,
    // which PATCHes { auto_empty_trash_30d: <bool> } (see createSettingHook +
    // useAutoEmptyTrashSetting). The former auto_draft_enabled toggle is gone.
    await page.locator('.settings-toggle').nth(0).click()
    await page.waitForTimeout(1000)
    expect(settingsPatchCalls.length).toBeGreaterThan(0)
    const body = settingsPatchCalls[0].body as Record<string, unknown>
    expect('auto_empty_trash_30d' in body).toBe(true)
  })
})

// ============================================================================
// SECTION: Général (index 5) — theme, language, LLM
// ============================================================================

test.describe('Settings > General', () => {
  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openSettings(page)
    await clickSidebarItem(page, 5)
  })

  test('affiche le theme picker', async ({ page }) => {
    const themePicker = page.locator('.settings-theme-picker, .settings-theme-options').first()
    await expect(themePicker).toBeVisible({ timeout: 5000 })
  })

  test('affiche une seule option de theme (Clarity)', async ({ page }) => {
    const themeOptions = page.locator('.theme-option-card')
    await themeOptions.first().waitFor({ state: 'visible', timeout: 5000 })
    expect(await themeOptions.count()).toBe(1)
    await expect(themeOptions.first()).toContainText('Clarity')
  })

  test('theme Clarity est actif par defaut', async ({ page }) => {
    const activeTheme = page.locator('.theme-option-card.active')
    await expect(activeTheme).toBeVisible({ timeout: 5000 })
    await expect(activeTheme).toContainText('Clarity')
  })

  // The "About / version" section was removed from the Général tab. The
  // .settings-about / .about-info classes survive only as dead CSS in
  // Settings.css — no TSX renders them anymore. Skip until a version/about
  // section is reintroduced.
  test.skip('affiche la section info (version)', async ({ page }) => {
    // The about section has version info
    const aboutSection = page.locator('.settings-about, .about-info').first()
    await expect(aboutSection).toBeVisible({ timeout: 5000 })
  })

  test('language selector visible avec 2 options', async ({ page }) => {
    // FR / EN only. Spanish and German are hidden until fully productized.
    const selector = page.locator('.settings-language-selector, .language-options').first()
    await expect(selector).toBeVisible({ timeout: 5000 })
    const buttons = page.locator('.language-option-btn')
    await buttons.first().waitFor({ state: 'visible', timeout: 5000 })
    expect(await buttons.count()).toBe(2)
  })

  test('language button active par defaut', async ({ page }) => {
    const activeBtn = page.locator('.language-option-btn.active')
    await expect(activeBtn.first()).toBeVisible({ timeout: 5000 })
  })

  // AI Provider / LLM settings section is intentionally hidden in the UI
  // (Settings.tsx: "AI Provider section hidden — Claude is the default and the
  // picker confuses non-power users"). Skip until it becomes user-facing again.
  test.skip('LLM settings section visible', async ({ page }) => {
    const llm = page.locator('.llm-settings').first()
    await expect(llm).toBeVisible({ timeout: 5000 })
  })

  test.skip('LLM provider radio buttons visibles', async ({ page }) => {
    const radios = page.locator('.llm-settings input[type="radio"], .llm-settings-option input[type="radio"]')
    await radios.first().waitFor({ state: 'attached', timeout: 5000 })
    expect(await radios.count()).toBeGreaterThanOrEqual(2)
  })

  test.skip('LLM test connection button visible', async ({ page }) => {
    const testBtn = page.locator('.llm-settings-btn-test, .llm-settings-btn.llm-settings-btn-test').first()
    await expect(testBtn).toBeVisible({ timeout: 5000 })
  })

  test('autostart toggle hidden in browser (Tauri only)', async ({ page }) => {
    // AutostartToggle returns null when not in Tauri context — verify no crash
    const autostart = page.locator('.autostart-toggle')
    // Should not be visible (returns null in browser), but page should not crash
    await expect(page.locator('.settings').first()).toBeVisible()
    expect(await autostart.count()).toBe(0)
  })

  test('referral panel hidden without subscription data', async ({ page }) => {
    // ReferralPanel returns null when no referral stats — verify no crash
    const referral = page.locator('[data-testid="referral-panel"]')
    await expect(page.locator('.settings').first()).toBeVisible()
    expect(await referral.count()).toBe(0)
  })
})

// ============================================================================
// NAVIGATION: Switching between sections
// ============================================================================

test.describe('Settings > Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await setupAllMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openSettings(page)
  })

  test('sidebar affiche toutes les sections', async ({ page }) => {
    const items = page.locator('.settings-sidebar-item')
    await items.first().waitFor({ state: 'visible', timeout: 5000 })
    const count = await items.count()
    expect(count).toBe(6) // Compte, Personnalisation, Outils, Productivité, Automatisation, Général
  })

  test('chaque section se charge sans erreur', async ({ page }) => {
    const items = page.locator('.settings-sidebar-item')
    const count = await items.count()
    for (let i = 0; i < count; i++) {
      await items.nth(i).click()
      await page.waitForTimeout(300)
      // Settings should still be visible (no crash)
      await expect(page.locator('.settings').first()).toBeVisible()
    }
  })

  test('fermeture avec le bouton X', async ({ page }) => {
    const closeBtn = page.locator('.settings-close')
    await closeBtn.click()
    await expect(page.locator('.settings')).not.toBeVisible({ timeout: 5000 })
  })

  test('fermeture avec Escape', async ({ page }) => {
    await page.keyboard.press('Escape')
    await expect(page.locator('.settings')).not.toBeVisible({ timeout: 5000 })
  })
})

// ============================================================================
// CONSOLE ERRORS: Verify no JS errors during settings navigation
// ============================================================================

test.describe('Settings > Console Errors', () => {
  test('pas d\'erreurs console critiques lors de la navigation settings', async ({ page }) => {
    const errors: string[] = []
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        const text = msg.text()
        // Ignore known non-critical errors
        if (
          text.includes('favicon') ||
          text.includes('socket') ||
          text.includes('WebSocket') ||
          text.includes('DialogTitle') ||       // Radix UI accessibility warning
          text.includes('DialogContent') ||
          text.includes('VisuallyHidden') ||
          text.includes('net::ERR') ||
          text.includes('ERR_CONNECTION_REFUSED') ||
          text.includes('Failed to load signature')
        ) return
        errors.push(text)
      }
    })

    await setupAllMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openSettings(page)

    // Navigate through all sections
    const items = page.locator('.settings-sidebar-item')
    const count = await items.count()
    for (let i = 0; i < count; i++) {
      await items.nth(i).click()
      await page.waitForTimeout(500)
    }

    // Open signature modal from Compte section
    await items.nth(0).click()
    await page.waitForTimeout(300)
    const signatureBtn = page.locator('.settings-link-btn').filter({ hasText: /Signature/i }).first()
    await expect(signatureBtn).toBeVisible({ timeout: 2000 })
    await signatureBtn.click()
    await page.waitForTimeout(1500)
    // The signature modal's cancel/close affordance is the header × button
    // (.sig-close → handleCancel); there is no .sig-btn-cancel class anymore.
    const sigClose = page.locator('.sig-close')
    await expect(sigClose).toBeVisible({ timeout: 1000 })
    await sigClose.click()

    expect(errors).toEqual([])
  })
})
