/**
 * Inline Image Insert E2E Tests
 *
 * Tests: image insertion in compose editor, size limit, MIME type validation.
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

async function setupComposeMocks(page: Page) {
  await setupBaseMocks(page)
  await page.route((url) => url.origin === API && url.pathname === '/api/contacts/autocomplete', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  })
  await page.route((url) => url.origin === API && url.pathname.startsWith('/api/snippets'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ snippets: [], total: 0 }) })
  })
}

async function openNewMessage(page: Page) {
  await page.locator('body').click({ position: { x: 10, y: 10 } })
  await page.keyboard.press('n')
  await page.locator('.new-message-modal').first().waitFor({ state: 'visible', timeout: 10000 })
}

// Minimal 1x1 red PNG (89 bytes)
const TINY_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==',
  'base64'
)

test.describe('Inline Image Insert', () => {
  test.beforeEach(async ({ page }) => {
    await setupComposeMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('inserting a valid image shows <img> in the editor', async ({ page }) => {
    await openNewMessage(page)

    const fileInput = page.locator('.new-message-modal input[type="file"][accept="image/*"]').first()
    await fileInput.setInputFiles({
      name: 'test-image.png',
      mimeType: 'image/png',
      buffer: TINY_PNG,
    })

    const editorImg = page.locator('.new-message-modal .draft-editor-content img').first()
    await expect(editorImg).toBeVisible({ timeout: 5000 })
    const src = await editorImg.getAttribute('src')
    expect(src).toMatch(/^data:image\//)
  })

  test('oversized image shows error message', async ({ page }) => {
    await openNewMessage(page)

    const fileInput = page.locator('.new-message-modal input[type="file"][accept="image/*"]').first()
    const largeBuffer = Buffer.alloc(6 * 1024 * 1024, 0)
    await fileInput.setInputFiles({
      name: 'huge.png',
      mimeType: 'image/png',
      buffer: largeBuffer,
    })

    const errorBanner = page.locator('.new-message-modal .rc-error').first()
    await expect(errorBanner).toBeVisible({ timeout: 3000 })

    const editorImg = page.locator('.new-message-modal .draft-editor-content img')
    await expect(editorImg).toHaveCount(0)
  })

  test('non-image file shows invalid type error', async ({ page }) => {
    await openNewMessage(page)

    const fileInput = page.locator('.new-message-modal input[type="file"][accept="image/*"]').first()
    await fileInput.setInputFiles({
      name: 'document.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('fake pdf content'),
    })

    const errorBanner = page.locator('.new-message-modal .rc-error').first()
    await expect(errorBanner).toBeVisible({ timeout: 3000 })
  })
})
