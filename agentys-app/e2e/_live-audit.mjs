/**
 * Live exploratory audit — drives the REAL app (localhost:1420 → backend :5050)
 * like a real user, READ-ONLY discipline:
 *   - never clicks send / archive / delete / snooze / spam / unsubscribe
 *   - compose & reply are opened, typed into, then closed (fields cleared first)
 *   - calendar quick-event popover is exercised then CANCELLED, never saved
 *   - settings tabs are opened and screenshotted, no toggles flipped
 * Captures: console errors/warnings, page errors, HTTP >= 400, failed requests,
 * per-step results + screenshots.
 *
 * Run: node e2e/_live-audit.mjs   (from agentys-app, dev server already up)
 */
import { chromium } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const OUT = 'C:/Users/Alexa/Desktop/agentys/tasks/audit-reports/live-audit-2026-06-09'
fs.mkdirSync(OUT, { recursive: true })

const steps = []
const consoleEvents = []
const netEvents = []
let currentStep = 'init'

const browser = await chromium.launch({ headless: true })
const ctx = await browser.newContext({ viewport: { width: 1600, height: 950 } })

// Authenticate: JWT minted via /api/auth/dev-login (localhost-only) for the
// real user — the app reads it from localStorage key `agentys_jwt`.
const jwt = fs.readFileSync(path.join(OUT, '.jwt'), 'utf8').trim()
await ctx.addInitScript(token => {
  window.localStorage.setItem('agentys_jwt', token)
}, jwt)

const page = await ctx.newPage()

page.on('console', m => {
  const type = m.type()
  if (type === 'error' || type === 'warning') {
    consoleEvents.push({ step: currentStep, type, text: m.text().slice(0, 600) })
  }
})
page.on('pageerror', e => {
  consoleEvents.push({ step: currentStep, type: 'pageerror', text: String(e).slice(0, 800) })
})
page.on('response', r => {
  if (r.status() >= 400) {
    netEvents.push({ step: currentStep, status: r.status(), method: r.request().method(), url: r.url().slice(0, 200) })
  }
})
page.on('requestfailed', r => {
  netEvents.push({ step: currentStep, status: 'NET-FAIL', err: r.failure()?.errorText, method: r.method(), url: r.url().slice(0, 200) })
})

let shotIdx = 0
async function shot(name) {
  shotIdx++
  const file = `${String(shotIdx).padStart(2, '0')}-${name}.png`
  await page.screenshot({ path: path.join(OUT, file) }).catch(() => {})
  return file
}

async function step(name, fn) {
  currentStep = name
  const t0 = Date.now()
  try {
    const note = await fn()
    steps.push({ name, ok: true, ms: Date.now() - t0, note: note ?? null })
    console.log(`[OK]   ${name} (${Date.now() - t0}ms)${note ? ' — ' + note : ''}`)
  } catch (e) {
    const file = await shot(`FAIL-${name}`)
    steps.push({ name, ok: false, ms: Date.now() - t0, error: String(e).slice(0, 400), screenshot: file })
    console.log(`[FAIL] ${name}: ${String(e).slice(0, 200)}`)
  }
}

const tid = id => page.locator(`[data-testid="${id}"]`)

// ---------- 1. Load app ----------
await step('load-app', async () => {
  await page.goto('http://localhost:1420/', { waitUntil: 'load', timeout: 60000 })
  await tid('nav-inbox').waitFor({ state: 'visible', timeout: 20000 })
  await page.waitForTimeout(2500)
  await shot('inbox-initial')
})

// ---------- 2. Inbox list ----------
await step('inbox-list', async () => {
  const items = tid('email-item')
  await items.first().waitFor({ state: 'visible', timeout: 15000 })
  const count = await items.count()
  return `${count} emails visible`
})

// ---------- 3. Open first email ----------
await step('open-email-1', async () => {
  await tid('email-item').first().click()
  await page.waitForTimeout(2000)
  await shot('email-detail')
  const hasReply = await tid('reply-button').first().isVisible().catch(() => false)
  const bodyVisible = await page.locator('.email-body, .email-detail-body, iframe').first().isVisible().catch(() => false)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(800)
  return `reply-button=${hasReply} body=${bodyVisible}`
})

// ---------- 4. Open second email ----------
await step('open-email-2', async () => {
  const items = tid('email-item')
  if (await items.count() > 1) {
    await items.nth(1).click()
    await page.waitForTimeout(1800)
    await shot('email-detail-2')
    await page.keyboard.press('Escape')
    await page.waitForTimeout(600)
  }
})

// ---------- 5. Search ----------
await step('search', async () => {
  const search = page.locator('[data-testid="search-input"], input[type="search"], input[placeholder*="echerch"], input[placeholder*="earch"]').first()
  await search.waitFor({ state: 'visible', timeout: 5000 })
  await search.click()
  await search.fill('facture')
  await page.waitForTimeout(2500)
  await shot('search-facture')
  await search.fill('')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(500)
})

// ---------- 6. Folder walk ----------
for (const folder of ['drafts', 'snoozed', 'sent', 'archived', 'spam', 'trash']) {
  await step(`folder-${folder}`, async () => {
    const nav = tid(`nav-${folder}`)
    await nav.waitFor({ state: 'visible', timeout: 5000 })
    await nav.click()
    await page.waitForTimeout(2200)
    await shot(`folder-${folder}`)
    const count = await tid('email-item').count().catch(() => -1)
    const emptyState = await page.locator('.empty-state, [class*="empty"]').first().isVisible().catch(() => false)
    return `items=${count} empty-state=${emptyState}`
  })
}

// ---------- 7. Back to inbox ----------
await step('back-to-inbox', async () => {
  await tid('nav-inbox').click()
  await page.waitForTimeout(1500)
})

// ---------- 8. Compose (no send) ----------
await step('compose-open', async () => {
  await tid('compose-button').click()
  const modal = tid('new-message-modal')
  await modal.waitFor({ state: 'visible', timeout: 8000 })
  await page.waitForTimeout(800)
  await shot('compose-modal')
})

await step('compose-type-and-close', async () => {
  // Type in whatever field is focused / find recipient + subject inputs
  const to = page.locator('[data-testid="new-message-modal"] input').first()
  await to.fill('cours.universite@gmail.com').catch(() => {})
  const subject = page.locator('[data-testid="new-message-modal"] input[placeholder*="bjet"], [data-testid="new-message-modal"] input[placeholder*="ubject"]').first()
  await subject.fill('Audit test — do not send').catch(() => {})
  await page.waitForTimeout(400)
  await shot('compose-filled')
  // Clear fields so no stray draft persists, then close
  await subject.fill('').catch(() => {})
  await to.fill('').catch(() => {})
  await page.keyboard.press('Escape')
  await page.waitForTimeout(800)
  await shot('compose-after-close')
  // If a confirm dialog appeared, capture it and close it with Escape
  const modalStillOpen = await tid('new-message-modal').isVisible().catch(() => false)
  if (modalStillOpen) {
    await page.keyboard.press('Escape')
    await page.waitForTimeout(600)
  }
  return `modalStillOpen=${modalStillOpen}`
})

// ---------- 9. Reply (no send) ----------
await step('reply-open-close', async () => {
  await tid('nav-inbox').click()
  await page.waitForTimeout(1200)
  await tid('email-item').first().click()
  await page.waitForTimeout(1500)
  const reply = tid('reply-button').first()
  await reply.waitFor({ state: 'visible', timeout: 6000 })
  await reply.click()
  await page.waitForTimeout(2000)
  await shot('reply-composer')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(800)
  const escaped = !(await page.locator('.reply-composer, [data-testid="pending-draft-detail"]').first().isVisible().catch(() => false))
  await page.keyboard.press('Escape')
  await page.waitForTimeout(500)
  return `closedWithEscape=${escaped}`
})

// ---------- 10. Calendar ----------
await step('calendar-open', async () => {
  await tid('nav-calendar').first().click()
  await page.locator('.calendar-view, .fc, .calendar-week-body').first().waitFor({ state: 'visible', timeout: 10000 })
  await page.waitForTimeout(2000)
  await shot('calendar-default')
})

await step('calendar-quick-event-popover', async () => {
  await page.keyboard.press('c')
  const popover = page.locator('.qe-popover')
  const visible = await popover.waitFor({ state: 'visible', timeout: 3000 }).then(() => true, () => false)
  if (!visible) await page.keyboard.press('b')
  await popover.waitFor({ state: 'visible', timeout: 5000 })
  await page.waitForTimeout(600)
  await shot('qe-popover-initial')

  const checks = {}
  // New UI: duration presets
  checks.presets = await page.locator('.qe-duration-preset').count()
  checks.activePreset = await page.locator('.qe-duration-preset.active').textContent().catch(() => null)
  // New UI: boxed date field
  checks.dateField = await page.locator('.qe-date-field').count()
  // New UI: editable end time (2 start + 2 end = 4 time digits)
  checks.timeDigits = await page.locator('.qe-time-digit').count()
  // New UI: cancel button
  checks.cancelBtn = await page.locator('.qe-cancel-btn').count()
  // Save disabled style when title empty
  checks.saveDisabled = await page.locator('.qe-save-btn').isDisabled().catch(() => null)
  checks.saveBg = await page.locator('.qe-save-btn').evaluate(el => getComputedStyle(el).backgroundColor).catch(() => null)

  // Click 2h preset → end time should move
  const startVals = await page.locator('.qe-time-digit').evaluateAll(els => els.map(e => e.value))
  await page.locator('.qe-duration-preset', { hasText: '2h' }).click().catch(() => {})
  await page.waitForTimeout(400)
  const after2h = await page.locator('.qe-time-digit').evaluateAll(els => els.map(e => e.value))
  checks.timesBefore = startVals.join(':')
  checks.timesAfter2h = after2h.join(':')
  await shot('qe-popover-2h-preset')

  // Type a custom end time → custom label should appear
  const endHour = page.locator('.qe-time-digit').nth(2)
  await endHour.fill('').catch(() => {})
  await endHour.fill(String((parseInt(after2h[0]) + 1) % 24).padStart(2, '0')).catch(() => {})
  await page.locator('.qe-title-input').click() // blur commits
  await page.waitForTimeout(400)
  checks.customLabel = await page.locator('.qe-duration-custom-label').textContent().catch(() => null)
  await shot('qe-popover-custom-end')

  // Type a title → save becomes enabled (visual check)
  await page.locator('.qe-title-input').fill('audit visual check')
  await page.waitForTimeout(300)
  checks.saveEnabledAfterTitle = !(await page.locator('.qe-save-btn').isDisabled().catch(() => true))
  checks.saveBgEnabled = await page.locator('.qe-save-btn').evaluate(el => getComputedStyle(el).backgroundColor).catch(() => null)
  await shot('qe-popover-title-filled')

  // CANCEL — never save (real backend!)
  await page.locator('.qe-cancel-btn').click()
  await popover.waitFor({ state: 'hidden', timeout: 3000 })
  return JSON.stringify(checks)
})

await step('calendar-view-toggles', async () => {
  const toggles = page.locator('.calendar-view-toggle-btn, .calendar-view-selector-btn')
  const n = await toggles.count()
  for (let i = 0; i < Math.min(n, 4); i++) {
    await toggles.nth(i).click().catch(() => {})
    await page.waitForTimeout(1200)
    await shot(`calendar-toggle-${i}`)
  }
  return `${n} view toggles`
})

// ---------- 11. Settings — every tab ----------
await step('settings-open', async () => {
  await tid('nav-settings').click()
  await tid('settings-modal').waitFor({ state: 'visible', timeout: 8000 })
  await page.waitForTimeout(800)
  await shot('settings-initial')
})

await step('settings-tabs', async () => {
  // Tabs are buttons inside the modal nav — enumerate them
  const tabs = page.locator('[data-testid="settings-modal"] [role="tab"], [data-testid="settings-modal"] .settings-nav button, [data-testid="settings-modal"] [class*="tab"]')
  let n = await tabs.count()
  if (n === 0) {
    // fallback: any button in left rail of modal
    n = 0
  }
  const visited = []
  for (let i = 0; i < Math.min(n, 14); i++) {
    const label = (await tabs.nth(i).textContent().catch(() => ''))?.trim().slice(0, 30)
    await tabs.nth(i).click().catch(() => {})
    await page.waitForTimeout(900)
    await shot(`settings-tab-${i}`)
    visited.push(label)
  }
  return `tabs: ${visited.join(' | ')}`
})

await step('settings-close', async () => {
  await page.keyboard.press('Escape')
  await page.waitForTimeout(600)
})

// ---------- 12. Command palette + shortcuts help ----------
await step('command-palette', async () => {
  await page.keyboard.press('Control+k')
  await page.waitForTimeout(900)
  await shot('command-palette')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)
})

await step('shortcuts-help', async () => {
  await page.keyboard.press('Control+/')
  await page.waitForTimeout(900)
  await shot('shortcuts-help')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(400)
})

// ---------- 13. Support + learning ----------
await step('support-panel', async () => {
  await tid('nav-support').click()
  await page.waitForTimeout(1500)
  await shot('support-panel')
  await page.keyboard.press('Escape')
})

await step('learning-view', async () => {
  const nav = tid('nav-learning')
  if (await nav.isVisible().catch(() => false)) {
    await nav.click()
    await page.waitForTimeout(1800)
    await shot('learning-view')
  } else {
    return 'nav-learning not visible'
  }
})

// ---------- 14. Mobile viewport sanity ----------
await step('mobile-viewport', async () => {
  await page.setViewportSize({ width: 390, height: 844 })
  await tid('nav-inbox').click().catch(() => {})
  await page.waitForTimeout(2000)
  await shot('mobile-inbox')
  await page.setViewportSize({ width: 1600, height: 950 })
  await page.waitForTimeout(800)
})

// ---------- Save results ----------
currentStep = 'done'
const result = { startedAt: new Date().toISOString(), steps, consoleEvents, netEvents }
fs.writeFileSync(path.join(OUT, 'findings.json'), JSON.stringify(result, null, 2))
console.log(`\n=== AUDIT DONE: ${steps.filter(s => !s.ok).length} failed steps, ${consoleEvents.length} console events, ${netEvents.length} net events ===`)
console.log(`Results: ${OUT}`)

await browser.close()
