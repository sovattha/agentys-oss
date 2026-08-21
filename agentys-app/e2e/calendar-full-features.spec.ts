/**
 * Calendar Full Features — Tests complets pour Gmail et Outlook
 *
 * Couvre:
 * - Création d'événement avec tous les champs (titre, durée, all-day, lieu, notes, labels, conference, reminder, récurrence)
 * - Google Meet (Gmail) vs Teams (Outlook)
 * - "Au plus tôt" (ASAP scheduling via SmartSchedulerPanel)
 * - Labels + colorId dans le body POST
 * - Édition d'événement via EventModal → QuickEventPopover
 * - Lien Meet/Teams dans EventModal
 * - Régressions critiques (filteredEvents, Hotmail primary, double-mount React StrictMode)
 */

import { test, expect, Page, Route } from '@playwright/test'
import { setupBaseMocks, waitForAppReady, isApiRoute } from './support/fixtures/setup'

// ──────────────────────────────────────────────────────────────
// Mock data
// ──────────────────────────────────────────────────────────────

const PROJECT_LABELS = [
  { id: 1, name: 'Mon Projet', color: '#7986cb', is_project: true },
  { id: 2, name: 'Urgent', color: '#d50000', is_project: true },
]

const now = new Date()
const todayStart = new Date(now)
todayStart.setHours(10, 0, 0, 0)

function makeEvent(
  id: string,
  title: string,
  opts: {
    color?: string
    meetLink?: string
    providerSource?: string
    calendarId?: string
    attendees?: string[]
  } = {}
) {
  const start = new Date(todayStart)
  const end = new Date(start.getTime() + 3600000)
  return {
    id,
    title,
    start: start.toISOString(),
    end: end.toISOString(),
    calendar_id: opts.calendarId ?? 'cal-1',
    calendarId: opts.calendarId ?? 'cal-1',
    color: opts.color ?? '#6b7280',
    isAllDay: false,
    status: 'confirmed',
    providerSource: opts.providerSource ?? 'google_calendar',
    isRecurring: false,
    attendees: opts.attendees ?? [],
    meet_link: opts.meetLink ?? null,
    meetLink: opts.meetLink ?? null,
    event_type: 'event',
    is_overdue: false,
  }
}

// ──────────────────────────────────────────────────────────────
// Setup helpers
// ──────────────────────────────────────────────────────────────

interface MockOpts {
  provider?: 'gmail' | 'outlook'
  initialEvents?: ReturnType<typeof makeEvent>[]
  freebusySlots?: { start: string; end: string }[]
}

async function setupFullCalendarMocks(page: Page, opts: MockOpts = {}) {
  const { provider = 'gmail', initialEvents = [], freebusySlots = [] } = opts
  const providerSource = provider === 'gmail' ? 'google_calendar' : 'outlook'

  await setupBaseMocks(page)

  let events = [...initialEvents]
  let nextId = 100

  // Calendar status
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/status',
    (route) =>
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ connected: true, provider, email: 'test@example.com' }),
      })
  )

  // Calendar events — stateful GET/POST
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/events' &&
      !/\/api\/calendar\/events\/[^/]+$/.test(url.pathname),
    (route: Route) => {
      const method = route.request().method()
      if (method === 'POST') {
        const body = JSON.parse(route.request().postData() || '{}')
        const newId = `evt-new-${nextId++}`
        events.push(makeEvent(newId, body.title || 'Sans titre'))
        route.fulfill({
          status: 201, contentType: 'application/json',
          body: JSON.stringify({ success: true, event_id: newId }),
        })
      } else {
        route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({ events, count: events.length }),
        })
      }
    }
  )

  // Single event — PATCH / DELETE
  await page.route(
    (url) => isApiRoute(url) && /\/api\/calendar\/events\/[^/]+$/.test(url.pathname),
    (route: Route) => {
      const method = route.request().method()
      const eventId = route.request().url().match(/\/api\/calendar\/events\/([^/?]+)/)?.[1]
      if (method === 'DELETE') {
        events = events.filter((e) => e.id !== eventId)
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
      } else if (method === 'PATCH') {
        const body = JSON.parse(route.request().postData() || '{}')
        events = events.map((e) => e.id === eventId ? { ...e, title: body.title ?? e.title } : e)
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
      } else {
        const event = events.find((e) => e.id === eventId)
        route.fulfill({ status: event ? 200 : 404, contentType: 'application/json', body: JSON.stringify(event ? { event } : { error: 'Not found' }) })
      }
    }
  )

  // Calendars — providerSource controls calendarProvider state in CalendarView
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/calendars',
    (route) =>
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          calendars: [{
            id: 'cal-1',
            name: provider === 'gmail' ? 'test@example.com' : 'Mon calendrier',
            primary: true,
            isPrimary: true,
            providerSource,
            color: provider === 'gmail' ? '#4285f4' : '#0078d4',
          }],
        }),
      })
  )

  // Labels — project labels so the label picker appears in QuickEventPopover
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/labels',
    (route) =>
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ labels: PROJECT_LABELS, counts: {} }),
      })
  )

  // Freebusy
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/freebusy',
    (route) =>
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ slots: freebusySlots, attendees: [], duration_minutes: 60 }),
      })
  )

  // Followups / today / upcoming
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/followups',
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ followups: [] }) })
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/today',
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ events: [], count: 0 }) })
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/upcoming',
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ events, count: events.length }) })
  )

  // Holidays / region / stats
  for (const p of ['/api/calendar/holidays', '/api/calendar/public-holidays', '/api/calendar/detect-region', '/api/stats/feature']) {
    await page.route(
      (url) => isApiRoute(url) && url.pathname === p,
      (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) })
    )
  }
}

async function navigateToCalendar(page: Page) {
  const calBtn = page.locator('[data-testid="nav-calendar"]').first()
  await expect(calBtn).toBeVisible({ timeout: 5000 })
  await calBtn.click()
  await page.locator('.calendar-view, .calendar-week-body').first().waitFor({ state: 'visible', timeout: 10000 })
}

async function openEventPopover(page: Page) {
  await page.keyboard.press('c')
  const popover = page.locator('.qe-popover')
  const visibleAfterC = await popover.waitFor({ state: 'visible', timeout: 3000 }).then(() => true, () => false)
  if (!visibleAfterC) await page.keyboard.press('b')
  await expect(popover).toBeVisible({ timeout: 5000 })
  return popover
}

/** Add an attendee email via ContactAutocomplete — type + Enter */
async function addAttendee(page: Page, popover: ReturnType<typeof page.locator>, email: string) {
  const input = popover.locator('.qe-contact-autocomplete input').first()
  await input.click()
  await input.type(email, { delay: 10 })
  await input.press('Enter')
  await page.waitForTimeout(300) // React state update
}

// ══════════════════════════════════════════════════════════════
// A. Gmail — Toggle conférence Google Meet
// ══════════════════════════════════════════════════════════════

test.describe('Gmail — Toggle Google Meet', () => {
  test.beforeEach(async ({ page }) => {
    await setupFullCalendarMocks(page, { provider: 'gmail' })
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToCalendar(page)
  })

  test('affiche "Google Meet" dans le toggle vidéo', async ({ page }) => {
    const popover = await openEventPopover(page)
    await expect(popover.locator('.qe-toggle-btn').filter({ hasText: 'Google Meet' })).toBeVisible({ timeout: 5000 })
  })

  test('active Google Meet et affiche la coche de confirmation', async ({ page }) => {
    const popover = await openEventPopover(page)
    const toggleBtn = popover.locator('.qe-toggle-btn').filter({ hasText: 'Google Meet' })
    await toggleBtn.click()
    // Le badge `.qe-conference-badge` n'existe plus — l'état actif est
    // signalé par la classe .active + la coche .qe-toggle-check.
    await expect(toggleBtn).toHaveClass(/active/)
    await expect(toggleBtn.locator('.qe-toggle-check')).toBeVisible({ timeout: 3000 })
  })

  test('désactive Google Meet en recliquant (toggle)', async ({ page }) => {
    const popover = await openEventPopover(page)
    const toggleBtn = popover.locator('.qe-toggle-btn').filter({ hasText: 'Google Meet' })
    await toggleBtn.click()
    await expect(toggleBtn).toHaveClass(/active/)
    await toggleBtn.click()
    await expect(toggleBtn).not.toHaveClass(/active/)
    await expect(toggleBtn.locator('.qe-toggle-check')).not.toBeVisible()
  })

  test('envoie conference:true dans le body POST (Gmail)', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null
    await page.route(
      (url) => isApiRoute(url) && url.pathname === '/api/calendar/events',
      async (route: Route) => {
        if (route.request().method() === 'POST') {
          capturedBody = JSON.parse(route.request().postData() || '{}')
          await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ success: true, event_id: 'evt-meet', meet_link: 'https://meet.google.com/abc-def-ghi' }) })
        } else { await route.fallback() }
      }
    )

    const popover = await openEventPopover(page)
    await popover.locator('.qe-title-input').fill('Réunion Google Meet')
    await popover.locator('.qe-toggle-btn').filter({ hasText: 'Google Meet' }).click()
    await popover.locator('.qe-save-btn').click()
    await popover.waitFor({ state: 'hidden', timeout: 5000 })

    expect(capturedBody).not.toBeNull()
    expect(capturedBody!['conference']).toBe(true)
  })
})

// ══════════════════════════════════════════════════════════════
// B. Gmail — Champs du formulaire
// ══════════════════════════════════════════════════════════════

test.describe('Gmail — Champs du formulaire', () => {
  test.beforeEach(async ({ page }) => {
    await setupFullCalendarMocks(page, { provider: 'gmail' })
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToCalendar(page)
  })

  // NOTE (2026-06-09) : le slider piecewise a été remplacé par des chips de
  // presets (30m / 1h / 1h30 / 2h) sous la ligne date/heure, et l'heure de
  // fin est désormais éditable (2 inputs `.qe-time-digit` supplémentaires).
  // Toute autre durée se règle en tapant l'heure de fin ; un libellé
  // `.qe-duration-custom-label` affiche la durée quand aucun preset ne
  // correspond.

  test('durée — le preset 30m décale l\'heure de fin de 30 minutes', async ({ page }) => {
    const popover = await openEventPopover(page)
    await popover.locator('.qe-duration-preset', { hasText: /^30m$/ }).click()
    await expect(popover.locator('.qe-duration-preset', { hasText: /^30m$/ })).toHaveClass(/active/)
    // Poll : la mise à jour des inputs de fin passe par un effect React —
    // lire les 4 valeurs d'un coup et attendre la convergence.
    await expect.poll(async () => {
      const v = await popover.locator('.qe-time-digit').evaluateAll(
        els => els.map(e => (e as HTMLInputElement).value))
      return (((+v[2] * 60 + +v[3]) - (+v[0] * 60 + +v[1])) + 1440) % 1440
    }, { timeout: 5000 }).toBe(30)
  })

  test('durée — le preset 2h devient actif et met à jour la fin', async ({ page }) => {
    const popover = await openEventPopover(page)
    await popover.locator('.qe-duration-preset', { hasText: /^2h$/ }).click()
    await expect(popover.locator('.qe-duration-preset', { hasText: /^2h$/ })).toHaveClass(/active/)
    await expect.poll(async () => {
      const v = await popover.locator('.qe-time-digit').evaluateAll(
        els => els.map(e => (e as HTMLInputElement).value))
      return (((+v[2] * 60 + +v[3]) - (+v[0] * 60 + +v[1])) + 1440) % 1440
    }, { timeout: 5000 }).toBe(120)
  })

  test('durée — une heure de fin hors presets affiche le libellé custom', async ({ page }) => {
    const popover = await openEventPopover(page)
    // Fin = début + 45 min → durée 45m, aucun preset ne correspond
    const digits = popover.locator('.qe-time-digit')
    const startH = parseInt(await digits.nth(0).inputValue(), 10)
    await digits.nth(2).fill(String(startH).padStart(2, '0'))
    await digits.nth(3).fill('45')
    await popover.locator('.qe-title-input').click() // blur → commit
    await expect(popover.locator('.qe-duration-custom-label')).toHaveText('45m')
    await expect(popover.locator('.qe-duration-preset.active')).toHaveCount(0)
  })

  test('footer — Annuler ferme le popover sans créer d\'événement', async ({ page }) => {
    let posted = false
    await page.route(
      (url) => isApiRoute(url) && url.pathname === '/api/calendar/events',
      async (route: Route) => {
        if (route.request().method() === 'POST') { posted = true }
        await route.fallback()
      }
    )
    const popover = await openEventPopover(page)
    await popover.locator('.qe-title-input').fill('Ne pas créer')
    await popover.locator('.qe-cancel-btn').click()
    await expect(popover).not.toBeVisible({ timeout: 3000 })
    expect(posted).toBe(false)
  })

  test('affiche le champ lieu après toggle Location', async ({ page }) => {
    const popover = await openEventPopover(page)
    // Location toggle is the 1st toggle button (by SVG + text "Lieu")
    await popover.locator('.qe-toggle-btn').nth(0).click()
    await expect(popover.locator('.qe-field-input').first()).toBeVisible({ timeout: 3000 })
  })

  test('remplit le champ lieu', async ({ page }) => {
    const popover = await openEventPopover(page)
    await popover.locator('.qe-toggle-btn').nth(0).click()
    const locationInput = popover.locator('.qe-field-input').first()
    await locationInput.fill('Salle de réunion B2')
    await expect(locationInput).toHaveValue('Salle de réunion B2')
  })

  test('affiche le champ notes après toggle Notes', async ({ page }) => {
    const popover = await openEventPopover(page)
    await popover.locator('.qe-toggle-btn').nth(1).click()
    // Le champ notes est un RichTextEditor (plus un textarea) depuis la
    // migration RTE — cibler le wrapper stable.
    await expect(popover.locator('.qe-field-rte-wrap')).toBeVisible({ timeout: 3000 })
  })

  test('affiche les options de reminder après toggle', async ({ page }) => {
    const popover = await openEventPopover(page)
    await popover.locator('.qe-toggle-btn').nth(2).click()
    await expect(popover.locator('.qe-reminder-track')).toBeVisible({ timeout: 3000 })
  })

  test('sélectionne le reminder 15min', async ({ page }) => {
    const popover = await openEventPopover(page)
    await popover.locator('.qe-toggle-btn').nth(2).click()
    const btn15 = popover.locator('.qe-reminder-track .qe-reminder-seg').filter({ hasText: '15min' })
    await btn15.click()
    await expect(btn15).toHaveClass(/active/)
  })

  test('affiche le picker de récurrence après toggle', async ({ page }) => {
    const popover = await openEventPopover(page)
    await popover.locator('.qe-toggle-btn').nth(3).click()
    await expect(popover.locator('.qe-field-row--recurrence')).toBeVisible({ timeout: 3000 })
  })

  test('envoie location et description dans le body POST', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null
    await page.route(
      (url) => isApiRoute(url) && url.pathname === '/api/calendar/events',
      async (route: Route) => {
        if (route.request().method() === 'POST') {
          capturedBody = JSON.parse(route.request().postData() || '{}')
          await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ success: true, event_id: 'evt-fields' }) })
        } else { await route.fallback() }
      }
    )

    const popover = await openEventPopover(page)
    await popover.locator('.qe-title-input').fill('Test champs complets')

    // Location
    await popover.locator('.qe-toggle-btn').nth(0).click()
    await popover.locator('.qe-field-input').first().fill('Bureau 4ème étage')

    // Notes — RichTextEditor (contenteditable), plus un textarea
    await popover.locator('.qe-toggle-btn').nth(1).click()
    await popover.locator('.qe-field-rte-wrap .rte-editor').fill('Apporter le dossier client')

    await popover.locator('.qe-save-btn').click()
    await popover.waitFor({ state: 'hidden', timeout: 5000 })

    expect(capturedBody!['location']).toBe('Bureau 4ème étage')
    expect(typeof capturedBody!['description']).toBe('string')
    expect((capturedBody!['description'] as string)).toContain('Apporter le dossier client')
  })

  test('envoie reminder dans le body POST quand non-défaut', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null
    await page.route(
      (url) => isApiRoute(url) && url.pathname === '/api/calendar/events',
      async (route: Route) => {
        if (route.request().method() === 'POST') {
          capturedBody = JSON.parse(route.request().postData() || '{}')
          await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ success: true, event_id: 'evt-reminder' }) })
        } else { await route.fallback() }
      }
    )

    const popover = await openEventPopover(page)
    await popover.locator('.qe-title-input').fill('Test reminder')
    await popover.locator('.qe-toggle-btn').nth(2).click()
    // Use exact regex to avoid '5min' matching '15min' (substring)
    await popover.locator('.qe-reminder-track .qe-reminder-seg').filter({ hasText: /^5min$/ }).click()
    await popover.locator('.qe-save-btn').click()
    await popover.waitFor({ state: 'hidden', timeout: 5000 })

    // 5min reminder (non-default) should be sent
    expect(Array.isArray(capturedBody!['reminders'])).toBe(true)
    expect(capturedBody!['reminders']).toContain(5)
  })
})

// ══════════════════════════════════════════════════════════════
// C. Gmail — Labels et colorId
// ══════════════════════════════════════════════════════════════

test.describe('Gmail — Labels et colorId', () => {
  test.beforeEach(async ({ page }) => {
    await setupFullCalendarMocks(page, { provider: 'gmail' })
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToCalendar(page)
  })

  test('affiche le label toggle (Étiquette) quand des labels projet existent', async ({ page }) => {
    const popover = await openEventPopover(page)
    // Labels are fetched async — wait for the Étiquette chip to appear
    await expect(popover.locator('.qe-label-pills .qe-label-chip-toggle')).toBeVisible({ timeout: 6000 })
  })

  test('ouvre le dropdown de labels en cliquant le toggle', async ({ page }) => {
    const popover = await openEventPopover(page)
    const chip = popover.locator('.qe-label-pills .qe-label-chip-toggle')
    await expect(chip).toBeVisible({ timeout: 6000 })
    await chip.click()
    await expect(popover.locator('.qe-label-dropdown')).toBeVisible({ timeout: 3000 })
  })

  test('sélectionne un label et active la chip Étiquette', async ({ page }) => {
    const popover = await openEventPopover(page)
    const chip = popover.locator('.qe-label-pills .qe-label-chip-toggle')
    await expect(chip).toBeVisible({ timeout: 6000 })
    await chip.click()
    await popover.locator('.qe-label-option').first().click()

    // Post-selection : la chip passe en .active et son texte devient le nom
    // du label sélectionné (au lieu du générique "Étiquette").
    await expect(chip).toHaveClass(/active/, { timeout: 3000 })
  })

  test('envoie colorId et labels dans le body POST', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null
    await page.route(
      (url) => isApiRoute(url) && url.pathname === '/api/calendar/events',
      async (route: Route) => {
        if (route.request().method() === 'POST') {
          capturedBody = JSON.parse(route.request().postData() || '{}')
          await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ success: true, event_id: 'evt-label' }) })
        } else { await route.fallback() }
      }
    )

    const popover = await openEventPopover(page)
    await popover.locator('.qe-title-input').fill('Événement avec label')

    // Select "Mon Projet" label (first option)
    const chip = popover.locator('.qe-label-pills .qe-label-chip-toggle')
    await expect(chip).toBeVisible({ timeout: 6000 })
    await chip.click()
    await popover.locator('.qe-label-option').first().click()

    await popover.locator('.qe-save-btn').click()
    await popover.waitFor({ state: 'hidden', timeout: 5000 })

    expect(capturedBody).not.toBeNull()
    // color_id: hex color mapped to Google Calendar colorId (1-11) — sent as 'color_id' to API
    expect(capturedBody!['color_id']).toBeTruthy()
    // Labels are encoded in the description as [tags:encoded,labels] — not a separate field
    expect(typeof capturedBody!['description']).toBe('string')
    expect((capturedBody!['description'] as string)).toContain('[tags:')
  })

  test('retire un label en re-sélectionnant l\'option dans le dropdown', async ({ page }) => {
    // Nouveau flow (2026-04-14) : les pills LabelBadge side-by-side avec la chip
    // Étiquette ont été retirées pour éviter le doublon visuel (la chip elle-
    // même affiche maintenant le nom du label sélectionné). La désélection se
    // fait donc en ré-ouvrant le dropdown et en re-cliquant la même option.
    const popover = await openEventPopover(page)
    const chip = popover.locator('.qe-label-pills .qe-label-chip-toggle')
    await expect(chip).toBeVisible({ timeout: 6000 })

    // Select
    await chip.click()
    await popover.locator('.qe-label-option').first().click()
    await expect(chip).toHaveClass(/active/, { timeout: 3000 })

    // Toggle off : re-open dropdown + click same option
    await chip.click()
    await popover.locator('.qe-label-option').first().click()
    await expect(chip).not.toHaveClass(/active/, { timeout: 3000 })
  })
})

// ══════════════════════════════════════════════════════════════
// D. Gmail — ASAP "Au plus tôt" (SmartSchedulerPanel)
// ══════════════════════════════════════════════════════════════

test.describe('Gmail — ASAP "Au plus tôt"', () => {
  const SLOT_START = (() => {
    const d = new Date(); d.setDate(d.getDate() + 2); d.setHours(10, 0, 0, 0); return d.toISOString()
  })()
  const SLOT_END = (() => {
    const d = new Date(); d.setDate(d.getDate() + 2); d.setHours(11, 0, 0, 0); return d.toISOString()
  })()

  test.beforeEach(async ({ page }) => {
    await setupFullCalendarMocks(page, {
      provider: 'gmail',
      freebusySlots: [{ start: SLOT_START, end: SLOT_END }],
    })
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToCalendar(page)
  })

  test('affiche le bouton "Voir les créneaux" après ajout d\'un participant gmail', async ({ page }) => {
    const popover = await openEventPopover(page)
    await popover.locator('.qe-title-input').fill('Réunion ASAP')
    await addAttendee(page, popover, 'colleague@gmail.com')

    // Free/busy section should appear
    await expect(popover.locator('.qe-slot-browse-link')).toBeVisible({ timeout: 5000 })
  })

  // NOTE (2026-06-09) : l'ancien SmartSchedulerPanel (`.qe-scheduler`) a été
  // remplacé par le PickATimePicker (`.pat-overlay` / `.pat-shell`). Les
  // créneaux sont des `.pat-chip` ; le meilleur créneau porte `.is-best` ;
  // la sélection se fait au double-clic.

  test('ouvre le PickATimePicker via "Voir les créneaux"', async ({ page }) => {
    const popover = await openEventPopover(page)
    await popover.locator('.qe-title-input').fill('Réunion ASAP')
    await addAttendee(page, popover, 'colleague@gmail.com')

    await popover.locator('.qe-slot-browse-link').click()
    await expect(page.locator('.pat-overlay')).toBeVisible({ timeout: 5000 })
    await expect(page.locator('.pat-shell')).toBeVisible({ timeout: 3000 })
  })

  test('le meilleur créneau (.is-best) est visible dans le PickATimePicker', async ({ page }) => {
    const popover = await openEventPopover(page)
    await popover.locator('.qe-title-input').fill('Réunion ASAP')
    await addAttendee(page, popover, 'colleague@gmail.com')
    await popover.locator('.qe-slot-browse-link').click()

    // Le panneau auto-search à l'ouverture — le créneau mocké doit
    // apparaître comme chip, marqué "best" (étoile).
    await expect(page.locator('.pat-chip.is-best')).toBeVisible({ timeout: 8000 })
    await expect(page.locator('.pat-chip-best')).toBeVisible()
  })

  test('double-clic sur un créneau ferme le picker et affiche la confirmation', async ({ page }) => {
    const popover = await openEventPopover(page)
    await popover.locator('.qe-title-input').fill('Réunion ASAP')
    await addAttendee(page, popover, 'colleague@gmail.com')
    await popover.locator('.qe-slot-browse-link').click()

    const best = page.locator('.pat-chip.is-best')
    await expect(best).toBeVisible({ timeout: 8000 })
    await best.dblclick()

    // Picker should close
    await page.locator('.pat-overlay').waitFor({ state: 'hidden', timeout: 8000 })

    // Slot confirmation badge should appear in the popover
    await expect(popover.locator('.qe-slot-confirm')).toBeVisible({ timeout: 5000 })
  })

  test('crée l\'événement après sélection ASAP (un seul POST)', async ({ page }) => {
    let postCount = 0
    await page.route(
      (url) => isApiRoute(url) && url.pathname === '/api/calendar/events',
      async (route: Route) => {
        if (route.request().method() === 'POST') {
          postCount++
          await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ success: true, event_id: 'asap-evt' }) })
        } else {
          await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ events: [], count: 0 }) })
        }
      }
    )

    const popover = await openEventPopover(page)
    await popover.locator('.qe-title-input').fill('Réunion ASAP')
    await addAttendee(page, popover, 'colleague@gmail.com')

    await popover.locator('.qe-slot-browse-link').click()
    // Auto-search → double-clic sur le meilleur créneau (PickATimePicker)
    const best = page.locator('.pat-chip.is-best')
    await expect(best).toBeVisible({ timeout: 8000 })
    await best.dblclick()
    await page.locator('.pat-overlay').waitFor({ state: 'hidden', timeout: 8000 })

    // Save
    await popover.locator('.qe-save-btn').click()
    await popover.waitFor({ state: 'hidden', timeout: 8000 })

    await page.waitForTimeout(1000)
    expect(postCount).toBe(1)
  })

  test('n\'affiche pas le bouton créneaux pour un participant Outlook (cross-provider)', async ({ page }) => {
    const popover = await openEventPopover(page)
    await popover.locator('.qe-title-input').fill('Réunion cross-provider')
    await addAttendee(page, popover, 'contact@outlook.com')

    // Free/busy NOT compatible with Outlook attendee when provider is gmail
    await page.waitForTimeout(500)
    await expect(popover.locator('.qe-slot-browse-link')).not.toBeVisible()
  })
})

// ══════════════════════════════════════════════════════════════
// E. Gmail — Édition d'événement via EventModal
// ══════════════════════════════════════════════════════════════

test.describe('Gmail — Édition d\'événement', () => {
  const EXISTING_EVENT = makeEvent('evt-edit', 'Réunion à modifier', { attendees: ['alice@gmail.com'] })

  test.beforeEach(async ({ page }) => {
    await setupFullCalendarMocks(page, { provider: 'gmail', initialEvents: [EXISTING_EVENT] })
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToCalendar(page)
  })

  test('ouvre le modal de détail en cliquant un événement', async ({ page }) => {
    const event = page.locator('.calendar-event, .fc-event').first()
    await expect(event).toBeVisible({ timeout: 8000 })
    await event.click()

    await expect(page.locator('.calendar-event-modal')).toBeVisible({ timeout: 5000 })
    await expect(page.locator('.calendar-event-modal-title')).toContainText('Réunion à modifier')
  })

  test('ouvre le QuickEventPopover en mode édition via le bouton Edit', async ({ page }) => {
    const event = page.locator('.calendar-event, .fc-event').first()
    await event.click()
    await expect(page.locator('.calendar-event-modal')).toBeVisible({ timeout: 5000 })

    // Click edit button
    await page.locator('.calendar-event-modal-edit-btn').click()
    await expect(page.locator('.qe-popover')).toBeVisible({ timeout: 5000 })

    // Title should be pre-filled
    await expect(page.locator('.qe-title-input')).toHaveValue('Réunion à modifier')
  })

  test('édite le titre et envoie un PATCH', async ({ page }) => {
    let patchBody: Record<string, unknown> | null = null
    await page.route(
      (url) => isApiRoute(url) && /\/api\/calendar\/events\/[^/]+$/.test(url.pathname),
      async (route: Route) => {
        if (route.request().method() === 'PATCH') {
          patchBody = JSON.parse(route.request().postData() || '{}')
          await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
        } else { await route.fallback() }
      }
    )

    const event = page.locator('.calendar-event, .fc-event').first()
    await event.click()
    await page.locator('.calendar-event-modal-edit-btn').click()
    await expect(page.locator('.qe-popover')).toBeVisible({ timeout: 5000 })

    // Change title
    const titleInput = page.locator('.qe-title-input')
    await titleInput.clear()
    await titleInput.fill('Réunion modifiée ✓')

    // Save (edit mode shows "Enregistrer")
    await page.locator('.qe-save-btn').click()
    await page.locator('.qe-popover').waitFor({ state: 'hidden', timeout: 5000 })

    expect(patchBody).not.toBeNull()
    expect(patchBody!['title']).toBe('Réunion modifiée ✓')
  })

  test('affiche les label chips dans le EventModal', async ({ page }) => {
    const event = page.locator('.calendar-event, .fc-event').first()
    await event.click()
    const modal = page.locator('.calendar-event-modal')
    await expect(modal).toBeVisible({ timeout: 5000 })

    // Default labels are always rendered in the modal label picker
    await expect(modal.locator('.cal-label-chip').first()).toBeVisible({ timeout: 3000 })
  })
})

// ══════════════════════════════════════════════════════════════
// F. Outlook — Toggle Teams et conference link
// ══════════════════════════════════════════════════════════════

test.describe('Outlook — Toggle Teams', () => {
  test.beforeEach(async ({ page }) => {
    await setupFullCalendarMocks(page, { provider: 'outlook' })
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToCalendar(page)
  })

  test('affiche "Teams" (pas "Google Meet") pour le toggle vidéo Outlook', async ({ page }) => {
    const popover = await openEventPopover(page)
    await expect(popover.locator('.qe-toggle-btn').filter({ hasText: 'Teams' })).toBeVisible({ timeout: 5000 })
    await expect(popover.locator('.qe-toggle-btn').filter({ hasText: 'Google Meet' })).not.toBeVisible()
  })

  test('affiche la coche de confirmation sur le toggle Teams', async ({ page }) => {
    const popover = await openEventPopover(page)
    const toggleBtn = popover.locator('.qe-toggle-btn').filter({ hasText: 'Teams' })
    await toggleBtn.click()
    // Le badge `.qe-conference-badge` n'existe plus — voir le test Gmail.
    await expect(toggleBtn).toHaveClass(/active/)
    await expect(toggleBtn.locator('.qe-toggle-check')).toBeVisible({ timeout: 3000 })
  })

  test('envoie conference:true dans le body POST (Outlook)', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null
    await page.route(
      (url) => isApiRoute(url) && url.pathname === '/api/calendar/events',
      async (route: Route) => {
        if (route.request().method() === 'POST') {
          capturedBody = JSON.parse(route.request().postData() || '{}')
          await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ success: true, event_id: 'evt-teams', meet_link: 'https://teams.microsoft.com/l/meetup-join/abc' }) })
        } else { await route.fallback() }
      }
    )

    const popover = await openEventPopover(page)
    await popover.locator('.qe-title-input').fill('Appel Teams')
    await popover.locator('.qe-toggle-btn').filter({ hasText: 'Teams' }).click()
    await popover.locator('.qe-save-btn').click()
    await popover.waitFor({ state: 'hidden', timeout: 5000 })

    expect(capturedBody!['conference']).toBe(true)
  })
})

// ══════════════════════════════════════════════════════════════
// G. Meet / Teams link dans EventModal
// ══════════════════════════════════════════════════════════════

test.describe('EventModal — Liens Meet/Teams', () => {
  test('affiche "Rejoindre Google Meet" pour un événement Gmail avec meetLink', async ({ page }) => {
    const meetLink = 'https://meet.google.com/abc-def-ghi'
    await setupFullCalendarMocks(page, {
      provider: 'gmail',
      initialEvents: [makeEvent('evt-meet', 'Réunion Meet', { meetLink })],
    })
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToCalendar(page)

    const event = page.locator('.calendar-event, .fc-event').first()
    await expect(event).toBeVisible({ timeout: 8000 })
    await event.click()

    await expect(page.locator('.calendar-event-modal')).toBeVisible({ timeout: 5000 })
    const link = page.locator('.calendar-event-modal-meet-link')
    await expect(link).toBeVisible({ timeout: 3000 })
    await expect(link).toContainText('Google Meet')
    // Link should have correct href
    const href = await link.getAttribute('href')
    expect(href).toBe(meetLink)
  })

  test('affiche "Rejoindre Teams" pour un événement Outlook avec meetLink', async ({ page }) => {
    const teamsLink = 'https://teams.microsoft.com/l/meetup-join/test123'
    await setupFullCalendarMocks(page, {
      provider: 'outlook',
      initialEvents: [makeEvent('evt-teams', 'Appel Teams', { meetLink: teamsLink, providerSource: 'outlook' })],
    })
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToCalendar(page)

    const event = page.locator('.calendar-event, .fc-event').first()
    await expect(event).toBeVisible({ timeout: 8000 })
    await event.click()

    await expect(page.locator('.calendar-event-modal')).toBeVisible({ timeout: 5000 })
    const link = page.locator('.calendar-event-modal-meet-link')
    await expect(link).toBeVisible({ timeout: 3000 })
    await expect(link).toContainText('Teams')
    const href = await link.getAttribute('href')
    expect(href).toBe(teamsLink)
  })

  test('n\'affiche pas de lien visio si l\'événement n\'a pas de meetLink', async ({ page }) => {
    await setupFullCalendarMocks(page, {
      provider: 'gmail',
      initialEvents: [makeEvent('evt-no-meet', 'Réunion sans visio')],
    })
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToCalendar(page)

    const event = page.locator('.calendar-event, .fc-event').first()
    await event.click()
    await expect(page.locator('.calendar-event-modal')).toBeVisible({ timeout: 5000 })
    await expect(page.locator('.calendar-event-modal-meet-link')).not.toBeVisible()
  })
})

// ══════════════════════════════════════════════════════════════
// H. Régressions critiques (lessons.md)
// ══════════════════════════════════════════════════════════════

test.describe('Régressions critiques', () => {
  test('filteredEvents — l\'événement créé reste visible après refresh serveur', async ({ page }) => {
    await setupFullCalendarMocks(page, { provider: 'gmail', initialEvents: [] })
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToCalendar(page)

    const popover = await openEventPopover(page)
    await popover.locator('.qe-title-input').fill('Test filteredEvents')
    await popover.locator('.qe-save-btn').click()
    await popover.waitFor({ state: 'hidden', timeout: 5000 })

    const eventLocator = page.locator('.calendar-event-title-text, .cal-event-text, .fc-event-title')
      .filter({ hasText: 'Test filteredEvents' }).first()
    await expect(eventLocator).toBeVisible({ timeout: 8000 })

    // Wait > 2s for delayed fetchEvents and verify still visible
    await page.waitForTimeout(3000)
    await expect(eventLocator).toBeVisible({ timeout: 3000 })
  })

  test('Hotmail primary — événement visible quand aucun calendrier n\'a isPrimary=true', async ({ page }) => {
    // Hotmail doesn't set isDefaultCalendar / isPrimary — all calendars have false
    await setupBaseMocks(page)

    const evt = makeEvent('hotmail-evt', 'Réunion Hotmail', { calendarId: 'AAMkHotmail123', providerSource: 'outlook' })

    await page.route((url) => isApiRoute(url) && url.pathname === '/api/calendar/status', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ connected: true, provider: 'outlook', email: 'test@hotmail.com' }) }))
    await page.route((url) => isApiRoute(url) && url.pathname === '/api/calendar/calendars', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ calendars: [
        // No isPrimary / isDefaultCalendar — typical Hotmail
        { id: 'AAMkHotmail123', name: 'Calendar', primary: false, isPrimary: false, providerSource: 'outlook', color: '#0078d4' },
      ] }) }))
    await page.route((url) => isApiRoute(url) && url.pathname === '/api/calendar/events' &&
      !/\/api\/calendar\/events\/[^/]+$/.test(url.pathname), (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ events: [evt], count: 1 }) }))
    for (const p of ['/api/calendar/followups', '/api/calendar/today', '/api/calendar/upcoming',
      '/api/calendar/holidays', '/api/calendar/public-holidays', '/api/calendar/detect-region',
      '/api/calendar/freebusy', '/api/stats/feature']) {
      await page.route((url) => isApiRoute(url) && url.pathname === p, (route) =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) }))
    }
    await page.route((url) => isApiRoute(url) && url.pathname === '/api/labels', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ labels: [] }) }))

    await page.goto('/')
    await waitForAppReady(page)
    await navigateToCalendar(page)

    // Event must be visible even without isPrimary calendar
    await expect(
      page.locator('.calendar-event-title-text, .cal-event-text, .fc-event-title')
        .filter({ hasText: 'Réunion Hotmail' }).first()
    ).toBeVisible({ timeout: 10000 })
  })

  test('double-mount React StrictMode — un seul POST envoyé', async ({ page }) => {
    let postCount = 0
    await setupFullCalendarMocks(page, { provider: 'gmail', initialEvents: [] })
    // Override with counter
    await page.route(
      (url) => isApiRoute(url) && url.pathname === '/api/calendar/events' &&
        !/\/api\/calendar\/events\/[^/]+$/.test(url.pathname),
      async (route: Route) => {
        if (route.request().method() === 'POST') {
          postCount++
          await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ success: true, event_id: `evt-dm-${postCount}` }) })
        } else {
          await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ events: [], count: 0 }) })
        }
      }
    )

    await page.goto('/')
    await waitForAppReady(page)
    await navigateToCalendar(page)

    const popover = await openEventPopover(page)
    await popover.locator('.qe-title-input').fill('Test double-mount')
    await popover.locator('.qe-save-btn').click()
    await popover.waitFor({ state: 'hidden', timeout: 5000 })

    // Wait for potential React StrictMode second mount
    await page.waitForTimeout(2000)
    expect(postCount).toBe(1)
  })

  // Test "création d'événement all-day" retiré (2026-04-14) — le bouton
  // "Toute la journée" n'existe plus dans QuickEventPopover (state `allDay`
  // conservé en lecture seule pour compat edit d'events externes all-day).

  test('organizer.email n\'est pas utilisé comme calendar_id (anti-régression)', async ({ page }) => {
    // If organizer.email was used as calendar_id, the event would be filtered out
    // because calendarId wouldn't match the visible calendar 'cal-1'
    const eventWithOrganizer = {
      ...makeEvent('evt-org', 'Réunion organisateur'),
      organizer: 'boss@company.com', // Should NOT be used as calendar_id
      calendar_id: 'cal-1',          // This is the correct calendar_id
    }
    await setupFullCalendarMocks(page, { provider: 'gmail', initialEvents: [eventWithOrganizer] })
    await page.goto('/')
    await waitForAppReady(page)
    await navigateToCalendar(page)

    await expect(
      page.locator('.calendar-event-title-text, .cal-event-text, .fc-event-title')
        .filter({ hasText: 'Réunion organisateur' }).first()
    ).toBeVisible({ timeout: 10000 })
  })
})
