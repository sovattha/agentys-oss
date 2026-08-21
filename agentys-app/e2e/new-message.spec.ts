/**
 * NewMessageModal E2E Tests
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

async function setupComposeMocks(page: Page) {
  await setupBaseMocks(page)
  await page.route((url) => url.origin === API && url.pathname === '/api/contacts/autocomplete', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  })
  await page.route((url) => url.origin === API && url.pathname === '/api/refine-text', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, refined_text: 'Texte affiné par IA.' }) })
  })
  await page.route((url) => url.origin === API && url.pathname === '/api/emails/compose', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, message_id: 'msg-123' }) })
  })
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/snippets'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ snippets: [], total: 0 }) })
  })
}

async function openNewMessage(page: Page) {
  // Défocuser puis N pour nouveau message
  await page.locator('body').click({ position: { x: 10, y: 10 } })
  await page.keyboard.press('n')
  await page.locator('.new-message-modal').first().waitFor({ state: 'visible', timeout: 10000 })
}

test.describe('NewMessage — ouverture et affichage', () => {
  test.beforeEach(async ({ page }) => { await setupComposeMocks(page); await page.goto('/'); await waitForAppReady(page) })

  test('ouvre la modale avec N', async ({ page }) => {
    await openNewMessage(page)
    await expect(page.locator('.new-message-modal').first()).toBeVisible()
  })

  test('affiche le titre Nouveau message', async ({ page }) => {
    await openNewMessage(page)
    await expect(page.locator('.gmail-title').first()).toBeVisible({ timeout: 5000 })
  })

  test('affiche le champ To', async ({ page }) => {
    await openNewMessage(page)
    await expect(page.locator('.gmail-input').first()).toBeVisible({ timeout: 5000 })
  })

  test('affiche le champ Objet', async ({ page }) => {
    await openNewMessage(page)
    await expect(page.locator('.gmail-input').first()).toBeVisible({ timeout: 5000 })
  })

  test('affiche l\'éditeur du corps', async ({ page }) => {
    await openNewMessage(page)
    // Le corps est un DraftEditor (TipTap/ProseMirror) — plus un textarea.
    await expect(page.locator('.new-message-modal .draft-editor').first()).toBeVisible({ timeout: 5000 })
  })

  test('affiche le bouton Envoyer', async ({ page }) => {
    await openNewMessage(page)
    await expect(page.locator('.send-pill').first()).toBeVisible({ timeout: 5000 })
  })

  test('le bouton Envoyer est désactivé sans destinataire', async ({ page }) => {
    await openNewMessage(page)
    await expect(page.locator('.send-pill').first()).toBeDisabled({ timeout: 5000 })
  })
})

test.describe('NewMessage — CC/BCC', () => {
  test.beforeEach(async ({ page }) => { await setupComposeMocks(page); await page.goto('/'); await waitForAppReady(page); await openNewMessage(page) })

  test('affiche le toggle Cc', async ({ page }) => {
    await expect(page.locator('.gmail-cc-link').first()).toBeVisible({ timeout: 5000 })
  })

  test('affiche le champ Cc au clic', async ({ page }) => {
    await page.locator('.gmail-cc-link').first().click()
    await expect(page.locator('input[placeholder="Cc"]').first()).toBeVisible({ timeout: 5000 })
  })

  test('affiche le champ Cci au clic', async ({ page }) => {
    // Cliquer sur le lien Cci (peut être le 2e .gmail-cc-link)
    const bccLink = page.locator('.gmail-cc-link:has-text("Cci"), .gmail-cc-link:has-text("Bcc")')
    await expect(bccLink.first()).toBeVisible({ timeout: 5000 })
    await bccLink.first().click()
    await expect(page.locator('input[placeholder="Cci"], input[placeholder="Bcc"]').first()).toBeVisible({ timeout: 5000 })
  })
})

test.describe('NewMessage — AICommandMenu (refonte composer 2026-04)', () => {
  test.beforeEach(async ({ page }) => { await setupComposeMocks(page); await page.goto('/'); await waitForAppReady(page); await openNewMessage(page) })

  test('affiche le trigger AICommandMenu', async ({ page }) => {
    await expect(page.locator('[data-testid="ai-command-trigger"]').first()).toBeVisible({ timeout: 5000 })
  })

  test('ouvre le popover au clic sur le trigger', async ({ page }) => {
    await page.locator('[data-testid="ai-command-trigger"]').first().click()
    await expect(page.locator('.ai-cmd-popover').first()).toBeVisible({ timeout: 5000 })
    await expect(page.locator('.ai-cmd-input').first()).toBeVisible({ timeout: 5000 })
  })

  test('liste les commandes prédéfinies', async ({ page }) => {
    await page.locator('[data-testid="ai-command-trigger"]').first().click()
    await expect(page.locator('.ai-cmd-popover .ai-cmd-row').first()).toBeVisible({ timeout: 5000 })
    const count = await page.locator('.ai-cmd-popover .ai-cmd-row').count()
    expect(count).toBeGreaterThan(0)
  })

  test('Escape referme le popover', async ({ page }) => {
    await page.locator('[data-testid="ai-command-trigger"]').first().click()
    await expect(page.locator('.ai-cmd-popover').first()).toBeVisible({ timeout: 5000 })
    await page.keyboard.press('Escape')
    await expect(page.locator('.ai-cmd-popover').first()).toBeHidden({ timeout: 5000 })
  })
})

test.describe('NewMessage — maximiser', () => {
  test.beforeEach(async ({ page }) => { await setupComposeMocks(page); await page.goto('/'); await waitForAppReady(page); await openNewMessage(page) })

  test('affiche les boutons header (maximiser, fermer)', async ({ page }) => {
    await expect(page.locator('.gmail-header-btn').first()).toBeVisible({ timeout: 5000 })
  })

  // FIXME (audit 2026-06-09) : le bouton « maximiser » a été retiré du
  // header (seul le bouton fermer reste — NewMessageModal.tsx:1733). Le
  // CSS .maximized subsiste mais aucun contrôle UI ne l'active.
  test.fixme('maximise la modale au clic', async ({ page }) => {
    await page.locator('.gmail-header-btn').first().click()
    await expect(page.locator('.new-message-modal.maximized').first()).toBeVisible({ timeout: 5000 })
  })
})

test.describe('NewMessage — auto-save', () => {
  test.beforeEach(async ({ page }) => { await setupComposeMocks(page); await page.goto('/'); await waitForAppReady(page); await openNewMessage(page) })

  test('sauvegarde le brouillon à la fermeture', async ({ page }) => {
    // Remplir le sujet (placeholder est "OBJET" en majuscules)
    const subjectInput = page.locator('.gmail-input').first()
    await expect(subjectInput).toBeVisible({ timeout: 5000 })
    await subjectInput.fill('Test auto-save')
    // Fermer via le bouton X (dernier .gmail-header-btn)
    const closeBtn = page.locator('.gmail-header-btn').last()
    await closeBtn.click()
    await page.locator('.new-message-modal').first().waitFor({ state: 'hidden', timeout: 5000 })
    // Vérifier le localStorage — les brouillons sont désormais scopés par
    // compte (`agentys_saved_drafts:<accountId>`, voir draftStorage.ts) ;
    // balayer toutes les clés du préfixe.
    const hasDraft = await page.evaluate(() => {
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i)
        if (!key || !key.startsWith('agentys_saved_drafts')) continue
        try {
          const drafts = JSON.parse(localStorage.getItem(key) || '[]')
          if (Array.isArray(drafts) && drafts.length > 0) return true
        } catch { /* clé corrompue — ignorer */ }
      }
      return false
    })
    expect(hasDraft).toBe(true)
  })
})

test.describe('NewMessage — footer', () => {
  test.beforeEach(async ({ page }) => { await setupComposeMocks(page); await page.goto('/'); await waitForAppReady(page); await openNewMessage(page) })

  test('affiche le footer', async ({ page }) => {
    await expect(page.locator('.gmail-footer').first()).toBeVisible({ timeout: 5000 })
  })

  test('affiche le bouton pièce jointe', async ({ page }) => {
    await expect(page.locator('button[aria-label="Joindre des fichiers"]').first()).toBeVisible({ timeout: 5000 })
  })

  test('affiche le bouton poubelle', async ({ page }) => {
    await expect(page.locator('.rc-delete-btn').first()).toBeVisible({ timeout: 5000 })
  })
})
