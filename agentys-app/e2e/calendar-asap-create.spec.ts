/**
 * Regression test: "Au plus tôt" — création d'évènement silencieuse
 *
 * Bug: setCurrentWeekStart() était appelé AVANT l'await createCalendarEvent(),
 * ce qui déclenchait un fetch prématuré (useEffect([fetchEvents])) → réponse vide
 * → l'évènement optimiste disparaissait.
 *
 * Fix: naviguer vers la semaine de l'évènement APRÈS la création.
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady, isApiRoute } from './support/fixtures/setup'

// Créneau ASAP dans 3 jours (couvre le bug cross-week si on est en fin de semaine)
const SLOT_START = (() => {
  const d = new Date(); d.setDate(d.getDate() + 3); d.setHours(11, 0, 0, 0); return d.toISOString();
})()
const SLOT_END = (() => {
  const d = new Date(); d.setDate(d.getDate() + 3); d.setHours(12, 0, 0, 0); return d.toISOString();
})()
const NEW_EVENT_ID = 'asap-evt-created'
const EVENT_TITLE = 'Test ASAP'

async function setupAsapMocks(page: Page) {
  await setupBaseMocks(page)

  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/status',
    (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ connected: true, ready: true, provider: 'google', email: 'test@example.com' }),
    })
  )

  // GET events — vide au départ, rempli après création
  let eventCreated = false
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/events',
    (route) => {
      if (route.request().method() === 'POST') {
        // Créer l'évènement
        eventCreated = true
        route.fulfill({
          status: 201, contentType: 'application/json',
          body: JSON.stringify({ success: true, event_id: NEW_EVENT_ID }),
        })
      } else {
        // GET — retourner le nouvel évènement s'il a été créé
        const events = eventCreated
          ? [{ id: NEW_EVENT_ID, title: EVENT_TITLE, start: SLOT_START, end: SLOT_END, calendar_id: 'cal-1', color: '#22c55e' }]
          : []
        route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({ events, count: events.length }),
        })
      }
    }
  )

  // Freebusy → retourne le créneau ASAP
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/freebusy',
    (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ slots: [{ start: SLOT_START, end: SLOT_END }], attendees: [], duration_minutes: 60 }),
    })
  )

  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/calendars',
    (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        calendars: [{
          id: 'cal-1',
          name: 'test@example.com',
          primary: true,
          isPrimary: true,
          providerSource: 'google_calendar', // → calendarProvider = 'gmail' → shows "Google Meet" + slot section
          color: '#4285f4',
        }],
      }),
    })
  )
  // Labels — needed to avoid fetchLabels() errors
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/labels',
    (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ labels: [], counts: {} }),
    })
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/today',
    (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ events: [], count: 0 }),
    })
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/upcoming',
    (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ events: [], count: 0 }),
    })
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/followups',
    (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ followups: [] }),
    })
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/stats/feature',
    (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ ok: true }),
    })
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname.startsWith('/api/contacts'),
    (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    }),
  )
}

async function navigateToCalendar(page: Page) {
  const calBtn = page.locator('[data-testid="nav-calendar"]').first()
  if (await calBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await calBtn.click()
  } else {
    await page.getByRole('button', { name: /calendrier/i }).first().click()
  }
  await page.locator('.calendar-view, .calendar-week-body').first().waitFor({ state: 'visible', timeout: 10000 })
}

test.describe('Calendar — "Au plus tôt" crée bien l\'évènement', () => {
  test.beforeEach(async ({ page }) => {
    await setupAsapMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('crée l\'évènement dans le calendrier après sélection ASAP', async ({ page }) => {
    await navigateToCalendar(page)

    // Ouvrir le popover via le raccourci C
    await page.keyboard.press('c')
    const popover = page.locator('.qe-popover')
    const visibleAfterC = await popover.waitFor({ state: 'visible', timeout: 3000 }).then(() => true, () => false)
    if (!visibleAfterC) await page.keyboard.press('b')
    await expect(popover).toBeVisible({ timeout: 5000 })

    // Entrer un titre
    await page.locator('.qe-title-input').fill(EVENT_TITLE)

    // Ajouter un participant gmail (compatible avec le provider google)
    const attendeeInput = page.locator('.qe-contact-autocomplete input').first()
    await attendeeInput.click()
    await attendeeInput.type('collegue@gmail.com', { delay: 20 })
    await attendeeInput.press('Enter')
    await page.waitForTimeout(500)

    // Le premier créneau suggéré est l'équivalent fonctionnel du choix
    // "Au plus tôt". Il reste dans le popover, tandis que "Voir plus de
    // créneaux" ouvre maintenant le picker plein écran.
    const earliest = page.locator('.qe-slot-suggestion.is-earliest')
    await expect(earliest).toBeVisible({ timeout: 5000 })
    await earliest.click()

    // Le badge de confirmation du créneau s'affiche
    await expect(page.locator('.qe-slot-confirm')).toBeVisible({ timeout: 5000 })

    // Créer l'évènement
    await page.locator('.qe-save-btn').click()

    // Le popover doit se fermer
    await page.locator('.qe-popover').waitFor({ state: 'hidden', timeout: 8000 })

    // L'évènement doit apparaître dans le calendrier
    await expect(
      page.locator('.calendar-event-title-text, .cal-event-text, .fc-event-title')
        .filter({ hasText: EVENT_TITLE })
        .first()
    ).toBeVisible({ timeout: 10000 })
  })
})
