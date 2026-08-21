/**
 * Calendar E2E Tests
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady, isApiRoute } from './support/fixtures/setup'

const mockCalendarEvents = [
  { id: 'evt-1', title: 'Réunion équipe', start: new Date().toISOString(), end: new Date(Date.now() + 3600000).toISOString(), calendar_id: 'cal-1', color: '#6b7280' },
  { id: 'evt-2', title: 'Appel client', start: new Date(Date.now() + 7200000).toISOString(), end: new Date(Date.now() + 10800000).toISOString(), calendar_id: 'cal-1', color: '#3b82f6' },
]

async function setupCalendarMocks(page: Page, opts: { connected?: boolean } = { connected: true }) {
  await setupBaseMocks(page)
  await page.route((url) => isApiRoute(url) && url.pathname === '/api/calendar/status', (route) => {
    if (opts.connected) {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ connected: true, provider: 'google', email: 'test@example.com' }) })
    } else {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ connected: false }) })
    }
  })
  await page.route((url) => isApiRoute(url) && url.pathname === '/api/calendar/events', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ events: mockCalendarEvents, count: mockCalendarEvents.length }) })
  })
  await page.route((url) => isApiRoute(url) && url.pathname === '/api/calendar/today', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ events: mockCalendarEvents, count: mockCalendarEvents.length }) })
  })
  await page.route((url) => isApiRoute(url) && url.pathname === '/api/calendar/upcoming', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ events: mockCalendarEvents, count: mockCalendarEvents.length }) })
  })
  await page.route((url) => isApiRoute(url) && url.pathname === '/api/calendar/calendars', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ calendars: [{ id: 'cal-1', name: 'Mon calendrier', primary: true }] }) })
  })
  await page.route((url) => isApiRoute(url) && url.pathname === '/api/calendar/followups', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ followups: [] }) })
  })
}

async function navigateToCalendar(page: Page) {
  const calBtn = page.locator('[data-testid="nav-calendar"]').first()
  await expect(calBtn).toBeVisible({ timeout: 5000 })
  await calBtn.click()
  await page.locator('.calendar-view, .fc').first().waitFor({ state: 'visible', timeout: 10000 })
}

test.describe('Calendar — navigation', () => {
  test.beforeEach(async ({ page }) => { await setupCalendarMocks(page, { connected: true }); await page.goto('/'); await waitForAppReady(page) })

  test('navigue vers le calendrier sans erreur', async ({ page }) => {
    await navigateToCalendar(page)
    await expect(page.locator('text=/erreur|error|500/i')).not.toBeVisible({ timeout: 5000 })
  })

  test('affiche la vue calendrier', async ({ page }) => {
    await navigateToCalendar(page)
    await expect(page.locator('.calendar-view, .fc').first()).toBeVisible({ timeout: 10000 })
  })

  test('retour à l\'inbox depuis le calendrier', async ({ page }) => {
    await navigateToCalendar(page)
    // nav-inbox is only rendered when appMode === 'mail', use calendar close or sidebar mail icon
    const closeBtn = page.locator('.calendar-close-btn').first()
    const mailIcon = page.locator('.sidebar-item').first()
    const trigger = await closeBtn.isVisible().catch(() => false) ? closeBtn : mailIcon
    await trigger.click()
    await expect(page.locator('[data-testid="nav-inbox"]')).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Calendar — état non connecté', () => {
  test.beforeEach(async ({ page }) => { await setupCalendarMocks(page, { connected: false }); await page.goto('/'); await waitForAppReady(page) })

  test('affiche l\'état non connecté', async ({ page }) => {
    await navigateToCalendar(page)
    await expect(page.locator('text=/connecte|calendrier/i').first()).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Calendar — affichage connecté', () => {
  test.beforeEach(async ({ page }) => { await setupCalendarMocks(page, { connected: true }); await page.goto('/'); await waitForAppReady(page) })

  test('affiche le bouton Aujourd\'hui', async ({ page }) => {
    await navigateToCalendar(page)
    const todayBtn = page.locator('button:has-text("Aujourd\'hui"), .fc-today-button').first()
    await expect(todayBtn).toBeVisible({ timeout: 5000 })
  })

  test('affiche les boutons de vue (Mois/Semaine/Jour)', async ({ page }) => {
    await navigateToCalendar(page)
    const viewBtn = page.locator('button:has-text("Mois"), button:has-text("Semaine"), button:has-text("Jour")').first()
    await expect(viewBtn).toBeVisible({ timeout: 5000 })
  })

  test('affiche la légende des couleurs', async ({ page }) => {
    await navigateToCalendar(page)
    const legend = page.locator('text=/Événement|Follow-up|En retard/i').first()
    await expect(legend).toBeVisible({ timeout: 5000 })
  })
})
