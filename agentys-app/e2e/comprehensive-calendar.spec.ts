/**
 * Comprehensive Calendar E2E Tests
 *
 * Tests complets : navigation, vues, événements, retour inbox, états.
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady, isApiRoute } from './support/fixtures/setup'

const now = new Date()
const mockEvents = [
  { id: 'evt-1', title: 'Réunion équipe', start: now.toISOString(), end: new Date(now.getTime() + 3600000).toISOString(), calendar_id: 'cal-1', color: '#6b7280' },
  { id: 'evt-2', title: 'Appel client important', start: new Date(now.getTime() + 7200000).toISOString(), end: new Date(now.getTime() + 10800000).toISOString(), calendar_id: 'cal-1', color: '#3b82f6' },
  { id: 'evt-3', title: 'Déjeuner partenaire', start: new Date(now.getTime() + 14400000).toISOString(), end: new Date(now.getTime() + 18000000).toISOString(), calendar_id: 'cal-1', color: '#10b981' },
]

async function setupCalendarMocks(page: Page, connected = true) {
  await setupBaseMocks(page)
  await page.route((url) => isApiRoute(url) && url.pathname === '/api/calendar/status', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(connected ? { connected: true, provider: 'google', email: 'test@example.com' } : { connected: false }) })
  })
  await page.route((url) => isApiRoute(url) && url.pathname === '/api/calendar/events', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ events: mockEvents, count: mockEvents.length }) })
  })
  await page.route((url) => isApiRoute(url) && url.pathname === '/api/calendar/today', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ events: mockEvents.slice(0, 2), count: 2 }) })
  })
  await page.route((url) => isApiRoute(url) && url.pathname === '/api/calendar/upcoming', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ events: mockEvents, count: mockEvents.length }) })
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
  await page.locator('.calendar-view, .fc, .calendar-week-body').first().waitFor({ state: 'visible', timeout: 10000 })
}

test.describe('Calendar — navigation et affichage', () => {
  test.beforeEach(async ({ page }) => { await setupCalendarMocks(page, true); await page.goto('/'); await waitForAppReady(page) })

  test('navigue vers le calendrier sans erreur', async ({ page }) => {
    await navigateToCalendar(page)
    await expect(page.locator('text=/erreur|error|500/i')).not.toBeVisible({ timeout: 5000 })
  })

  test('affiche la vue calendrier', async ({ page }) => {
    await navigateToCalendar(page)
    await expect(page.locator('.calendar-view, .fc').first()).toBeVisible({ timeout: 10000 })
  })

  test('affiche le bouton Aujourd\'hui', async ({ page }) => {
    await navigateToCalendar(page)
    const todayBtn = page.locator('button:has-text("Aujourd\'hui"), .fc-today-button').first()
    await expect(todayBtn).toBeVisible({ timeout: 5000 })
  })

  test('affiche les boutons de vue', async ({ page }) => {
    await navigateToCalendar(page)
    const viewBtns = page.locator('button:has-text("Mois"), button:has-text("Semaine"), button:has-text("Jour")')
    await expect(viewBtns.first()).toBeVisible({ timeout: 5000 })
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

  test('change de vue via raccourci clavier (7 → 1 → 3)', async ({ page }) => {
    await navigateToCalendar(page)
    // Main CalendarView uses keyboard shortcuts: 1=day, 3=3day, 7=week (no button toggles)
    await page.keyboard.press('1')
    await expect(page.locator('.calendar-view').first()).toBeVisible({ timeout: 5000 })
    await expect(page.locator('text=/erreur|error/i')).not.toBeVisible({ timeout: 3000 })

    await page.keyboard.press('3')
    await expect(page.locator('.calendar-view').first()).toBeVisible({ timeout: 5000 })
    await expect(page.locator('text=/erreur|error/i')).not.toBeVisible({ timeout: 3000 })
  })

  test('navigue semaine suivante/précédente via chevrons', async ({ page }) => {
    await navigateToCalendar(page)
    // Chevron buttons use class .calendar-chevron-btn and aria-label "Période suivante"/"Période précédente"
    const nextBtn = page.locator('.calendar-chevron-btn').nth(1)
    await expect(nextBtn).toBeVisible({ timeout: 5000 })
    await nextBtn.click()
    const prevBtn = page.locator('.calendar-chevron-btn').first()
    await prevBtn.click()
    await expect(page.locator('.calendar-view').first()).toBeVisible({ timeout: 5000 })
  })
})

test.describe('Calendar — état non connecté', () => {
  test.beforeEach(async ({ page }) => { await setupCalendarMocks(page, false); await page.goto('/'); await waitForAppReady(page) })

  test('affiche l\'état non connecté', async ({ page }) => {
    await navigateToCalendar(page)
    await expect(page.locator('text=/connecte|calendrier|Google/i').first()).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Calendar — performance', () => {
  test('charge le calendrier en moins de 5 secondes', async ({ page }) => {
    await setupCalendarMocks(page, true)
    await page.goto('/')
    await waitForAppReady(page)

    const t0 = Date.now()
    await navigateToCalendar(page)
    await expect(page.locator('.calendar-view, .fc').first()).toBeVisible({ timeout: 10000 })
    expect(Date.now() - t0).toBeLessThan(5000)
  })
})
