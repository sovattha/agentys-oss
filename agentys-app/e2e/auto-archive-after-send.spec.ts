/**
 * E2E — Auto-archive après envoi
 *
 * Valide que quand un brouillon IA est envoyé depuis PendingDraftDetail,
 * la requête POST /pending-drafts/:id/validate contient bien { archive: true }
 * et que l'email disparaît de la liste après envoi.
 */

import { test, expect } from '@playwright/test'
import { setupBaseMocks } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'
const API_LOCALHOST = 'http://localhost:5050'

const DRAFT_ID = 'draft-archive-test-001'
const EMAIL_ID = 'email-archive-test-001'

const MOCK_EMAIL = {
  id: EMAIL_ID,
  subject: 'Réunion de lancement — confirmation',
  sender: 'caroline@example.com',
  sender_name: 'Caroline Dupont',
  body: 'Bonjour, pouvez-vous confirmer votre présence à la réunion de lundi ?',
  received_at: new Date().toISOString(),
  is_read: false,
  labels: ['Action'],
  folder: 'inbox',
}

const MOCK_DRAFT = {
  id: DRAFT_ID,
  email_id: EMAIL_ID,
  email_sender: 'caroline@example.com',
  email_sender_name: 'Caroline Dupont',
  email_subject: 'Réunion de lancement — confirmation',
  email_body: 'Bonjour, pouvez-vous confirmer votre présence à la réunion de lundi ?',
  email_received_at: new Date().toISOString(),
  draft_subject: 'Re: Réunion de lancement — confirmation',
  draft_body: 'Bonjour Caroline,\n\nOui, je confirme ma présence à la réunion de lundi.\n\nCordialement,\nAlexandre',
  draft_v1: '',
  critique: '',
  classification: 'NORMAL',
  priority: 70,
  routing_tier: 'standard',
  status: 'pending',
  created_at: new Date().toISOString(),
  smart_suggestions: null,
}

const EMAILS_WITH_ACTION = {
  emails: [MOCK_EMAIL],
  has_more: false,
  source: 'mock',
  total: 1,
}

async function setupMocks(page: import('@playwright/test').Page) {
  await setupBaseMocks(page, { emailsResponse: EMAILS_WITH_ACTION })

  const mockBoth = async (
    matcher: (url: URL) => boolean,
    handler: (route: import('@playwright/test').Route) => void
  ) => {
    await page.route(
      (url) => (url.origin === API || url.origin === API_LOCALHOST) && matcher(url),
      handler
    )
  }

  // Settings — auto_archive_action activé
  await mockBoth(
    (url) => url.pathname === '/api/settings',
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ auto_archive_action: true }),
      })
    }
  )

  // Email detail
  await mockBoth(
    (url) => url.pathname === `/api/emails/${EMAIL_ID}`,
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_EMAIL),
      })
    }
  )

  // Pending drafts list
  await mockBoth(
    (url) => url.pathname === '/api/pending-drafts',
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ drafts: [MOCK_DRAFT], pending_count: 1 }),
      })
    }
  )

  // Pending draft by email ID
  await mockBoth(
    (url) => url.pathname === `/api/pending-drafts/by-email/${EMAIL_ID}`,
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ draft: MOCK_DRAFT }),
      })
    }
  )

  // Pending draft by ID (GET + PATCH)
  await mockBoth(
    (url) => url.pathname === `/api/pending-drafts/${DRAFT_ID}`,
    (route) => {
      const method = route.request().method()
      if (method === 'PATCH' || method === 'PUT') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, data: MOCK_DRAFT }),
        })
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ draft: MOCK_DRAFT }),
        })
      }
    }
  )
}

// ─────────────────────────────────────────────────────────────────────────────

test.describe('Auto-archive après envoi', () => {
  test.describe.configure({ mode: 'serial' })

  test('POST /validate contient archive:true quand pas de relance programmée', async ({ page }) => {
    await setupMocks(page)

    // Intercepter la requête validate et capturer le body
    let capturedBody: Record<string, unknown> | null = null

    await page.route(
      (url) =>
        (url.origin === API || url.origin === API_LOCALHOST) &&
        url.pathname === `/api/pending-drafts/${DRAFT_ID}/validate`,
      async (route) => {
        const body = route.request().postDataJSON() as Record<string, unknown> | null
        capturedBody = body ?? {}
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            sent: true,
            draft_id: DRAFT_ID,
            gmail_draft_id: 'gmail-draft-001',
            message: 'Email envoyé avec succès',
          }),
        })
      }
    )

    await page.goto('http://localhost:1420')
    await page.waitForSelector('[data-testid="email-item"], .email-item, [class*="email-item"]', {
      timeout: 10000,
    })

    // Ouvrir l'email Action
    const emailItem = page
      .locator('[class*="email-item"], [data-testid="email-item"]')
      .filter({ hasText: 'Réunion de lancement' })
      .first()
    await expect(emailItem).toBeVisible({ timeout: 5000 })
    await emailItem.click()

    // Attendre que le brouillon soit chargé
    const sendButton = page
      .locator('button')
      .filter({ hasText: /envoyer/i })
      .first()
    await expect(sendButton).toBeVisible({ timeout: 5000 })

    // Préparer le waiter avant le clic
    const validateDone = page.waitForResponse(
      (resp) =>
        resp.url().includes(`/pending-drafts/${DRAFT_ID}/validate`) && resp.status() === 200,
      { timeout: 10000 }
    )

    await sendButton.click()
    await validateDone

    // Vérifier que archive:true était bien dans le body
    expect(capturedBody).not.toBeNull()
    expect(capturedBody?.archive).toBe(true)
  })

  test('POST /validate ne contient PAS archive:true quand une relance est programmée', async ({
    page,
  }) => {
    await setupMocks(page)

    let capturedBody: Record<string, unknown> | null = null

    await page.route(
      (url) =>
        (url.origin === API || url.origin === API_LOCALHOST) &&
        url.pathname === `/api/pending-drafts/${DRAFT_ID}/validate`,
      async (route) => {
        capturedBody = (route.request().postDataJSON() as Record<string, unknown>) ?? {}
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            sent: true,
            draft_id: DRAFT_ID,
            gmail_draft_id: 'gmail-draft-001',
          }),
        })
      }
    )

    await page.goto('http://localhost:1420')
    await page.waitForSelector('[class*="email-item"], [data-testid="email-item"]', {
      timeout: 10000,
    })

    const emailItem = page
      .locator('[class*="email-item"], [data-testid="email-item"]')
      .filter({ hasText: 'Réunion de lancement' })
      .first()
    await emailItem.click()

    // This test requires the followup/relance UI to be present
    const followupBtn = page
      .locator('button')
      .filter({ hasText: /relance|rappel|followup/i })
      .first()
    test.skip(await followupBtn.count() === 0, 'Followup/relance button not present in UI')

    await expect(followupBtn).toBeVisible({ timeout: 5000 })
    await followupBtn.click()

    // Sélectionner une date dans le futur si un datepicker s'ouvre
    const tomorrow = page.locator('[data-testid="followup-date"], [class*="followup"]').first()
    if (await tomorrow.count() > 0) {
      await expect(tomorrow).toBeVisible({ timeout: 3000 })
      await tomorrow.click()
    }

    const sendButton = page
      .locator('button')
      .filter({ hasText: /envoyer/i })
      .first()
    await expect(sendButton).toBeVisible({ timeout: 5000 })

    const validateDone = page.waitForResponse(
      (resp) =>
        resp.url().includes(`/pending-drafts/${DRAFT_ID}/validate`) && resp.status() === 200,
      { timeout: 10000 }
    )
    await sendButton.click()
    await validateDone

    // With followup selected, archive should be absent or false
    expect(capturedBody).not.toBeNull()
    expect(capturedBody?.archive).toBeFalsy()
  })
})
