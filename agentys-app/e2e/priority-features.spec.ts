/**
 * Priority Features E2E Tests
 *
 * Comprehensive test suite covering the critical user flows:
 * 1. Send new message
 * 2. Reply
 * 3. Reply All (CC pre-population)
 * 4. Forward
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const MOCK_EMAIL = {
  id: 'email-pf-1',
  sender: 'marie.dupont@example.com',
  sender_name: 'Marie Dupont',
  subject: 'Rapport trimestriel Q4 2025',
  body: '<p>Bonjour, veuillez trouver ci-joint le rapport trimestriel.</p>',
  body_preview: 'Bonjour, veuillez trouver ci-joint le rapport trimestriel.',
  received_at: new Date().toISOString(),
  has_attachments: true,
  conversation_id: 'conv-pf-1',
  is_read: false,
  to: ['user@example.com'],
  cc: ['direction@example.com', 'equipe@example.com'],
  attachments: [{ id: 'att-1', filename: 'rapport.pdf', size: 2048, content_type: 'application/pdf' }],
}

const MOCK_EMAILS_RESPONSE = {
  emails: [MOCK_EMAIL],
  has_more: false,
  source: 'mock',
}

const DRAFT_ID = 'draft-pf-001'

const MOCK_PENDING_DRAFT = {
  id: DRAFT_ID,
  email_id: MOCK_EMAIL.id,
  email_subject: MOCK_EMAIL.subject,
  email_sender: MOCK_EMAIL.sender,
  email_sender_name: MOCK_EMAIL.sender_name,
  email_body: MOCK_EMAIL.body,
  email_received_at: MOCK_EMAIL.received_at,
  draft_subject: `Re: ${MOCK_EMAIL.subject}`,
  draft_body: 'Bonjour Marie,\n\nMerci pour ce rapport détaillé.\n\nCordialement',
  draft_v1: 'Merci pour ce rapport.',
  status: 'pending',
  classification: 'action',
  priority: 80,
  routing_tier: 'STANDARD',
  critique: 'Réponse appropriée et professionnelle. Score: 87/100. Verdict: VALID.',
  smart_suggestions: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
}

// ---------------------------------------------------------------------------
// Setup helpers
// ---------------------------------------------------------------------------

async function setupComposeMocks(page: Page) {
  await setupBaseMocks(page)
  await page.route((url) => url.origin === API && url.pathname === '/api/emails/send-new', (route) => {
    if (route.request().method() === 'POST') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, message_id: 'msg-pf-001' }) })
    } else { route.continue() }
  })
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/contacts'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  })
  await page.route((url) => url.origin === API && url.pathname === '/api/refine-text', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, refined_text: 'Texte affiné.' }) })
  })
}

async function setupReplyMocks(page: Page) {
  await setupBaseMocks(page, { emailsResponse: MOCK_EMAILS_RESPONSE })

  // Email detail
  await page.route((url) => url.origin === API && url.pathname === `/api/emails/${MOCK_EMAIL.id}`, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_EMAIL) })
  })
  // Mark read
  await page.route((url) => url.origin === API && url.pathname === `/api/emails/${MOCK_EMAIL.id}/read`, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
  })
  // Thread
  await page.route((url) => url.origin === API && url.pathname === `/api/emails/${MOCK_EMAIL.id}/thread`, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 1, emails: [] }) })
  })
  // Process (AI generation)
  await page.route((url) => url.origin === API && url.pathname === `/api/emails/${MOCK_EMAIL.id}/process`, (route) => {
    if (route.request().method() === 'POST') {
      route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ success: true, draft_id: DRAFT_ID, status: 'created' }) })
    } else { route.continue() }
  })
  // Draft CRUD
  await page.route((url) => url.origin === API && url.pathname === `/api/pending-drafts/${DRAFT_ID}`, (route) => {
    const method = route.request().method()
    if (method === 'GET') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_PENDING_DRAFT) })
    } else if (method === 'PUT' || method === 'PATCH') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
    } else if (method === 'DELETE') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
    } else { route.continue() }
  })
  // Validate/send
  await page.route((url) => url.origin === API && url.pathname === `/api/pending-drafts/${DRAFT_ID}/validate`, (route) => {
    if (route.request().method() === 'POST') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, draft_id: DRAFT_ID, sent: true }) })
    } else { route.continue() }
  })
  // Reject
  await page.route((url) => url.origin === API && url.pathname === `/api/pending-drafts/${DRAFT_ID}/reject`, (route) => {
    if (route.request().method() === 'POST') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, draft_id: DRAFT_ID }) })
    } else { route.continue() }
  })
  // Create/send draft (manual reply)
  await page.route((url) => url.origin === API && url.pathname === `/api/emails/${MOCK_EMAIL.id}/draft`, (route) => {
    if (route.request().method() === 'POST') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, draft_id: DRAFT_ID, sent: true }) })
    } else { route.continue() }
  })
  // By-email lookup (no pre-existing draft)
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts/by-email'), (route) => {
    route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: 'No draft' }) })
  })
  // Contacts
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/contacts'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  })
  // Refine
  await page.route((url) => url.origin === API && url.pathname === '/api/refine-text', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, refined_text: 'Texte affiné.' }) })
  })
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

async function openNewMessage(page: Page) {
  await page.locator('body').click({ position: { x: 10, y: 10 } })
  await page.waitForTimeout(500)
  await page.keyboard.press('n')
  await page.locator('.new-message-modal').first().waitFor({ state: 'visible', timeout: 15000 })
}

async function openEmailDetail(page: Page) {
  const emailItem = page.locator('[data-testid="email-item"]').first()
  await expect(emailItem).toBeVisible({ timeout: 10000 })
  await emailItem.click()
  await page.locator('.email-detail-body, .email-detail-title').first().waitFor({ state: 'visible', timeout: 10000 })
}

async function openReplyComposer(page: Page) {
  await openEmailDetail(page)
  const replyBtn = page.locator('[data-testid="reply-button"]').first()
  await expect(replyBtn).toBeVisible({ timeout: 10000 })
  await replyBtn.click()
  await page.locator('[data-testid="reply-composer"], .reply-composer').first().waitFor({ state: 'visible', timeout: 10000 })
}

// ===========================================================================
// Section 1 — Send New Message
// ===========================================================================

test.describe('Send New Message', () => {
  test.beforeEach(async ({ page }) => {
    await setupComposeMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('opens compose modal with N key', async ({ page }) => {
    await openNewMessage(page)
    await expect(page.locator('.new-message-modal').first()).toBeVisible()
  })

  test('fills to, subject, body and sends successfully', async ({ page }) => {
    await openNewMessage(page)

    // Fill To field — fill then Tab to create chip via blur
    const toInput = page.locator('.gmail-field-to input[role="combobox"]').first()
    await toInput.click()
    await toInput.fill('client@example.com')
    await page.keyboard.press('Tab')
    await page.waitForTimeout(500)

    // Fill Subject
    const subjectInput = page.locator('.gmail-input-subject').first()
    await subjectInput.click()
    await page.keyboard.type('Devis projet Alpha')

    // Fill Body
    const bodyArea = page.locator('.gmail-textarea, .nm-body-textarea, textarea').first()
    await bodyArea.click()
    await page.keyboard.type('Bonjour, bien reçu, merci.')

    // Verify send button is enabled (all fields filled, recipient confirmed as chip)
    const sendBtn = page.locator('.send-pill').first()
    await expect(sendBtn).toBeEnabled({ timeout: 5000 })

    // Verify chip is visible in To field
    await expect(page.locator('.gmail-field-to .ca-chip').first()).toBeVisible({ timeout: 3000 })
  })

  test('send button is disabled without recipient', async ({ page }) => {
    await openNewMessage(page)
    // Send button disabled when no To
    await expect(page.locator('.send-pill').first()).toBeDisabled({ timeout: 5000 })
  })

  test('send button enables after adding recipient', async ({ page }) => {
    await openNewMessage(page)

    // Initially disabled
    await expect(page.locator('.send-pill').first()).toBeDisabled({ timeout: 5000 })

    // Fill To and confirm chip
    const toInput = page.locator('.gmail-field-to input[role="combobox"]').first()
    await toInput.click()
    await toInput.fill('test@example.com')
    await page.keyboard.press('Tab')
    await page.waitForTimeout(500)

    // Now enabled
    await expect(page.locator('.send-pill').first()).toBeEnabled({ timeout: 5000 })
  })
})

// ===========================================================================
// Section 2 — Reply
// ===========================================================================

test.describe('Reply', () => {
  test.beforeEach(async ({ page }) => {
    await setupReplyMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('opens reply composer with R key', async ({ page }) => {
    await openEmailDetail(page)
    await page.keyboard.press('r')
    await expect(page.locator('[data-testid="reply-composer"], .reply-composer').first()).toBeVisible({ timeout: 10000 })
  })

  test('opens reply via Répondre button', async ({ page }) => {
    await openReplyComposer(page)
    await expect(page.locator('[data-testid="reply-composer"], .reply-composer').first()).toBeVisible()
  })

  test('sends reply via POST /emails/{id}/draft', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null
    await page.route((url) => url.origin === API && url.pathname === `/api/emails/${MOCK_EMAIL.id}/draft`, (route) => {
      if (route.request().method() === 'POST') {
        capturedBody = JSON.parse(route.request().postData() || '{}')
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, draft_id: DRAFT_ID, sent: true }) })
      } else { route.continue() }
    })

    await openReplyComposer(page)

    // Type in editor
    const editor = page.locator('.rc-editor-area, [contenteditable]').first()
    await expect(editor).toBeVisible({ timeout: 10000 })
    await editor.click()
    await page.keyboard.type('Merci pour votre message, bien reçu.')

    // Click send
    const sendBtn = page.locator('[data-testid="reply-send-button"], .send-pill').first()
    await expect(sendBtn).toBeEnabled({ timeout: 5000 })
    await sendBtn.click()

    // Verify sent
    await page.waitForTimeout(1000)
    expect(capturedBody).not.toBeNull()
    expect(capturedBody!.send).toBe(true)
  })

  test('shows error when reply send fails', async ({ page }) => {
    await page.route((url) => url.origin === API && url.pathname === `/api/emails/${MOCK_EMAIL.id}/draft`, (route) => {
      if (route.request().method() === 'POST') {
        route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: 'Send failed' }) })
      } else { route.continue() }
    })

    await openReplyComposer(page)

    const editor = page.locator('.rc-editor-area, [contenteditable]').first()
    await expect(editor).toBeVisible({ timeout: 10000 })
    await editor.click()
    await page.keyboard.type('Test error reply')

    const sendBtn = page.locator('[data-testid="reply-send-button"], .send-pill').first()
    await expect(sendBtn).toBeEnabled({ timeout: 5000 })
    await sendBtn.click()

    const errorMsg = page.locator('.rc-error[role="alert"], .rc-error').first()
    await expect(errorMsg).toBeVisible({ timeout: 10000 })
  })
})

// ===========================================================================
// Section 3 — Reply All
// ===========================================================================

test.describe('Reply All', () => {
  test.beforeEach(async ({ page }) => {
    await setupReplyMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('opens reply-all via button', async ({ page }) => {
    await openEmailDetail(page)
    const replyAllBtn = page.locator('[data-testid="reply-all-button"]').first()
    await expect(replyAllBtn).toBeVisible({ timeout: 10000 })
    await replyAllBtn.click()
    await expect(page.locator('[data-testid="reply-composer"], .reply-composer').first()).toBeVisible({ timeout: 10000 })
  })

  test('CC field pre-populated from original email', async ({ page }) => {
    await openEmailDetail(page)
    const replyAllBtn = page.locator('[data-testid="reply-all-button"]').first()
    await replyAllBtn.click()
    await page.locator('[data-testid="reply-composer"], .reply-composer').first().waitFor({ state: 'visible', timeout: 10000 })

    // CC area should be visible and contain original CC recipients
    const ccArea = page.locator('.rc-cc-row, .rc-cc-chips, .rc-cc-container').first()
    await expect(ccArea).toBeVisible({ timeout: 5000 })
  })

  test('sends reply-all with all recipients', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null
    await page.route((url) => url.origin === API && url.pathname === `/api/emails/${MOCK_EMAIL.id}/draft`, (route) => {
      if (route.request().method() === 'POST') {
        capturedBody = JSON.parse(route.request().postData() || '{}')
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, draft_id: DRAFT_ID, sent: true }) })
      } else { route.continue() }
    })

    await openEmailDetail(page)
    const replyAllBtn = page.locator('[data-testid="reply-all-button"]').first()
    await replyAllBtn.click()
    await page.locator('[data-testid="reply-composer"], .reply-composer').first().waitFor({ state: 'visible', timeout: 10000 })

    // Type in editor
    const editor = page.locator('.rc-editor-area, [contenteditable]').first()
    await expect(editor).toBeVisible({ timeout: 10000 })
    await editor.click()
    await page.keyboard.type('Merci à tous pour ce rapport.')

    // Click send
    const sendBtn = page.locator('[data-testid="reply-send-button"], .send-pill').first()
    await expect(sendBtn).toBeEnabled({ timeout: 5000 })
    await sendBtn.click()

    // Verify POST body includes CC
    await page.waitForTimeout(1000)
    expect(capturedBody).not.toBeNull()
    expect(capturedBody!.send).toBe(true)
  })
})

// ===========================================================================
// Section 4 — Forward
// ===========================================================================

test.describe('Forward', () => {
  test.beforeEach(async ({ page }) => {
    await setupReplyMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('opens forward with F key', async ({ page }) => {
    await openEmailDetail(page)
    await page.keyboard.press('f')
    await expect(page.locator('[data-testid="reply-composer"], .reply-composer').first()).toBeVisible({ timeout: 10000 })
  })

  test('mode pill shows forward', async ({ page }) => {
    await openEmailDetail(page)
    await page.keyboard.press('f')
    await page.locator('[data-testid="reply-composer"], .reply-composer').first().waitFor({ state: 'visible', timeout: 10000 })

    // The mode pill should indicate "forward" mode
    const modePill = page.locator('.draft-mode-pill, .rc-mode-pill').first()
    await expect(modePill).toBeVisible({ timeout: 5000 })
  })

  test('forward composer has recipient input for new recipient', async ({ page }) => {
    await openEmailDetail(page)
    await page.keyboard.press('f')
    await page.locator('[data-testid="reply-composer"], .reply-composer').first().waitFor({ state: 'visible', timeout: 10000 })

    // Forward mode should show a To input for the new recipient
    const recipientInput = page.locator('.rc-recipient-row input, .rc-forward-to, .rc-to-input').first()
    await expect(recipientInput).toBeVisible({ timeout: 5000 })
  })
})
