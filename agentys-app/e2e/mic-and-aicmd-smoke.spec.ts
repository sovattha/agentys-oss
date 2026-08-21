/**
 * Smoke test — Mic button + AICommandMenu (baguette magique)
 *
 * Valide dans CHAQUE composer :
 *   (a) `.nmm-mic-btn` visible dans le footer
 *   (b) `[data-testid="ai-command-trigger"]` visible à côté
 *   (c) clic mic → classe `nmm-mic-recording` (toggle on/off)
 *   (d) clic wand → popover `.ai-cmd-popover` (ouvre / Escape ferme)
 *
 * Couvre : NewMessageModal, ReplyComposer (reply + reply_all + forward),
 *          PendingDraftDetail.
 *
 * Utilise le backend réel (port 5050) + login dev. Le PDD injecte un mock
 * draft via interception de /api/pending-drafts au niveau localhost:1420
 * (le frontend requête en same-origin et Vite proxy vers :5050).
 */

import { test, expect, Page } from '@playwright/test'

const API = 'http://127.0.0.1:5050'
const FRONTEND = 'http://localhost:1420'

// ─── Mock Data ─────────────────────────────────────────────────────────────

const MOCK_EMAIL_ID = 'mock-email-mic-test'

const mockPendingDraft = {
  id: 'mock-draft-mic-1',
  email_id: MOCK_EMAIL_ID,
  email_sender: 'alice@example.com',
  email_sender_name: 'Alice Example',
  email_subject: 'Question projet Q2',
  email_body: '<p>Bonjour, peux-tu valider le planning Q2 ?</p>',
  email_received_at: new Date().toISOString(),
  draft_subject: 'Re: Question projet Q2',
  draft_body: 'Bonjour Alice,\n\nOui, le planning est validé.\n\nCordialement',
  draft_v1: 'Oui, validé.',
  critique: 'Score: 85/100. VALID.',
  conversation_history_count: 0,
  routing_tier: 'STANDARD',
  classification: 'action',
  priority: 1,
  confidence: 0.9,
  smart_suggestions: null,
  quick_replies: null,
  status: 'pending',
  account_id: '1',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
}

const mockEmailDetail = {
  id: MOCK_EMAIL_ID,
  sender: 'alice@example.com',
  sender_name: 'Alice Example',
  subject: 'Question projet Q2',
  body: '<p>Bonjour, peux-tu valider le planning Q2 ?</p>',
  body_html: '<p>Bonjour, peux-tu valider le planning Q2 ?</p>',
  body_preview: 'Bonjour, peux-tu valider le planning Q2 ?',
  received_at: new Date().toISOString(),
  has_attachments: false,
  conversation_id: null,
  is_read: false,
  to: ['test@example.com'],
  cc: [],
  attachments: [],
  labels: [],
}

const mockEmailListItem = {
  id: mockEmailDetail.id,
  sender: mockEmailDetail.sender,
  sender_name: mockEmailDetail.sender_name,
  subject: mockEmailDetail.subject,
  body_preview: mockEmailDetail.body_preview,
  received_at: mockEmailDetail.received_at,
  has_attachments: mockEmailDetail.has_attachments,
  conversation_id: mockEmailDetail.conversation_id,
  is_read: mockEmailDetail.is_read,
  labels: mockEmailDetail.labels,
}

const mockEmailsResponse = {
  count: 1,
  emails: [mockEmailListItem],
}

// ─── Setup ─────────────────────────────────────────────────────────────────

async function authenticateAndGoto(page: Page) {
  const res = await page.request.post(`${API}/api/auth/dev-login`, { data: { email: 'test@example.com' } })
  const { access_token } = await res.json()
  await page.addInitScript(token => {
    localStorage.setItem('agentys_jwt', token)
    localStorage.setItem('agentys_onboarding_complete', 'true')
    localStorage.setItem('agentys_onboarding_kb_complete', 'true')
    localStorage.setItem('agentys_onboarding_v2_complete', 'true')
    localStorage.setItem('agentys_language', 'fr')
  }, access_token)

  // Mock MediaRecorder + AudioContext + getUserMedia so mic "records" without device
  await page.addInitScript(() => {
    const fakeTrack = { stop: () => {}, kind: 'audio' as const, enabled: true }
    const fakeStream = { getTracks: () => [fakeTrack] } as unknown as MediaStream
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia: async () => fakeStream, enumerateDevices: async () => [] },
      writable: true,
    })
    class FakeAudioContext {
      createMediaStreamSource() { return { connect: () => {} } }
      createAnalyser() {
        return {
          fftSize: 256, smoothingTimeConstant: 0, frequencyBinCount: 128,
          getByteFrequencyData: (arr: Uint8Array) => arr.fill(0),
        }
      }
      close() { return Promise.resolve() }
    }
    ;(window as unknown as Record<string, unknown>).AudioContext = FakeAudioContext
    class FakeMediaRecorder {
      state: 'inactive' | 'recording' = 'inactive'
      mimeType = 'audio/webm'
      ondataavailable: ((e: { data: Blob }) => void) | null = null
      onstop: (() => void) | null = null
      static isTypeSupported() { return true }
      start() { this.state = 'recording' }
      stop() {
        this.state = 'inactive'
        const blob = new Blob([new Uint8Array(64)], { type: 'audio/webm' })
        this.ondataavailable?.({ data: blob })
        setTimeout(() => this.onstop?.(), 0)
      }
    }
    ;(window as unknown as Record<string, unknown>).MediaRecorder = FakeMediaRecorder
  })

  await page.route(url => url.pathname === '/api/billing/me', route => route.fulfill({
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
  }))

  await page.route(url => url.pathname === '/api/init', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      emails: mockEmailsResponse,
      label_counts: { counts: {}, total: 1 },
      pending_drafts: { drafts: [], pending_count: 0 },
      accounts: [{ id: 1, email: 'test@example.com', status: 'active' }],
    }),
  }))
  await page.route(url => url.pathname === '/api/emails', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(mockEmailsResponse),
  }))
  await page.route(url => url.pathname === `/api/emails/${MOCK_EMAIL_ID}`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(mockEmailDetail),
  }))
  await page.route(url => url.pathname === `/api/emails/${MOCK_EMAIL_ID}/read`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true }),
  }))
  await page.route(url => url.pathname === `/api/emails/${MOCK_EMAIL_ID}/thread`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ count: 1, emails: [] }),
  }))
  await page.route(url => url.pathname.startsWith('/api/pending-drafts/by-email'), route => route.fulfill({
    status: 404,
    contentType: 'application/json',
    body: JSON.stringify({ error: 'No draft' }),
  }))

  await page.goto('/')
  await page.locator('[data-testid="nav-inbox"]').waitFor({ state: 'visible', timeout: 15000 })
}

/**
 * Intercepts same-origin /api/pending-drafts* calls and returns mock data,
 * so PDD can be opened even when the real backend has no pending drafts
 * for the test user.
 */
async function interceptPendingDraftsWithMock(page: Page) {
  // List endpoint — must return the mock as sole draft
  await page.route(url => url.href.startsWith(`${FRONTEND}/api/pending-drafts?`) || url.href === `${FRONTEND}/api/pending-drafts`,
    route => {
      if (route.request().method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ count: 1, drafts: [mockPendingDraft], pending_count: 1 }),
        })
      } else {
        route.continue()
      }
    }
  )

  // Detail endpoint
  await page.route(url => url.href === `${FRONTEND}/api/pending-drafts/${mockPendingDraft.id}`,
    route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(mockPendingDraft),
    })
  )

  // by-email lookup used by composer mount
  await page.route(url => url.href.startsWith(`${FRONTEND}/api/pending-drafts/by-email`),
    route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(mockPendingDraft),
    })
  )

  // Linked email detail — fetched by PDD's EmailDetailModal side-panel
  await page.route(url => url.href === `${FRONTEND}/api/emails/${MOCK_EMAIL_ID}`,
    route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(mockEmailDetail),
    })
  )
  await page.route(url => url.href === `${FRONTEND}/api/emails/${MOCK_EMAIL_ID}/thread`,
    route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ count: 1, emails: [] }),
    })
  )
  await page.route(url => url.href === `${FRONTEND}/api/emails/${MOCK_EMAIL_ID}/read`,
    route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
  )
}

// ─── Navigation ────────────────────────────────────────────────────────────

async function openNewMessage(page: Page) {
  await page.locator('[data-testid="compose-button"]').click()
  await page.locator('.new-message-modal').first().waitFor({ state: 'visible', timeout: 10000 })
}

async function openReplyMode(page: Page, mode: 'reply' | 'reply_all' | 'forward') {
  await page.locator('[data-testid="email-item"]').first().click()
  await page.locator('.email-detail-body, .email-detail-title').first().waitFor({ state: 'visible', timeout: 10000 })
  const key = mode === 'reply' ? 'r' : mode === 'reply_all' ? 'a' : 'f'
  await page.keyboard.press(key)
  await page.locator('[data-testid="reply-composer"], .reply-composer').first().waitFor({ state: 'visible', timeout: 10000 })
}

async function openPendingDraft(page: Page) {
  await page.locator('[data-testid="nav-drafts"]').click()
  const firstDraft = page.locator('[data-testid="draft-item"]').first()
  await firstDraft.waitFor({ state: 'visible', timeout: 15000 })
  await firstDraft.click()
  await page.locator('.pending-draft-detail, .draft-card').first().waitFor({ state: 'visible', timeout: 10000 })
}

// ─── Assertions ────────────────────────────────────────────────────────────

function mic(page: Page) { return page.locator('.nmm-mic-btn').last() }
function wand(page: Page) { return page.locator('[data-testid="ai-command-trigger"]').last() }

async function assertVisible(page: Page, scope: string) {
  await expect(mic(page), `[${scope}] mic`).toBeVisible({ timeout: 5000 })
  await expect(wand(page), `[${scope}] wand`).toBeVisible({ timeout: 5000 })
}

async function assertMicToggle(page: Page, scope: string) {
  const m = mic(page)
  await m.click()
  const continueButton = page.getByRole('button', { name: /continuer|continue/i }).last()
  if (await continueButton.waitFor({ state: 'visible', timeout: 1500 }).then(() => true).catch(() => false)) {
    await continueButton.click()
  }
  await expect(m, `[${scope}] recording class on`).toHaveClass(/nmm-mic-recording/, { timeout: 3000 })
  await m.click()
  await expect(m, `[${scope}] recording class off`).not.toHaveClass(/nmm-mic-recording/, { timeout: 5000 })
}

async function assertWandOpens(page: Page, scope: string) {
  const trigger = wand(page)
  await expect(trigger, `[${scope}] wand enabled`).toBeEnabled({ timeout: 5000 })
  await trigger.click()
  const popover = page.locator('.ai-cmd-popover').first()
  await expect(popover, `[${scope}] popover visible`).toBeVisible({ timeout: 3000 })
  await page.keyboard.press('Escape')
  await expect(popover, `[${scope}] popover closes`).not.toBeVisible({ timeout: 3000 })
}

// ─── Tests ─────────────────────────────────────────────────────────────────

test.describe('NewMessageModal', () => {
  test('mic + wand : visibles + toggle + popover', async ({ page }) => {
    await authenticateAndGoto(page)
    await openNewMessage(page)
    await assertVisible(page, 'NewMessage')
    await assertMicToggle(page, 'NewMessage')
    await assertWandOpens(page, 'NewMessage')
  })
})

test.describe('ReplyComposer — Reply', () => {
  test('mic + wand : visibles + toggle + popover', async ({ page }) => {
    await authenticateAndGoto(page)
    await openReplyMode(page, 'reply')
    await assertVisible(page, 'Reply')
    await assertMicToggle(page, 'Reply')
    await assertWandOpens(page, 'Reply')
  })
})

test.describe('ReplyComposer — Reply All', () => {
  test('mic + wand : visibles + toggle + popover', async ({ page }) => {
    await authenticateAndGoto(page)
    await openReplyMode(page, 'reply_all')
    await assertVisible(page, 'ReplyAll')
    await assertMicToggle(page, 'ReplyAll')
    await assertWandOpens(page, 'ReplyAll')
  })
})

test.describe('ReplyComposer — Forward', () => {
  test('mic + wand : visibles + toggle + popover', async ({ page }) => {
    await authenticateAndGoto(page)
    await openReplyMode(page, 'forward')
    await assertVisible(page, 'Forward')
    await assertMicToggle(page, 'Forward')
    await assertWandOpens(page, 'Forward')
  })
})

test.describe('PendingDraftDetail', () => {
  test('mic + wand : visibles + toggle + popover (mock draft)', async ({ page }) => {
    await authenticateAndGoto(page)
    await interceptPendingDraftsWithMock(page)
    await openPendingDraft(page)
    await assertVisible(page, 'PendingDraft')
    await assertMicToggle(page, 'PendingDraft')
    await assertWandOpens(page, 'PendingDraft')
  })
})
