import { chromium, type FullConfig } from '@playwright/test'

/**
 * Warm the Vite dev server before the suite runs.
 *
 * `yarn dev` (Vite) answers `/` almost immediately, so Playwright's `webServer`
 * readiness probe passes — but the *first real page load* then triggers
 * on-demand compilation of the entire app module graph (hundreds of modules).
 * That first compile routinely exceeds the 30s per-test timeout, so whichever
 * tests run first (e.g. the Bug 1 "Pinned" block in pin-and-del-hover.spec.ts)
 * time out waiting for `nav-inbox` while every later test passes against the
 * now-warm server — a confusing, position-dependent "flake".
 *
 * Loading the app once here forces that compile up front, off the test clock.
 * When a dev server is already running (`reuseExistingServer`), this is a
 * near-instant no-op.
 */
async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0]?.use?.baseURL || 'http://localhost:1420'
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage()
    // `load` ensures the entry bundle executed → Vite transformed the static
    // import graph (App.tsx and everything it imports non-lazily). The extra
    // settle time lets deferred imports kicked off by the first render finish.
    await page.goto(baseURL, { waitUntil: 'load', timeout: 120_000 })
    await page.waitForTimeout(4_000)
    // The first load only compiles the STATIC import graph. Components behind
    // React.lazy() (command palette, settings, compose, email detail) compile
    // on first open — inside a test's expect timeout, which makes whichever
    // tests open them first flaky on a cold dev server (observed: palette
    // "element(s) not found" within 5s while Vite transforms the chunk).
    // Force-transform those chunks here, off the test clock. String form keeps
    // the dynamic imports out of Playwright's TS transpilation.
    await page.evaluate(`Promise.allSettled([
      import('/src/components/CommandPaletteContainer.tsx'),
      import('/src/components/Settings.tsx'),
      import('/src/components/compose/NewMessageModal.tsx'),
      import('/src/components/EmailDetailModal.tsx'),
    ])`)
  } catch {
    // Non-fatal: if the server is genuinely unreachable the tests themselves
    // fail with a clear error — don't mask that behind a setup crash.
  } finally {
    await browser.close()
  }
}

export default globalSetup
