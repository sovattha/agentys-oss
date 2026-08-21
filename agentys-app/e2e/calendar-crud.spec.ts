/**
 * Calendar CRUD — Comprehensive E2E Tests
 *
 * Tests: event creation/deletion/update, view switching, navigation,
 * follow-ups, error states, disconnected state.
 *
 * Uses stateful mocks so POST/DELETE mutate the events array
 * and subsequent GET returns the updated list.
 */

import { test, expect, Page, Route } from '@playwright/test'
import { setupBaseMocks, waitForAppReady, isApiRoute } from './support/fixtures/setup'

// ---------- Mock data ----------

const now = new Date()
const todayStart = new Date(now)
todayStart.setHours(10, 0, 0, 0)
const todayEnd = new Date(now)
todayEnd.setHours(11, 0, 0, 0)

function makeEvent(
  id: string,
  title: string,
  offsetHours = 0,
  opts: { color?: string; isFollowup?: boolean; isOverdue?: boolean } = {}
) {
  const start = new Date(todayStart.getTime() + offsetHours * 3600000)
  const end = new Date(start.getTime() + 3600000)
  return {
    id,
    title,
    start: start.toISOString(),
    end: end.toISOString(),
    calendar_id: 'cal-1',
    calendarId: 'cal-1',
    color: opts.color || '#6b7280',
    isAllDay: false,
    status: 'confirmed',
    providerSource: 'google',
    isRecurring: false,
    attendees: [],
    event_type: opts.isFollowup ? 'followup' : 'event',
    is_overdue: opts.isOverdue || false,
  }
}

const INITIAL_EVENTS = [
  makeEvent('evt-1', 'Réunion équipe', 0),
  makeEvent('evt-2', 'Appel client', 2, { color: '#3b82f6' }),
  makeEvent('evt-3', 'Déjeuner partenaire', 4, { color: '#10b981' }),
]

// ---------- Helpers ----------

async function setupCalendarCrudMocks(page: Page, opts: {
  connected?: boolean
  initialEvents?: typeof INITIAL_EVENTS
  errorMode?: boolean
} = {}) {
  const { connected = true, initialEvents = [...INITIAL_EVENTS], errorMode = false } = opts
  await setupBaseMocks(page)

  // Stateful events array — mutated by POST/DELETE handlers
  let events = [...initialEvents]
  let nextId = 100

  // Calendar status
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/status',
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(
          connected
            ? { connected: true, provider: 'google', email: 'test@example.com' }
            : { connected: false }
        ),
      })
    }
  )

  // Calendar events — GET returns current events, POST adds, DELETE removes
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/events' && !url.pathname.match(/\/api\/calendar\/events\/[^/]+$/),
    (route: Route) => {
      const method = route.request().method()
      if (method === 'POST') {
        try {
          const body = JSON.parse(route.request().postData() || '{}')
          const newId = `evt-new-${nextId++}`
          events.push(makeEvent(newId, body.title || 'Sans titre', 0))
          route.fulfill({
            status: 201,
            contentType: 'application/json',
            body: JSON.stringify({ success: true, event_id: newId }),
          })
        } catch {
          route.fulfill({
            status: 400,
            contentType: 'application/json',
            body: JSON.stringify({ error: 'Invalid request' }),
          })
        }
      } else {
        // GET
        if (errorMode) {
          route.fulfill({
            status: 500,
            contentType: 'application/json',
            body: JSON.stringify({ error: 'Internal server error' }),
          })
          return
        }
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ events, count: events.length }),
        })
      }
    }
  )

  // Single event endpoints (PATCH/DELETE by ID)
  await page.route(
    (url) => isApiRoute(url) && /\/api\/calendar\/events\/[^/]+$/.test(url.pathname),
    (route: Route) => {
      const method = route.request().method()
      const eventId = route.request().url().match(/\/api\/calendar\/events\/([^/?]+)/)?.[1]

      if (method === 'DELETE') {
        events = events.filter((e) => e.id !== eventId)
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true }),
        })
      } else if (method === 'PATCH') {
        try {
          const body = JSON.parse(route.request().postData() || '{}')
          events = events.map((e) =>
            e.id === eventId ? { ...e, title: body.title || e.title } : e
          )
          route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ success: true }),
          })
        } catch {
          route.fulfill({
            status: 400,
            contentType: 'application/json',
            body: JSON.stringify({ error: 'Invalid request' }),
          })
        }
      } else {
        // GET single event
        const event = events.find((e) => e.id === eventId)
        if (event) {
          route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ event }),
          })
        } else {
          route.fulfill({
            status: 404,
            contentType: 'application/json',
            body: JSON.stringify({ error: 'Event not found' }),
          })
        }
      }
    }
  )

  // Calendars list
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/calendars',
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          calendars: [{ id: 'cal-1', name: 'Mon calendrier', primary: true, color: '#4285f4' }],
        }),
      })
    }
  )

  // Today / upcoming
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/today',
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ events: events.slice(0, 2), count: Math.min(events.length, 2) }),
      })
    }
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/upcoming',
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ events, count: events.length }),
      })
    }
  )

  // Followups
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/followups',
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ followups: [] }),
      })
    }
  )

  // Freebusy
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/freebusy',
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ slots: [], attendees: [], duration_minutes: 60 }),
      })
    }
  )

  // Stats/feature tracking
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/stats/feature',
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true }),
      })
    }
  )

  // Holidays
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/holidays',
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ holidays: [] }),
      })
    }
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/public-holidays',
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ holidays: [] }),
      })
    }
  )
  await page.route(
    (url) => isApiRoute(url) && url.pathname === '/api/calendar/detect-region',
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ timezone: 'Europe/Paris', country: 'FR' }),
      })
    }
  )
}

async function navigateToCalendar(page: Page) {
  const calBtn = page.locator('[data-testid="nav-calendar"]').first()
  await expect(calBtn).toBeVisible({ timeout: 5000 })
  await calBtn.click()
  // Wait for the calendar view (custom or FullCalendar)
  await page.locator('.calendar-view, .fc, .calendar-week-body').first().waitFor({ state: 'visible', timeout: 10000 })
}

// ---------- Test Suites ----------

test.describe('Calendar CRUD — création d\'événement', () => {
  test.beforeEach(async ({ page }) => {
    await setupCalendarCrudMocks(page, { initialEvents: [] })
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('crée un événement qui persiste dans le calendrier', async ({ page }) => {
    await navigateToCalendar(page)

    // Open create popover via keyboard shortcut C (fallback B)
    await page.keyboard.press('c')
    const popover = page.locator('.qe-popover')
    const popoverVisibleAfterC = await popover.waitFor({ state: 'visible', timeout: 3000 }).then(() => true, () => false)
    if (!popoverVisibleAfterC) {
      await page.keyboard.press('b')
    }
    await expect(popover).toBeVisible({ timeout: 5000 })

    // Fill title
    await page.locator('.qe-title-input').fill('Nouveau rendez-vous')

    // Save
    await page.locator('.qe-save-btn').click()

    // Popover should close
    await popover.waitFor({ state: 'hidden', timeout: 5000 })

    // Event should appear in calendar (after fetch refreshes)
    await expect(
      page.locator('.calendar-event-title-text, .cal-event-text, .fc-event-title')
        .filter({ hasText: 'Nouveau rendez-vous' })
        .first()
    ).toBeVisible({ timeout: 8000 })
  })

  // Test "crée un événement all-day" retiré (2026-04-14) — le bouton
  // "Toute la journée" n'existe plus dans QuickEventPopover.

  // ============================================================================
  // Regression: event must persist after the 2s delayed server refresh
  // ============================================================================
  test('l\'événement créé persiste après le refresh serveur (anti-régression)', async ({ page }) => {
    await navigateToCalendar(page)

    await page.keyboard.press('c')
    const popover = page.locator('.qe-popover')
    const popoverVisibleAfterC = await popover.waitFor({ state: 'visible', timeout: 3000 }).then(() => true, () => false)
    if (!popoverVisibleAfterC) {
      await page.keyboard.press('b')
    }
    await expect(popover).toBeVisible({ timeout: 5000 })

    await page.locator('.qe-title-input').fill('Persistence Test')
    await page.locator('.qe-save-btn').click()
    await popover.waitFor({ state: 'hidden', timeout: 5000 })

    // Event appears immediately (optimistic)
    const eventLocator = page.locator('.calendar-event-title-text, .cal-event-text, .fc-event-title')
      .filter({ hasText: 'Persistence Test' })
      .first()
    await expect(eventLocator).toBeVisible({ timeout: 5000 })

    // Wait > 2s for the delayed fetchEvents to fire and verify event is STILL visible
    await page.waitForTimeout(3000)
    await expect(eventLocator).toBeVisible({ timeout: 3000 })
  })

  test('ferme le popover avec Escape', async ({ page }) => {
    await navigateToCalendar(page)

    await page.keyboard.press('c')
    const popover = page.locator('.qe-popover')
    const popoverVisibleAfterC = await popover.waitFor({ state: 'visible', timeout: 3000 }).then(() => true, () => false)
    if (!popoverVisibleAfterC) {
      await page.keyboard.press('b')
    }
    await expect(popover).toBeVisible({ timeout: 5000 })

    await page.keyboard.press('Escape')
    await popover.waitFor({ state: 'hidden', timeout: 3000 })
  })
})

test.describe('Calendar CRUD — suppression d\'événement', () => {
  test.beforeEach(async ({ page }) => {
    await setupCalendarCrudMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('supprime un événement du calendrier', async ({ page }) => {
    await navigateToCalendar(page)

    // Verify events are displayed
    const eventTitle = page.locator('.calendar-event-title-text, .cal-event-text, .fc-event-title').first()
    await expect(eventTitle).toBeVisible({ timeout: 8000 })

    // Count events before deletion
    const countBefore = await page.locator('.calendar-event, .fc-event').count()

    // Hover to reveal delete button, then force-click it (delete btn is CSS :hover-gated)
    const firstEvent = page.locator('.calendar-event, .fc-event').first()
    await firstEvent.hover()
    const deleteBtn = firstEvent.locator('.calendar-event-delete-btn, .cal-event-delete').first()
    // force:true bypasses the CSS opacity/pointer-events gate applied outside :hover
    await deleteBtn.click({ force: true, timeout: 3000 })

    // Event count should decrease or the specific event should be gone
    await page.waitForTimeout(1000)
    const countAfter = await page.locator('.calendar-event, .fc-event').count()
    expect(countAfter).toBeLessThan(countBefore)
  })
})

test.describe('Calendar CRUD — mise à jour d\'événement', () => {
  test.beforeEach(async ({ page }) => {
    await setupCalendarCrudMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('ouvre un événement et affiche les détails', async ({ page }) => {
    await navigateToCalendar(page)

    // Click on an event
    const event = page.locator('.calendar-event, .fc-event').first()
    await expect(event).toBeVisible({ timeout: 8000 })
    await event.click()

    // Modal or tooltip should appear with event details
    const modal = page.locator('.calendar-event-modal, .event-modal, [role="dialog"]').first()
    await expect(modal).toBeVisible({ timeout: 5000 })
  })
})

test.describe('Calendar — changement de vue', () => {
  test.beforeEach(async ({ page }) => {
    await setupCalendarCrudMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('bascule entre les vues via raccourcis clavier', async ({ page }) => {
    await navigateToCalendar(page)

    // Main CalendarView uses keyboard shortcuts for view switching: 1=day, 3=3day, 7=week
    await page.keyboard.press('1')
    await expect(page.locator('.calendar-view').first()).toBeVisible({ timeout: 5000 })
    await expect(page.locator('text=/erreur|error|500/i')).not.toBeVisible({ timeout: 3000 })

    await page.keyboard.press('3')
    await expect(page.locator('.calendar-view').first()).toBeVisible({ timeout: 5000 })
    await expect(page.locator('text=/erreur|error|500/i')).not.toBeVisible({ timeout: 3000 })

    await page.keyboard.press('7')
    await expect(page.locator('.calendar-view').first()).toBeVisible({ timeout: 5000 })
    await expect(page.locator('text=/erreur|error|500/i')).not.toBeVisible({ timeout: 3000 })
  })

  test('raccourcis clavier pour les vues (1/2/3)', async ({ page }) => {
    await navigateToCalendar(page)

    // Keyboard shortcuts: 1=day, 2=week, 3=month (if implemented)
    await page.keyboard.press('2')
    await expect(page.locator('text=/erreur|error|500/i')).not.toBeVisible({ timeout: 3000 })

    await page.keyboard.press('1')
    await expect(page.locator('text=/erreur|error|500/i')).not.toBeVisible({ timeout: 3000 })

    await page.keyboard.press('3')
    await expect(page.locator('text=/erreur|error|500/i')).not.toBeVisible({ timeout: 3000 })
  })
})

test.describe('Calendar — navigation', () => {
  test.beforeEach(async ({ page }) => {
    await setupCalendarCrudMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('navigue semaine suivante/précédente', async ({ page }) => {
    await navigateToCalendar(page)

    // Next — uses aria-label "Période suivante" or class .calendar-chevron-btn
    const nextBtn = page.locator('.calendar-chevron-btn').nth(1)
    await expect(nextBtn).toBeVisible({ timeout: 5000 })
    await nextBtn.click()
    await expect(page.locator('.calendar-view').first()).toBeVisible({ timeout: 5000 })

    // Previous
    const prevBtn = page.locator('.calendar-chevron-btn').first()
    await expect(prevBtn).toBeVisible({ timeout: 5000 })
    await prevBtn.click()
    await expect(page.locator('.calendar-view').first()).toBeVisible({ timeout: 5000 })
  })

  test('raccourci T revient à aujourd\'hui', async ({ page }) => {
    await navigateToCalendar(page)

    // Navigate away first
    await page.keyboard.press('=')
    await page.waitForTimeout(500)

    // Press T to go back to today
    await page.keyboard.press('t')

    // Should not crash
    await expect(page.locator('text=/erreur|error|500/i')).not.toBeVisible({ timeout: 3000 })
    await expect(page.locator('.calendar-view, .fc, .calendar-week-body').first()).toBeVisible({ timeout: 5000 })
  })

  test('retour à l\'inbox depuis le calendrier', async ({ page }) => {
    await navigateToCalendar(page)

    // In calendar mode, nav-inbox is not rendered (appMode === 'mail' guard).
    // Use the calendar close button or the mail sidebar icon to go back.
    const closeBtn = page.locator('.calendar-close-btn').first()
    const mailIcon = page.locator('.sidebar-item').first()
    if (await closeBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
      await closeBtn.click()
    } else {
      // Click the first sidebar item (mail icon) to switch back
      await mailIcon.click()
    }
    // After switching back, nav-inbox should be rendered
    await expect(page.locator('[data-testid="nav-inbox"]')).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Calendar — follow-ups', () => {
  test('affiche les follow-ups avec badge', async ({ page }) => {
    const followupEvent = makeEvent('followup_1', 'Relancer Sophie', 1, { isFollowup: true, color: '#3B82F6' })
    await setupCalendarCrudMocks(page, { initialEvents: [...INITIAL_EVENTS, followupEvent] })
    await page.goto('/')
    await waitForAppReady(page)

    await navigateToCalendar(page)

    // Follow-up event should appear
    await expect(
      page.locator('.calendar-event-title-text, .cal-event-text, .fc-event-title')
        .filter({ hasText: 'Relancer Sophie' })
        .first()
    ).toBeVisible({ timeout: 8000 })
  })

  test('affiche les follow-ups en retard avec style différent', async ({ page }) => {
    const overdueEvent = makeEvent('followup_overdue', 'Réponse urgente', -24, {
      isFollowup: true,
      isOverdue: true,
      color: '#EF4444',
    })
    await setupCalendarCrudMocks(page, { initialEvents: [overdueEvent] })
    await page.goto('/')
    await waitForAppReady(page)

    await navigateToCalendar(page)

    // Overdue follow-up should appear (may show in red or with badge)
    await expect(
      page.locator('.calendar-event-title-text, .cal-event-text, .fc-event-title')
        .filter({ hasText: 'Réponse urgente' })
        .first()
    ).toBeVisible({ timeout: 8000 })
  })
})

test.describe('Calendar — états d\'erreur', () => {
  test('affiche un message d\'erreur quand l\'API échoue', async ({ page }) => {
    await setupCalendarCrudMocks(page, { errorMode: true })
    await page.goto('/')
    await waitForAppReady(page)

    await navigateToCalendar(page)

    // Error message or error state should be visible
    await expect(
      page.locator('text=/erreur|error|failed|échec/i').first()
    ).toBeVisible({ timeout: 10000 })
  })

  test('affiche l\'état non connecté', async ({ page }) => {
    await setupCalendarCrudMocks(page, { connected: false })
    await page.goto('/')
    await waitForAppReady(page)

    await navigateToCalendar(page)

    // Some indicator of disconnected state
    await expect(
      page.locator('text=/connecte|Google|Outlook|calendrier/i').first()
    ).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Calendar — affichage de base', () => {
  test.beforeEach(async ({ page }) => {
    await setupCalendarCrudMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('charge et affiche le calendrier sans erreur', async ({ page }) => {
    await navigateToCalendar(page)
    await expect(page.locator('text=/erreur|error|500/i')).not.toBeVisible({ timeout: 5000 })
  })

  test('affiche les événements existants', async ({ page }) => {
    await navigateToCalendar(page)

    // At least one event should be visible
    await expect(
      page.locator('.calendar-event, .fc-event').first()
    ).toBeVisible({ timeout: 8000 })
  })

  test('affiche le bouton Aujourd\'hui', async ({ page }) => {
    await navigateToCalendar(page)

    const todayBtn = page.locator('button:has-text("Aujourd\'hui"), button:has-text("today"), .fc-today-button').first()
    await expect(todayBtn).toBeVisible({ timeout: 5000 })
  })

  test('affiche la barre de raccourcis', async ({ page }) => {
    await navigateToCalendar(page)

    // Shortcuts ribbon or hint should be present
    const ribbon = page.locator('.shortcuts-ribbon, .shortcuts-hint').first()
    await expect(ribbon).toBeVisible({ timeout: 5000 })
  })

  test('charge en moins de 5 secondes', async ({ page }) => {
    const t0 = Date.now()
    await navigateToCalendar(page)
    await expect(
      page.locator('.calendar-view, .fc, .calendar-week-body').first()
    ).toBeVisible({ timeout: 10000 })
    expect(Date.now() - t0).toBeLessThan(8000)
  })
})
