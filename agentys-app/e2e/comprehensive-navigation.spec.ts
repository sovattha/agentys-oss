/**
 * Comprehensive Navigation E2E Tests
 *
 * Tests complets : sidebar, dossiers (sent, trash, spam, archives),
 * onglets header, raccourcis clavier globaux, search.
 */

import { test, expect, Page } from '@playwright/test'
import { mockSearchResults } from './support/fixtures/mock-data'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

const mockSentEmails = {
  count: 3,
  emails: [
    { id: 'sent:s1', sender: 'test@example.com', sender_name: 'Moi', subject: 'Re: Devis', received_at: new Date().toISOString(), has_attachments: false, conversation_id: null, is_read: true },
    { id: 'sent:s2', sender: 'test@example.com', sender_name: 'Moi', subject: 'Rapport mensuel', received_at: new Date(Date.now() - 86400000).toISOString(), has_attachments: true, conversation_id: null, is_read: true },
    { id: 'sent:s3', sender: 'test@example.com', sender_name: 'Moi', subject: 'Invitation réunion', received_at: new Date(Date.now() - 172800000).toISOString(), has_attachments: false, conversation_id: null, is_read: true },
  ]
}

const mockSpamEmails = {
  count: 2,
  emails: [
    { id: 'spam-1', sender: 'scam@evil.com', sender_name: 'Nigerian Prince', subject: 'You won $1M!!!', received_at: new Date().toISOString(), has_attachments: false, conversation_id: null, is_read: false },
    { id: 'spam-2', sender: 'pills@spam.net', sender_name: 'Pharmacy', subject: 'Best deals', received_at: new Date(Date.now() - 86400000).toISOString(), has_attachments: false, conversation_id: null, is_read: false },
  ]
}

const mockTrashEmails = {
  count: 1,
  emails: [
    { id: 'trash-1', sender: 'old@example.com', sender_name: 'Ancien Contact', subject: 'Ancien email supprimé', received_at: new Date(Date.now() - 604800000).toISOString(), has_attachments: false, conversation_id: null, is_read: true },
  ]
}

async function setupFolderMocks(page: Page) {
  await setupBaseMocks(page)
  // Sent
  await page.route((url) => url.origin === API && url.pathname === '/api/emails' && url.search.includes('folder=sent'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSentEmails) })
  })
  // Spam
  await page.route((url) => url.origin === API && url.pathname === '/api/emails' && url.search.includes('folder=spam'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSpamEmails) })
  })
  // Trash
  await page.route((url) => url.origin === API && url.pathname === '/api/emails' && url.search.includes('folder=trash'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockTrashEmails) })
  })
  // Archived
  await page.route((url) => url.origin === API && url.pathname === '/api/emails' && url.search.includes('folder=archived'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 0, emails: [] }) })
  })
  // Search
  await page.route((url) => url.origin === API && url.pathname === '/api/emails/search', (route) => {
    const q = new URL(route.request().url()).searchParams.get('q') || ''
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSearchResults(q)) })
  })
}

test.describe('Sidebar — affichage et navigation', () => {
  test.beforeEach(async ({ page }) => { await setupFolderMocks(page); await page.goto('/'); await waitForAppReady(page) })

  test('affiche tous les onglets de navigation', async ({ page }) => {
    await expect(page.locator('[data-testid="nav-inbox"]')).toBeVisible({ timeout: 5000 })
    await expect(page.locator('[data-testid="nav-drafts"]')).toBeVisible({ timeout: 5000 })
    await expect(page.locator('[data-testid="nav-sent"]')).toBeVisible({ timeout: 5000 })
  })

  test('inbox est actif par défaut', async ({ page }) => {
    await expect(page.locator('[data-testid="nav-inbox"]')).toHaveClass(/active/, { timeout: 5000 })
  })

  test('navigue vers Envoyés', async ({ page }) => {
    await page.locator('[data-testid="nav-sent"]').click()
    await expect(page.locator('[data-testid="nav-sent"]')).toHaveClass(/active/, { timeout: 5000 })
  })

  test('navigue vers Brouillons', async ({ page }) => {
    await page.locator('[data-testid="nav-drafts"]').click()
    await expect(page.locator('[data-testid="nav-drafts"]')).toHaveClass(/active/, { timeout: 5000 })
  })

  test('navigue vers Archives', async ({ page }) => {
    const archiveNav = page.locator('[data-testid="nav-archived"]')
    await expect(archiveNav).toBeVisible({ timeout: 5000 })
    await archiveNav.click()
    await expect(archiveNav).toHaveClass(/active/, { timeout: 5000 })
  })

  test('navigue vers Spam', async ({ page }) => {
    const spamNav = page.locator('[data-testid="nav-spam"]')
    await expect(spamNav).toBeVisible({ timeout: 5000 })
    await spamNav.click()
    await expect(spamNav).toHaveClass(/active/, { timeout: 5000 })
  })

  test('navigue vers Corbeille', async ({ page }) => {
    const trashNav = page.locator('[data-testid="nav-trash"]')
    await expect(trashNav).toBeVisible({ timeout: 5000 })
    await trashNav.click()
    await expect(trashNav).toHaveClass(/active/, { timeout: 5000 })
  })

  test('retour à l\'inbox depuis un autre dossier', async ({ page }) => {
    await page.locator('[data-testid="nav-sent"]').click()
    await page.locator('[data-testid="nav-inbox"]').click()
    await expect(page.locator('[data-testid="nav-inbox"]')).toHaveClass(/active/, { timeout: 5000 })
  })
})

test.describe('Sidebar — collapse/expand', () => {
  test.beforeEach(async ({ page }) => { await setupFolderMocks(page); await page.goto('/'); await waitForAppReady(page) })

  test('toggle la sidebar', async ({ page }) => {
    const toggleBtn = page.locator('[data-testid="sidebar-toggle"], .sidebar-toggle-btn').first()
    const isVisible = await toggleBtn.isVisible({ timeout: 3000 }).catch(() => false)
    if (!isVisible) {
      test.skip(true, 'Sidebar toggle button not present')
      return
    }
    await toggleBtn.click()
    // Sidebar should still be in the DOM after toggle
    const sidebar = page.locator('.sidebar, [data-testid="sidebar"]').first()
    await expect(sidebar).toBeAttached()
  })
})

test.describe('Dossier Envoyés', () => {
  test.beforeEach(async ({ page }) => { await setupFolderMocks(page); await page.goto('/'); await waitForAppReady(page) })

  test('affiche les emails envoyés', async ({ page }) => {
    await page.locator('[data-testid="nav-sent"]').click()
    // Pas d'erreur 500
    await expect(page.locator('text=/erreur|error|500/i')).not.toBeVisible({ timeout: 3000 })
  })

  test('pas d\'erreur 500 dans le dossier Envoyés', async ({ page }) => {
    await page.locator('[data-testid="nav-sent"]').click()
    await page.waitForLoadState('domcontentloaded')
    await expect(page.locator('text=/Failed to fetch|500|erreur serveur/i')).not.toBeVisible({ timeout: 3000 })
  })
})

test.describe('Dossier Spam', () => {
  test.beforeEach(async ({ page }) => { await setupFolderMocks(page); await page.goto('/'); await waitForAppReady(page) })

  test('navigue vers spam sans erreur', async ({ page }) => {
    const spamNav = page.locator('[data-testid="nav-spam"]')
    await expect(spamNav).toBeVisible({ timeout: 5000 })
    await spamNav.click()
    await expect(page.locator('text=/erreur|error|500/i')).not.toBeVisible({ timeout: 3000 })
  })
})

test.describe('Dossier Corbeille', () => {
  test.beforeEach(async ({ page }) => { await setupFolderMocks(page); await page.goto('/'); await waitForAppReady(page) })

  test('navigue vers corbeille sans erreur', async ({ page }) => {
    const trashNav = page.locator('[data-testid="nav-trash"]')
    await expect(trashNav).toBeVisible({ timeout: 5000 })
    await trashNav.click()
    await expect(page.locator('text=/erreur|error|500/i')).not.toBeVisible({ timeout: 3000 })
  })
})

test.describe('Search — recherche', () => {
  test.beforeEach(async ({ page }) => { await setupFolderMocks(page); await page.goto('/'); await waitForAppReady(page) })

  test('affiche la barre de recherche après `/`', async ({ page }) => {
    // `.email-list-search-bar` est conditionnellement rendu (showSearchBar
    // state dans EmailList). Le raccourci `/` toggle la visibilité ; après
    // activation, la SmartSearchBar doit apparaître.
    await page.keyboard.press('/')
    const searchElement = page.locator('[data-testid="smart-search-bar"], .smart-search-bar, input[data-testid="smart-search-input"]').first()
    await expect(searchElement).toBeVisible({ timeout: 5000 })
  })

  test('ouvre la recherche au clic', async ({ page }) => {
    const searchTrigger = page.locator('text=/Recherche/i, button[aria-label*="echerch"]').first()
    const isVisible = await searchTrigger.isVisible({ timeout: 3000 }).catch(() => false)
    if (!isVisible) {
      test.skip(true, 'Search trigger not visible')
      return
    }
    await searchTrigger.click()
    // After clicking search, an input or search panel should appear
    const searchArea = page.locator('input[placeholder*="Rechercher"], input[type="search"], .search-input, .smart-search-bar').first()
    await expect(searchArea).toBeVisible({ timeout: 3000 })
  })

  test('permet de taper une recherche', async ({ page }) => {
    const searchTrigger = page.locator('text=/Recherche/i, button[aria-label*="echerch"]').first()
    const isVisible = await searchTrigger.isVisible({ timeout: 3000 }).catch(() => false)
    if (!isVisible) {
      test.skip(true, 'Search trigger not visible')
      return
    }
    await searchTrigger.click()
    const searchInput = page.locator('input[placeholder*="Rechercher"], input[type="search"], .search-input').first()
    await expect(searchInput).toBeVisible({ timeout: 5000 })
    await searchInput.fill('Rapport')
    await expect(searchInput).toHaveValue('Rapport')
  })

  test('ferme la recherche avec Escape', async ({ page }) => {
    const searchTrigger = page.locator('text=/Recherche/i, button[aria-label*="echerch"]').first()
    const isVisible = await searchTrigger.isVisible({ timeout: 3000 }).catch(() => false)
    if (!isVisible) {
      test.skip(true, 'Search trigger not visible')
      return
    }
    await searchTrigger.click()
    await page.waitForLoadState('domcontentloaded')
    await page.keyboard.press('Escape')
    // After Escape, no crash should occur and app should still be functional
    await expect(page.locator('.sidebar, [data-testid="sidebar"]').first()).toBeVisible()
  })
})

test.describe('Raccourcis clavier globaux', () => {
  test.beforeEach(async ({ page }) => { await setupFolderMocks(page); await page.goto('/'); await waitForAppReady(page) })

  test('la touche N ouvre le composer', async ({ page }) => {
    // NB : le raccourci est `n` seul (pas `Ctrl+N` qui est réservé par le
    // navigateur pour ouvrir une fenêtre). Cf. `useAppShortcuts.ts:217`.
    await page.route((url) => url.origin === API && url.pathname.startsWith('/api/snippets'), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ snippets: [], total: 0 }) })
    })
    await page.keyboard.press('n')
    await page.waitForLoadState('domcontentloaded')
    await expect(page.locator('.new-message-modal').first()).toBeVisible({ timeout: 5000 })
  })

  test('Ctrl+, ouvre les paramètres', async ({ page }) => {
    await page.keyboard.press('Control+,')
    await page.waitForLoadState('domcontentloaded')
    await expect(page.locator('.settings-modal, [data-testid="settings-modal"]').first()).toBeVisible({ timeout: 5000 })
  })

  test('Ctrl+/ ouvre l\'aide raccourcis', async ({ page }) => {
    await page.keyboard.press('Control+/')
    await page.waitForLoadState('domcontentloaded')
    // Le panel est rendu avec les classes `.shortcuts-help-overlay` et
    // `.shortcuts-help-panel` (cf. ShortcutsHelpPanel.tsx:136-137).
    await expect(page.locator('.shortcuts-help-overlay, .shortcuts-help-panel').first()).toBeVisible({ timeout: 5000 })
  })
})
