/**
 * Whisper Microphone Dictation E2E Tests
 *
 * Tests the mic button in Compose (NewMessageModal) and Reply (ReplyComposer).
 * MediaRecorder and getUserMedia are mocked since real audio is unavailable in CI.
 */

import { test, expect, Page } from '@playwright/test'
import { mockEmailDetails } from './support/fixtures/mock-data'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Inject MediaRecorder + getUserMedia + AudioContext mocks into the page context. */
async function mockMediaRecorder(page: Page) {
  await page.addInitScript(() => {
    // Fake audio stream with a stop-able track
    const fakeTrack = { stop: () => {}, kind: 'audio' as const, enabled: true }
    const fakeStream = { getTracks: () => [fakeTrack] } as unknown as MediaStream

    // Override getUserMedia
    Object.defineProperty(navigator, 'mediaDevices', {
      value: {
        getUserMedia: async () => fakeStream,
        enumerateDevices: async () => [],
      },
      writable: true,
    })

    // Mock AudioContext so createMediaStreamSource doesn't throw with fake stream
    class FakeAudioContext {
      createMediaStreamSource() { return { connect: () => {} } }
      createAnalyser() {
        return {
          fftSize: 256,
          smoothingTimeConstant: 0,
          frequencyBinCount: 128,
          getByteFrequencyData: (arr: Uint8Array) => arr.fill(0),
        }
      }
      close() { return Promise.resolve() }
    }
    ;(window as unknown as Record<string, unknown>).AudioContext = FakeAudioContext

    // Minimal MediaRecorder mock
    class FakeMediaRecorder {
      state = 'inactive' as 'inactive' | 'recording'
      mimeType = 'audio/webm'
      ondataavailable: ((e: { data: Blob }) => void) | null = null
      onstop: (() => void) | null = null

      static isTypeSupported() { return true }

      start() {
        this.state = 'recording'
      }

      stop() {
        this.state = 'inactive'
        // Simulate audio data chunk
        const fakeAudio = new Blob([new Uint8Array(8192)], { type: 'audio/webm' })
        this.ondataavailable?.({ data: fakeAudio })
        // Trigger onstop asynchronously (matches real MediaRecorder behavior)
        setTimeout(() => this.onstop?.(), 0)
      }
    }

    ;(window as unknown as Record<string, unknown>).MediaRecorder = FakeMediaRecorder
  })
}

/** Mock the /api/transcribe endpoint to return a known transcript. */
async function mockTranscribeEndpoint(page: Page, text = 'Bonjour, ceci est un test de dictée vocale.') {
  await page.route(
    (url) => url.pathname === '/api/transcribe',
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ text }),
    }),
  )
}

async function setupComposeMocks(page: Page) {
  await setupBaseMocks(page)
  await mockMediaRecorder(page)
  await mockTranscribeEndpoint(page)
  await page.route((url) => url.pathname === '/api/contacts/autocomplete', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  })
  await page.route((url) => url.pathname.startsWith('/api/snippets'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ snippets: [], total: 0 }) })
  })
}

async function setupReplyMocks(page: Page) {
  await setupBaseMocks(page)
  await mockMediaRecorder(page)
  await mockTranscribeEndpoint(page)
  await page.route((url) => url.pathname.match(/^\/api\/emails\/email-1$/) !== null, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockEmailDetails['email-1']) })
  })
  await page.route((url) => url.pathname.match(/\/api\/emails\/[^/]+\/read$/) !== null, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
  })
  await page.route((url) => url.pathname.match(/\/api\/emails\/[^/]+\/thread$/) !== null, (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 1, emails: [] }) })
  })
  await page.route((url) => url.pathname.startsWith('/api/pending-drafts/by-email'), (route) => {
    route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: 'No draft' }) })
  })
  await page.route((url) => url.pathname.startsWith('/api/contacts'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  })
}

async function openNewMessage(page: Page) {
  await page.locator('body').click({ position: { x: 10, y: 10 } })
  await page.keyboard.press('n')
  await page.locator('.new-message-modal').first().waitFor({ state: 'visible', timeout: 10000 })
}

async function openEmailDetail(page: Page) {
  await page.locator('[data-testid="email-item"]').first().click()
  await page.locator('.email-detail-body').first().waitFor({ state: 'visible', timeout: 10000 })
}

function replyMicButton(page: Page) {
  return page.locator('[data-testid="reply-composer"] .nmm-mic-btn, .reply-composer .nmm-mic-btn').first()
}

async function confirmMicPermissionIfVisible(page: Page) {
  const continueButton = page.getByRole('button', { name: /continuer|continue/i }).last()
  if (await continueButton.waitFor({ state: 'visible', timeout: 1500 }).then(() => true).catch(() => false)) {
    await continueButton.click()
  }
}

// ---------------------------------------------------------------------------
// Compose (NewMessageModal) — Mic button
// ---------------------------------------------------------------------------

test.describe('Whisper Mic — Compose', () => {
  test.beforeEach(async ({ page }) => {
    await setupComposeMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openNewMessage(page)
  })

  test('affiche le bouton mic dédié dans le footer', async ({ page }) => {
    const btn = page.locator('.nmm-mic-btn').first()
    await expect(btn).toBeVisible({ timeout: 5000 })
    await expect(btn).toHaveAttribute('aria-label', 'Dicter')
  })

  test('le bouton mic reste visible même avec du texte dans le body', async ({ page }) => {
    // Since mic refactor (2026-04-17), mic is always visible (independent button).
    const editor = page.locator('.draft-editor-content').first()
    await editor.click()
    await page.keyboard.type('Hello world')
    await expect(page.locator('.nmm-mic-btn').first()).toBeVisible({ timeout: 3000 })
  })

  test('click mic → enregistrement → stop → texte transcrit dans le body', async ({ page }) => {
    const btn = page.locator('.nmm-mic-btn').first()

    await btn.click()
    await confirmMicPermissionIfVisible(page)
    await expect(btn).toHaveClass(/nmm-mic-recording/, { timeout: 3000 })

    await btn.click()

    await expect(page.locator('.draft-editor-content').first()).toContainText(
      'Bonjour, ceci est un test',
      { timeout: 10000 },
    )
  })

  test('apres transcription, le bouton sort de l\'état recording', async ({ page }) => {
    const btn = page.locator('.nmm-mic-btn').first()

    await btn.click()
    await confirmMicPermissionIfVisible(page)
    await expect(btn).toHaveClass(/nmm-mic-recording/, { timeout: 3000 })
    await btn.click()

    await expect(page.locator('.draft-editor-content').first()).toContainText('Bonjour', { timeout: 10000 })
    await expect(btn).not.toHaveClass(/nmm-mic-recording/)
    await expect(btn).not.toHaveAttribute('title', 'Dicter')
  })
})

// ---------------------------------------------------------------------------
// Reply (ReplyComposer) — Mic button
// ---------------------------------------------------------------------------

test.describe('Whisper Mic — Reply', () => {
  test.beforeEach(async ({ page }) => {
    await setupReplyMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openEmailDetail(page)
    await page.keyboard.press('r')
    await expect(page.locator('[data-testid="reply-composer"], .reply-composer').first()).toBeVisible({ timeout: 10000 })
  })

  test('affiche le bouton mic dans le reply composer', async ({ page }) => {
    const btn = replyMicButton(page)
    await expect(btn).toBeVisible({ timeout: 5000 })
    await expect(btn).toHaveAttribute('aria-label', 'Dicter')
  })

  test('le bouton mic reste visible même avec du texte', async ({ page }) => {
    // Type in the DraftEditor inside reply composer
    const editor = page.locator('.reply-composer .draft-editor-content, [data-testid="reply-composer"] .draft-editor-content').first()
    await editor.click()
    await page.keyboard.type('Test reply')
    const btn = replyMicButton(page)
    await expect(btn).toBeVisible({ timeout: 3000 })
    await expect(btn).toHaveAttribute('aria-label', 'Dicter')
  })

  test('click mic → enregistrement → stop → texte transcrit dans le reply', async ({ page }) => {
    const btn = replyMicButton(page)

    // Start recording
    await btn.click()
    await confirmMicPermissionIfVisible(page)
    await expect(btn).toHaveClass(/recording/, { timeout: 3000 })

    // Stop recording
    await btn.click()

    // Body should contain the mocked transcript
    const editor = page.locator('.reply-composer .draft-editor-content, [data-testid="reply-composer"] .draft-editor-content').first()
    await expect(editor).toContainText('Bonjour, ceci est un test', { timeout: 10000 })
  })
})

// ---------------------------------------------------------------------------
// Forward — Mic button hidden (body pre-filled with forwarded content)
// ---------------------------------------------------------------------------

test.describe('Whisper Mic — Forward', () => {
  test.beforeEach(async ({ page }) => {
    await setupReplyMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
    await openEmailDetail(page)
    await page.keyboard.press('f')
    await expect(page.locator('[data-testid="reply-composer"], .reply-composer').first()).toBeVisible({ timeout: 10000 })
  })

  test('affiche le bouton mic même si le body contient le message transféré', async ({ page }) => {
    const btn = replyMicButton(page)
    await expect(btn).toBeVisible({ timeout: 5000 })
    await expect(btn).toHaveAttribute('aria-label', 'Dicter')
  })
})
