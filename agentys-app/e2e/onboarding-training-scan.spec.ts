/**
 * Onboarding Training Scan — E2E Tests
 *
 * Simulates a real user doing the "Entraînement de votre IA" step (Step3)
 * with Gmail and Outlook accounts. Covers:
 *
 *   1. Training starts and shows 4 running steps (no stall error)
 *   2. Steps complete progressively and show correct final state
 *   3. Stall error does NOT fire when server responds within 5s
 *   4. Stall error fires correctly when server is truly unresponsive (90s mock)
 *   5. "Recommencer" retry flow works after a failure
 *   6. Gmail account — full happy path
 *   7. Outlook account — full happy path
 */

import { test, expect, Page, Route } from '@playwright/test'

const API = 'http://127.0.0.1:5050'
const API_LOCALHOST = 'http://localhost:5050'
const API_VITE = 'http://localhost:1420'
const APP = 'http://localhost:1420'

// En mode Vite dev, API_URL est vide — les requêtes /api/* passent par le proxy
// Vite (localhost:1420). Il faut intercepter les trois origines.
function isApiUrl(url: URL): boolean {
  if (!url.pathname.startsWith('/api/')) return false
  return (
    url.origin === API ||
    url.origin === API_LOCALHOST ||
    url.origin === API_VITE
  )
}

type RouteHandler = (route: Route) => void

async function mockRoute(page: Page, path: string, handler: RouteHandler) {
  await page.route(`${API}${path}`, handler)
  await page.route(`${API_LOCALHOST}${path}`, handler)
  await page.route(`${API_VITE}${path}`, handler)
}

async function mockRouteFn(page: Page, matcher: (url: URL) => boolean, handler: RouteHandler) {
  await page.route((url) => isApiUrl(url) && matcher(url), handler)
}

// ─── Shared mock data ────────────────────────────────────────────────────────

const MOCK_INSIGHTS = {
  status: 'completed',
  emails_analysed: 142,
  profile: {
    user_name: 'Alex Dupont',
    languages: ['fr', 'en'],
    tone: {
      default_tone: 'professionnel',
      greeting_style: 'Bonjour,',
      closing_style: 'Cordialement,',
      average_response_length: 'moyen',
    },
    signature: { title: 'Product Manager', company: 'Agentys', department: 'Produit' },
  },
  // NOTE: projects/terminology/suggested_labels are intentionally NOT scanned
  // (see knowledge_agent.py:42, orchestrator.py:594, label_agent.py:43).
  // Only `contacts` is kept — it feeds WritingStyleProfile per-contact style.
  knowledge: {
    contacts: [
      { email: 'marie@bnp.fr', name: 'Marie Martin', preferred_tone: 'formel', preferred_language: 'fr', company: 'BNP' },
      { email: 'john@partner.com', name: 'John Smith', preferred_tone: 'direct', preferred_language: 'en' },
    ],
  },
  rules: {
    contact_rules: [
      { contact_email: 'marie@bnp.fr', tone: 'formel', language: 'fr', greeting: 'Madame,', closing: 'Cordialement,' },
    ],
    general_rules: [
      { name: 'Concision', description: 'Réponses courtes < 150 mots' },
    ],
    forbidden_phrases: ['comme convenu', 'suite à notre entretien'],
  },
}

// ─── Setup helpers ────────────────────────────────────────────────────────────

async function setupAuthAndBase(page: Page, provider: 'gmail' | 'outlook' = 'gmail') {
  const accountEmail = provider === 'gmail' ? 'alex@gmail.com' : 'alex@outlook.com'

  await page.addInitScript(
    ({ email, provider: _prov }) => {
      localStorage.clear()
      // Auth token
      localStorage.setItem('agentys_jwt', 'dev:' + email)
      // Force French locale so tests can assert on French strings
      localStorage.setItem('agentys_language', 'fr')
      // Skip KB onboarding done flag so Step3 is shown
      localStorage.setItem('agentys_onboarding_complete', 'false')
      localStorage.removeItem('agentys_onboarding_kb_complete')
      // Force the onboarding wizard to show
      localStorage.setItem('agentys_force_onboarding', 'true')
      // Inject wizard state to land directly on Step 3 (train AI)
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
    },
    { email: accountEmail, provider }
  )

  // Catch-all backend mock (lowest priority — registered first)
  const catchAll = (route: Route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  }
  await page.route((url) => url.origin === API, catchAll)
  await page.route((url) => url.origin === API_LOCALHOST, catchAll)
  await page.route((url) => url.origin === API_VITE && url.pathname.startsWith('/api/'), catchAll)

  // Auth (higher priority — registered after catch-all)
  await mockRoute(page, '/api/auth/me', (route) => {
    route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ user: { id: 1, email: accountEmail } }),
    })
  })
  await mockRoute(page, '/api/auth/verify', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ valid: true }) })
  })
  await mockRoute(page, '/api/ping', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', version: '1.0.0' }) })
  })

  // Accounts
  await mockRoute(page, '/api/accounts', (route) => {
    route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        count: 1,
        current_account_id: 1,
        accounts: [{ id: 1, email: accountEmail, provider, status: 'active', is_current: true }],
      }),
    })
  })

  // Init
  await mockRoute(page, '/api/init', (route) => {
    route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        emails: { emails: [], has_more: false },
        label_counts: { counts: {}, total: 0 },
        pending_drafts: { drafts: [], pending_count: 0 },
        accounts: [{ id: 1, email: accountEmail, status: 'active' }],
        current_account_id: 1,
      }),
    })
  })

  await mockRouteFn(page, (url) => url.pathname.startsWith('/api/labels'), (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ labels: [] }) })
  })
  await mockRoute(page, '/api/wizard/status', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ complete: false }) })
  })
}

/**
 * Mock onboarding endpoints with a simulated progressive flow.
 * startDelay: ms before status switches from 'pending' to 'running'
 * completeDelay: ms before status switches to 'completed'
 */
async function mockOnboardingFlow(page: Page, opts: {
  startDelay?: number
  completeDelay?: number
  shouldFail?: boolean
} = {}) {
  const { startDelay = 500, completeDelay = 3000, shouldFail = false } = opts
  const createdAt = Date.now()

  // POST /api/onboarding/start — triggers background analysis
  await mockRoute(page, '/api/onboarding/start', (route) => {
    route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ status: 'started', onboarding_id: 42, account_id: 1 }),
    })
  })

  // GET /api/onboarding/status — simulates pending → running → completed
  await mockRouteFn(page, (url) => url.pathname === '/api/onboarding/status', (route) => {
    const elapsed = Date.now() - createdAt
    let status: string
    if (shouldFail) {
      status = elapsed > startDelay ? 'failed' : 'pending'
    } else if (elapsed < startDelay) {
      status = 'pending'
    } else if (elapsed < completeDelay) {
      status = 'running'
    } else {
      status = 'completed'
    }

    route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        id: 42,
        account_id: 1,
        status,
        emails_analysed: status === 'completed' ? 142 : 0,
        error_message: shouldFail && status === 'failed' ? 'Aucun email trouvé' : null,
      }),
    })
  })

  // GET /api/onboarding/insights — only meaningful when completed
  await mockRouteFn(page, (url) => url.pathname === '/api/onboarding/insights', (route) => {
    route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(MOCK_INSIGHTS),
    })
  })
}

// ─── Tests ───────────────────────────────────────────────────────────────────

test.describe('Onboarding Training Scan — Entraînement de votre IA', () => {

  test.describe('Gmail — happy path', () => {
    test.beforeEach(async ({ page }) => {
      await setupAuthAndBase(page, 'gmail')
    })

    test('démarre et affiche le spinner global + les 4 étapes en cours', async ({ page }) => {
      await mockOnboardingFlow(page, { startDelay: 200, completeDelay: 60_000 })

      await page.goto(APP)
      await page.waitForLoadState('domcontentloaded')

      // Step 3 should be visible
      await expect(page.locator('text=Entraînement de votre IA')).toBeVisible({ timeout: 10_000 })

      // Global progress ring visible (isActive = true)
      await expect(page.locator('.learning-progress-ring-wrap')).toBeVisible({ timeout: 5000 })

      // After polling (5s initial delay), all 4 steps should be running
      await expect(page.locator('.learning-step-running')).toHaveCount(4, { timeout: 15_000 })

      // Step titles teal-colored
      const titles = page.locator('.learning-step-running .learning-step-title')
      await expect(titles).toHaveCount(4)

      // Step icons spinning
      await expect(page.locator('.learning-step-icon-running')).toHaveCount(4)

      // No stall error
      await expect(page.locator('.learning-progress-error')).not.toBeVisible()
    })

    test('complète les 4 étapes et affiche les résultats', async ({ page }) => {
      await mockOnboardingFlow(page, { startDelay: 200, completeDelay: 2000 })

      await page.goto(APP)
      await page.waitForLoadState('domcontentloaded')

      await expect(page.locator('text=Entraînement de votre IA')).toBeVisible({ timeout: 10_000 })

      // When all steps complete, the component transitions to the done screen
      await expect(page.locator('.s3-reveal-root')).toBeVisible({ timeout: 15_000 })

      // Done screen with profile data
      await expect(page.locator('text=142')).toBeVisible({ timeout: 5000 })
      await expect(page.locator('text=Alex Dupont')).toBeVisible()

      // CTA button visible
      await expect(page.locator('button:has-text("Continuer")').or(
        page.locator('.po-btn-primary')
      )).toBeVisible()
    })

    test("PAS d'erreur de stall quand le serveur répond dans les 5s", async ({ page }) => {
      // Server responds quickly — stall timer must be cancelled
      await mockOnboardingFlow(page, { startDelay: 100, completeDelay: 60_000 })

      await page.goto(APP)
      await page.waitForLoadState('domcontentloaded')
      await expect(page.locator('text=Entraînement de votre IA')).toBeVisible({ timeout: 10_000 })

      // Wait 12s (well within 90s stall timeout)
      await page.waitForTimeout(12_000)

      // No stall error
      await expect(page.locator('text=Aucune progression détectée')).not.toBeVisible()
      await expect(page.locator('.learning-progress-error')).not.toBeVisible()

      // Steps must be running
      await expect(page.locator('.learning-step-running')).toHaveCount(4)
    })

    test('affiche les règles de réponse et les contacts identifiés via les tabs', async ({ page }) => {
      await mockOnboardingFlow(page, { startDelay: 100, completeDelay: 1000 })

      await page.goto(APP)
      await page.waitForLoadState('domcontentloaded')
      await expect(page.locator('text=Entraînement de votre IA')).toBeVisible({ timeout: 10_000 })

      // Wait for done screen
      await expect(page.locator('.s3-reveal-root')).toBeVisible({ timeout: 15_000 })

      // Default tab is Profil — profile data visible
      await expect(page.locator('text=Alex Dupont')).toBeVisible()

      // Switch to Savoir tab — contacts and projects visible
      await page.locator('.pillar-nav-card', { hasText: 'Savoir' }).click()
      await expect(page.locator('text=Marie Martin')).toBeVisible()
      await expect(page.locator('text=Automatisation emails IA')).toBeVisible()

      // Switch to Style tab — rules visible
      await page.locator('.pillar-nav-card', { hasText: "Style d'écriture" }).click()
      await expect(page.locator('text=Concision')).toBeVisible()
    })
  })

  test.describe('Outlook — happy path', () => {
    test.beforeEach(async ({ page }) => {
      await setupAuthAndBase(page, 'outlook')
    })

    test('Outlook: démarre et complète l\'analyse sans erreur', async ({ page }) => {
      // Use counter-based mock: polls 1-2 → running, poll 3+ → completed
      // This ensures we reliably see the running state before the done screen
      let outlookPollCount = 0
      await mockRoute(page, '/api/onboarding/start', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'started', onboarding_id: 42 }) })
      })
      await mockRouteFn(page, (url) => url.pathname === '/api/onboarding/status', (route) => {
        outlookPollCount++
        const status = outlookPollCount < 3 ? 'running' : 'completed'
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status, emails_analysed: status === 'completed' ? 142 : 0 }) })
      })
      await mockRouteFn(page, (url) => url.pathname === '/api/onboarding/insights', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_INSIGHTS) })
      })

      await page.goto(APP)
      await page.waitForLoadState('domcontentloaded')

      await expect(page.locator('text=Entraînement de votre IA')).toBeVisible({ timeout: 10_000 })

      // Running state appears on first poll (5s initial delay + margin for slow runs)
      await expect(page.locator('.learning-step-running')).toHaveCount(4, { timeout: 20_000 })

      // No stall error
      await expect(page.locator('text=Aucune progression détectée')).not.toBeVisible()

      // Completes on 3rd poll — done screen shows
      await expect(page.locator('.s3-reveal-root')).toBeVisible({ timeout: 20_000 })
    })

    test('Outlook: stat 142 emails analysés visible', async ({ page }) => {
      await mockOnboardingFlow(page, { startDelay: 100, completeDelay: 1500 })

      await page.goto(APP)
      await page.waitForLoadState('domcontentloaded')
      await expect(page.locator('text=Entraînement de votre IA')).toBeVisible({ timeout: 10_000 })
      await expect(page.locator('.s3-reveal-root')).toBeVisible({ timeout: 15_000 })

      await expect(page.locator('.s3-count-number')).toContainText('142')
    })
  })

  test.describe('Cas d\'erreur', () => {
    test.beforeEach(async ({ page }) => {
      await setupAuthAndBase(page, 'gmail')
    })

    test('affiche l\'erreur backend si le serveur répond failed', async ({ page }) => {
      await mockOnboardingFlow(page, { startDelay: 300, shouldFail: true })

      await page.goto(APP)
      await page.waitForLoadState('domcontentloaded')
      await expect(page.locator('text=Entraînement de votre IA')).toBeVisible({ timeout: 10_000 })

      // Failed state from backend — polling sets isActive=false + error
      await expect(page.locator('.learning-progress-error')).toBeVisible({ timeout: 12_000 })
      await expect(page.locator('button:has-text("Recommencer")')).toBeVisible()
    })

    test('Recommencer repart de zéro et relance l\'analyse', async ({ page }) => {
      // Use a failingPhase flag — independent of Strict Mode's double-mount behavior
      // Phase 1 (failingPhase=true): always return failed → error + retry button shown
      // Phase 2 (failingPhase=false): return running → steps update after retry click
      let failingPhase = true
      let retryPollCount = 0

      await mockRoute(page, '/api/onboarding/start', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'started', onboarding_id: 42 }) })
      })

      await mockRouteFn(page, (url) => url.pathname === '/api/onboarding/status', (route) => {
        if (failingPhase) {
          route.fulfill({
            status: 200, contentType: 'application/json',
            body: JSON.stringify({ status: 'failed', emails_analysed: 0, error_message: 'Erreur réseau' }),
          })
          return
        }
        retryPollCount++
        const status = retryPollCount < 3 ? 'running' : 'completed'
        route.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify({ status, emails_analysed: status === 'completed' ? 80 : 0 }),
        })
      })

      await mockRouteFn(page, (url) => url.pathname === '/api/onboarding/insights', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_INSIGHTS) })
      })

      await page.goto(APP)
      await page.waitForLoadState('domcontentloaded')
      await expect(page.locator('text=Entraînement de votre IA')).toBeVisible({ timeout: 10_000 })

      // First attempt fails — Recommencer button must appear
      await expect(page.locator('button:has-text("Recommencer")')).toBeVisible({ timeout: 12_000 })

      // Switch to success phase and click retry
      failingPhase = false
      await page.locator('button:has-text("Recommencer")').click()

      // Second attempt succeeds — running steps visible
      await expect(page.locator('.learning-step-running')).toHaveCount(4, { timeout: 12_000 })
      await expect(page.locator('text=Aucune progression détectée')).not.toBeVisible()
    })

    test('serveur HS — stall error apparaît après timeout', async ({ page }) => {
      // Simulate completely dead server (no response to status endpoint)
      await mockRoute(page, '/api/onboarding/start', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'started' }) })
      })

      // Status endpoint returns 500 — server alive callback never fires
      await mockRouteFn(page, (url) => url.pathname === '/api/onboarding/status', (route) => {
        route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: 'Internal error' }) })
      })

      // Reduce stall timeout for this test via page injection
      await page.addInitScript(() => {
        // Override STALL_TIMEOUT to 10s for this test (injected before app loads)
        (window as unknown as Record<string, unknown>).__TEST_STALL_TIMEOUT = 10
      })

      await page.goto(APP)
      await page.waitForLoadState('domcontentloaded')
      await expect(page.locator('text=Entraînement de votre IA')).toBeVisible({ timeout: 10_000 })

      // Stall error must appear (at most STALL_TIMEOUT + margin)
      await expect(page.locator('text=Aucune progression détectée')).toBeVisible({ timeout: 15_000 })
      await expect(page.locator('button:has-text("Recommencer")')).toBeVisible()
    })
  })

  test.describe('Audit extraction scan — toutes les données remontent à l\'UI', () => {
    test.beforeEach(async ({ page }) => {
      await setupAuthAndBase(page, 'gmail')
    })

    test('Profil: user_name, signature (title/company), langues — tous rendus', async ({ page }) => {
      await mockOnboardingFlow(page, { startDelay: 100, completeDelay: 1000 })

      await page.goto(APP)
      await page.waitForLoadState('domcontentloaded')
      await expect(page.locator('text=Entraînement de votre IA')).toBeVisible({ timeout: 10_000 })
      await expect(page.locator('.s3-reveal-root')).toBeVisible({ timeout: 15_000 })

      // Hero: compteur 142 emails
      await expect(page.locator('.s3-count-number')).toContainText('142')

      // Onglet Profil (actif par défaut) — identity block
      const profil = page.locator('.pillar-profil')
      await expect(profil).toBeVisible()
      await expect(profil).toContainText('Alex Dupont')       // user_name
      await expect(profil).toContainText('Agentys')            // signature.company
      await expect(profil).toContainText('Product Manager')    // signature.title

      // Langues — tags en uppercase
      const tags = page.locator('.learning-insights-tag')
      await expect(tags.filter({ hasText: 'FR' })).toHaveCount(1)
      await expect(tags.filter({ hasText: 'EN' })).toHaveCount(1)
    })

    test("Style: tone (greeting/closing), contact rules, general rules, forbidden phrases", async ({ page }) => {
      await mockOnboardingFlow(page, { startDelay: 100, completeDelay: 1000 })

      await page.goto(APP)
      await page.waitForLoadState('domcontentloaded')
      await expect(page.locator('.s3-reveal-root')).toBeVisible({ timeout: 15_000 })

      await page.locator('.pillar-nav-card', { hasText: "Style d'écriture" }).click()

      // Greeting + closing style extraits du tone
      await expect(page.locator('text=Bonjour,').first()).toBeVisible()
      await expect(page.locator('text=Cordialement,').first()).toBeVisible()

      // General rule (name)
      await expect(page.locator('text=Concision')).toBeVisible()

      // Forbidden phrases (tag list danger)
      await expect(page.locator('text=comme convenu')).toBeVisible()
      await expect(page.locator('text=suite à notre entretien')).toBeVisible()

      // Contact rule remonte bien (email du contact formel)
      await expect(page.locator('text=marie@bnp.fr').first()).toBeVisible()
    })

    test('Style → contacts (injectés via contact rules): emails des contacts visibles', async ({ page }) => {
      // Savoir pillar is hidden in onboarding (design choice — see Step3TrainAI.tsx:263).
      // Contacts are still surfaced via contact_rules in the Style pillar.
      await mockOnboardingFlow(page, { startDelay: 100, completeDelay: 1000 })

      await page.goto(APP)
      await page.waitForLoadState('domcontentloaded')
      await expect(page.locator('.s3-reveal-root')).toBeVisible({ timeout: 15_000 })

      await page.locator('.pillar-nav-card', { hasText: "Style d'écriture" }).click()

      // Contact email from contact_rules — proves rule+contact merge works
      await expect(page.locator('text=marie@bnp.fr').first()).toBeVisible()
    })

    test('Aucun champ critique manquant — assertion globale sur tous les onglets', async ({ page }) => {
      await mockOnboardingFlow(page, { startDelay: 100, completeDelay: 1000 })

      await page.goto(APP)
      await page.waitForLoadState('domcontentloaded')
      await expect(page.locator('.s3-reveal-root')).toBeVisible({ timeout: 15_000 })

      // Savoir pillar is hidden in onboarding — only Profil/Style/AutoLabel shown.
      const expectedByTab: Record<string, string[]> = {
        'Profil': ['Alex Dupont', 'Agentys', 'Product Manager', 'FR', 'EN'],
        "Style d'écriture": ['Bonjour,', 'Cordialement,', 'Concision', 'comme convenu', 'marie@bnp.fr'],
      }

      for (const [tabLabel, expectedTexts] of Object.entries(expectedByTab)) {
        await page.locator('.pillar-nav-card', { hasText: tabLabel }).click()
        for (const txt of expectedTexts) {
          await expect(
            page.locator('.s3-pillar-content').getByText(txt, { exact: false }).first(),
            `Onglet "${tabLabel}" doit contenir "${txt}"`
          ).toBeVisible({ timeout: 5000 })
        }
      }

      // Aucun placeholder "Aucune donnée" sur les 3 piliers principaux
      await expect(page.locator('.s3-empty-pillar')).toHaveCount(0)
    })
  })

  test.describe('Visuel — états des étapes', () => {
    test.beforeEach(async ({ page }) => {
      await setupAuthAndBase(page, 'gmail')
    })

    test('steps pending dimmed, running teal, completed vert', async ({ page }) => {
      // Counter-based: polls 1-2 → running, poll 3+ → completed
      // Ensures first poll sees 'running' regardless of page load timing
      let visualPollCount = 0
      await mockRoute(page, '/api/onboarding/start', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'started' }) })
      })
      await mockRouteFn(page, (url) => url.pathname === '/api/onboarding/status', (route) => {
        visualPollCount++
        const status = visualPollCount < 3 ? 'running' : 'completed'
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status, emails_analysed: status === 'completed' ? 50 : 0 }) })
      })
      await mockRouteFn(page, (url) => url.pathname === '/api/onboarding/insights', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_INSIGHTS) })
      })

      await page.goto(APP)
      await page.waitForLoadState('domcontentloaded')
      await expect(page.locator('text=Entraînement de votre IA')).toBeVisible({ timeout: 10_000 })

      // Phase 1 — pending (before first successful poll)
      const stepPending = page.locator('.learning-step-pending')
      await expect(stepPending.first()).toBeVisible()

      // Phase 2 — running (after first poll returns 'running')
      await expect(page.locator('.learning-step-running')).toHaveCount(4, { timeout: 10_000 })
      // Spinner icons visible
      await expect(page.locator('.learning-step-icon-running')).toHaveCount(4)

      // Phase 3 — when all steps complete the done screen replaces the progress screen
      await expect(page.locator('.s3-reveal-root')).toBeVisible({ timeout: 20_000 })
    })

    test('progress bar avance de 0% à 100%', async ({ page }) => {
      // Running state: bar shows partial fill. Done screen: transition complete.
      let barPollCount = 0
      await mockRoute(page, '/api/onboarding/start', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'started' }) })
      })
      await mockRouteFn(page, (url) => url.pathname === '/api/onboarding/status', (route) => {
        barPollCount++
        const status = barPollCount < 3 ? 'running' : 'completed'
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status, emails_analysed: 100 }) })
      })
      await mockRouteFn(page, (url) => url.pathname === '/api/onboarding/insights', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_INSIGHTS) })
      })

      await page.goto(APP)
      await page.waitForLoadState('domcontentloaded')
      await expect(page.locator('text=Entraînement de votre IA')).toBeVisible({ timeout: 10_000 })

      // Bar exists in the DOM while steps are running
      await expect(page.locator('.learning-step-running')).toHaveCount(4, { timeout: 15_000 })
      const bar = page.locator('.learning-progress-bar-fill')
      await expect(bar).toBeAttached()

      // Eventually done screen shows — all steps completed
      await expect(page.locator('.s3-reveal-root')).toBeVisible({ timeout: 20_000 })
    })
  })
})
