/**
 * Email Send, Reply, Reply All, Forward & Slash Commands E2E Tests
 *
 * Comprehensive tests for all email composition flows:
 * - Send new email
 * - Reply to an email
 * - Reply All
 * - Forward
 * - All slash commands in compose and reply modes
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'
import { mockEmailsResponse, mockEmailDetails } from './support/fixtures/mock-data'

const API = 'http://127.0.0.1:5050'

// ── Mock Setup ──────────────────────────────────────────────────────────────

async function setupFullMocks(page: Page) {
  await setupBaseMocks(page, { emailsResponse: mockEmailsResponse })

  // Mock email detail endpoint
  await page.route(
    (url) => url.origin === API && /^\/api\/emails\/[^/]+$/.test(url.pathname),
    (route) => {
      const url = new URL(route.request().url())
      const id = url.pathname.split('/').pop() || 'email-1'
      const detail = mockEmailDetails[id] || mockEmailDetails['email-1']
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(detail),
      })
    }
  )

  // Mock send new email
  await page.route(
    (url) => url.origin === API && url.pathname === '/api/emails/send-new',
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      })
    }
  )

  // Mock compose (AI generate)
  await page.route(
    (url) => url.origin === API && url.pathname === '/api/emails/compose',
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          final_draft: { content: 'Bonjour,\n\nVoici le brouillon généré par l\'IA.\n\nCordialement' },
        }),
      })
    }
  )

  // Mock create draft (reply/forward send)
  await page.route(
    (url) => url.origin === API && /^\/api\/emails\/[^/]+\/draft$/.test(url.pathname),
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, draft_id: 'draft-reply-1', sent: true }),
      })
    }
  )

  // Mock refine text (slash commands on user text)
  await page.route(
    (url) => url.origin === API && url.pathname === '/api/refine-text',
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, refined_text: 'Texte raffiné par l\'IA.' }),
      })
    }
  )

  // Mock process (generate reply draft)
  await page.route(
    (url) => url.origin === API && /^\/api\/emails\/[^/]+\/process$/.test(url.pathname),
    (route) => {
      route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, message: 'Processing' }),
      })
    }
  )

  // Mock refine draft
  await page.route(
    (url) => url.origin === API && /^\/api\/drafts\/[^/]+\/refine$/.test(url.pathname),
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          draft_id: 'draft-reply-1',
          refined_body: '<p>Brouillon raffiné.</p>',
          pipeline_details: { draft_v1: 'v1', critique: { is_valid: true, feedback: 'ok' }, was_corrected: false },
        }),
      })
    }
  )

  // Mock contacts
  await page.route(
    (url) => url.origin === API && url.pathname.startsWith('/api/contacts'),
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ contacts: [] }),
      })
    }
  )
}

// ── Helpers ─────────────────────────────────────────────────────────────────

async function openComposeModal(page: Page) {
  await page.locator('button.sidebar-compose').click()
  await page.locator('[role="dialog"][aria-label="Nouveau message"]').waitFor({ state: 'visible', timeout: 5000 })
}

async function openEmailDetail(page: Page) {
  const firstEmail = page.locator('[data-testid="email-item"]').first()
  await firstEmail.click()
  await page.locator('[data-testid="reply-button"]').waitFor({ state: 'visible', timeout: 10000 })
}

async function clickReply(page: Page) {
  await page.locator('[data-testid="reply-button"]').click()
  await page.locator('[data-testid="reply-send-button"]').waitFor({ state: 'visible', timeout: 5000 })
}

async function clickReplyAll(page: Page) {
  await page.locator('[data-testid="reply-all-button"]').click()
  await page.locator('[data-testid="reply-send-button"]').waitFor({ state: 'visible', timeout: 5000 })
}

async function clickForward(page: Page) {
  await page.locator('[data-testid="forward-button"]').click()
  await page.locator('[data-testid="reply-send-button"]').waitFor({ state: 'visible', timeout: 5000 })
}

// ── Tests: Send New Email ───────────────────────────────────────────────────

test.describe('Send New Email', () => {
  test.beforeEach(async ({ page }) => {
    await setupFullMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should compose and send a new email', async ({ page }) => {
    await openComposeModal(page)

    // Fill recipient
    const toField = page.locator('.contact-autocomplete input')
    await toField.fill('destinataire@example.com')
    await toField.press('Enter')

    // Fill subject
    const subjectField = page.locator('input[aria-label="Objet du message"]')
    await subjectField.fill('Test envoi nouveau message')

    // Fill body
    const bodyField = page.locator('.draft-editor-content')
    await bodyField.fill('Bonjour, ceci est un test d\'envoi.')

    // Verify send button is enabled and send
    const sendBtn = page.locator('button.send-pill')
    await expect(sendBtn).toBeEnabled()
    await sendBtn.click()

    // After send, the button shows a success animation (spinner or checkmark)
    // The send was accepted — verify no error toast appeared
    const errorToast = page.locator('.toast-error, .Toastify__toast--error')
    await expect(errorToast).not.toBeVisible({ timeout: 3000 })
  })

  test('should not send without recipient', async ({ page }) => {
    await openComposeModal(page)

    const sendBtn = page.locator('button.send-pill')
    await expect(sendBtn).toBeDisabled()
  })

  test('should send with only recipient (no subject/body)', async ({ page }) => {
    await openComposeModal(page)

    const toField = page.locator('.contact-autocomplete input')
    await toField.fill('test@example.com')
    await toField.press('Enter')

    const sendBtn = page.locator('button.send-pill')
    await expect(sendBtn).toBeEnabled()
  })
})

// ── Tests: Reply ────────────────────────────────────────────────────────────

test.describe('Reply', () => {
  test.beforeEach(async ({ page }) => {
    await setupFullMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openEmailDetail(page)
  })

  test('should open reply composer', async ({ page }) => {
    await clickReply(page)

    const sendBtn = page.locator('[data-testid="reply-send-button"]')
    await expect(sendBtn).toBeVisible()
  })

  test('should show reply mode indicator', async ({ page }) => {
    await clickReply(page)

    const modePill = page.locator('.draft-mode-pill')
    await expect(modePill).toBeVisible()
  })

  test('should type in reply body and send', async ({ page }) => {
    await clickReply(page)

    // Type in the Tiptap draft editor
    const editor = page.locator('.draft-editor-content')
    await editor.click()
    await page.keyboard.type('Merci pour votre message.')

    // Send
    const sendBtn = page.locator('[data-testid="reply-send-button"]')
    await expect(sendBtn).toBeEnabled()
    await sendBtn.click()

    // Reply composer should close
    await expect(sendBtn).not.toBeVisible({ timeout: 8000 })
  })
})

// ── Tests: Reply All ────────────────────────────────────────────────────────

test.describe('Reply All', () => {
  test.beforeEach(async ({ page }) => {
    await setupFullMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openEmailDetail(page)
  })

  test('should open reply-all composer', async ({ page }) => {
    await clickReplyAll(page)

    const sendBtn = page.locator('[data-testid="reply-send-button"]')
    await expect(sendBtn).toBeVisible()
  })

  test('should switch from reply to reply-all via mode switcher', async ({ page }) => {
    await clickReply(page)

    // Open mode dropdown
    const modePill = page.locator('.draft-mode-pill')
    await modePill.click()

    // Select Reply All option
    const dropdown = page.locator('.draft-mode-dropdown')
    await expect(dropdown).toBeVisible()
    const replyAllOption = dropdown.locator('[role="menuitem"]').nth(1)
    await replyAllOption.click({ force: true })

    // Dropdown should close
    await expect(dropdown).not.toBeVisible({ timeout: 3000 })
  })

  test('should type and send reply-all', async ({ page }) => {
    await clickReplyAll(page)

    const editor = page.locator('.draft-editor-content')
    await editor.click()
    await page.keyboard.type('Merci à tous pour vos retours.')

    const sendBtn = page.locator('[data-testid="reply-send-button"]')
    await expect(sendBtn).toBeEnabled()
    await sendBtn.click()

    await expect(sendBtn).not.toBeVisible({ timeout: 8000 })
  })
})

// ── Tests: Forward ──────────────────────────────────────────────────────────

test.describe('Forward', () => {
  test.beforeEach(async ({ page }) => {
    await setupFullMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openEmailDetail(page)
  })

  test('should open forward composer with To field', async ({ page }) => {
    await clickForward(page)

    // Forward mode should show the forward-to input container
    const forwardToInput = page.locator('.draft-to-input input')
    await expect(forwardToInput).toBeVisible()
  })

  test('should disable send when forward-to is empty', async ({ page }) => {
    await clickForward(page)

    const sendBtn = page.locator('[data-testid="reply-send-button"]')
    await expect(sendBtn).toBeDisabled()
  })

  test('should switch from reply to forward via mode switcher', async ({ page }) => {
    await clickReply(page)

    const modePill = page.locator('.draft-mode-pill')
    await modePill.click()

    const dropdown = page.locator('.draft-mode-dropdown')
    await expect(dropdown).toBeVisible()
    // Forward is the 3rd option
    const forwardOption = dropdown.locator('[role="menuitem"]').nth(2)
    await forwardOption.click({ force: true })

    // Forward-to input should appear
    const forwardToInput = page.locator('.draft-to-input input')
    await expect(forwardToInput).toBeVisible({ timeout: 3000 })
  })

  test('should fill forward-to and send', async ({ page }) => {
    await clickForward(page)

    // Fill forward recipient (target the input inside the ContactAutocomplete wrapper)
    const forwardToInput = page.locator('.draft-to-input input')
    await forwardToInput.fill('collegue@example.com')
    await forwardToInput.press('Enter')

    // Type a message
    const editor = page.locator('.draft-editor-content')
    await editor.click()
    await page.keyboard.type('FYI, voir le message ci-dessous.')

    const sendBtn = page.locator('[data-testid="reply-send-button"]')
    await expect(sendBtn).toBeEnabled()
    await sendBtn.click()

    // Verify no error toast appeared
    const errorToast = page.locator('.toast-error, .Toastify__toast--error')
    await expect(errorToast).not.toBeVisible({ timeout: 3000 })
  })
})

// ── Tests: Mode Switching ───────────────────────────────────────────────────

test.describe('Mode Switching', () => {
  test.beforeEach(async ({ page }) => {
    await setupFullMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openEmailDetail(page)
  })

  test('should cycle through all modes: reply → reply-all → forward', async ({ page }) => {
    await clickReply(page)

    const modePill = page.locator('.draft-mode-pill')
    const dropdown = page.locator('.draft-mode-dropdown')

    // Switch to Reply All
    await modePill.click()
    await expect(dropdown).toBeVisible()
    await dropdown.locator('[role="menuitem"]').nth(1).click({ force: true })
    // Click elsewhere to dismiss dropdown
    await page.locator('.draft-editor-content').click()
    await page.waitForTimeout(300)

    // Switch to Forward
    await modePill.click()
    await expect(dropdown).toBeVisible()
    await dropdown.locator('[role="menuitem"]').nth(2).click({ force: true })
    await page.locator('.draft-editor-content').click()
    await page.waitForTimeout(300)

    // Forward-to input should be visible
    const forwardToInput = page.locator('.draft-to-input input')
    await expect(forwardToInput).toBeVisible()

    // Switch back to Reply
    await modePill.click()
    await expect(dropdown).toBeVisible()
    await dropdown.locator('[role="menuitem"]').nth(0).click({ force: true })
    await page.locator('.draft-editor-content').click()
    await page.waitForTimeout(300)
  })
})

// ── Tests: Ctrl+Enter sends (regression — was triggering AI pipeline) ──────
//
// 2026-05-11 — User reported that Ctrl+Enter in the reply composer was
// re-running the AI pipeline instead of sending the email (the way Ctrl+Enter
// behaves in the NewMessageModal). Behavior is now: Ctrl+Enter → handleSend()
// in all three modes (reply, reply_all, forward). The AI pipeline stays
// reachable via W, Ctrl+G, Ctrl+Shift+G, and the +Processus IA button.
//
// Verification: after Ctrl+Enter, the composer closes within 8s (proving the
// send pipeline ran end-to-end — error paths leave the composer open) AND the
// AI pipeline panel never becomes visible (proving handleAIGenerate didn't
// fire, which was the old behavior).

test.describe('Ctrl+Enter sends instead of running AI pipeline', () => {
  test.beforeEach(async ({ page }) => {
    // setupBaseMocks marks Part I + KB onboarding complete, but the v2
    // welcome overlay (useOnboardingV2) keys off a different localStorage
    // flag — without it, ob-v2-backdrop intercepts pointer events.
    await page.addInitScript(() => {
      localStorage.setItem('agentys_onboarding_v2_complete', 'true')
    })
    await setupFullMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openEmailDetail(page)
  })

  async function ctrlEnterShouldSendNotAi(page: Page) {
    const editor = page.locator('.draft-editor-content')
    await editor.click()
    await page.keyboard.type('Merci, je confirme la réception.')

    const sendBtn = page.locator('[data-testid="reply-send-button"]')
    await expect(sendBtn).toBeEnabled()

    // The AI pipeline panel is the dead-giveaway of the old behavior — it
    // was force-expanded in the pre-fix handler (setShowPipeline(true)).
    const pipelinePanel = page.locator('.rc-pipeline-panel')
    await expect(pipelinePanel).not.toBeVisible()

    await page.keyboard.press('Control+Enter')

    // Send path is async (createDraft → 1.2s 'sent' animation → onSend closes
    // composer). If we land here, the send pipeline ran to completion;
    // any error along the way would leave the composer open.
    await expect(sendBtn).not.toBeVisible({ timeout: 10000 })

    // The pipeline panel should never have opened — that's the regression
    // we're guarding against.
    await expect(pipelinePanel).not.toBeVisible()
  }

  test('Reply — Ctrl+Enter sends', async ({ page }) => {
    await clickReply(page)
    await ctrlEnterShouldSendNotAi(page)
  })

  test('Reply All — Ctrl+Enter sends', async ({ page }) => {
    await clickReplyAll(page)
    await ctrlEnterShouldSendNotAi(page)
  })

  test('Forward — Ctrl+Enter sends', async ({ page }) => {
    await clickForward(page)
    // Forward requires an explicit recipient before send is enabled
    const forwardToInput = page.locator('.draft-to-input input')
    await forwardToInput.fill('collegue@example.com')
    await forwardToInput.press('Enter')
    await ctrlEnterShouldSendNotAi(page)
  })
})
