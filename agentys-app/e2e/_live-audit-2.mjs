/**
 * Follow-up exploratory pass — closes gaps from run 1:
 *  1. search via the collapsed search icon + smart-search-input
 *  2. quick-event custom duration label (end at :45 → no preset match)
 *  3. spam folder skeleton: wait 12s, watch the /api response
 *  4. mobile viewport: full reload, check inbox layout + hamburger
 * READ-ONLY: no send/save/delete.
 */
import { chromium } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const OUT = 'C:/Users/Alexa/Desktop/agentys/tasks/audit-reports/live-audit-2026-06-09'
const steps = []
const consoleEvents = []
const netEvents = []
let currentStep = 'init'

const browser = await chromium.launch({ headless: true })
const ctx = await browser.newContext({ viewport: { width: 1600, height: 950 } })
const jwt = fs.readFileSync(path.join(OUT, '.jwt'), 'utf8').trim()
await ctx.addInitScript(token => { window.localStorage.setItem('agentys_jwt', token) }, jwt)
const page = await ctx.newPage()

page.on('console', m => { if (['error', 'warning'].includes(m.type())) consoleEvents.push({ step: currentStep, type: m.type(), text: m.text().slice(0, 500) }) })
page.on('pageerror', e => consoleEvents.push({ step: currentStep, type: 'pageerror', text: String(e).slice(0, 600) }))
page.on('response', r => { if (r.status() >= 400) netEvents.push({ step: currentStep, status: r.status(), url: r.url().slice(0, 180) }) })

async function shot(name) { await page.screenshot({ path: path.join(OUT, `F2-${name}.png`) }).catch(() => {}) }
async function step(name, fn) {
  currentStep = name
  try { const note = await fn(); steps.push({ name, ok: true, note: note ?? null }); console.log(`[OK]   ${name}${note ? ' — ' + note : ''}`) }
  catch (e) { await shot(`FAIL-${name}`); steps.push({ name, ok: false, error: String(e).slice(0, 300) }); console.log(`[FAIL] ${name}: ${String(e).slice(0, 160)}`) }
}
const tid = id => page.locator(`[data-testid="${id}"]`)

await step('load', async () => {
  await page.goto('http://localhost:1420/', { waitUntil: 'load', timeout: 60000 })
  await tid('nav-inbox').waitFor({ state: 'visible', timeout: 20000 })
  await page.waitForTimeout(2000)
})

// 1. Search via icon → smart-search-input
await step('search-via-icon', async () => {
  const input = tid('smart-search-input')
  if (!(await input.isVisible().catch(() => false))) {
    // collapsed: click the search icon in the list header
    const icon = page.locator('.smart-search-bar, .search-icon, [class*="search-trigger"], [aria-label*="echerch"], [title*="echerch"]').first()
    await icon.click({ timeout: 5000 })
    await page.waitForTimeout(600)
  }
  await input.waitFor({ state: 'visible', timeout: 5000 })
  await input.fill('test')
  await page.waitForTimeout(2500)
  await shot('search-results')
  const results = await tid('email-item').count()
  await input.fill('')
  await page.keyboard.press('Escape')
  return `results=${results}`
})

// 2. Spam skeleton — wait long, observe API
await step('spam-skeleton-12s', async () => {
  let spamResp = null
  const listener = r => { if (r.url().includes('spam') || r.url().includes('folder')) spamResp = `${r.status()} ${r.url().slice(0, 140)}` }
  page.on('response', listener)
  await tid('nav-spam').click()
  await page.waitForTimeout(12000)
  page.off('response', listener)
  await shot('spam-after-12s')
  const items = await tid('email-item').count()
  const skeletons = await page.locator('[class*="skeleton"], [class*="shimmer"]').count()
  return `items=${items} skeletons=${skeletons} resp=${spamResp}`
})

// 3. Calendar custom duration label
await step('qe-custom-duration-label', async () => {
  await tid('nav-calendar').first().click()
  await page.locator('.calendar-view, .fc, .calendar-week-body').first().waitFor({ state: 'visible', timeout: 10000 })
  await page.waitForTimeout(1500)
  await page.keyboard.press('c')
  const popover = page.locator('.qe-popover')
  await popover.waitFor({ state: 'visible', timeout: 5000 })
  // end minute := 45 → duration 1h45, matches no preset
  const endMin = page.locator('.qe-time-digit').nth(3)
  await endMin.click()
  await endMin.fill('45')
  await page.locator('.qe-title-input').click()
  await page.waitForTimeout(500)
  const label = await page.locator('.qe-duration-custom-label').textContent().catch(() => null)
  const activeChips = await page.locator('.qe-duration-preset.active').count()
  await shot('qe-custom-45')
  // also: wheel down on end hour should shrink duration
  await page.locator('.qe-cancel-btn').click()
  await popover.waitFor({ state: 'hidden', timeout: 3000 })
  return `customLabel=${JSON.stringify(label)} activeChips=${activeChips}`
})

// 4. Mobile: full reload at mobile size
await step('mobile-reload', async () => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('http://localhost:1420/', { waitUntil: 'load', timeout: 60000 })
  await page.waitForTimeout(4000)
  await shot('mobile-fresh-load')
  const navVisible = await tid('nav-inbox').isVisible().catch(() => false)
  const items = await tid('email-item').count()
  return `nav-inbox-visible=${navVisible} email-items=${items}`
})

// 5. Stats banner link
await step('stats-banner', async () => {
  await page.setViewportSize({ width: 1600, height: 950 })
  await page.goto('http://localhost:1420/', { waitUntil: 'load', timeout: 60000 })
  await tid('nav-inbox').waitFor({ state: 'visible', timeout: 20000 })
  await page.waitForTimeout(2000)
  const banner = page.locator('text=statistiques').first()
  if (await banner.isVisible().catch(() => false)) {
    await banner.click()
    await page.waitForTimeout(2000)
    await shot('stats-after-click')
    await page.keyboard.press('Escape')
    return 'clicked'
  }
  return 'banner not visible'
})

currentStep = 'done'
fs.writeFileSync(path.join(OUT, 'findings-2.json'), JSON.stringify({ steps, consoleEvents, netEvents }, null, 2))
console.log(`\n=== PASS 2 DONE: ${steps.filter(s => !s.ok).length} failed, ${consoleEvents.length} console, ${netEvents.length} net ===`)
await browser.close()
