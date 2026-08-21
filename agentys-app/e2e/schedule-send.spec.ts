/**
 * Schedule send E2E tests.
 *
 * Couvre :
 * - bouton split visible dans NewMessageModal (compose) et ReplyComposer (reply)
 * - selection d'un preset declenche un POST /api/emails/schedule
 * - apparition dans la vue unifiee "Plus tard" (sidebar nav-snoozed avec filtre Envois)
 * - annulation depuis la liste declenche un DELETE
 */

import { test, expect, Page, Route } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

interface ScheduledRow {
  id: string
  send_at: string
  status: 'pending' | 'sent' | 'failed' | 'cancelled'
  to: string[]
  cc: string[]
  bcc: string[]
  subject: string
  body: string
  is_html: boolean
  reply_to_id: string | null
  thread_id: string | null
  attachments_count: number
  created_at: string | null
  updated_at: string | null
  sent_at: string | null
  sent_message_id: string | null
  error: string | null
}

async function setupScheduleMocks(page: Page) {
  await setupBaseMocks(page)
  const state: { rows: ScheduledRow[]; lastPostBody: Record<string, unknown> | null } = {
    rows: [],
    lastPostBody: null,
  }
  ;(page as Page & { __scheduleState?: typeof state }).__scheduleState = state

  // POST /api/emails/schedule
  await page.route(
    (url) => /\/api\/emails\/schedule$/.test(url.pathname) && url.origin.includes('5050'),
    async (route: Route) => {
      const req = route.request()
      const body = req.postDataJSON() as Record<string, unknown>
      state.lastPostBody = body
      const id = `sched-${state.rows.length + 1}`
      const newRow: ScheduledRow = {
        id,
        send_at: String(body.send_at),
        status: 'pending',
        to: typeof body.to === 'string' ? [body.to as string] : (body.to as string[]) || [],
        cc: [],
        bcc: [],
        subject: String(body.subject || ''),
        body: String(body.body || ''),
        is_html: Boolean(body.is_html),
        reply_to_id: (body.reply_to_id as string) || null,
        thread_id: (body.thread_id as string) || null,
        attachments_count: 0,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        sent_at: null,
        sent_message_id: null,
        error: null,
      }
      state.rows.push(newRow)
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          scheduled_id: id,
          status: 'pending',
          send_at: newRow.send_at,
        }),
      })
    },
  )

  // GET /api/emails/scheduled
  await page.route(
    (url) =>
      /\/api\/emails\/scheduled(\?|$)/.test(url.pathname + url.search) &&
      url.origin.includes('5050'),
    async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: state.rows.filter((r) => r.status === 'pending'), count: state.rows.filter((r) => r.status === 'pending').length }),
      })
    },
  )

  // DELETE /api/emails/scheduled/<id>
  await page.route(
    (url) =>
      /\/api\/emails\/scheduled\/[^/]+$/.test(url.pathname) && url.origin.includes('5050'),
    async (route: Route) => {
      const method = route.request().method()
      const m = route.request().url().match(/scheduled\/([^/?]+)/)
      const id = m ? m[1] : ''
      if (method === 'DELETE') {
        const row = state.rows.find((r) => r.id === id)
        if (row) row.status = 'cancelled'
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, scheduled_id: id }),
        })
        return
      }
      if (method === 'PATCH') {
        const body = route.request().postDataJSON() as Record<string, unknown>
        const row = state.rows.find((r) => r.id === id)
        if (row && body.send_at) row.send_at = String(body.send_at)
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, scheduled: row }),
        })
        return
      }
      await route.continue()
    },
  )

  // Email detail mocks reduits pour ReplyComposer
  await page.route(
    (url) => /\/api\/contacts\/autocomplete/.test(url.pathname) && url.origin.includes('5050'),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      }),
  )
  await page.route(
    (url) => /\/api\/snippets/.test(url.pathname) && url.origin.includes('5050'),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ snippets: [], total: 0 }),
      }),
  )
}

async function getScheduleState(page: Page) {
  return (page as Page & { __scheduleState?: { rows: ScheduledRow[]; lastPostBody: Record<string, unknown> | null } }).__scheduleState
}

async function openNewMessage(page: Page) {
  await page.locator('body').click({ position: { x: 10, y: 10 } })
  await page.keyboard.press('n')
  await page.locator('.new-message-modal').first().waitFor({ state: 'visible', timeout: 10000 })
}

test.describe('Schedule send — bouton split', () => {
  test.beforeEach(async ({ page }) => {
    await setupScheduleMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('le chevron de programmation est visible dans NewMessageModal', async ({ page }) => {
    await openNewMessage(page)
    const chevron = page.locator('[data-testid="send-split-chevron"]').first()
    await expect(chevron).toBeVisible({ timeout: 5000 })
  })

  test('cliquer le chevron ouvre le SchedulePicker avec 3 presets', async ({ page }) => {
    await openNewMessage(page)
    await page.locator('[data-testid="send-split-chevron"]').first().click()
    await expect(page.locator('[data-testid="schedule-picker"]')).toBeVisible({ timeout: 3000 })
    await expect(page.locator('[data-testid="schedule-preset-tomorrow_morning"]')).toBeVisible()
    await expect(page.locator('[data-testid="schedule-preset-tomorrow_afternoon"]')).toBeVisible()
    await expect(page.locator('[data-testid="schedule-preset-monday_morning"]')).toBeVisible()
    await expect(page.locator('[data-testid="schedule-custom-btn"]')).toBeVisible()
  })

  test("selectionner 'Demain matin' programme l'email et ferme le modal", async ({ page }) => {
    await openNewMessage(page)
    // Remplir le destinataire
    const toInput = page.locator('input[type="email"], .nm-to-input input, [data-testid="compose-to-input"]').first()
    await toInput.fill('alice@example.com')
    await toInput.press('Enter').catch(() => {})

    // Remplir le corps via TipTap (input contenteditable)
    const editor = page.locator('.ProseMirror').first()
    await editor.click()
    await editor.type('Bonjour Alice, ceci est un test programme.')

    // Click chevron + preset
    await page.locator('[data-testid="send-split-chevron"]').first().click()
    await page.locator('[data-testid="schedule-preset-tomorrow_morning"]').click()

    // Le modal doit fermer apres ~2s d'animation
    await expect(page.locator('.new-message-modal')).toBeHidden({ timeout: 6000 })

    // Verifier le payload envoye
    const state = await getScheduleState(page)
    expect(state?.rows.length).toBe(1)
    expect(state?.rows[0].subject).toBe('')  // pas rempli dans ce test
    expect(state?.lastPostBody?.send_at).toBeTruthy()
  })
})

test.describe('Schedule send — vue Plus tard', () => {
  test.beforeEach(async ({ page }) => {
    await setupScheduleMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('le tab Plus tard apparait dans la sidebar', async ({ page }) => {
    const navLater = page.locator('[data-testid="nav-snoozed"]')
    await expect(navLater).toBeVisible({ timeout: 5000 })
  })

  test('un email programme apparait dans la liste unifiee', async ({ page }) => {
    // Programmer un email d'abord
    await openNewMessage(page)
    const toInput = page.locator('input[type="email"], .nm-to-input input, [data-testid="compose-to-input"]').first()
    await toInput.fill('bob@example.com')
    await toInput.press('Enter').catch(() => {})
    const editor = page.locator('.ProseMirror').first()
    await editor.click()
    await editor.type('Test programme.')
    await page.locator('[data-testid="send-split-chevron"]').first().click()
    await page.locator('[data-testid="schedule-preset-tomorrow_afternoon"]').click()
    await expect(page.locator('.new-message-modal')).toBeHidden({ timeout: 6000 })

    // Naviguer vers Plus tard puis filtrer sur Envois
    await page.locator('[data-testid="nav-snoozed"]').click()
    await expect(page.locator('.snoozed-view')).toBeVisible({ timeout: 5000 })
    await page.locator('[data-testid="later-filter-scheduled"]').click()
    await expect(page.locator('.sv-row--scheduled').first()).toBeVisible({ timeout: 5000 })
    await expect(page.locator('.sv-row--scheduled .email-sender').first()).toContainText('bob@example.com')
  })

  test("annulation d'un envoi programme retire l'item", async ({ page }) => {
    // Pre-seed un envoi via l'API mockee
    const state = await getScheduleState(page)
    if (state) {
      state.rows.push({
        id: 'sched-pre-1',
        send_at: new Date(Date.now() + 3600_000).toISOString(),
        status: 'pending',
        to: ['carol@example.com'],
        cc: [],
        bcc: [],
        subject: 'Pre-seed',
        body: 'Hello carol',
        is_html: false,
        reply_to_id: null,
        thread_id: null,
        attachments_count: 0,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        sent_at: null,
        sent_message_id: null,
        error: null,
      })
    }

    await page.locator('[data-testid="nav-snoozed"]').click()
    await expect(page.locator('.sv-row--scheduled').first()).toBeVisible({ timeout: 5000 })

    // Hover the row to reveal action buttons, then click the inline cancel
    await page.locator('[data-testid="later-row-scheduled-sched-pre-1"]').hover()
    await page.locator('[data-testid="later-cancel-sched-pre-1"]').click()
    // L'item disparait apres l'optimistic update
    await expect(page.locator('[data-testid="later-row-scheduled-sched-pre-1"]')).toBeHidden({ timeout: 5000 })
  })
})
