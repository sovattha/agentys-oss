/**
 * LIVE REAL-USER AUDIT — 2026-05-30
 *
 * Drives the app at localhost:1420 against the REAL backend (real account data:
 * real emails, real calendar events, real settings) so flows behave like a real
 * user's. SAFETY: every mutating request (POST/PUT/PATCH/DELETE to /api/*) is
 * intercepted and answered locally — nothing is actually sent / created / deleted
 * on the user's real Gmail/Outlook/Calendar. Dedicated tests inject 500s on the
 * mutation path to verify the UI surfaces failures instead of swallowing them.
 *
 * Inert unless AGENTYS_LIVE_AUDIT=1 (so normal `playwright test` runs skip it).
 * Run: AGENTYS_LIVE_AUDIT=1 npx playwright test audit-realuser-20260530 --workers=1
 */
import { test, expect, Page, APIRequestContext } from '@playwright/test'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const LIVE = !!process.env.AGENTYS_LIVE_AUDIT
const REPORT_DIR = path.resolve(__dirname, '../../tasks/audit-reports/2026-05-30_1346_e2e')
const SHOTS = path.join(REPORT_DIR, 'screenshots')

test.skip(!LIVE, 'live audit only — set AGENTYS_LIVE_AUDIT=1')

type Obs = {
  scenario: string
  consoleErrors: string[]
  pageErrors: string[]
  netFailures: { url: string; status: number; method: string }[]
  notes: string[]
}
const observations: Obs[] = []
let shotIdx = 0

async function getToken(request: APIRequestContext): Promise<string> {
  const r = await request.post('/api/auth/dev-login', {
    data: { email: 'audit@agentys.local' },
    headers: { 'Content-Type': 'application/json' },
  })
  const j = await r.json()
  return j.access_token
}

/** Intercept ALL mutations; let reads hit the real backend. */
async function installSafetyNet(page: Page) {
  await page.route('**/api/**', (route) => {
    const m = route.request().method()
    if (m === 'GET' || m === 'HEAD') return route.continue()
    // Block real mutations with a generic success-shaped body.
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, intercepted: true, message_id: 'audit-mock', id: 'audit-mock' }),
    })
  })
}

function attach(page: Page, obs: Obs) {
  page.on('console', (msg) => {
    const t = msg.type()
    if (t === 'error') obs.consoleErrors.push(msg.text().slice(0, 300))
  })
  page.on('pageerror', (err) => obs.pageErrors.push(String(err).slice(0, 300)))
  page.on('response', (resp) => {
    const s = resp.status()
    const u = resp.url()
    if (s >= 400 && u.includes('/api/')) {
      obs.netFailures.push({ url: u.replace(/https?:\/\/[^/]+/, ''), status: s, method: resp.request().method() })
    }
  })
}

async function snap(page: Page, name: string) {
  const file = path.join(SHOTS, `${String(++shotIdx).padStart(2, '0')}-${name}.png`)
  try { await page.screenshot({ path: file, fullPage: false }) } catch { /* ignore */ }
}

async function boot(page: Page, request: APIRequestContext, obs: Obs) {
  const token = await getToken(request)
  await page.addInitScript((tok) => {
    localStorage.setItem('agentys_jwt', tok as string)
    localStorage.setItem('agentys_onboarding_complete', 'true')
    localStorage.setItem('agentys_onboarding_kb_complete', 'true')
    localStorage.setItem('agentys_onboarding_v2_complete', 'true')
    localStorage.setItem('agentys_language', 'fr')
  }, token)
  attach(page, obs)
  await installSafetyNet(page)
  await page.goto('/')
  // Shell readiness: sidebar/app-main render once authenticated & out of wizard.
  await page.locator('[data-testid="sidebar"], [data-testid="app-main"]').first()
    .waitFor({ state: 'visible', timeout: 25000 }).catch(() => {})
  await page.waitForTimeout(2500) // let real backend reads (emails/calendar) settle
  const navIds = await page.locator('[data-testid^="nav-"]')
    .evaluateAll((els) => els.map((e) => e.getAttribute('data-testid'))).catch(() => [])
  obs.notes.push(`nav testids present: [${navIds.join(', ')}]`)
}

async function shellReady(page: Page) {
  await page.locator('[data-testid="sidebar"], [data-testid="app-main"]').first()
    .waitFor({ state: 'visible', timeout: 25000 }).catch(() => {})
}

function mkObs(scenario: string): Obs {
  const o: Obs = { scenario, consoleErrors: [], pageErrors: [], netFailures: [], notes: [] }
  observations.push(o)
  return o
}

// ---------------------------------------------------------------------------

test('A — boot + real inbox loads', async ({ page, request }) => {
  const obs = mkObs('A:boot+inbox')
  await boot(page, request, obs)
  const shell = await page.locator('[data-testid="sidebar"], [data-testid="app-main"]').first().isVisible().catch(() => false)
  const navInbox = await page.locator('[data-testid="nav-inbox"]').isVisible().catch(() => false)
  obs.notes.push(`shell visible=${shell}, nav-inbox visible=${navInbox}`)
  expect.soft(shell, 'app reaches main shell').toBe(true)
  // wait for real emails to load before counting
  await page.locator('[data-testid="email-item"]').first().waitFor({ state: 'visible', timeout: 12000 }).catch(() => {})
  const emailCount = await page.locator('[data-testid="email-item"]').count().catch(() => 0)
  obs.notes.push(`email-item count = ${emailCount}`)
  await snap(page, 'inbox')
})

test('B — calendar: views, navigation, event open, create UI', async ({ page, request }) => {
  const obs = mkObs('B:calendar')
  await boot(page, request, obs)
  await shellReady(page)
  const calBtn = page.locator('[data-testid="nav-calendar"]').first()
  const calVisible = await calBtn.isVisible({ timeout: 8000 }).catch(() => false)
  obs.notes.push(`nav-calendar visible = ${calVisible}`)
  if (!calVisible) { await snap(page, 'calendar-no-nav'); return }
  await calBtn.click()
  const viewShown = await page.locator('.calendar-view, .fc, .calendar-week-body').first()
    .isVisible({ timeout: 12000 }).catch(() => false)
  obs.notes.push(`calendar view rendered = ${viewShown}`)
  await snap(page, 'calendar-default')

  // view shortcuts 1 (day) / 3 (3-day) / 7 (week)
  for (const key of ['1', '3', '7']) {
    await page.keyboard.press(key).catch(() => {})
    await page.waitForTimeout(400)
    const stillOk = await page.locator('.calendar-view, .fc').first().isVisible().catch(() => false)
    obs.notes.push(`view key ${key}: view visible=${stillOk}`)
  }
  await snap(page, 'calendar-week')

  // period chevrons
  const chevrons = page.locator('.calendar-chevron-btn')
  if (await chevrons.count() >= 2) {
    await chevrons.nth(1).click().catch(() => {})
    await page.waitForTimeout(300)
    await chevrons.first().click().catch(() => {})
    obs.notes.push('chevron next/prev clicked')
  } else obs.notes.push('chevron buttons not found')

  // open an existing real event if any
  const evt = page.locator('.calendar-event, .fc-event, [class*="event"]').first()
  if (await evt.isVisible({ timeout: 3000 }).catch(() => false)) {
    await evt.click().catch(() => {})
    await page.waitForTimeout(600)
    await snap(page, 'calendar-event-open')
    obs.notes.push('clicked an existing event')
    await page.keyboard.press('Escape').catch(() => {})
  } else obs.notes.push('no rendered event tile found to click')
})

test('B2 — calendar: create event with 500 injection (silent-failure probe)', async ({ page, request }) => {
  const obs = mkObs('B2:calendar-create-500')
  await boot(page, request, obs)
  await shellReady(page)
  const calBtn = page.locator('[data-testid="nav-calendar"]').first()
  if (!(await calBtn.isVisible({ timeout: 8000 }).catch(() => false))) { obs.notes.push('no calendar nav'); return }
  await calBtn.click()
  await page.locator('.calendar-view, .fc').first().isVisible({ timeout: 12000 }).catch(() => {})
  // Force calendar create endpoints to 500 (overrides safety net via LIFO).
  await page.route((u) => u.pathname.startsWith('/api/calendar/') && u.pathname.includes('event'), (route) => {
    if (route.request().method() === 'GET') return route.continue()
    return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: 'injected 500' }) })
  })
  // Try a quick-create entry point if present.
  const createBtn = page.locator('button:has-text("Créer"), button:has-text("Nouvel"), .calendar-create-btn, [data-testid="calendar-create"]').first()
  if (await createBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await createBtn.click().catch(() => {})
    await page.waitForTimeout(800)
    await snap(page, 'calendar-create-form')
    obs.notes.push('opened create UI')
  } else {
    obs.notes.push('no obvious calendar create button — skipped create submit')
  }
})

test('C — settings: visit ALL 6 sections + screenshot each', async ({ page, request }) => {
  const obs = mkObs('C:settings-all-sections')
  await boot(page, request, obs)
  await shellReady(page)
  await page.locator('[data-testid="nav-settings"]').first().click().catch(() => {})
  const modal = page.locator('.settings-modal, [data-testid="settings-modal"]').first()
  const opened = await modal.isVisible({ timeout: 8000 }).catch(() => false)
  obs.notes.push(`settings modal opened = ${opened}`)
  if (!opened) { await snap(page, 'settings-failed-open'); return }
  const items = page.locator('.settings-sidebar-item')
  const n = await items.count()
  obs.notes.push(`settings sidebar items = ${n}`)
  for (let i = 0; i < n; i++) {
    const label = (await items.nth(i).innerText().catch(() => `section-${i}`)).replace(/\s+/g, ' ').trim().slice(0, 24)
    await items.nth(i).click().catch(() => {})
    await page.waitForTimeout(500)
    const boundaryErr = await page.locator('text=/Une erreur|something went wrong|section indisponible/i').first()
      .isVisible({ timeout: 800 }).catch(() => false)
    obs.notes.push(`section "${label}": errorBoundary=${boundaryErr}`)
    if (boundaryErr) obs.notes.push(`!! SECTION CRASH in "${label}"`)
    await snap(page, `settings-${i}-${label.replace(/[^a-z0-9]/gi, '_')}`)
  }
})

test('C2 — settings: toggle with 500 injection (silent-failure probe)', async ({ page, request }) => {
  const obs = mkObs('C2:settings-toggle-500')
  await boot(page, request, obs)
  await shellReady(page)
  await page.locator('[data-testid="nav-settings"]').first().click().catch(() => {})
  if (!(await page.locator('.settings-modal').first().isVisible({ timeout: 8000 }).catch(() => false))) { obs.notes.push('settings not open'); return }
  // Force settings writes to 500.
  await page.route((u) => u.pathname === '/api/settings', (route) => {
    if (route.request().method() === 'GET') return route.continue()
    return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: 'injected 500' }) })
  })
  // Go to Automation section (has toggles).
  await page.locator('.settings-sidebar-item', { hasText: /Automat/i }).first().click().catch(() => {})
  await page.waitForTimeout(500)
  const toggle = page.locator('.settings-toggle').first()
  if (await toggle.isVisible({ timeout: 4000 }).catch(() => false)) {
    await toggle.click().catch(() => {})
    await page.waitForTimeout(1200)
    const toastShown = await page.locator('.toast-container .toast, [class*="toast"]').first().isVisible({ timeout: 1500 }).catch(() => false)
    obs.notes.push(`toggle->500: error feedback visible = ${toastShown} (false => candidate silent failure)`)
    await snap(page, 'settings-toggle-500')
  } else obs.notes.push('no toggle found in automation section')
})

test('D — reply: open real email, reply UI, send with 500 injection', async ({ page, request }) => {
  const obs = mkObs('D:reply')
  await boot(page, request, obs)
  await shellReady(page)
  const items = page.locator('[data-testid="email-item"]')
  await items.first().waitFor({ state: 'visible', timeout: 15000 }).catch(() => {})
  const cnt = await items.count().catch(() => 0)
  obs.notes.push(`inbox email-item count = ${cnt}`)
  if (cnt === 0) { obs.notes.push('inbox empty — cannot test reply on real email'); await snap(page, 'reply-empty-inbox'); return }
  await items.first().click().catch(() => {})
  const detailShown = await page.locator('.email-detail-body, .email-detail-title').first().isVisible({ timeout: 12000 }).catch(() => false)
  obs.notes.push(`email detail rendered = ${detailShown}`)
  await snap(page, 'email-detail')
  // Open reply
  await page.keyboard.press('r').catch(() => {})
  const composer = page.locator('[data-testid="reply-composer"], .reply-composer').first()
  const rcShown = await composer.isVisible({ timeout: 10000 }).catch(() => false)
  obs.notes.push(`reply composer opened = ${rcShown}`)
  await snap(page, 'reply-composer')
  if (!rcShown) return
  // Inject 500 on all send endpoints
  await page.route((u) => /\/api\/emails\/send-reply$|\/api\/pending-drafts\/[^/]+\/validate$|\/api\/emails\/[^/]+\/reply$/.test(u.pathname), (route) => {
    if (route.request().method() === 'GET') return route.continue()
    return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: 'injected 500' }) })
  })
  // Type something into the body editor if present
  const body = page.locator('.gmail-textarea, .reply-composer [contenteditable="true"], .rc-editor [contenteditable="true"]').first()
  if (await body.isVisible({ timeout: 2000 }).catch(() => false)) { await body.click().catch(() => {}); await body.type('Merci, je reviens vers vous. (audit)').catch(() => {}) }
  const sendBtn = page.locator('[data-testid="reply-send-button"], .reply-composer .send-pill').first()
  if (await sendBtn.isVisible({ timeout: 3000 }).catch(() => false) && await sendBtn.isEnabled().catch(() => false)) {
    await sendBtn.click().catch(() => {})
    await page.waitForTimeout(1500)
    const errShown = await page.locator('.toast-container .toast, [class*="toast"], text=/échou|erreur|failed|réessay/i').first().isVisible({ timeout: 2000 }).catch(() => false)
    obs.notes.push(`reply send->500: error feedback visible = ${errShown} (false => candidate silent failure)`)
    await snap(page, 'reply-send-500')
  } else obs.notes.push('reply send button not enabled/visible — could not test 500 path')
})

test('E — compose: new message form, invalid recipient, send 500, escape', async ({ page, request }) => {
  const obs = mkObs('E:compose')
  await boot(page, request, obs)
  await shellReady(page)
  await page.locator('body').click({ position: { x: 12, y: 12 } }).catch(() => {})
  await page.keyboard.press('n').catch(() => {})
  const modal = page.locator('.new-message-modal').first()
  let open = await modal.isVisible({ timeout: 6000 }).catch(() => false)
  if (!open) {
    await page.locator('[data-testid="compose-button"]').first().click().catch(() => {})
    open = await modal.isVisible({ timeout: 6000 }).catch(() => false)
  }
  obs.notes.push(`compose modal opened = ${open}`)
  if (!open) { await snap(page, 'compose-failed-open'); return }
  await snap(page, 'compose-open')
  // Send disabled with no recipient
  const sendPill = page.locator('.new-message-modal .send-pill').first()
  obs.notes.push(`send disabled w/o recipient = ${await sendPill.isDisabled().catch(() => 'n/a')}`)
  // Fill fields
  await page.locator('.new-message-modal .gmail-input').first().fill('not-an-email').catch(() => {})
  const subj = page.getByRole('textbox', { name: /objet/i }).first()
  await subj.fill('Audit E2E (intercepté)').catch(() => {})
  await page.locator('.new-message-modal .gmail-textarea').first().fill('Corps de test audit.').catch(() => {})
  await page.waitForTimeout(400)
  obs.notes.push(`send enabled after invalid recipient "not-an-email" = ${await sendPill.isEnabled().catch(() => 'n/a')} (true => no client-side email validation)`)
  await snap(page, 'compose-invalid-recipient')
  // Now valid recipient + inject 500 on compose send
  await page.locator('.new-message-modal .gmail-input').first().fill('').catch(() => {})
  await page.locator('.new-message-modal .gmail-input').first().fill('audit@agentys.local').catch(() => {})
  await page.route((u) => u.pathname === '/api/emails/compose' || u.pathname === '/api/emails/send', (route) => {
    if (route.request().method() === 'GET') return route.continue()
    return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: 'injected 500' }) })
  })
  await page.waitForTimeout(300)
  if (await sendPill.isEnabled().catch(() => false)) {
    await sendPill.click().catch(() => {})
    await page.waitForTimeout(1500)
    const errShown = await page.locator('.toast-container .toast, [class*="toast"], text=/échou|erreur|failed|réessay/i').first().isVisible({ timeout: 2000 }).catch(() => false)
    obs.notes.push(`compose send->500: error feedback visible = ${errShown} (false => candidate silent failure)`)
    await snap(page, 'compose-send-500')
  } else obs.notes.push('compose send not enabled — could not test 500 path')
  // Escape with content => expect close or discard confirm
  await page.keyboard.press('Escape').catch(() => {})
  await page.waitForTimeout(800)
  const stillOpen = await modal.isVisible().catch(() => false)
  obs.notes.push(`after Escape with content: modal still open = ${stillOpen}`)
  await snap(page, 'compose-after-escape')
})

test('F — archive with 500 injection (known #325 area)', async ({ page, request }) => {
  const obs = mkObs('F:archive-500')
  await boot(page, request, obs)
  await shellReady(page)
  const items = page.locator('[data-testid="email-item"]')
  await items.first().waitFor({ state: 'visible', timeout: 15000 }).catch(() => {})
  if (await items.count().catch(() => 0) === 0) { obs.notes.push('inbox empty'); return }
  await page.route((u) => /\/api\/emails\/[^/]+\/archive$|\/api\/emails\/archive$/.test(u.pathname), (route) => {
    if (route.request().method() === 'GET') return route.continue()
    return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: 'injected 500' }) })
  })
  await items.first().hover().catch(() => {})
  const archiveBtn = page.locator('[data-testid="archive-button"], button[aria-label*="rchiv"], .email-archive-btn').first()
  if (await archiveBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await archiveBtn.click().catch(() => {})
    await page.waitForTimeout(1500)
    const errShown = await page.locator('.toast-container .toast, [class*="toast"], text=/échou|erreur|failed|réessay/i').first().isVisible({ timeout: 2000 }).catch(() => false)
    const stillThere = await items.count().catch(() => 0)
    obs.notes.push(`archive->500: error feedback=${errShown}, items remaining=${stillThere} (no error + item gone => optimistic, silent)`)
    await snap(page, 'archive-500')
  } else obs.notes.push('archive affordance not found on hover')
})

test.afterAll(async () => {
  try {
    fs.mkdirSync(REPORT_DIR, { recursive: true })
    fs.writeFileSync(path.join(REPORT_DIR, 'live-observations.json'), JSON.stringify(observations, null, 2))
  } catch (e) { console.error('failed to write observations', e) }
})
