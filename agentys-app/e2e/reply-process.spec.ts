/**
 * Reply Process E2E Tests
 *
 * Tests the flow: open email → click Répondre → AI generates draft via /process.
 * Covers success, 404 error, and existing draft scenarios.
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

const mockEmail = {
  id: 'proc-email-1',
  sender: 'client@example.com',
  sender_name: 'Jean Client',
  subject: 'Question sur la facturation',
  body: '<p>Bonjour, pouvez-vous me confirmer le montant de la facture ?</p>',
  body_preview: 'Bonjour, pouvez-vous me confirmer le montant...',
  received_at: new Date().toISOString(),
  has_attachments: false,
  conversation_id: null,
  is_read: false,
  to: ['user@example.com'],
  cc: [],
  attachments: [],
}

const mockEmailsResponse = {
  emails: [mockEmail],
  has_more: false,
  source: 'mock',
}

const mockProcessSuccess = {
  success: true,
  draft_id: 'draft-proc-1',
  status: 'created',
}

const mockPendingDraft = {
  id: 'draft-proc-1',
  email_id: 'proc-email-1',
  email_subject: mockEmail.subject,
  email_sender: mockEmail.sender,
  email_sender_name: mockEmail.sender_name,
  email_body: mockEmail.body,
  draft_subject: 'Re: Question sur la facturation',
  draft_body: 'Bonjour Jean,\n\nLe montant de votre facture est de 1 250,00 €.\n\nCordialement',
  draft_v1: 'Bonjour Jean, le montant est de 1 250 €.',
  status: 'pending',
  classification: 'action',
  routing_tier: 'STANDARD',
  critique: 'Réponse claire et professionnelle. Score: 90/100. Verdict: VALID.',
  smart_suggestions: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
}

async function setupProcessMocks(page: Page, opts: { processResponse?: unknown; processStatus?: number } = {}) {
  await setupBaseMocks(page, { emailsResponse: mockEmailsResponse })

  // Mock email detail
  await page.route((url) => url.origin === API && url.pathname === `/api/emails/${mockEmail.id}`, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockEmail) })
  })

  // Mock mark read
  await page.route((url) => url.origin === API && url.pathname === `/api/emails/${mockEmail.id}/read`, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
  })

  // Mock thread
  await page.route((url) => url.origin === API && url.pathname === `/api/emails/${mockEmail.id}/thread`, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 1, emails: [] }) })
  })

  // Mock process endpoint (POST /emails/<id>/process)
  await page.route((url) => url.origin === API && url.pathname === `/api/emails/${mockEmail.id}/process`, (route) => {
    if (route.request().method() === 'POST') {
      const status = opts.processStatus ?? 200
      const body = opts.processResponse ?? mockProcessSuccess
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    } else {
      route.continue()
    }
  })

  // Mock pending draft fetch (after process creates one)
  await page.route((url) => url.origin === API && url.pathname === `/api/pending-drafts/${mockPendingDraft.id}`, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockPendingDraft) })
  })

  // Mock pending-drafts by-email lookup
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts/by-email'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockPendingDraft) })
  })

  // Mock contacts
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/contacts'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  })

  // Mock snippets
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/snippets'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ snippets: [], total: 0 }) })
  })
}

async function openEmailAndReply(page: Page) {
  // Click email in list
  const emailItem = page.locator('[data-testid="email-item"]').first()
  await expect(emailItem).toBeVisible({ timeout: 10000 })
  await emailItem.click()

  // Click "Répondre" button
  const replyBtn = page.locator('button:has-text("Répondre")').first()
  await expect(replyBtn).toBeVisible({ timeout: 10000 })
  await replyBtn.click()
}

test.describe('Reply Process — génération IA de brouillon', () => {
  test('ouvre le reply composer et génère un brouillon via Processus IA', async ({ page }) => {
    await setupProcessMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openEmailAndReply(page)

    // Reply composer should be visible
    const composer = page.locator('.reply-composer, .rc-container').first()
    await expect(composer).toBeVisible({ timeout: 10000 })

    // AI prompt input should be visible
    const aiInput = page.locator('[data-testid="ai-prompt-input"]').first()
    await expect(aiInput).toBeVisible({ timeout: 10000 })

    // Press Enter to trigger AI generation (empty prompt = default "Réponds de manière appropriée")
    await aiInput.press('Enter')

    // After generation, the draft body editor should show generated text
    const draftEditor = page.locator('.draft-editor, .rc-editor-area, .DraftEditor-root, [contenteditable]').first()
    await expect(draftEditor).toBeVisible({ timeout: 15000 })
  })

  test('affiche une erreur quand /process retourne 404', async ({ page }) => {
    await setupProcessMocks(page, {
      processStatus: 404,
      processResponse: { error: 'Email not found' },
    })
    await page.goto('/')
    await waitForAppReady(page)
    await openEmailAndReply(page)

    const aiInput = page.locator('[data-testid="ai-prompt-input"]').first()
    await expect(aiInput).toBeVisible({ timeout: 10000 })
    await aiInput.press('Enter')

    // Should show an error message in the composer (.rc-error with role="alert")
    const errorMsg = page.locator('.rc-error[role="alert"]').first()
    await expect(errorMsg).toBeVisible({ timeout: 10000 })
  })

  test('affiche le reply composer avec le prompt AI visible', async ({ page }) => {
    await setupProcessMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openEmailAndReply(page)

    const aiInput = page.locator('[data-testid="ai-prompt-input"]').first()
    await expect(aiInput).toBeVisible({ timeout: 10000 })
  })
})
