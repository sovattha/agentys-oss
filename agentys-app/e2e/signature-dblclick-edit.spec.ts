/**
 * Signature — clic pour éditer + chips de bascule (issue #914)
 *
 * 1. Cliquer le footer signature du ReplyComposer ouvre l'éditeur
 *    inline per-contact (le bouton ✏️ Signature dédié a été retiré :
 *    la signature elle-même est l'affordance).
 * 2. Si la bibliothèque de signatures du compte contient des entrées,
 *    l'éditeur affiche des chips (noms) ; cliquer un chip remplit le
 *    textarea avec le texte de cette signature.
 */

import { test, expect, Page } from '@playwright/test'
import { isApiRoute, setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const EMAIL = {
  id: 'sig-dblclick-1',
  sender: 'Alexandre <alexandre@example.com>',
  sender_name: 'Alexandre',
  sender_email: 'alexandre@example.com',
  subject: 'Vendredi',
  body: '<p>Tu confirmes pour vendredi ?</p>',
  body_preview: 'Tu confirmes pour vendredi ?',
  received_at: new Date().toISOString(),
  has_attachments: false,
  conversation_id: 'thread-sig-dblclick',
  is_read: false,
  to: ['me@example.com'],
  cc: [],
  attachments: [],
}

const ACCOUNTS = [
  {
    id: 'hash-a',
    hash_id: 'hash-a',
    email: 'me@example.com',
    provider: 'gmail',
    status: 'active',
    is_current: true,
    signature: 'Alexandre Simon\nCo-fondateur',
    signature_html: '<div>Alexandre Simon</div><div>Co-fondateur</div>',
  },
]

const LIBRARY = {
  signatures: [
    { id: 'sig_a', name: 'Pro', html: '<div>Alexandre Simon</div><div>Co-fondateur</div>', text: 'Alexandre Simon\nCo-fondateur', is_default: true },
    { id: 'sig_b', name: 'Perso', html: '<div>Alex</div>', text: 'Alex', is_default: false },
  ],
  default_id: 'sig_a',
}

async function setupMocks(page: Page) {
  await setupBaseMocks(page, {
    emailsResponse: { emails: [EMAIL], has_more: false, source: 'mock' },
  })
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/accounts',
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ count: 1, current_account_id: 'hash-a', accounts: ACCOUNTS }),
    }),
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/accounts/hash-a/signatures',
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(LIBRARY),
    }),
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/writing-style/contact-style',
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ exists: false }),
    }),
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname === `/api/emails/${EMAIL.id}`,
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EMAIL) }),
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname === `/api/emails/${EMAIL.id}/thread`,
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ count: 1, emails: [EMAIL] }),
    }),
  )
}

async function openReplyComposer(page: Page) {
  await page.goto('/')
  await waitForAppReady(page)
  await page.locator('.swipeable-email-item').first().click()
  const replyBtn = page.locator('[data-testid="reply-button"]').first()
  await expect(replyBtn).toBeVisible({ timeout: 10_000 })
  await replyBtn.click()
  const composer = page.locator('[data-testid="reply-composer"], .reply-composer').first()
  await expect(composer).toBeVisible({ timeout: 10_000 })
  return composer
}

test.describe('Signature — clic pour éditer', () => {
  test('clic sur le footer signature ouvre l\'éditeur inline (pas de bouton dédié)', async ({ page }) => {
    await setupMocks(page)
    const composer = await openReplyComposer(page)

    const footer = composer.locator('.rc-signature-footer').first()
    await expect(footer).toBeVisible({ timeout: 5_000 })
    await expect(composer.locator('.rc-signature-edit-button')).toHaveCount(0)
    await footer.click()

    await expect(composer.locator('.rc-signature-textarea')).toBeVisible({ timeout: 3_000 })

    // Régression : le padding global des <button> compressait les SVG des
    // boutons Enregistrer/Annuler à largeur nulle (icônes invisibles).
    const saveIcon = composer.locator('.rc-signature-icon-button--primary svg')
    await expect(saveIcon).toBeVisible()
    const box = await saveIcon.boundingBox()
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(12)

    // Échap ferme l'éditeur inline SANS fermer le composer hôte.
    await composer.locator('.rc-signature-textarea').press('Escape')
    await expect(composer.locator('.rc-signature-textarea')).toHaveCount(0)
    await expect(composer).toBeVisible()
  })

  test('l\'éditeur affiche les chips de la bibliothèque et un clic remplit le texte', async ({ page }) => {
    await setupMocks(page)
    const composer = await openReplyComposer(page)

    const footer = composer.locator('.rc-signature-footer').first()
    await expect(footer).toBeVisible({ timeout: 5_000 })
    await footer.click()

    const chips = composer.locator('[data-testid="rc-signature-chip"]')
    await expect(chips).toHaveCount(2, { timeout: 5_000 })
    await expect(chips.nth(0)).toContainText('Pro')
    await expect(chips.nth(1)).toContainText('Perso')

    await chips.nth(1).click()
    await expect(composer.locator('.rc-signature-textarea')).toHaveValue('Alex')
  })

  test('compose : clic sur la signature ouvre le même éditeur que la réponse, portée message', async ({ page }) => {
    await setupMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await page.locator('body').click({ position: { x: 10, y: 10 } })
    await page.keyboard.press('n')
    const modal = page.locator('.new-message-modal').first()
    await expect(modal).toBeVisible({ timeout: 10_000 })

    const footer = modal.locator('.nm-signature-footer')
    await expect(footer).toBeVisible({ timeout: 5_000 })
    await expect(footer).toContainText('Co-fondateur')
    await footer.click()

    // Même UI que la réponse : chips + textarea + ✓/✕.
    const textarea = modal.locator('.rc-signature-textarea')
    await expect(textarea).toBeVisible({ timeout: 3_000 })
    const chips = modal.locator('[data-testid="rc-signature-chip"]')
    await expect(chips).toHaveCount(2, { timeout: 5_000 })

    // Échap ferme l'éditeur SANS fermer le compose.
    await textarea.press('Escape')
    await expect(modal.locator('.rc-signature-textarea')).toHaveCount(0)
    await expect(modal).toBeVisible()

    // Chip « Perso » remplit le textarea ; ✓ applique à ce message.
    await footer.click()
    await modal.locator('[data-testid="rc-signature-chip"]').nth(1).click()
    await expect(modal.locator('.rc-signature-textarea')).toHaveValue('Alex')
    await modal.locator('.rc-signature-icon-button--primary').click()
    await expect(footer).not.toContainText('Co-fondateur')
    await expect(footer).toContainText('Alex')
    await expect(modal.locator('.rc-signature-textarea')).toHaveCount(0)
  })
})
