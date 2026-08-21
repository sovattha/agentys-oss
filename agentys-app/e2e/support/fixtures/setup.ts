/**
 * Common E2E test setup helpers
 *
 * Provides setupBaseMocks() to mock all routes needed for the app
 * to reach the main inbox view (bypass wizard, loading states, etc.)
 *
 * IMPORTANT: Route patterns must NOT match Vite dev server files.
 * The frontend serves from localhost:1420 (including src/api/*.ts modules).
 * The backend API is at 127.0.0.1:5050 (config.ts uses 127.0.0.1 pour éviter
 * la résolution IPv6 de "localhost" sur Windows).
 *
 * Les mocks doivent intercepter 127.0.0.1:5050 ET localhost:5050 car
 * certains spec files utilisent encore 'http://localhost:5050' comme constante.
 *
 * Playwright evaluates routes in LIFO order (last registered = highest priority).
 * Register the catch-all FIRST, then specific routes, so specific ones win.
 */

import { Page } from '@playwright/test'
import { mockEmailsResponse, mockHealthResponse, mockWizardStatus } from './mock-data'

// L'app utilise 127.0.0.1 (config.ts), les spec files utilisent localhost.
// On intercepte les deux.
// En mode Vite dev, API_URL est VIDE : les requêtes /api/* passent par le proxy Vite
// (localhost:1420) → on doit aussi intercepter l'origine du dev server pour les paths /api/*.
const API = 'http://127.0.0.1:5050'
const API_LOCALHOST = 'http://localhost:5050'
const API_VITE = 'http://localhost:1420'

interface SetupOptions {
  emailsResponse?: unknown
  completeOnboardingV2?: boolean
}


/**
 * Setup all API mocks required for the app to display the main view.
 * Call this in beforeEach for any test that needs the app fully loaded.
 */
export async function setupBaseMocks(page: Page, opts?: SetupOptions) {
  // Set localStorage to skip wizard AND KB onboarding + auth token (DEV mode bypass)
  // `agentys_onboarding_v2_complete` is required too: useOnboardingV2 auto-starts
  // the product tour 700ms after mount when KB is done but V2 isn't — its modal
  // ("Write an email in 5 seconds") then steals focus from every spec.
  await page.addInitScript((completeOnboardingV2) => {
    localStorage.setItem('agentys_onboarding_complete', 'true')
    localStorage.setItem('agentys_onboarding_kb_complete', 'true')
    if (completeOnboardingV2) {
      localStorage.setItem('agentys_onboarding_v2_complete', 'true')
    } else {
      localStorage.removeItem('agentys_onboarding_v2_complete')
    }
    // NOTE: le backend REFUSE désormais les tokens « dev:* » (401, même en
    // loopback) — voir auth.py _enforce_auth. Si une requête fuit hors des
    // mocks (teardown Playwright, route oubliée), elle est rejetée au lieu
    // d'être servie comme l'utilisateur réel (audit 2026-06-09 : id mock
    // « cal-1 » envoyé à la vraie API Google Calendar).
    localStorage.setItem('agentys_jwt', 'dev:test@example.com')
    // Pin the UI language to French for deterministic e2e: the suite asserts
    // French copy, but Playwright's Chromium defaults to en-US, so without this
    // i18n auto-detects English (see src/i18n/index.ts detectBrowserLang).
    localStorage.setItem('agentys_language', 'fr')
  }, opts?.completeOnboardingV2 !== false)

  // --- Catch-all FIRST (lowest priority due to LIFO) ---
  // Intercepts 127.0.0.1:5050 (spec files direct), localhost:5050 (spec files),
  // et localhost:1420/api/* (app en mode Vite dev — proxy relative /api/*).
  const catchAll = (route: import('@playwright/test').Route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) })
  }
  await page.route((url) => url.origin === API, catchAll)
  await page.route((url) => url.origin === API_LOCALHOST, catchAll)
  await page.route(
    (url) => url.origin === API_VITE && url.pathname.startsWith('/api/'),
    catchAll,
  )

  // --- Specific routes AFTER (higher priority due to LIFO) ---
  // Helper: enregistre une route sur les trois origins (127.0.0.1 + localhost:5050 + localhost:1420 via proxy)
  const mockBoth = async (
    path: string,
    handler: (route: import('@playwright/test').Route) => void
  ) => {
    await page.route(`${API}${path}`, handler)
    await page.route(`${API_LOCALHOST}${path}`, handler)
    await page.route(`${API_VITE}${path}`, handler)
  }
  const mockBothFn = async (
    matcher: (url: URL) => boolean,
    handler: (route: import('@playwright/test').Route) => void
  ) => {
    await page.route(
      (url) =>
        (url.origin === API ||
          url.origin === API_LOCALHOST ||
          (url.origin === API_VITE && url.pathname.startsWith('/api/'))) &&
        matcher(url),
      handler,
    )
  }

  // Mock /api/auth/me — returns authenticated user
  await mockBoth('/api/auth/me', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ user: { id: 1, email: 'test@example.com' } }),
    })
  })

  // Mock /api/ping — the app's primary health check
  await mockBoth('/api/ping', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'ok', version: '1.0.0' }),
    })
  })

  // Mock /api/init — parallel init endpoint (emails + labels + drafts + accounts)
  await mockBoth('/api/init', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      // The app paints the inbox list from /api/init.emails (useBackendConnection
      // ts:192), NOT /api/emails, on first load. This default must therefore match
      // the /api/emails default (mockEmailsResponse) — otherwise every spec that
      // calls setupBaseMocks() without an explicit emailsResponse renders an empty
      // inbox and times out waiting for [data-testid="email-item"]. Specs that want
      // an empty inbox already pass emailsResponse: mockEmptyEmails explicitly.
      body: JSON.stringify({
        emails: opts?.emailsResponse ?? mockEmailsResponse,
        label_counts: { counts: {}, total: 0 },
        pending_drafts: { drafts: [], pending_count: 0 },
        accounts: [{ id: 1, email: 'test@example.com', status: 'active' }],
      }),
    })
  })

  // Mock /api/health (used by some tests directly)
  await mockBoth('/api/health', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockHealthResponse),
    })
  })

  // Mock /api/wizard/status
  await mockBoth('/api/wizard/status', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockWizardStatus),
    })
  })

  // Mock /api/settings — GET must return Deep Work disabled so the inbox renders
  // the EmailList, not the DeepWorkOverlay "Focus mode" panel. useDeepWorkSetting
  // self-heals `enabled = rawEnabled || emailsEnabled || workEnabled`, so ALL three
  // sub-flags must be false. Without this the catch-all `{}` leaves
  // `deep_work_emails_enabled` defaulting to `true` → overlay replaces the list on
  // any weekday outside a check slot (a time-of-day-dependent flaky failure).
  await mockBoth('/api/settings', (route) => {
    if (route.request().method() !== 'GET') {
      route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
      return
    }
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        deep_work_enabled: false,
        deep_work_emails_enabled: false,
        deep_work_work_enabled: false,
      }),
    })
  })

  // Mock /api/accounts
  await mockBoth('/api/accounts', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        count: 1,
        current_account_id: 'acc_1',
        accounts: [{ id: 'acc_1', email: 'test@example.com', provider: 'gmail', status: 'active', is_current: true, signature: '', signature_html: '' }],
      }),
    })
  })

  // Mock /api/emails (with or without query string)
  const emailsBody = JSON.stringify(opts?.emailsResponse ?? mockEmailsResponse)
  await mockBoth('/api/emails?*', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: emailsBody })
  })
  const emailsNoQuery = (route: import('@playwright/test').Route) => {
    if (route.request().url().includes('?')) return
    route.fulfill({ status: 200, contentType: 'application/json', body: emailsBody })
  }
  await page.route(`${API}/api/emails`, emailsNoQuery)
  await page.route(`${API_LOCALHOST}/api/emails`, emailsNoQuery)

  // Mock /api/labels
  await mockBothFn((url) => url.pathname.startsWith('/api/labels'), (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ labels: [], counts: {} }),
    })
  })

  // Mock /api/sync/status
  await mockBoth('/api/sync/status', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ is_syncing: false, last_sync: null }),
    })
  })

  // Mock /api/drafts (legacy)
  await mockBothFn((url) => url.pathname.startsWith('/api/drafts'), (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ drafts: [], pending_count: 0 }),
      })
    } else {
      // fallback() retombe sur le catch-all ({}). continue() partait au VRAI
      // backend qui 401 les tokens dev:* → auth:unauthorized → logout → écran
      // de login en plein test (diagnostic 2026-06-13).
      route.fallback()
    }
  })

  // Mock /api/pending-drafts (actual endpoint used by PendingDraftList)
  await mockBothFn((url) => url.pathname.startsWith('/api/pending-drafts'), (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ drafts: [], pending_count: 0 }),
      })
    } else {
      // fallback() retombe sur le catch-all ({}). continue() partait au VRAI
      // backend qui 401 les tokens dev:* → auth:unauthorized → logout → écran
      // de login en plein test (diagnostic 2026-06-13).
      route.fallback()
    }
  })

  // Mock /api/snippets (required by SnippetSelector in NewMessageModal)
  await mockBothFn((url) => url.pathname.startsWith('/api/snippets'), (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ snippets: [], total: 0 }),
    })
  })

  // Mock /api/contacts/autocomplete — MUST be an array. The command palette
  // feeds the raw response to contacts.map(); the catch-all's `{}` crashes the
  // palette render mid-test (observed: "should show empty state" failing with
  // the whole dialog unmounted).
  await mockBothFn((url) => url.pathname.startsWith('/api/contacts/autocomplete'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })

  // Mock /api/stats
  await mockBothFn((url) => url.pathname.startsWith('/api/stats'), (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ total_emails: 10, unread: 4, drafts: 0 }),
    })
  })
}

/**
 * Wait for the app to be fully loaded (past wizard/loading).
 * Use after setupBaseMocks + page.goto('/').
 */
export async function waitForAppReady(page: Page) {
  // Wait for the sidebar to appear — it only renders when connected + not in wizard
  await page.locator('[data-testid="nav-inbox"]').waitFor({ state: 'visible', timeout: 15000 })
}

/**
 * Retourne true si l'URL cible une route `/api/*` d'une des origines acceptées :
 * - 127.0.0.1:5050 (constante `API` utilisée dans les specs)
 * - localhost:5050 (variante)
 * - localhost:1420 (app en dev, proxy Vite pour les paths relatifs)
 *
 * À utiliser dans les handlers de routes spécifiques d'un spec :
 *   await page.route((url) => isApiRoute(url) && url.pathname === '/api/calendar/status', ...)
 */
export function isApiRoute(url: URL): boolean {
  if (!url.pathname.startsWith('/api/')) return false
  return (
    url.origin === API ||
    url.origin === API_LOCALHOST ||
    url.origin === API_VITE
  )
}
