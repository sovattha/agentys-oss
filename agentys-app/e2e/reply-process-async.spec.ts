/**
 * Test: AI Process button with polling fallback
 * Verifies that when /process returns without draft_id (async),
 * the polling mechanism fetches the draft within ~10s.
 */

import { test, expect } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'
const API_LOCALHOST = 'http://localhost:5050'

const mockEmail = {
  id: 'poll-email-1',
  sender: 'client@example.com',
  sender_name: 'Jean Client',
  subject: 'Test polling fallback',
  body: '<p>Bonjour, question de test.</p>',
  body_preview: 'Bonjour, question de test.',
  received_at: new Date().toISOString(),
  has_attachments: false,
  conversation_id: null,
  is_read: false,
  to: ['user@example.com'],
  cc: [],
  attachments: [],
}

const DRAFT_BODY = 'Bonjour Jean,\n\nVoici la réponse générée par le polling.\n\nCordialement'

test.describe('Processus IA — polling fallback', () => {

  test('async /process sans draft_id → polling récupère le brouillon', async ({ page }) => {
    // Track when /process was called so we can time-gate the mock
    let processCalledAt = 0
    // Track poll count from AFTER /process was called
    let pollsSinceProcess = 0

    await setupBaseMocks(page, {
      emailsResponse: { emails: [mockEmail], has_more: false, source: 'mock' },
    })

    // Email detail mocks
    const fulfill = (body: unknown) => (route: import('@playwright/test').Route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    }
    for (const origin of [API, API_LOCALHOST]) {
      await page.route(`${origin}/api/emails/${mockEmail.id}`, fulfill(mockEmail))
      await page.route(`${origin}/api/emails/${mockEmail.id}/read`, fulfill({ success: true }))
      await page.route(`${origin}/api/emails/${mockEmail.id}/thread`, fulfill({ count: 1, emails: [] }))
    }

    // Contacts + snippets
    await page.route((url) => (url.origin === API || url.origin === API_LOCALHOST) && url.pathname.startsWith('/api/contacts'),
      fulfill([]))
    await page.route((url) => (url.origin === API || url.origin === API_LOCALHOST) && url.pathname.startsWith('/api/snippets'),
      fulfill({ snippets: [], total: 0 }))

    // /process — returns WITHOUT draft_id (async, like real backend)
    for (const origin of [API, API_LOCALHOST]) {
      await page.route(`${origin}/api/emails/${mockEmail.id}/process`, (route) => {
        if (route.request().method() === 'POST') {
          processCalledAt = Date.now()
          console.log('[MOCK] /process called')
          route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              success: true, status: 'processing', task_id: 'task-poll-1',
              message: 'Draft generation started.',
            }),
          })
        } else {
          route.continue()
        }
      })
    }

    // pending-drafts by-email:
    // - Before /process: always return 404 (no draft exists)
    // - After /process: first poll → 404 (still generating), second+ poll → 200 (draft ready)
    await page.route(
      (url) => (url.origin === API || url.origin === API_LOCALHOST) && url.pathname.includes(`/pending-drafts/by-email/${mockEmail.id}`),
      (route) => {
        if (processCalledAt === 0) {
          // Before /process — no draft
          route.fulfill({ status: 404, contentType: 'application/json', body: '{"error":"not found"}' })
          return
        }
        pollsSinceProcess++
        console.log(`[MOCK] pending-drafts/by-email poll #${pollsSinceProcess}`)
        if (pollsSinceProcess <= 1) {
          // First poll after /process: still generating
          route.fulfill({ status: 404, contentType: 'application/json', body: '{"error":"not found"}' })
        } else {
          // Draft ready!
          route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              id: 'draft-poll-1', email_id: mockEmail.id, draft_body: DRAFT_BODY,
              draft_subject: 'Re: Test polling fallback', status: 'pending',
              classification: 'action', critique: 'Score: 90. Verdict: VALID.',
            }),
          })
        }
      }
    )

    await page.goto('/')
    await waitForAppReady(page)

    // Open email + reply
    await page.locator('[data-testid="email-item"]').first().click()
    const replyBtn = page.locator('button:has-text("Répondre")').first()
    await expect(replyBtn).toBeVisible({ timeout: 10000 })
    await replyBtn.click()

    // Click the process button
    const submitBtn = page.locator('[data-testid="ai-prompt-submit"]')
    await expect(submitBtn).toBeVisible({ timeout: 10000 })
    await expect(submitBtn).toBeEnabled()
    await submitBtn.click()

    // Spinner should appear immediately
    await page.waitForTimeout(500)
    expect(await page.locator('.rc-refine-spinner').isVisible().catch(() => false)).toBe(true)
    console.log('[TEST] Spinner active after click')

    // Wait for polling to deliver the draft (3s delay + first poll 404 + second poll at 8s → ~8-10s)
    // Use a robust check: wait for the spinner to disappear (state = 'editing')
    await expect(page.locator('.rc-refine-spinner')).not.toBeVisible({ timeout: 20000 })
    console.log(`[TEST] Spinner gone! Elapsed: ${Date.now() - processCalledAt}ms`)

    // Button should be re-enabled
    await expect(submitBtn).toBeEnabled({ timeout: 5000 })

    // Draft body should contain generated text (use data-testid or a more specific selector)
    const _editorText = await page.locator('[data-testid="ai-prompt-input"]').inputValue().catch(() => '')
    const bodyText = await page.evaluate(() => {
      const el = document.querySelector('.DraftEditor-root, .rc-editor-area [contenteditable]')
      return el?.textContent || ''
    })
    console.log(`[TEST] Editor body: "${bodyText.substring(0, 60)}"`)
    console.log(`[TEST] Total polls since /process: ${pollsSinceProcess}`)

    // The body should contain our draft text
    expect(bodyText).toContain('Voici la réponse')
  })
})
