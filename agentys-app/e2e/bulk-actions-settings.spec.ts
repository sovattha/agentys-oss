/**
 * BulkActionsPanel — E2E coverage for the Settings → Tâches en arrière-plan
 * section that visualizes the rate-limited bulk-action queue.
 *
 * Targets the user-visible contract:
 *   1. The panel is present in Settings → Automatisation, with an empty
 *      state message when /api/bulk-jobs returns no rows.
 *   2. A populated list renders one row per job with type label, status
 *      pill, progress bar (or terminal counters), and the right action
 *      buttons depending on status (running → Pause, paused → Reprendre,
 *      failed → Réessayer les échecs, non-terminal → Annuler).
 *   3. Clicking Pause / Reprendre / Annuler / Retry hits the matching
 *      POST endpoint and re-renders with the server's new snapshot.
 *
 * We deliberately do not test the actual worker — that lives behind
 * the /api boundary and is exercised by the Python integration tests
 * (`tests/services/test_bulk_*`).
 */

import { test, expect, Page, Route } from '@playwright/test'
import { setupBaseMocks, waitForAppReady, isApiRoute } from './support/fixtures/setup'


// ─── Mock job library ─────────────────────────────────────────────────
type MockJob = {
  id: string
  user_id: number | null
  account_id: number
  job_type: string
  source: string
  status:
    | 'queued'
    | 'running'
    | 'paused'
    | 'completed'
    | 'failed'
    | 'cancelled'
  target_total: number
  succeeded_count: number
  failed_count: number
  skipped_count: number
  params: Record<string, unknown> | null
  error_summary: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

function mkJob(over: Partial<MockJob>): MockJob {
  const base: MockJob = {
    id: 'JOB000000000000000000000000',
    user_id: 1,
    account_id: 1,
    job_type: 'archive',
    source: 'manual',
    status: 'running',
    target_total: 100,
    succeeded_count: 30,
    failed_count: 0,
    skipped_count: 0,
    params: null,
    error_summary: null,
    created_at: '2026-05-04T11:00:00Z',
    started_at: '2026-05-04T11:00:01Z',
    completed_at: null,
  }
  return { ...base, ...over }
}

const RUNNING = mkJob({
  id: 'JOB1RUNNING0000000000000000',
  status: 'running',
  job_type: 'archive',
  target_total: 100,
  succeeded_count: 42,
})

const FAILED = mkJob({
  id: 'JOB2FAILED00000000000000000',
  status: 'failed',
  job_type: 'move_to_trash',
  target_total: 20,
  succeeded_count: 12,
  failed_count: 8,
  error_summary: 'auth dead',
  completed_at: '2026-05-04T11:30:00Z',
})

const COMPLETED = mkJob({
  id: 'JOB3COMPLETED00000000000000',
  status: 'completed',
  job_type: 'restore_from_trash',
  source: 'auto_deletion',
  target_total: 5,
  succeeded_count: 5,
  completed_at: '2026-05-04T10:55:00Z',
})

// ─── Mock harness ─────────────────────────────────────────────────────
async function setupBulkJobsMocks(
  page: Page,
  initialJobs: MockJob[],
): Promise<{
  jobs: Map<string, MockJob>
  postedActions: Array<{ job_id: string; action: string }>
}> {
  const jobs = new Map<string, MockJob>(initialJobs.map((j) => [j.id, j]))
  const postedActions: Array<{ job_id: string; action: string }> = []

  // GET /api/bulk-jobs → list (function matcher tolerates query string).
  // isApiRoute couvre AUSSI le proxy Vite (localhost:1420) — l'app en dev
  // fait des fetch relatifs /api/* ; sans cette origine le mock était raté
  // et le panneau affichait la bannière d'erreur.
  const listMatcher = (url: URL) =>
    isApiRoute(url) && url.pathname === '/api/bulk-jobs'
  await page.route(listMatcher, (route: Route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ jobs: Array.from(jobs.values()) }),
    })
  })

  // POST /api/bulk-jobs/<id>/{pause,resume,cancel,retry-failed}
  const actionMatcher = (url: URL) =>
    isApiRoute(url) &&
    /^\/api\/bulk-jobs\/[^/]+\/(pause|resume|cancel|retry-failed)$/.test(
      url.pathname,
    )
  await page.route(actionMatcher, (route: Route) => {
    const url = new URL(route.request().url())
    const m = url.pathname.match(/\/api\/bulk-jobs\/([^/]+)\/([^/]+)/)
    if (!m) return route.fallback()
    const [, jobId, action] = m
    const job = jobs.get(jobId)
    if (!job) {
      return route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'not found' }),
      })
    }
    postedActions.push({ job_id: jobId, action })
    let next: MockJob = job
    if (action === 'pause') next = { ...job, status: 'paused' }
    else if (action === 'resume') next = { ...job, status: 'queued' }
    else if (action === 'cancel') {
      const remaining =
        job.target_total -
        job.succeeded_count -
        job.failed_count -
        job.skipped_count
      next = {
        ...job,
        status: 'cancelled',
        skipped_count: job.skipped_count + Math.max(remaining, 0),
        completed_at: '2026-05-04T11:35:00Z',
      }
    } else if (action === 'retry-failed') {
      next = {
        ...job,
        status: 'queued',
        failed_count: 0,
        completed_at: null,
      }
    }
    jobs.set(jobId, next)
    if (action === 'retry-failed') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ job: next, requeued: job.failed_count }),
      })
    } else {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ job: next }),
      })
    }
  })

  return { jobs, postedActions }
}

// ─── Settings navigation helper ────────────────────────────────────────
async function openSettingsAutomatisation(page: Page) {
  await page.locator('[data-testid="nav-settings"]').click()
  await expect(
    page.locator('[data-testid="settings-modal"]'),
  ).toBeVisible({ timeout: 5000 })
  // Le panneau vit désormais dans la modale « Tâches en arrière-plan »
  // (BackgroundTasksModal), ouverte depuis la section GÉNÉRAL via un
  // settings-link-btn — il n'est plus rendu inline sous Automatisation.
  const sidebarItem = page
    .locator('.settings-sidebar-item')
    .filter({ hasText: /Général/i })
  await sidebarItem.click()
  await page
    .locator('.settings-link-btn')
    .filter({ hasText: /Tâches en arrière-plan/i })
    .click()
  await expect(
    page.locator('.bulk-actions-panel'),
  ).toBeVisible({ timeout: 5000 })
}

// ─── Tests ─────────────────────────────────────────────────────────────
test.describe('BulkActionsPanel', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
  })

  test('empty state when /api/bulk-jobs returns no rows', async ({ page }) => {
    await setupBulkJobsMocks(page, [])
    await page.goto('/')
    await waitForAppReady(page)
    await openSettingsAutomatisation(page)

    await expect(page.locator('.bulk-actions-panel__empty')).toBeVisible()
    await expect(page.locator('.bulk-job-row')).toHaveCount(0)
  })

  test('renders one row per job with the right action buttons', async ({
    page,
  }) => {
    await setupBulkJobsMocks(page, [RUNNING, FAILED, COMPLETED])
    await page.goto('/')
    await waitForAppReady(page)
    await openSettingsAutomatisation(page)

    // 3 rows, sorted active-first (running before completed/failed).
    const rows = page.locator('.bulk-job-row')
    await expect(rows).toHaveCount(3)

    // Running job: Pause + Annuler buttons.
    const runningRow = page.locator('.bulk-job-row--running')
    await expect(runningRow.locator('button', { hasText: 'Pause' })).toBeVisible()
    await expect(runningRow.locator('button', { hasText: 'Annuler' })).toBeVisible()
    await expect(
      runningRow.locator('.bulk-job-row__progress-bar'),
    ).toBeVisible()

    // Failed job: retry button, but no Pause/Annuler.
    const failedRow = page.locator('.bulk-job-row--failed')
    await expect(
      failedRow.locator('button', { hasText: /Réessayer|Retry|Reintentar|Erneut/i }),
    ).toBeVisible()
    await expect(failedRow.locator('button', { hasText: 'Pause' })).toHaveCount(0)

    // Completed job: no action buttons (terminal, no failures).
    const completedRow = page.locator('.bulk-job-row--completed')
    await expect(completedRow.locator('button')).toHaveCount(0)
  })

  test('Pause then Reprendre flips status both ways', async ({ page }) => {
    const { postedActions } = await setupBulkJobsMocks(page, [RUNNING])
    await page.goto('/')
    await waitForAppReady(page)
    await openSettingsAutomatisation(page)

    // Pause
    await page.locator('.bulk-job-row--running button', { hasText: 'Pause' }).click()
    await expect(page.locator('.bulk-job-row--paused')).toBeVisible({
      timeout: 5000,
    })

    // Resume
    await page
      .locator('.bulk-job-row--paused button', { hasText: 'Reprendre' })
      .click()
    // After resume, job goes back to "queued" — row class updates to --queued.
    await expect(page.locator('.bulk-job-row--queued')).toBeVisible({
      timeout: 5000,
    })

    expect(postedActions).toEqual([
      { job_id: RUNNING.id, action: 'pause' },
      { job_id: RUNNING.id, action: 'resume' },
    ])
  })

  test('Cancel marks the job as cancelled with skipped counters', async ({
    page,
  }) => {
    await setupBulkJobsMocks(page, [RUNNING])
    await page.goto('/')
    await waitForAppReady(page)
    await openSettingsAutomatisation(page)

    await page.locator('.bulk-job-row--running button', { hasText: 'Annuler' }).click()
    const cancelledRow = page.locator('.bulk-job-row--cancelled')
    await expect(cancelledRow).toBeVisible({ timeout: 5000 })
    // Terminal rows show the result chips (ok/err/skip), not the progress bar.
    // (`.bulk-job-row__counters` n'existe plus — remplacé par __chips.)
    await expect(cancelledRow.locator('.bulk-job-row__chips').first()).toBeVisible()
    await expect(cancelledRow.locator('.bulk-job-row__progress-bar')).toHaveCount(0)
  })

  test('Retry-failed re-queues the job', async ({ page }) => {
    const { postedActions } = await setupBulkJobsMocks(page, [FAILED])
    await page.goto('/')
    await waitForAppReady(page)
    await openSettingsAutomatisation(page)

    await page
      .locator('.bulk-job-row--failed button', {
        hasText: /Réessayer|Retry|Reintentar|Erneut/i,
      })
      .click()
    // After retry the job is queued — row class flips and progress bar
    // returns (counters disappear because it's no longer terminal).
    await expect(page.locator('.bulk-job-row--queued')).toBeVisible({
      timeout: 5000,
    })

    expect(postedActions).toEqual([
      { job_id: FAILED.id, action: 'retry-failed' },
    ])
  })
})
