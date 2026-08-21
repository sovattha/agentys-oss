/**
 * Smart Suggestions E2E Tests (Phase 18)
 *
 * Vérifie les suggestion chips IA dans PendingDraftDetail.
 * Les smart suggestions remplacent les Quick Reply buttons de Phase 16.
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

const MOCK_DRAFT_WITH_SUGGESTIONS = {
  id: 'draft-sug-1',
  email_id: 'email-sug-1',
  email_subject: 'Disponible mardi ?',
  email_sender: 'alice@example.com',
  email_body: 'Bonjour, es-tu disponible mardi pour une réunion ?',
  draft_body: '',
  draft_subject: 'Re: Disponible mardi ?',
  status: 'PENDING',
  created_at: new Date().toISOString(),
  smart_suggestions: ['Oui, je suis disponible.', 'Non, je ne suis pas disponible mardi.', 'Je vérifierai et te reviens.'],
  quick_replies: null,
}

async function setupSuggestionMocks(page: Page) {
  await setupBaseMocks(page)

  // Override pending-drafts to return draft with smart_suggestions
  await page.route((url) => url.origin === API && url.pathname === '/api/pending-drafts', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        count: 1,
        pending_count: 1,
        drafts: [MOCK_DRAFT_WITH_SUGGESTIONS],
      }),
    })
  })

  await page.route((url) => url.origin === API && url.pathname === `/api/pending-drafts/${MOCK_DRAFT_WITH_SUGGESTIONS.id}`, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_DRAFT_WITH_SUGGESTIONS),
    })
  })

  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts/') && url.pathname.endsWith('/validate'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, message_id: 'sent-sug-1' }) })
  })

  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts/') && url.pathname.endsWith('/reject'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
  })

  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/refine-text'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, refined_text: 'Oui, je suis disponible mardi.' }) })
  })

  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/emails/email-sug-1'), (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'email-sug-1',
        subject: 'Disponible mardi ?',
        sender: 'alice@example.com',
        body: 'Bonjour, es-tu disponible mardi pour une réunion ?',
        received_at: new Date().toISOString(),
      }),
    })
  })

  await page.route((url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/read$/) !== null, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
  })

  await page.route((url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/thread$/) !== null, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 1, emails: [] }) })
  })

  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts/by-email'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_DRAFT_WITH_SUGGESTIONS) })
  })
}

async function openDraftWithSuggestions(page: Page) {
  // Navigate to brouillons tab
  await page.locator('[data-testid="nav-drafts"]').click()
  const draftItem = page.locator('.draft-item, [data-testid="email-item"], .pending-draft-row').first()
  await expect(draftItem).toBeVisible({ timeout: 10000 })
  await draftItem.click()
  await page.waitForLoadState('domcontentloaded')
}

test.describe('Smart Suggestions — affichage', () => {
  test.beforeEach(async ({ page }) => {
    await setupSuggestionMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openDraftWithSuggestions(page)
  })

  test('affiche les suggestion chips', async ({ page }) => {
    // Smart suggestions should appear as clickable chips in PendingDraftDetail
    const chips = page.locator('.smart-suggestion-chip, .suggestion-chip, .rc-suggestion-chip')
    await expect(chips.first()).toBeVisible({ timeout: 5000 })
    const count = await chips.count()
    expect(count).toBeGreaterThan(0)
    expect(count).toBeLessThanOrEqual(3)
  })

  test('les suggestion chips contiennent le texte suggéré', async ({ page }) => {
    const chips = page.locator('.smart-suggestion-chip, .suggestion-chip, .rc-suggestion-chip')
    const firstChip = chips.first()
    await expect(firstChip).toBeVisible({ timeout: 5000 })
    const text = await firstChip.textContent()
    expect(text?.trim().length).toBeGreaterThan(0)
  })
})

test.describe('Smart Suggestions — interaction', () => {
  test.beforeEach(async ({ page }) => {
    await setupSuggestionMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openDraftWithSuggestions(page)
  })

  test('cliquer sur un chip remplit le brouillon', async ({ page }) => {
    const chips = page.locator('.smart-suggestion-chip, .suggestion-chip, .rc-suggestion-chip')
    await expect(chips.first()).toBeVisible({ timeout: 5000 })
    await chips.first().click()
    // The draft body should now contain the suggestion text.
    // Parité compose (2026-06-09) : le body Drafts est un DraftEditor TipTap
    // (contenteditable) — lire textContent, pas inputValue.
    const editor = page.locator('[data-testid="draft-body"] .draft-editor-content').first()
    await expect(editor).toBeVisible({ timeout: 5000 })
    const val = (await editor.textContent()) ?? ''
    expect(val.trim().length).toBeGreaterThan(0)
  })
})
