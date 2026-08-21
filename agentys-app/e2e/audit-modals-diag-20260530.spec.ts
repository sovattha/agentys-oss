/**
 * MODAL-OPEN DIAGNOSTIC — classify real bug vs harness artifact for the
 * settings / reply / compose modals that failed to open in the live audit.
 * Real backend reads, mutations intercepted. Inert unless AGENTYS_LIVE_AUDIT=1.
 * Run: AGENTYS_LIVE_AUDIT=1 npx playwright test audit-modals-diag-20260530 --workers=1
 */
import { test, Page, APIRequestContext } from '@playwright/test'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const LIVE = !!process.env.AGENTYS_LIVE_AUDIT
const REPORT_DIR = path.resolve(__dirname, '../../tasks/audit-reports/2026-05-30_1346_e2e')
const SHOTS = path.join(REPORT_DIR, 'screenshots')
test.skip(!LIVE, 'live audit only')

const diag: Record<string, unknown>[] = []

async function boot(page: Page, request: APIRequestContext) {
  const r = await request.post('/api/auth/dev-login', { data: { email: 'audit@agentys.local' }, headers: { 'Content-Type': 'application/json' } })
  const token = (await r.json()).access_token
  await page.addInitScript((tok) => {
    localStorage.setItem('agentys_jwt', tok as string)
    localStorage.setItem('agentys_onboarding_complete', 'true')
    localStorage.setItem('agentys_onboarding_kb_complete', 'true')
    localStorage.setItem('agentys_onboarding_v2_complete', 'true')
    localStorage.setItem('agentys_language', 'fr')
  }, token)
  await page.route('**/api/**', (route) => {
    const m = route.request().method()
    if (m === 'GET' || m === 'HEAD') return route.continue()
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, id: 'mock' }) })
  })
  await page.goto('/')
  await page.locator('[data-testid="sidebar"], [data-testid="app-main"]').first().waitFor({ state: 'visible', timeout: 25000 }).catch(() => {})
  await page.waitForTimeout(2500)
}

/** Snapshot of every overlay/portal-ish element currently in the DOM. */
async function domState(page: Page) {
  return await page.evaluate(() => {
    const sel = (s: string) => document.querySelectorAll(s).length
    const topMost = (() => {
      try {
        const el = document.elementFromPoint(window.innerWidth / 2, window.innerHeight / 2)
        return el ? `${el.tagName}.${(el.className || '').toString().slice(0, 40)}` : 'none'
      } catch { return 'err' }
    })()
    return {
      newMessageModal: sel('.new-message-modal'),
      settingsModal: sel('.settings-modal'),
      settingsModalTestid: sel('[data-testid="settings-modal"]'),
      replyComposer: sel('.reply-composer') + sel('[data-testid="reply-composer"]'),
      roleDialog: sel('[role="dialog"]'),
      anyModal: sel('.modal, [class*="modal"]'),
      toast: sel('.toast-container .toast'),
      composeBtnVisible: !!document.querySelector('[data-testid="compose-button"]'),
      navSettingsVisible: !!document.querySelector('[data-testid="nav-settings"]'),
      emailReplyBtn: sel('.email-reply-btn'),
      detailBody: sel('.email-detail-body'),
      detailTitle: sel('.email-detail-title'),
      centerTopElement: topMost,
    }
  })
}

test('DIAG compose: click compose-button (force) + key n', async ({ page, request }) => {
  await boot(page, request)
  const before = await domState(page)
  // focus the email list (neutral), then keyboard 'n'
  await page.locator('[data-testid="email-list"]').click({ position: { x: 5, y: 5 } }).catch(() => {})
  await page.keyboard.press('n')
  await page.waitForTimeout(1500)
  const afterKey = await domState(page)
  // explicit button click, scrolled + forced
  const btn = page.locator('[data-testid="compose-button"]').first()
  await btn.scrollIntoViewIfNeeded().catch(() => {})
  const clickErr = await btn.click({ force: true, timeout: 5000 }).then(() => null).catch((e) => String(e).slice(0, 160))
  await page.waitForTimeout(2000)
  const afterClick = await domState(page)
  await page.screenshot({ path: path.join(SHOTS, 'diag-compose.png') })
  diag.push({ test: 'compose', before, afterKey, afterClick, clickErr })
})

test('DIAG settings: click nav-settings (force) + key Ctrl+,', async ({ page, request }) => {
  await boot(page, request)
  const before = await domState(page)
  await page.keyboard.press('Control+Comma')
  await page.waitForTimeout(1200)
  const afterKey = await domState(page)
  const btn = page.locator('[data-testid="nav-settings"]').first()
  await btn.scrollIntoViewIfNeeded().catch(() => {})
  const box = await btn.boundingBox().catch(() => null)
  const clickErr = await btn.click({ force: true, timeout: 5000 }).then(() => null).catch((e) => String(e).slice(0, 160))
  await page.waitForTimeout(2000)
  const afterClick = await domState(page)
  await page.screenshot({ path: path.join(SHOTS, 'diag-settings.png') })
  diag.push({ test: 'settings', before, afterKey, afterClick, clickErr, navSettingsBox: box })
})

test('DIAG reply: open email, click .email-reply-btn (force) + key r', async ({ page, request }) => {
  await boot(page, request)
  const items = page.locator('[data-testid="email-item"]')
  await items.first().waitFor({ state: 'visible', timeout: 15000 }).catch(() => {})
  await items.first().click().catch(() => {})
  await page.waitForTimeout(2500) // allow lazy body fetch
  const afterOpen = await domState(page)
  await page.screenshot({ path: path.join(SHOTS, 'diag-detail.png') })
  // keyboard r
  await page.keyboard.press('r')
  await page.waitForTimeout(1500)
  const afterKey = await domState(page)
  // ribbon reply button (force)
  const rb = page.locator('.email-reply-btn').first()
  const clickErr = await rb.click({ force: true, timeout: 5000 }).then(() => null).catch((e) => String(e).slice(0, 160))
  await page.waitForTimeout(2500)
  const afterClick = await domState(page)
  await page.screenshot({ path: path.join(SHOTS, 'diag-reply.png') })
  diag.push({ test: 'reply', afterOpen, afterKey, afterClick, clickErr })
})

test.afterAll(async () => {
  try {
    fs.mkdirSync(REPORT_DIR, { recursive: true })
    fs.writeFileSync(path.join(REPORT_DIR, 'diag-modals.json'), JSON.stringify(diag, null, 2))
  } catch (e) { console.error(e) }
})
