/**
 * Onboarding Canary — E2E regression guard for bug #290
 *
 * Bug #290: `_resolve_room_for_account` broke → WS events were silently
 * dropped → training screen stuck at **0% / "Chargement..."** for 5 days
 * in prod. The WS sentinel (observability layer 3) probes the backend
 * path. This canary (layer 4) probes the **full frontend-to-scorecard
 * path**: if either the WS hook, the HTTP polling fallback, or the
 * scorecard rendering breaks, the nightly workflow opens an issue
 * labelled `auto-sentinelle`.
 *
 * Scope: one scenario, happy path, <60s. Richer coverage (stall error,
 * retry, per-provider differences) lives in `onboarding-training-scan`.
 */

import { test, expect, Page, Route } from '@playwright/test'

const API = 'http://127.0.0.1:5050'
const API_LOCALHOST = 'http://localhost:5050'
const API_VITE = 'http://localhost:1420'
const APP = 'http://localhost:1420'

function isApiUrl(url: URL): boolean {
  if (!url.pathname.startsWith('/api/')) return false
  return (
    url.origin === API ||
    url.origin === API_LOCALHOST ||
    url.origin === API_VITE
  )
}

type RouteHandler = (route: Route) => void | Promise<void>

async function mockRoute(page: Page, path: string, handler: RouteHandler) {
  await page.route(`${API}${path}`, handler)
  await page.route(`${API_LOCALHOST}${path}`, handler)
  await page.route(`${API_VITE}${path}`, handler)
}

async function mockRouteFn(
  page: Page,
  matcher: (url: URL) => boolean,
  handler: RouteHandler,
) {
  await page.route((url) => isApiUrl(url) && matcher(url), handler)
}

const MOCK_INSIGHTS = {
  status: 'completed',
  emails_analysed: 142,
  profile: {
    user_name: 'Canary User',
    languages: ['fr'],
    tone: {
      default_tone: 'neutre',
      greeting_style: 'Bonjour,',
      closing_style: 'Cordialement,',
      average_response_length: 'moyen',
    },
    signature: { title: 'Canary', company: 'Agentys', department: 'QA' },
  },
  knowledge: { contacts: [] },
  rules: { contact_rules: [], general_rules: [], forbidden_phrases: [] },
  categories: { auto_label_enabled: false, categories: [] },
}

test.describe('Onboarding canary — #290 regression guard', () => {
  test('scorecard s\'affiche en <60s depuis Step 3', async ({ page }) => {
    // Inject state that puts the wizard on Step 3 (train AI).
    await page.addInitScript(() => {
      localStorage.clear()
      localStorage.setItem('agentys_jwt', 'dev:canary@agentys.local')
      localStorage.setItem('agentys_language', 'fr')
      localStorage.setItem('agentys_onboarding_complete', 'false')
      localStorage.removeItem('agentys_onboarding_kb_complete')
      localStorage.setItem('agentys_force_onboarding', 'true')
      localStorage.setItem('agentys_premium_onboarding', JSON.stringify({
        step: 3,
        direction: 'forward',
        connected: true,
        llmConfigured: true,
        scanData: null,
        cleanupData: null,
        trainingData: null,
        suggestedLabels: [],
        labelData: null,
        firstReplyData: null,
        startedAt: new Date().toISOString(),
        completedAt: null,
      }))
    })

    // Low-priority catch-all for unmatched API calls.
    const catchAll = (route: Route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    }
    await page.route((url) => url.origin === API, catchAll)
    await page.route((url) => url.origin === API_LOCALHOST, catchAll)
    await page.route(
      (url) => url.origin === API_VITE && url.pathname.startsWith('/api/'),
      catchAll,
    )

    // Auth + accounts + init mocks
    await mockRoute(page, '/api/auth/me', (route) => {
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ user: { id: 1, email: 'canary@agentys.local' } }),
      })
    })
    await mockRoute(page, '/api/accounts', (route) => {
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          count: 1,
          current_account_id: 1,
          accounts: [{
            id: 1, email: 'canary@agentys.local',
            provider: 'gmail', status: 'active', is_current: true,
          }],
        }),
      })
    })
    await mockRoute(page, '/api/init', (route) => {
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          emails: { emails: [], has_more: false },
          label_counts: { counts: {}, total: 0 },
          pending_drafts: { drafts: [], pending_count: 0 },
          // useBackendConnection reads accounts + current_account_id from /api/init
          // first (falls back to /api/accounts). Both need to be present or
          // accountId stays null → Step3 parks on "En attente du compte...".
          accounts: [{ id: 1, email: 'canary@agentys.local', status: 'active' }],
          current_account_id: 1,
        }),
      })
    })
    await mockRoute(page, '/api/wizard/status', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json',
                     body: JSON.stringify({ complete: false }) })
    })
    await mockRouteFn(page, (url) => url.pathname.startsWith('/api/labels'), (route) => {
      route.fulfill({ status: 200, contentType: 'application/json',
                     body: JSON.stringify({ labels: [] }) })
    })

    // POST /api/onboarding/start → "started"
    await mockRoute(page, '/api/onboarding/start', (route) => {
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          status: 'started', account_id: 1, onboarding_id: 1,
          current_email_count: 200, min_emails_required: 50,
          already_running: false,
        }),
      })
    })

    // Time-based status transition: running for 2s then completed.
    // Bug #290 would leave the frontend stuck at "0% / Chargement..."
    // because `isActive` never flipped true (WS event lost). The HTTP
    // polling fallback (/api/onboarding/status) still advances the
    // `status` field — but the frontend also needs it to drive UI.
    const createdAt = Date.now()
    await mockRouteFn(
      page,
      (url) => url.pathname === '/api/onboarding/status',
      (route) => {
        const elapsed = Date.now() - createdAt
        const status = elapsed < 2000 ? 'running' : 'completed'
        route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({
            id: 1, account_id: 1, status,
            emails_analysed: status === 'completed' ? 142 : 0,
            error_message: null,
          }),
        })
      },
    )

    await mockRouteFn(
      page,
      (url) => url.pathname === '/api/onboarding/insights',
      (route) => {
        route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify(MOCK_INSIGHTS),
        })
      },
    )

    await mockRouteFn(
      page,
      (url) => url.pathname === '/api/onboarding/learning-status',
      (route) => {
        route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({
            cooldown_active: false, event_counter: 0, threshold: 10,
            last_refresh_at: null, next_refresh_in: 0,
          }),
        })
      },
    )

    // Boot
    await page.goto(APP)
    await page.waitForLoadState('domcontentloaded')

    // Step 3 must appear (the bug-site).
    await expect(
      page.getByText(/Entraînement de votre IA|Training your AI/i),
    ).toBeVisible({ timeout: 10_000 })

    // THE #290 SIGNATURE: "0%" + "Chargement..." forever.
    // Assert the scorecard ("votre IA est prête") appears in <60s.
    // If it doesn't, either the WS path OR the HTTP polling fallback
    // is broken — both are required to keep the user unstuck.
    await expect(
      page.getByText(/votre IA est prête|your AI is ready/i),
    ).toBeVisible({ timeout: 60_000 })
  })
})
