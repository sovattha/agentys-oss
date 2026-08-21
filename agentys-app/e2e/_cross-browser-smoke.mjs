/**
 * Cross-browser smoke test (NOT run by playwright test runner — `_` prefix).
 *
 * Loads the Agentys login page on Chromium, Firefox, WebKit (Safari) and
 * exercises the popup-blocker scenario from oauth-troubleshoot.spec.ts.
 *
 * Usage: node e2e/_cross-browser-smoke.mjs
 */

import { chromium, firefox, webkit } from 'playwright'

const FRONTEND = 'http://localhost:1420'
const API = 'http://127.0.0.1:5050'
const API_LOCALHOST = 'http://localhost:5050'
const API_VITE = 'http://localhost:1420'
const GOOGLE = 'https://accounts.google.com/o/oauth2/v2/auth'

const browsers = [
  { name: 'chromium', launcher: chromium },
  { name: 'firefox', launcher: firefox },
  { name: 'webkit', launcher: webkit },
]

const results = []

for (const { name, launcher } of browsers) {
  const checks = {
    loaded: false,
    popupNotice: false,
    googleRedirect: false,
    uuidFallback: false,
    clipboardFallback: false,
    error: null,
  }
  let browser

  try {
    browser = await launcher.launch()
    const context = await browser.newContext()

    await context.addInitScript(() => {
      localStorage.clear()
      sessionStorage.clear()
      const origOpen = window.open
      Object.defineProperty(window, 'open', {
        configurable: true, writable: true,
        value: function (url, target) {
          if (target === 'oauth-popup') return null
          return origOpen?.call(window, url, target)
        },
      })
    })

    const page = await context.newPage()

    const json200 = (route, body) =>
      route.fulfill({ status: 200, contentType: 'application/json', body })
    const json401 = (route) =>
      route.fulfill({ status: 401, contentType: 'application/json', body: '{"error":"Unauthorized"}' })

    await page.route((u) => u.origin === API, (r) => json200(r, '{}'))
    await page.route((u) => u.origin === API_LOCALHOST, (r) => json200(r, '{}'))
    await page.route(
      (u) => u.origin === API_VITE && u.pathname.startsWith('/api/'),
      (r) => json200(r, '{}'),
    )
    for (const origin of [API, API_LOCALHOST, API_VITE]) {
      await page.route(`${origin}/api/auth/me`, json401)
      await page.route(`${origin}/api/auth/verify`, json401)
      await page.route(`${origin}/api/health`, (r) => json200(r, '{"status":"ok"}'))
      await page.route(`${origin}/api/oauth/pkce/store`, (r) => json200(r, '{"ok":true}'))
      // Endpoints that return shaped data — the App's hooks read .items / .length
      // on the response and crash if they get the catch-all empty `{}`.
      await page.route((u) => u.origin === origin && u.pathname.startsWith('/api/emails/scheduled'),
        (r) => json200(r, '{"items":[],"count":0}'))
    }

    let capturedAuthUrl = null
    await page.route(
      (u) => u.toString().startsWith(GOOGLE),
      (r) => {
        capturedAuthUrl = r.request().url()
        r.fulfill({
          status: 200,
          contentType: 'text/html',
          body: '<html><body>Stubbed OAuth.</body></html>',
        })
      },
    )

    // Capture page errors so we know if the bundle even loaded
    const pageErrors = []
    page.on('pageerror', (err) => pageErrors.push(`${err.name}: ${err.message}`))

    await page.goto(FRONTEND, { waitUntil: 'domcontentloaded' })
    await page.locator('.login-card').waitFor({ state: 'visible', timeout: 10000 })
    checks.loaded = true

    const gmailBtn = page.locator('.login-oauth-card', { hasText: 'Gmail' })
    await gmailBtn.click()

    await page.locator('.oauth-troubleshoot--brief').waitFor({ state: 'visible', timeout: 5000 })
    checks.popupNotice = true

    const start = Date.now()
    while (!capturedAuthUrl && Date.now() - start < 5000) {
      await new Promise((r) => setTimeout(r, 100))
    }
    checks.googleRedirect = !!capturedAuthUrl

    // Verify cross-browser helpers via a fresh page (escape OAuth navigation).
    const verifyPage = await context.newPage()
    await verifyPage.goto(FRONTEND, { waitUntil: 'domcontentloaded' })

    // safeRandomUUID — hide native crypto.randomUUID and confirm the fallback
    // produces a valid v4 UUID even on browsers that lack the API.
    const uuidResult = await verifyPage.evaluate(async () => {
      const orig = crypto.randomUUID
      delete crypto.randomUUID
      try {
        const mod = await import('/src/utils/uuid.ts')
        return mod.safeRandomUUID()
      } finally {
        crypto.randomUUID = orig
      }
    })
    const UUID_V4_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
    checks.uuidFallback = UUID_V4_RE.test(uuidResult)
    if (!checks.uuidFallback) {
      checks.error = `UUID fallback returned non-v4: ${uuidResult}`
    }

    // copyToClipboard — execCommand('copy') needs a user-gesture chain on
    // Safari, so attach the helper to a real button click. Hide
    // navigator.clipboard inside the click handler so the fallback path runs.
    await verifyPage.evaluate(async () => {
      const mod = await import('/src/utils/clipboard.ts')
      window.__copyToClipboard = mod.copyToClipboard
      const btn = document.createElement('button')
      btn.id = 'smoke-copy-btn'
      btn.textContent = 'copy'
      btn.style.cssText = 'position:fixed;top:0;left:0;z-index:999999;width:100px;height:40px;'
      btn.addEventListener('click', async () => {
        const origDescriptor = Object.getOwnPropertyDescriptor(Navigator.prototype, 'clipboard')
        Object.defineProperty(navigator, 'clipboard', { configurable: true, get: () => undefined })
        try {
          window.__copyResult = await window.__copyToClipboard('cross-browser-smoke')
        } finally {
          if (origDescriptor) Object.defineProperty(Navigator.prototype, 'clipboard', origDescriptor)
        }
      })
      document.body.appendChild(btn)
    })
    await verifyPage.locator('#smoke-copy-btn').click({ force: true })
    await verifyPage.waitForFunction(() => typeof window.__copyResult === 'boolean', null, { timeout: 5000 })
    const clipboardResult = await verifyPage.evaluate(() => window.__copyResult)
    checks.clipboardFallback = clipboardResult === true
    if (!checks.clipboardFallback && !checks.error) {
      checks.error = `Clipboard fallback returned ${clipboardResult}`
    }

    if (pageErrors.length > 0 && !checks.error) {
      checks.error = `Page errors: ${pageErrors.slice(0, 3).join(' | ')}`
    }
  } catch (err) {
    checks.error = err.message?.split('\n')[0] || String(err).split('\n')[0]
  } finally {
    if (browser) await browser.close()
  }

  results.push({ browser: name, ...checks })
}

console.log('\n=== Cross-browser smoke (OAuth troubleshoot + browser-compat helpers) ===\n')
for (const r of results) {
  const ok = (b) => (b ? 'PASS' : 'FAIL')
  console.log(
    `[${r.browser.padEnd(10)}] loaded=${ok(r.loaded)} popupNotice=${ok(r.popupNotice)} googleRedirect=${ok(r.googleRedirect)} uuid=${ok(r.uuidFallback)} clipboard=${ok(r.clipboardFallback)}` +
      (r.error ? `\n           error: ${r.error}` : ''),
  )
}
const allOk = results.every(
  (r) => r.loaded && r.popupNotice && r.googleRedirect && r.uuidFallback && r.clipboardFallback && !r.error,
)
console.log(`\n${allOk ? 'ALL BROWSERS PASS' : 'SOME BROWSERS FAILED'}`)
process.exit(allOk ? 0 : 1)
