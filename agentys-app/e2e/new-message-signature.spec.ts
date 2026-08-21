/**
 * NewMessageModal — Signature + Contact Autocomplete E2E Tests
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

const ACCOUNT_WITH_SIGNATURE = {
  accounts: [{
    id: '1',
    email: 'test@example.com',
    status: 'active',
    signature: 'Cordialement,\nAlexandre',
    signature_html: '<div>Cordialement,<br>Alexandre</div>',
  }],
  current_account_id: '1',
}

const CONTACTS_RESULTS = [
  { name: 'Alexandre Simon', email: 'alexandre.simon@hotmail.com' },
  { name: 'Alex Martin', email: 'alex.martin@gmail.com' },
]

async function setupSignatureMocks(page: Page) {
  await setupBaseMocks(page)

  // Override /api/accounts with signature data
  await page.route(`${API}/api/accounts`, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(ACCOUNT_WITH_SIGNATURE),
    })
  })

  // Override contacts autocomplete with results
  await page.route(
    (url) => url.origin === API && url.pathname === '/api/contacts/autocomplete',
    (route) => {
      const q = new URL(route.request().url()).searchParams.get('q') || ''
      const filtered = q
        ? CONTACTS_RESULTS.filter(c =>
            c.name.toLowerCase().includes(q.toLowerCase()) ||
            c.email.toLowerCase().includes(q.toLowerCase())
          )
        : CONTACTS_RESULTS
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(filtered),
      })
    }
  )

  // Mock other compose-related routes
  await page.route((url) => url.origin === API && url.pathname === '/api/refine-text', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, refined_text: 'Texte affiné.' }) })
  })
  await page.route((url) => url.origin === API && url.pathname === '/api/emails/compose', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, message_id: 'msg-123' }) })
  })
}

async function openNewMessage(page: Page) {
  await page.locator('body').click({ position: { x: 10, y: 10 } })
  await page.keyboard.press('n')
  await page.locator('.new-message-modal').first().waitFor({ state: 'visible', timeout: 10000 })
}

test.describe('NewMessage — Signature insertion', () => {
  test.beforeEach(async ({ page }) => {
    await setupSignatureMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('insère la signature au premier affichage', async ({ page }) => {
    await openNewMessage(page)
    const textarea = page.locator('.gmail-textarea').first()
    await expect(textarea).toBeVisible({ timeout: 5000 })
    // Wait for async fetchAccounts to resolve and signature to be inserted
    await expect(textarea).toHaveValue(/Cordialement/, { timeout: 5000 })
  })

  test('insère la signature après fermeture et réouverture', async ({ page }) => {
    // First open
    await openNewMessage(page)
    await expect(page.locator('.gmail-textarea').first()).toHaveValue(/Cordialement/, { timeout: 5000 })

    // Close via X button
    await page.locator('.gmail-header-btn').last().click()
    await page.locator('.new-message-modal').first().waitFor({ state: 'hidden', timeout: 5000 })

    // Reopen
    await openNewMessage(page)
    await expect(page.locator('.gmail-textarea').first()).toHaveValue(/Cordialement/, { timeout: 5000 })
  })
})

test.describe('NewMessage — Contact Autocomplete', () => {
  test.beforeEach(async ({ page }) => {
    await setupSignatureMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openNewMessage(page)
  })

  test('affiche les suggestions quand on tape dans le champ To', async ({ page }) => {
    const toInput = page.locator('.gmail-field .contact-autocomplete input').first()
    await toInput.focus()
    await toInput.fill('alex')
    // Wait for debounced API call (300ms) + render
    await expect(page.locator('.suggestions-list')).toBeVisible({ timeout: 5000 })
    await expect(page.locator('.suggestion-item').first()).toBeVisible({ timeout: 3000 })
  })

  test('affiche le nom et email du contact', async ({ page }) => {
    const toInput = page.locator('.gmail-field .contact-autocomplete input').first()
    await toInput.focus()
    await toInput.fill('alex')
    await expect(page.locator('.suggestions-list')).toBeVisible({ timeout: 5000 })
    await expect(page.locator('.contact-name').first()).toContainText('Alexandre')
    await expect(page.locator('.contact-email').first()).toContainText('alexandre.simon')
  })

  test('sélectionne un contact au clic', async ({ page }) => {
    const toInput = page.locator('.gmail-field .contact-autocomplete input').first()
    await toInput.focus()
    await toInput.fill('alex')
    await expect(page.locator('.suggestion-item').first()).toBeVisible({ timeout: 5000 })
    await page.locator('.suggestion-item').first().click()
    // Should create a chip with the contact
    await expect(page.locator('.ca-chip').first()).toBeVisible({ timeout: 3000 })
  })

  test('dropdown au-dessus des champs suivants (z-index)', async ({ page }) => {
    const toInput = page.locator('.gmail-field .contact-autocomplete input').first()
    await toInput.focus()
    await toInput.fill('alex')
    await expect(page.locator('.suggestions-list')).toBeVisible({ timeout: 5000 })

    // The dropdown should be clickable (not hidden behind subject field)
    const firstItem = page.locator('.suggestion-item').first()
    await expect(firstItem).toBeVisible()
    const box = await firstItem.boundingBox()
    expect(box).toBeTruthy()
    expect(box!.height).toBeGreaterThan(0)
  })
})
