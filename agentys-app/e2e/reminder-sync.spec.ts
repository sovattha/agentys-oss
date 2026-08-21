/**
 * E2E — syncRemindersFromBackend
 *
 * Vérifie que quand localStorage ne contient PAS d'entrée snooze pour un email
 * (ex: après redémarrage de l'app), le hook useSnooze récupère les rappels
 * depuis GET /api/reminders et reconstruit l'entrée localStorage.
 * L'email doit ensuite apparaître avec le badge 🔔 et être épinglé.
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

// Email dont le rappel est passé (dans le passé)
const WOKEN_EMAIL_ID = 'email-sync-1'
const WOKEN_SUBJECT = 'Demande de devis urgente'
const REMINDER_DATE_PAST = new Date(Date.now() - 3_600_000).toISOString() // il y a 1h

const mockEmails = [
  {
    id: WOKEN_EMAIL_ID,
    sender: 'client@example.com',
    sender_name: 'Client Test',
    subject: WOKEN_SUBJECT,
    received_at: new Date(Date.now() - 7_200_000).toISOString(),
    has_attachments: false,
    conversation_id: null,
    is_read: true,
    has_pending_draft: false,
  },
]

async function setupSyncMocks(page: Page, includeReminders: boolean) {
  await setupBaseMocks(page, {
    emailsResponse: { emails: mockEmails, has_more: false, source: 'mock' },
  })

  // Mock GET /api/reminders
  await page.route(
    (url) => url.origin === API && url.pathname === '/api/reminders',
    (route) => {
      if (route.request().method() === 'GET') {
        const reminders = includeReminders
          ? [{
              id: 'r-sync-1',
              email_id: WOKEN_EMAIL_ID,
              subject: WOKEN_SUBJECT,
              reminder_date: REMINDER_DATE_PAST,
              notified: true,
            }]
          : []
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ reminders }),
        })
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ reminders: [] }) })
    },
  )

  // Mock POST /api/reminders
  await page.route(
    (url) => url.origin === API && url.pathname === '/api/reminders' && false, // handled above
    (route) => route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ id: 'r-x', success: true }) }),
  )
}

// ─── Tests ────────────────────────────────────────────────────────────────────

test.describe('syncRemindersFromBackend — synchro localStorage au démarrage', () => {

  // ── 1. Sans localStorage, le backend injecte l'entrée ─────────────────────
  test('injecte l\'entrée localStorage depuis le backend si absente', async ({ page }) => {
    await setupSyncMocks(page, true)

    // S'assurer que localStorage est vide au départ
    await page.addInitScript(() => {
      localStorage.removeItem('agentys_snoozed')
    })

    await page.goto('/')
    await waitForAppReady(page)

    // Attendre que la synchro s'exécute (useEffect au montage)
    await page.waitForFunction((key) => {
      try {
        const entries = JSON.parse(localStorage.getItem(key) || '[]')
        return entries.some((e: { emailId: string }) => e.emailId === 'email-sync-1')
      } catch { return false }
    }, 'agentys_snoozed', { timeout: 5000 })

    // Vérifier que l'entrée a été écrite dans localStorage
    const entries = await page.evaluate(() => {
      try { return JSON.parse(localStorage.getItem('agentys_snoozed') || '[]') }
      catch { return [] }
    })

    const entry = (entries as Array<{ emailId: string; type?: string; date: string }>)
      .find(e => e.emailId === WOKEN_EMAIL_ID)

    expect(entry).not.toBeUndefined()
    expect(entry!.type).toBe('followup')
    // La date doit correspondre au rappel backend
    expect(entry!.date).toBe(REMINDER_DATE_PAST)
  })

  // ── 2. L'email apparaît avec le badge 🔔 après la synchro ─────────────────
  test('l\'email réveillé affiche le badge 🔔 après synchro backend', async ({ page }) => {
    await setupSyncMocks(page, true)

    await page.addInitScript(() => {
      localStorage.removeItem('agentys_snoozed')
    })

    await page.goto('/')
    await waitForAppReady(page)

    // Attendre que localStorage soit peuplé par la synchro (jusqu'à 5s)
    await page.waitForFunction((key) => {
      try {
        const entries = JSON.parse(localStorage.getItem(key) || '[]')
        return entries.some((e: { emailId: string }) => e.emailId === 'email-sync-1')
      } catch { return false }
    }, 'agentys_snoozed', { timeout: 5000 })

    // Le badge followup doit être visible après le re-render
    const badge = page.locator('[data-testid="badge-followup"]').first()
    await expect(badge).toBeVisible({ timeout: 5000 })
  })

  // ── 3. L'email est épinglé automatiquement après synchro ──────────────────
  test('l\'email réveillé est épinglé en tête de liste après synchro', async ({ page }) => {
    await setupSyncMocks(page, true)

    await page.addInitScript(() => {
      localStorage.removeItem('agentys_snoozed')
      localStorage.removeItem('agentys_pinned')
    })

    await page.goto('/')
    await waitForAppReady(page)

    // Attendre que pinnedIds soit peuplé par la synchro
    await page.waitForFunction((emailId) => {
      try {
        const pinned = JSON.parse(localStorage.getItem('agentys_pinned') || '[]')
        return pinned.includes(emailId)
      } catch { return false }
    }, WOKEN_EMAIL_ID, { timeout: 5000 })

    // Vérifier que l'email est dans pinnedIds (localStorage)
    const pinned = await page.evaluate(() => {
      try { return JSON.parse(localStorage.getItem('agentys_pinned') || '[]') }
      catch { return [] }
    })

    expect((pinned as string[]).includes(WOKEN_EMAIL_ID)).toBe(true)
  })

  // ── 4. Sans rappel backend, localStorage reste vide ───────────────────────
  test('aucune entrée injectée si le backend ne retourne aucun rappel', async ({ page }) => {
    await setupSyncMocks(page, false) // pas de reminders

    await page.addInitScript(() => {
      localStorage.removeItem('agentys_snoozed')
    })

    await page.goto('/')
    await waitForAppReady(page)

    // TODO: replace when data-testid available — negative assertion needs a settle period
    await page.waitForTimeout(1500)

    const entries = await page.evaluate(() => {
      try { return JSON.parse(localStorage.getItem('agentys_snoozed') || '[]') }
      catch { return [] }
    })

    expect((entries as unknown[]).length).toBe(0)
  })

  // ── 5. Pas de doublon si l'entrée existe déjà dans localStorage ───────────
  test('ne crée pas de doublon si l\'entrée existe déjà en localStorage', async ({ page }) => {
    await setupSyncMocks(page, true)

    // Pré-remplir localStorage avec l'entrée
    await page.addInitScript((args: { emailId: string; date: string; subject: string }) => {
      localStorage.setItem('agentys_snoozed', JSON.stringify([{
        emailId: args.emailId,
        date: args.date,
        subject: args.subject,
        type: 'followup',
      }]))
    }, { emailId: WOKEN_EMAIL_ID, date: REMINDER_DATE_PAST, subject: WOKEN_SUBJECT })

    await page.goto('/')
    await waitForAppReady(page)
    // Attendre que la synchro GET /api/reminders soit terminée
    await page.waitForResponse(
      (resp) => resp.url().includes('/api/reminders') && resp.request().method() === 'GET',
      { timeout: 5000 }
    )

    const entries = await page.evaluate(() => {
      try { return JSON.parse(localStorage.getItem('agentys_snoozed') || '[]') }
      catch { return [] }
    })

    // Exactement 1 entrée, pas de doublon
    const matches = (entries as Array<{ emailId: string }>).filter(e => e.emailId === WOKEN_EMAIL_ID)
    expect(matches.length).toBe(1)
  })
})
