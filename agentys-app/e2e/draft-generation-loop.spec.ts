/**
 * E2E — boucle brouillon IA :
 * générer depuis l'inbox, retrouver dans Brouillons, revenir dans l'inbox,
 * puis rééditer le même brouillon IA.
 */

import { expect, test, type Page, type Route } from '@playwright/test'
import { isApiRoute, setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const EMAIL_ID = 'draft-loop-email-1'
const DRAFT_ID = 'draft-loop-1'
const SUBJECT = 'Boucle UX draft IA'
const ORIGINAL_BODY = 'Bonjour, voici les éléments du dossier à traiter cette semaine. Merci pour votre retour détaillé.'
const GENERATED_BODY = 'Bonjour Camille,\n\nMerci pour votre message. Je regarde cela et je reviens vers vous rapidement.\n\nCordialement'

const makeEmail = (hasDraft: boolean) => ({
  id: EMAIL_ID,
  sender: 'camille.renaud@example.com',
  sender_name: 'Camille Renaud',
  subject: SUBJECT,
  received_at: new Date().toISOString(),
  has_attachments: false,
  conversation_id: 'draft-loop-conversation',
  is_read: false,
  body_preview: ORIGINAL_BODY,
  has_pending_draft: hasDraft,
})

const makeEmailDetail = () => ({
  ...makeEmail(false),
  body: `<p>${ORIGINAL_BODY}</p>`,
  body_html: `<p>${ORIGINAL_BODY}</p>`,
  to: ['test@example.com'],
  cc: [],
  attachments: [],
})

function makePendingDraft(body = GENERATED_BODY) {
  return {
    id: DRAFT_ID,
    email_id: EMAIL_ID,
    email_sender: 'camille.renaud@example.com',
    email_sender_name: 'Camille Renaud',
    email_subject: SUBJECT,
    email_body: `<p>${ORIGINAL_BODY}</p>`,
    email_received_at: new Date().toISOString(),
    draft_subject: `Re: ${SUBJECT}`,
    draft_body: body,
    body,
    content: body,
    draft_final: body,
    draft_v1: body,
    critique: 'Score: 91/100. Verdict: VALID.',
    classification: 'action',
    priority: 2,
    confidence: 0.94,
    routing_tier: 'STANDARD',
    status: 'pending' as const,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    smart_suggestions: [],
  }
}

async function setupDraftLoopMocks(page: Page) {
  let pendingDraft: ReturnType<typeof makePendingDraft> | null = null
  let sentEmail: ReturnType<typeof makeEmailDetail> | null = null
  const scheduledRows: Array<{
    id: string
    send_at: string
    status: 'pending' | 'cancelled'
    to: string[]
    cc: string[]
    bcc: string[]
    subject: string
    body: string
    is_html: boolean
    reply_to_id: string | null
    thread_id: string | null
    attachments_count: number
    created_at: string | null
    updated_at: string | null
    sent_at: string | null
    sent_message_id: string | null
    error: string | null
  }> = []
  const savedBodies: string[] = []

  await setupBaseMocks(page, {
    emailsResponse: { count: 1, emails: [makeEmail(false)], has_more: false, source: 'mock' },
  })

  const fulfillJson = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })

  await page.route((url) => isApiRoute(url) && url.pathname === '/api/emails', (route) => {
    if (route.request().method() !== 'GET') return fulfillJson(route, {})
    if (route.request().url().includes('folder=sent')) {
      const sentEmails = sentEmail ? [sentEmail] : []
      return fulfillJson(route, {
        count: sentEmails.length,
        emails: sentEmails,
        has_more: false,
        source: 'mock',
      })
    }
    fulfillJson(route, {
      count: 1,
      emails: [makeEmail(Boolean(pendingDraft))],
      has_more: false,
      source: 'mock',
    })
  })

  await page.route((url) => isApiRoute(url) && url.pathname === `/api/emails/${EMAIL_ID}`, (route) => {
    fulfillJson(route, makeEmailDetail())
  })

  await page.route((url) => isApiRoute(url) && url.pathname === `/api/emails/${EMAIL_ID}/read`, (route) => {
    fulfillJson(route, { success: true })
  })

  await page.route((url) => isApiRoute(url) && url.pathname === `/api/emails/${EMAIL_ID}/thread`, (route) => {
    fulfillJson(route, { count: 1, emails: [] })
  })

  await page.route((url) => isApiRoute(url) && /\/api\/emails\/sent(%3A|:)draft-loop-1$/.test(url.pathname), (route) => {
    if (!sentEmail) return fulfillJson(route, { error: 'not found' }, 404)
    fulfillJson(route, sentEmail)
  })

  await page.route((url) => isApiRoute(url) && /\/api\/emails\/sent(%3A|:)draft-loop-1\/read$/.test(url.pathname), (route) => {
    fulfillJson(route, { success: true })
  })

  await page.route((url) => isApiRoute(url) && /\/api\/emails\/sent(%3A|:)draft-loop-1\/thread$/.test(url.pathname), (route) => {
    fulfillJson(route, { count: 1, emails: [] })
  })

  await page.route((url) => isApiRoute(url) && url.pathname === `/api/emails/${EMAIL_ID}/process`, (route) => {
    pendingDraft = makePendingDraft()
    fulfillJson(route, {
      success: true,
      draft_id: DRAFT_ID,
      email_id: EMAIL_ID,
      classification: 'action',
      priority: 'normal',
      status: 'pending',
      draft_preview: GENERATED_BODY.slice(0, 80),
      instructions: 'Réponds simplement',
      reply_type: 'reply',
    })
  })

  await page.route((url) => isApiRoute(url) && url.pathname === '/api/pending-drafts', (route) => {
    const drafts = pendingDraft ? [pendingDraft] : []
    fulfillJson(route, { count: drafts.length, pending_count: drafts.length, drafts })
  })

  await page.route((url) => isApiRoute(url) && url.pathname === `/api/pending-drafts/by-email/${EMAIL_ID}`, (route) => {
    if (!pendingDraft) return fulfillJson(route, { error: 'not found' }, 404)
    fulfillJson(route, { draft: pendingDraft })
  })

  await page.route((url) => isApiRoute(url) && new RegExp(`/api/pending-drafts/${DRAFT_ID}/?$`).test(url.pathname), async (route) => {
    if (!pendingDraft) return fulfillJson(route, { error: 'not found' }, 404)

    if (route.request().method() === 'DELETE') {
      pendingDraft = null
      return fulfillJson(route, { success: true, draft_id: DRAFT_ID })
    }

    if (route.request().method() === 'PATCH') {
      const payload = route.request().postDataJSON() as { subject?: string; body?: string }
      pendingDraft = {
        ...pendingDraft,
        draft_subject: payload.subject ?? pendingDraft.draft_subject,
        draft_body: payload.body ?? pendingDraft.draft_body,
        status: 'modified',
        updated_at: new Date().toISOString(),
      }
      savedBodies.push(pendingDraft.draft_body)
      return fulfillJson(route, { success: true, draft_id: DRAFT_ID })
    }

    fulfillJson(route, pendingDraft)
  })

  await page.route((url) => isApiRoute(url) && url.pathname === `/api/pending-drafts/${DRAFT_ID}/validate`, async (route) => {
    if (!pendingDraft) return fulfillJson(route, { error: 'not found' }, 404)

    sentEmail = {
      ...makeEmailDetail(),
      id: `sent:${DRAFT_ID}`,
      sender: 'test@example.com',
      sender_name: 'Moi',
      subject: pendingDraft.draft_subject,
      body: pendingDraft.draft_body,
      body_html: `<p>${pendingDraft.draft_body.replace(/\n/g, '<br>')}</p>`,
      is_read: true,
    }
    pendingDraft = null

    fulfillJson(route, {
      success: true,
      draft_id: DRAFT_ID,
      gmail_draft_id: `gmail-${DRAFT_ID}`,
      sent: true,
      message: 'Email envoyé',
    })
  })

  await page.route((url) => isApiRoute(url) && url.pathname === '/api/emails/schedule', async (route) => {
    const payload = route.request().postDataJSON() as {
      to?: string
      cc?: string
      bcc?: string
      subject?: string
      body?: string
      send_at?: string
      is_html?: boolean
      reply_to_id?: string
      thread_id?: string
    }
    const scheduled = {
      id: `scheduled-${scheduledRows.length + 1}`,
      send_at: payload.send_at || new Date(Date.now() + 86400_000).toISOString(),
      status: 'pending' as const,
      to: payload.to ? [payload.to] : [],
      cc: payload.cc ? [payload.cc] : [],
      bcc: payload.bcc ? [payload.bcc] : [],
      subject: payload.subject || '',
      body: payload.body || '',
      is_html: Boolean(payload.is_html),
      reply_to_id: payload.reply_to_id || null,
      thread_id: payload.thread_id || null,
      attachments_count: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      sent_at: null,
      sent_message_id: null,
      error: null,
    }
    scheduledRows.push(scheduled)
    fulfillJson(route, {
      scheduled_id: scheduled.id,
      status: scheduled.status,
      send_at: scheduled.send_at,
    }, 201)
  })

  await page.route((url) => isApiRoute(url) && /\/api\/emails\/scheduled(\?|$)/.test(url.pathname + url.search), (route) => {
    const items = scheduledRows.filter(row => row.status === 'pending')
    fulfillJson(route, { items, count: items.length })
  })

  await page.route((url) => isApiRoute(url) && /\/api\/emails\/scheduled\/[^/]+$/.test(url.pathname), (route) => {
    const id = route.request().url().match(/scheduled\/([^/?]+)/)?.[1] || ''
    if (route.request().method() === 'DELETE') {
      const row = scheduledRows.find(item => item.id === id)
      if (row) row.status = 'cancelled'
      return fulfillJson(route, { success: true, scheduled_id: id })
    }
    fulfillJson(route, { error: 'unsupported' }, 405)
  })

  await page.route((url) => isApiRoute(url) && url.pathname === `/api/drafts/${DRAFT_ID}/refine`, (route) => {
    if (!pendingDraft) return fulfillJson(route, { error: 'not found' }, 404)
    pendingDraft = {
      ...pendingDraft,
      draft_body: `${pendingDraft.draft_body}\n\nVersion affinée.`,
      status: 'modified',
      updated_at: new Date().toISOString(),
    }
    fulfillJson(route, {
      success: true,
      refined_body: pendingDraft.draft_body,
      pipeline_details: {
        draft_v1: pendingDraft.draft_v1,
        critique: { is_valid: true, feedback: pendingDraft.critique },
      },
    })
  })

  return {
    getSavedBodies: () => savedBodies.slice(),
    getCurrentBody: () => pendingDraft?.draft_body ?? '',
    getScheduledRows: () => scheduledRows.slice(),
    getSentEmail: () => sentEmail,
  }
}

async function revealDraftTextarea(page: Page) {
  // Parité compose (2026-06-09) : le body Drafts est un DraftEditor TipTap
  // (contenteditable), plus un <textarea>. `fill()` marche sur contenteditable,
  // mais il faut viser l'élément éditable interne, pas le wrapper porteur du
  // data-testid. Le premier état après génération peut rester dans le
  // ReplyComposer; les étapes Brouillons utilisent PendingDraftDetail.
  // Les assertions de contenu utilisent toContainText.
  const editor = page.locator(
    '[data-testid="draft-body"] .draft-editor-content, ' +
    '[data-testid="reply-composer"] .draft-editor-content'
  ).first()
  if (await editor.isVisible().catch(() => false)) {
    return editor
  }

  await page.evaluate(() => {
    const reveal = document.querySelector<HTMLElement>('.typing-reveal-container')
    reveal?.click()
  })

  await expect(editor).toBeVisible({ timeout: 10000 })
  return editor
}

test.describe('Boucle brouillon IA', () => {
  test('générer → Brouillons → Inbox → rééditer le même draft IA', async ({ page }) => {
    const mocks = await setupDraftLoopMocks(page)

    await page.goto('/')
    await waitForAppReady(page)

    await page.getByTestId('email-item').filter({ hasText: SUBJECT }).click()
    await expect(page.getByTestId('reply-button')).toBeVisible({ timeout: 10000 })
    await page.getByTestId('reply-button').click()

    await page.getByTestId('ai-command-trigger').click()
    await page.locator('.ai-cmd-input').fill('Réponds simplement')
    await page.locator('.ai-cmd-send-btn').click()

    await expect(page.getByTestId('pending-draft-detail')).toBeVisible({ timeout: 10000 })

    await page.getByTestId('nav-drafts').click()
    const draftRow = page.getByTestId('draft-item').filter({ hasText: SUBJECT })
    await expect(draftRow).toBeVisible({ timeout: 10000 })
    await draftRow.click()

    const draftBodyFromDrafts = await revealDraftTextarea(page)
    await expect(draftBodyFromDrafts).toContainText(/Merci pour votre message/)
    await draftBodyFromDrafts.fill(`${GENERATED_BODY}\n\nAjout depuis Brouillons.`)
    await expect.poll(() => mocks.getSavedBodies().join('\n')).toContain('Ajout depuis Brouillons.')

    await page.getByTestId('nav-inbox').click()
    const inboxRow = page.getByTestId('email-item').filter({ hasText: SUBJECT })
    await expect(inboxRow.getByTestId('draft-ready-badge')).toBeVisible({ timeout: 10000 })
    await inboxRow.click()

    const draftBodyFromInbox = await revealDraftTextarea(page)
    await expect(draftBodyFromInbox).toContainText(/Ajout depuis Brouillons\./)
    await draftBodyFromInbox.fill(`${mocks.getCurrentBody()}\nAjout depuis Inbox.`)

    await expect.poll(() => mocks.getSavedBodies().join('\n')).toContain('Ajout depuis Inbox.')
  })

  test('générer → envoyer → retrouver dans Envoyés', async ({ page }) => {
    const mocks = await setupDraftLoopMocks(page)

    await page.goto('/')
    await waitForAppReady(page)

    await page.getByTestId('email-item').filter({ hasText: SUBJECT }).click()
    await page.getByTestId('reply-button').click()
    await page.getByTestId('ai-command-trigger').click()
    await page.locator('.ai-cmd-input').fill('Réponds simplement')
    await page.locator('.ai-cmd-send-btn').click()

    await expect(page.getByTestId('pending-draft-detail')).toBeVisible({ timeout: 10000 })
    await page.getByTestId('send-button').click()
    await expect(page.getByTestId('send-summary')).toBeVisible({ timeout: 5000 })
    await expect(page.getByTestId('summary-recipient')).toContainText('Camille')
    await expect(page.getByTestId('confirm-button')).toBeDisabled()
    await expect(page.getByTestId('confirm-button')).toBeEnabled({ timeout: 5000 })
    await page.getByTestId('confirm-button').click()

    await expect.poll(() => mocks.getSentEmail()?.subject ?? '').toBe(`Re: ${SUBJECT}`)

    await page.getByTestId('nav-sent').click()
    const sentRow = page.getByTestId('email-item').filter({ hasText: `Re: ${SUBJECT}` })
    await expect(sentRow).toBeVisible({ timeout: 10000 })
    await sentRow.click()
    await expect(page.locator('.email-body-iframe')).toBeVisible({ timeout: 10000 })
    await expect(page.frameLocator('.email-body-iframe').locator('body')).toContainText('Merci pour votre message')
  })

  test('générer → programmer → Plus tard → annuler', async ({ page }) => {
    const mocks = await setupDraftLoopMocks(page)

    await page.goto('/')
    await waitForAppReady(page)

    await page.getByTestId('email-item').filter({ hasText: SUBJECT }).click()
    await page.getByTestId('reply-button').click()
    await page.getByTestId('ai-command-trigger').click()
    await page.locator('.ai-cmd-input').fill('Réponds simplement')
    await page.locator('.ai-cmd-send-btn').click()

    await expect(page.getByTestId('pending-draft-detail')).toBeVisible({ timeout: 10000 })
    await page.getByTestId('send-split-chevron').click()
    await expect(page.getByTestId('schedule-picker')).toBeVisible({ timeout: 5000 })
    await page.getByTestId('schedule-preset-tomorrow_morning').click()

    await expect.poll(() => mocks.getScheduledRows().length).toBe(1)
    await expect(page.getByTestId('pending-draft-detail')).toBeHidden({ timeout: 10000 })

    await page.getByTestId('nav-snoozed').click()
    await expect(page.locator('.snoozed-view')).toBeVisible({ timeout: 10000 })
    await page.getByTestId('later-filter-scheduled').click()
    const scheduledRow = page.getByTestId('later-row-scheduled-scheduled-1')
    await expect(scheduledRow).toBeVisible({ timeout: 10000 })
    await expect(scheduledRow).toContainText(`Re: ${SUBJECT}`)

    await scheduledRow.hover()
    await page.getByTestId('later-cancel-scheduled-1').click()
    await expect(scheduledRow).toBeHidden({ timeout: 10000 })
  })
})
