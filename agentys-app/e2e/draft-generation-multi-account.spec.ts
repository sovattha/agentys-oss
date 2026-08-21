import { test, expect, Page } from '@playwright/test'
import { isApiRoute, setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const replyAccountEmail = 'reply@example.com'

const replyEmail = {
  id: 'multi-account-draft-email-1',
  sender: 'client@example.com',
  sender_name: 'Client Compte B',
  sender_email: 'client@example.com',
  subject: 'Question compte B',
  body: '<p>Peux-tu confirmer que la réponse part du bon compte ?</p>',
  body_preview: 'Peux-tu confirmer que la réponse part du bon compte ?',
  received_at: new Date().toISOString(),
  has_attachments: false,
  conversation_id: 'thread-multi-account-draft-1',
  is_read: false,
  to: [replyAccountEmail],
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
    email: replyAccountEmail,
    provider: 'gmail',
    status: 'active',
    is_current: false,
    signature: 'Signature Compte B',
    signature_html: '<strong>Signature Compte B</strong>',
  },
]

async function setupMultiAccountDraftMocks(page: Page, opts: { draftReadyAfterMs?: number } = {}) {
  let processHeaders: Record<string, string> | null = null
  let processPayload: Record<string, unknown> | null = null
  let processStarted = false
  let processStartedAt = 0
  const buildDraft = () => ({
    id: 'draft-compte-b-1',
    email_id: replyEmail.id,
    email_subject: replyEmail.subject,
    email_sender: replyEmail.sender,
    email_sender_name: replyEmail.sender_name,
    email_body: replyEmail.body,
    draft_subject: `Re: ${replyEmail.subject}`,
    draft_body: 'Bonjour,\n\nBrouillon généré pour le compte B.\n\nCordialement,',
    draft_v1: 'Bonjour,\n\nBrouillon généré pour le compte B.\n\nCordialement,',
    status: 'pending',
    classification: 'action',
    routing_tier: 'STANDARD',
    critique: 'Score: 90/100. Verdict: VALID.',
    smart_suggestions: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  })

  await setupBaseMocks(page, {
    emailsResponse: { emails: [replyEmail], has_more: false, source: 'mock' },
  })

  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/init',
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        current_account_id: 'hash-b',
        emails: { emails: [replyEmail], has_more: false, source: 'mock' },
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
    (url) => isApiRoute(url) && url.pathname === `/api/emails/${replyEmail.id}`,
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(replyEmail),
    }),
  )

  await page.route(
    (url) => isApiRoute(url) && url.pathname === `/api/emails/${replyEmail.id}/read`,
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true }),
    }),
  )

  await page.route(
    (url) => isApiRoute(url) && url.pathname === `/api/emails/${replyEmail.id}/thread`,
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ count: 1, emails: [replyEmail] }),
    }),
  )

  await page.route(
    (url) => isApiRoute(url) && url.pathname === `/api/emails/${replyEmail.id}/process`,
    (route) => {
      processStarted = true
      processStartedAt = Date.now()
      processHeaders = route.request().headers()
      const payload = route.request().postDataJSON() as Record<string, unknown>
      processPayload = payload
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          status: 'processing',
          task_id: 'task-compte-b-1',
          message: 'Draft generation started.',
          instructions: payload.instructions,
        }),
      })
    },
  )

  await page.route(
    (url) => isApiRoute(url) && url.pathname.startsWith('/api/pending-drafts/by-email'),
    (route) => {
      const draftReady = processStarted && Date.now() - processStartedAt >= (opts.draftReadyAfterMs ?? 0)
      const draft = draftReady ? buildDraft() : null
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ draft }),
      })
    },
  )

  await page.route(
    (url) => isApiRoute(url) && url.pathname.startsWith('/api/contacts'),
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    }),
  )

  await page.route(
    (url) => isApiRoute(url) && url.pathname.startsWith('/api/snippets'),
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ snippets: [], total: 0 }),
    }),
  )

  return {
    getProcessHeaders: () => processHeaders,
    getProcessPayload: () => processPayload,
  }
}

test.describe('Génération de brouillon multi-compte', () => {
  test('génère le draft avec le compte de réponse actif', async ({ page }) => {
    const processSpy = await setupMultiAccountDraftMocks(page, { draftReadyAfterMs: 1_500 })

    await page.goto('/')
    await waitForAppReady(page)

    await page.locator('[data-testid="email-item"], .swipeable-email-item').first().click()
    await page.locator('[data-testid="reply-button"]').first().click()

    const composer = page.locator('[data-testid="reply-composer"], .reply-composer').first()
    await expect(composer).toBeVisible({ timeout: 10_000 })

    const editor = composer.locator('.draft-editor-content[contenteditable="true"]').first()
    await expect(editor).toBeFocused({ timeout: 10_000 })
    await page.keyboard.type('Confirmer depuis le compte B.')
    await page.keyboard.press('Control+G')

    await expect.poll(() => processSpy.getProcessHeaders()?.['x-account-id']).toBe('hash-b')
    expect(processSpy.getProcessHeaders()?.['x-account-id']).not.toBe('hash-a')
    expect(String(processSpy.getProcessPayload()?.instructions ?? '')).toContain('Confirmer depuis le compte B.')
    await expect(composer.locator('.draft-editor-content').first()).toContainText('Confirmer depuis le compte B', { timeout: 500 })

    const generatedText = page.getByText('Brouillon généré pour le compte B.')
    await expect(generatedText).toBeVisible({ timeout: 20_000 })

    await generatedText.click()
    await page.keyboard.type(' Ajout manuel.')
    await expect(page.getByText('Ajout manuel.')).toBeVisible({ timeout: 5000 })
  })
})
