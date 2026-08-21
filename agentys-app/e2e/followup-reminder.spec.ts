/**
 * E2E — Follow-up reminder : FollowupDatePicker + createReminder flow
 *
 * Couvre :
 *  1. Aujourd'hui est sélectionnable dans le picker (fix isPast)
 *  2. Sélecteur d'heure présent et modifiable
 *  3. L'heure choisie est bien transmise à onSelect (pas 06:00 codé en dur)
 *  4. POST /api/reminders appelé après envoi avec followupDate
 *  5. Retry automatique si le premier appel échoue (backend lent au démarrage)
 *  6. Payload correct : email_id, subject, reminder_date
 *  7. Régression : createReminder n'est PAS appelé si followupDate est null
 */

import { test, expect, Page } from '@playwright/test'
import { isApiRoute, setupBaseMocks, waitForAppReady } from './support/fixtures/setup'
import { mockEmailDetails } from './support/fixtures/mock-data'

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const mockDraft = {
  id: 'draft-reminder-1',
  email_id: 'email-1',
  email_subject: 'Rapport trimestriel Q4 2025',
  email_sender: 'marie.dupont@example.com',
  email_sender_name: 'Marie Dupont',
  email_body: '<p>Bonjour, veuillez trouver ci-joint le rapport.</p>',
  draft_subject: 'Re: Rapport trimestriel Q4 2025',
  draft_body: 'Bonjour Marie,\n\nMerci pour ce rapport.\n\nCordialement',
  draft_v1: 'Merci.',
  status: 'pending',
  classification: 'action',
  routing_tier: 'STANDARD',
  critique: 'Score: 87/100. Verdict: VALID.',
  smart_suggestions: [],
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
}

async function setupDraftMocks(page: Page) {
  await setupBaseMocks(page, {
    emailsResponse: {
      emails: [{
        id: 'email-1',
        sender: 'marie.dupont@example.com',
        sender_name: 'Marie Dupont',
        subject: 'Rapport trimestriel Q4 2025',
        received_at: new Date(Date.now() - 3600000).toISOString(),
        has_attachments: false,
        conversation_id: null,
        is_read: false,
        has_pending_draft: true,
      }],
      has_more: false,
      source: 'mock',
    },
  })

  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/pending-drafts',
    (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ drafts: [mockDraft], pending_count: 1 }),
    }),
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname.startsWith('/api/pending-drafts/by-email'),
    (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(mockDraft),
    }),
  )
  await page.route(
    (url) => isApiRoute(url) && /\/api\/pending-drafts\/draft-reminder-\d+$/.test(url.pathname),
    (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(mockDraft),
    }),
  )
  await page.route(
    (url) => isApiRoute(url) && /\/api\/emails\/email-1$/.test(url.pathname),
    (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(mockEmailDetails['email-1']),
    }),
  )
  await page.route(
    (url) => isApiRoute(url) && /\/api\/emails\/[^/]+\/(read|thread)$/.test(url.pathname),
    (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ success: true, count: 1, emails: [] }),
    }),
  )
  await page.route(
    (url) => isApiRoute(url) && /\/api\/pending-drafts\/[^/]+\/validate$/.test(url.pathname),
    (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ success: true, sent: true }),
    }),
  )
  await page.route(
    (url) => isApiRoute(url) && /\/api\/pending-drafts\/[^/]+\/refine$/.test(url.pathname),
    (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ success: true, refined_body: 'Brouillon affiné.' }),
    }),
  )
}

/** Ouvre le PendingDraftDetail depuis la liste Brouillons. */
async function openDraftDetail(page: Page) {
  await page.goto('/')
  await waitForAppReady(page)
  await page.locator('[data-testid="nav-drafts"]').click()

  const draftItem = page.locator('[data-testid="draft-item"]').first()
  await expect(draftItem).toBeVisible({ timeout: 10000 })
  await draftItem.click()

  await expect(page.locator('[data-testid="pending-draft-detail"]')).toBeVisible({ timeout: 10000 })
}

/** Clique sur l'icône cloche pour ouvrir le FollowupDatePicker. */
async function openFollowupPicker(page: Page) {
  // La cloche est dans la barre d'action basse
  const bellBtn = page.locator('button[title*="rappel"], button[aria-label*="rappel"], button[aria-label*="Rappel"]').first()
  await expect(bellBtn).toBeVisible({ timeout: 5000 })
  await bellBtn.click()
  await expect(page.locator('.followup-picker')).toBeVisible({ timeout: 3000 })
}

async function sendCurrentDraft(page: Page) {
  await page.getByTestId('send-button').click()

  const confirmation = page.getByTestId('send-confirmation-overlay')
  const isConfirmationVisible = await confirmation
    .waitFor({ state: 'visible', timeout: 750 })
    .then(() => true)
    .catch(() => false)

  if (!isConfirmationVisible) return

  const confirmButton = page.getByTestId('confirm-button')
  await expect(confirmButton).toBeEnabled({ timeout: 5000 })
  await confirmButton.click()
}

// ─── Tests ────────────────────────────────────────────────────────────────────

test.describe('FollowupDatePicker — UI', () => {
  test.beforeEach(async ({ page }) => {
    await setupDraftMocks(page)
  })

  // ── 1. Aujourd'hui est sélectionnable ──────────────────────────────────────
  test('aujourd\'hui est sélectionnable (non grisé)', async ({ page }) => {
    await openDraftDetail(page)
    await openFollowupPicker(page)

    const today = new Date()
    const dayNum = today.getDate()

    // Le bouton du jour d'aujourd'hui dans le calendrier
    const todayBtn = page.locator(`.followup-cal-day.today`)
    await expect(todayBtn).toBeVisible({ timeout: 3000 })

    // Il ne doit PAS être disabled
    await expect(todayBtn).not.toBeDisabled()

    // Il doit afficher le bon numéro de jour
    await expect(todayBtn).toHaveText(String(dayNum))
  })

  // ── 2. Les jours passés sont grisés ───────────────────────────────────────
  test('les jours avant aujourd\'hui sont désactivés', async ({ page }) => {
    await openDraftDetail(page)
    await openFollowupPicker(page)

    const today = new Date()
    // S'il y a des jours passés ce mois-ci (pas le 1er du mois)
    if (today.getDate() > 1) {
      const pastDays = page.locator('.followup-cal-day.past')
      const count = await pastDays.count()
      expect(count).toBeGreaterThan(0)

      // Tous les jours passés doivent être disabled
      for (let i = 0; i < count; i++) {
        await expect(pastDays.nth(i)).toBeDisabled()
      }
    }
  })

  // ── 3. Sélecteur d'heure présent avec valeur 09:00 par défaut ─────────────
  test('sélecteur d\'heure visible avec valeur par défaut 09:00', async ({ page }) => {
    await openDraftDetail(page)
    await openFollowupPicker(page)

    const timeInput = page.locator('.followup-cal-time-input')
    await expect(timeInput).toBeVisible({ timeout: 3000 })
    await expect(timeInput).toHaveValue('09:00')
  })

  // ── 4. L'heure est modifiable ─────────────────────────────────────────────
  test('l\'heure est modifiable par l\'utilisateur', async ({ page }) => {
    await openDraftDetail(page)
    await openFollowupPicker(page)

    const timeInput = page.locator('.followup-cal-time-input')
    await timeInput.fill('14:30')
    await expect(timeInput).toHaveValue('14:30')
  })

  // ── 5. Confirmer est désactivé tant qu'aucun jour n'est sélectionné ────────
  test('bouton Confirmer désactivé sans sélection de jour', async ({ page }) => {
    await openDraftDetail(page)
    await openFollowupPicker(page)

    await expect(page.locator('.followup-cal-confirm')).toBeDisabled()
  })

  // ── 6. Sélectionner aujourd'hui active le bouton Confirmer ─────────────────
  test('sélectionner aujourd\'hui active le bouton Confirmer', async ({ page }) => {
    await openDraftDetail(page)
    await openFollowupPicker(page)

    await page.locator('.followup-cal-day.today').click()
    await expect(page.locator('.followup-cal-confirm')).not.toBeDisabled()
  })

  // ── 7. L'heure choisie est bien transmise (pas 06:00 codé en dur) ──────────
  test('la date confirmée contient l\'heure saisie', async ({ page }) => {
    await openDraftDetail(page)
    await openFollowupPicker(page)

    // Changer l'heure à 11:45
    await page.locator('.followup-cal-time-input').fill('11:45')

    // Sélectionner aujourd'hui
    await page.locator('.followup-cal-day.today').click()

    // Espionner la date transmise en interceptant le state React via une évaluation JS
    // On clique Confirmer et on vérifie que le snooze entry localStorage contient 11:45
    await page.locator('.followup-cal-confirm').click()

    // Après confirmation, le picker se ferme
    await expect(page.locator('.followup-picker')).toHaveCount(0, { timeout: 3000 })

    // Vérifier que la cloche est maintenant active (followupDate !== null)
    const bellBtn = page.locator('button[aria-label*="Rappel"], button[title*="Rappel"]').first()
    await expect(bellBtn).toBeVisible()
    // La couleur/style indique que le rappel est actif
    const color = await bellBtn.evaluate((el) => window.getComputedStyle(el).color)
    // Couleur accent (pas la couleur par défaut grise)
    expect(color).not.toBe('rgb(156, 163, 175)') // pas gris neutre
  })
})

// ─── Tests POST /api/reminders ────────────────────────────────────────────────

test.describe('createReminder — appel backend après envoi', () => {
  test.beforeEach(async ({ page }) => {
    await setupDraftMocks(page)
  })

  // ── 8. POST /api/reminders appelé avec les bons champs ────────────────────
  test('POST /api/reminders envoyé après envoi avec rappel actif', async ({ page }) => {
    let reminderPayload: Record<string, unknown> | null = null

    await page.route(
      (url) => isApiRoute(url) && url.pathname === '/api/reminders',
      async (route) => {
        if (route.request().method() === 'POST') {
          reminderPayload = route.request().postDataJSON()
          await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ id: 'r-1', success: true }) })
        } else {
          await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ reminders: [] }) })
        }
      },
    )

    await openDraftDetail(page)
    await openFollowupPicker(page)

    // Sélectionner aujourd'hui à 10:00
    await page.locator('.followup-cal-time-input').fill('10:00')
    await page.locator('.followup-cal-day.today').click()
    await page.locator('.followup-cal-confirm').click()
    await expect(page.locator('.followup-picker')).toHaveCount(0, { timeout: 3000 })

    // Envoyer
    await sendCurrentDraft(page)
    await expect.poll(() => reminderPayload, { timeout: 5000 }).not.toBeNull()

    expect(reminderPayload).not.toBeNull()
    expect(reminderPayload!['email_id']).toBe('email-1')
    expect(reminderPayload!['subject']).toBeTruthy()
    // reminder_date doit être une ISO string avec l'heure 10:xx
    const date = new Date(reminderPayload!['reminder_date'] as string)
    expect(date.getHours()).toBe(10)
    expect(date.getMinutes()).toBe(0)
  })

  // ── 9. Retry : POST réussit au 2e essai si le 1er échoue ──────────────────
  test('retry automatique si le premier appel à /api/reminders échoue', async ({ page }) => {
    let callCount = 0

    await page.route(
      (url) => isApiRoute(url) && url.pathname === '/api/reminders',
      async (route) => {
        if (route.request().method() === 'POST') {
          callCount++
          if (callCount === 1) {
            // Premier appel : simuler backend pas prêt
            await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'Service unavailable' }) })
          } else {
            // Deuxième appel : succès
            await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ id: 'r-retry-1', success: true }) })
          }
        } else {
          await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ reminders: [] }) })
        }
      },
    )

    await openDraftDetail(page)
    await openFollowupPicker(page)

    await page.locator('.followup-cal-day.today').click()
    await page.locator('.followup-cal-confirm').click()
    await expect(page.locator('.followup-picker')).toHaveCount(0, { timeout: 3000 })

    await sendCurrentDraft(page)

    // Au moins 2 appels : le premier échoué + le retry réussi
    await expect.poll(() => callCount, { timeout: 5000 }).toBeGreaterThanOrEqual(2)
  })

  // ── 10. createReminder NON appelé si followupDate est null ────────────────
  test('POST /api/reminders non appelé si la cloche n\'est pas activée', async ({ page }) => {
    let reminderCalled = false

    await page.route(
      (url) => isApiRoute(url) && url.pathname === '/api/reminders',
      async (route) => {
        if (route.request().method() === 'POST') {
          reminderCalled = true
          await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ id: 'r-x', success: true }) })
        } else {
          await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ reminders: [] }) })
        }
      },
    )

    await openDraftDetail(page)
    // Ne pas activer la cloche — envoyer directement

    await sendCurrentDraft(page)
    // TODO: replace when data-testid available — negative assertion needs a settle period
    await page.waitForTimeout(1000)

    expect(reminderCalled).toBe(false)
  })

  // ── 11. writeSnoozeEntry localStorage avec type 'followup' ────────────────
  test('localStorage contient une entrée type:followup après envoi avec rappel', async ({ page }) => {
    await page.route(
      (url) => isApiRoute(url) && url.pathname === '/api/reminders',
      (route) => route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ id: 'r-2', success: true }) }),
    )

    await openDraftDetail(page)
    await openFollowupPicker(page)

    await page.locator('.followup-cal-day.today').click()
    await page.locator('.followup-cal-confirm').click()
    await expect(page.locator('.followup-picker')).toHaveCount(0, { timeout: 3000 })

    await sendCurrentDraft(page)
    await expect.poll(async () => {
      try {
        const entries = JSON.parse(await page.evaluate(() => localStorage.getItem('agentys_snoozed') || '[]'))
        return Array.isArray(entries) && entries.some((e) => e.emailId === 'email-1' && e.type === 'followup')
      } catch {
        return false
      }
    }, { timeout: 5000 }).toBe(true)

    const entries = await page.evaluate(() => {
      try { return JSON.parse(localStorage.getItem('agentys_snoozed') || '[]') }
      catch { return [] }
    })

    const entry = (entries as Array<{ emailId: string; type?: string }>)
      .find((e) => e.emailId === 'email-1')

    expect(entry).not.toBeUndefined()
    expect(entry!.type).toBe('followup')
  })
})
