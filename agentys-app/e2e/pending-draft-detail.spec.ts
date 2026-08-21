/**
 * Pending Draft Detail E2E Tests
 *
 * Tests pour le composant PendingDraftDetail de l'application Agentys.
 */

import { test, expect, Page } from '@playwright/test'
import { mockEmailDetails } from './support/fixtures/mock-data'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

const mockPendingDraft = {
  id: 'draft-1', email_id: 'email-1',
  email_subject: 'Rapport trimestriel Q4 2025', email_sender: 'marie.dupont@example.com', email_sender_name: 'Marie Dupont',
  email_body: '<p>Bonjour, veuillez trouver ci-joint le rapport trimestriel.</p>',
  draft_subject: 'Re: Rapport trimestriel Q4 2025',
  draft_body: 'Bonjour Marie,\n\nMerci pour ce rapport détaillé. Les résultats sont très encourageants.\n\nCordialement',
  draft_v1: 'Merci pour le rapport.',
  status: 'pending', classification: 'action', routing_tier: 'STANDARD',
  critique: 'Bon ton, réponse complète. Score: 87/100. Verdict: VALID.',
  smart_suggestions: ['Merci, bien noté !', 'Je reviens vers vous rapidement.'],
  created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
}

const mockDraftsResponse = {
  drafts: [mockPendingDraft, { ...mockPendingDraft, id: 'draft-2', email_id: 'email-2', email_sender: 'pierre.martin@example.com', email_sender_name: 'Pierre Martin', email_subject: 'Re: Réunion projet Alpha' }],
  pending_count: 2,
}

async function setupDraftDetailMocks(page: Page) {
  await setupBaseMocks(page)
  await page.route((url) => url.origin === API && url.pathname === '/api/pending-drafts', (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDraftsResponse) })
    } else { route.continue() }
  })
  await page.route((url) => url.origin === API && url.pathname.match(/^\/api\/pending-drafts\/draft-\d+$/) !== null, (route) => {
    if (route.request().method() === 'GET') { route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockPendingDraft) }) }
    else if (route.request().method() === 'PUT') { route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: mockPendingDraft }) }) }
    else if (route.request().method() === 'DELETE') { route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, draft_id: 'draft-1' }) }) }
    else { route.continue() }
  })
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts/by-email'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockPendingDraft) })
  })
  await page.route((url) => url.origin === API && url.pathname.match(/^\/api\/emails\/email-\d+$/) !== null, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockEmailDetails['email-1']) })
  })
  await page.route((url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/read$/) !== null, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
  })
  await page.route((url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/thread$/) !== null, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 1, emails: [] }) })
  })
  await page.route((url) => url.origin === API && url.pathname.match(/\/api\/pending-drafts\/[^/]+\/validate$/) !== null, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, sent: true }) })
  })
  await page.route((url) => url.origin === API && url.pathname.match(/\/api\/pending-drafts\/[^/]+\/refine$/) !== null, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, refined_body: 'Brouillon affiné.' }) })
  })
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/contacts'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  })
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/snippets'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ snippets: [], total: 0 }) })
  })
}

async function openFirstDraft(page: Page) {
  await page.locator('[data-testid="nav-drafts"]').click()
  const draftItem = page.locator('.draft-item').first()
  await expect(draftItem).toBeVisible({ timeout: 10000 })
  await draftItem.click()
}

test.describe('Pending Draft Detail — affichage', () => {
  test.beforeEach(async ({ page }) => { await setupDraftDetailMocks(page); await page.goto('/'); await waitForAppReady(page) })

  test('ouvre le détail d\'un brouillon au clic', async ({ page }) => {
    await openFirstDraft(page)
    await expect(page.locator('.pending-draft-detail, .pdd-draft-zone, .draft-card').first()).toBeVisible({ timeout: 10000 })
  })
  test('affiche le sujet de l\'email original', async ({ page }) => {
    await openFirstDraft(page)
    await expect(page.locator('text=Rapport trimestriel Q4 2025').first()).toBeVisible({ timeout: 10000 })
  })
  test('affiche l\'expéditeur', async ({ page }) => {
    await openFirstDraft(page)
    await expect(page.locator('text=/Marie Dupont/i').first()).toBeVisible({ timeout: 10000 })
  })
  test('affiche le corps du brouillon', async ({ page }) => {
    await openFirstDraft(page)
    await expect(page.locator('.draft-card-body-textarea, .rc-editor-area, [data-testid="draft-body"]').first()).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Pending Draft Detail — actions', () => {
  test.beforeEach(async ({ page }) => { await setupDraftDetailMocks(page); await page.goto('/'); await waitForAppReady(page); await openFirstDraft(page) })

  test('affiche le bouton Envoyer', async ({ page }) => {
    await expect(page.locator('[data-testid="send-button"], .rc-send-pill-main, [data-testid="reply-send-button"]').first()).toBeVisible({ timeout: 10000 })
  })
  test('affiche le bouton Supprimer', async ({ page }) => {
    await expect(page.locator('[data-testid="reject-button"], .rc-delete-btn').first()).toBeVisible({ timeout: 10000 })
  })
  test('affiche la barre d\'actions', async ({ page }) => {
    await expect(page.locator('.rc-action-bar').first()).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Pending Draft Detail — pipeline', () => {
  test.beforeEach(async ({ page }) => { await setupDraftDetailMocks(page); await page.goto('/'); await waitForAppReady(page); await openFirstDraft(page) })

  test('affiche le toggle pipeline', async ({ page }) => {
    await expect(page.locator('.pipeline-disclosure, .ai-intelligence-banner, [data-testid="ai-process-button"]').first()).toBeVisible({ timeout: 10000 })
  })
  test('ouvre les pipeline cards au clic', async ({ page }) => {
    await page.locator('.pipeline-disclosure, [data-testid="ai-process-button"]').first().click()
    await expect(page.locator('.pipeline-cards-section, .rc-pipeline-cards').first()).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Pending Draft Detail — mode réponse', () => {
  test.beforeEach(async ({ page }) => { await setupDraftDetailMocks(page); await page.goto('/'); await waitForAppReady(page); await openFirstDraft(page) })

  test('affiche la pill de mode réponse', async ({ page }) => {
    await expect(page.locator('.draft-mode-pill').first()).toBeVisible({ timeout: 10000 })
  })
  test('affiche le destinataire', async ({ page }) => {
    await expect(page.locator('.draft-card-recipient, .rc-recipient-row, [data-testid="recipient-to"]').first()).toBeVisible({ timeout: 10000 })
  })
})
