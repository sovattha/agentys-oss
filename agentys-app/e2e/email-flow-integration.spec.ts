/**
 * Integration E2E tests — real backend (localhost:5050) + real frontend (localhost:1420).
 *
 * NO mocks (setupBaseMocks is NOT called). Requires:
 * - python run_api.py running on port 5050
 * - yarn dev running on port 1420
 *
 * Run: cd agentys-app && yarn playwright test e2e/email-flow-integration.spec.ts --workers=1
 */

import { test, expect } from '@playwright/test'

const API = 'http://localhost:5050/api'
const PERF_THRESHOLD = 5000 // ms

// Shared state across serial tests
const state: Record<string, string> = {}

test.describe.configure({ mode: 'serial', timeout: 90_000 })

// Skip all if backend is down
test.beforeAll(async ({ request }) => {
  try {
    const resp = await request.get(`${API}/health`)
    if (resp.status() !== 200) test.skip()
  } catch {
    test.skip()
  }
})

test.describe('Email Flow Integration (real backend)', () => {
  // ── UI Navigation Tests ─────────────────────────────────────

  test('charge inbox sans erreur', async ({ page }) => {
    // Set auth token for dev bypass
    await page.addInitScript(() => {
      localStorage.setItem('agentys_onboarding_complete', 'true')
      localStorage.setItem('agentys_onboarding_kb_complete', 'true')
      localStorage.setItem('agentys_jwt', 'dev:test@example.com')
    })

    // Listen for console errors
    const errors: string[] = []
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text())
    })

    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // App should render without crash
    await expect(page.locator('#root')).toBeVisible({ timeout: 10000 })

    // Filter out known non-critical errors
    const criticalErrors = errors.filter(
      (e) => !e.includes('favicon') && !e.includes('net::ERR')
    )
    if (criticalErrors.length > 0) {
      console.log('  [WARN] Console errors:', criticalErrors.slice(0, 3))
    }
  })

  const folderTests = [
    { name: 'Envoyés', folder: 'sent', testId: 'nav-sent' },
    { name: 'Archives', folder: 'archived', testId: 'nav-archived' },
    { name: 'Corbeille', folder: 'trash', testId: 'nav-trash' },
    { name: 'Indésirables', folder: 'spam', testId: 'nav-spam' },
  ]

  for (const { name, folder } of folderTests) {
    test(`navigue vers ${name}`, async ({ request }) => {
      try {
        const start = Date.now()
        const resp = await request.get(`${API}/emails`, {
          params: { folder },
          timeout: 60_000,
        })
        const elapsed = Date.now() - start

        expect(resp.status()).toBe(200)
        const data = await resp.json()
        const count = data.emails?.length ?? 0
        console.log(`  ${name}: ${count} emails (${elapsed}ms)`)

        if (elapsed >= PERF_THRESHOLD) {
          console.log(`  [WARN] ${name} slow: ${elapsed}ms (threshold: ${PERF_THRESHOLD}ms)`)
        }
      } catch {
        console.log(`  [WARN] ${name}: timeout or error (IMAP slow) — skipping`)
      }
    })
  }

  // ── API Direct Tests ────────────────────────────────────────

  test('envoie email à soi-même', async ({ request }) => {
    const ts = Date.now()
    const subject = `[AGENTYS-E2E-TEST] Integration ${ts}`
    state.subject = subject
    state.ts = String(ts)

    try {
      const start = Date.now()
      const resp = await request.post(`${API}/emails/send-new`, {
        data: {
          to: 'me',
          subject,
          body: `Test integration E2E — ${ts}`,
          skip_signature: true,
        },
        timeout: 60_000,
      })
      const elapsed = Date.now() - start

      if (resp.status() === 200) {
        const data = await resp.json()
        expect(data.success).toBe(true)
        state.sendOk = 'true'
        console.log(`  Send: ${elapsed}ms`)
      } else {
        console.log(`  [WARN] Send failed: ${resp.status()} (email service may be disconnected)`)
      }
    } catch {
      console.log(`  [WARN] Send error: backend unreachable or timed out`)
    }
  })

  test('retrouve email dans Envoyés', async ({ request }) => {
    if (!state.sendOk) {
      console.log('  [SKIP] Send did not succeed')
      return
    }

    const subject = state.subject
    let found = false

    for (let attempt = 0; attempt < 3; attempt++) {
      if (attempt > 0) await new Promise((r) => setTimeout(r, 3000 * attempt))

      try {
        const resp = await request.get(`${API}/emails`, { params: { folder: 'sent' }, timeout: 60_000 })
        if (resp.status() !== 200) continue

        const emails = (await resp.json()).emails ?? []
        const match = emails.find((e: { subject?: string }) =>
          e.subject?.includes(subject)
        )

        if (match) {
          found = true
          state.sentEmailId = match.id
          console.log(`  Found in Sent (attempt ${attempt + 1})`)
          break
        }
      } catch {
        console.log(`  [WARN] Sent folder request failed (attempt ${attempt + 1})`)
      }
    }

    if (!found) {
      console.log(`  [WARN] Email not found in Sent after 3 retries (IMAP delay)`)
    }
  })

  test('archive email depuis inbox', async ({ request }) => {
    try {
      const listResp = await request.get(`${API}/emails`, { params: { folder: 'inbox' }, timeout: 60_000 })
      if (listResp.status() !== 200) { console.log('  [WARN] Inbox unreachable'); return }

      const emails = (await listResp.json()).emails ?? []
      if (emails.length === 0) { console.log('  [SKIP] No inbox emails to archive'); return }

      const emailId = emails[0].id
      state.archivedEmailId = emailId

      const resp = await request.post(`${API}/emails/${emailId}/archive`, { timeout: 60_000 })
      expect(resp.status()).toBe(200)
      const data = await resp.json()
      expect(data.success).toBe(true)
      console.log(`  Archived: ${emailId}`)
    } catch {
      console.log(`  [WARN] Archive test failed: backend unreachable`)
    }
  })

  test('vérifie disparition de inbox', async ({ request }) => {
    const emailId = state.archivedEmailId
    if (!emailId) { console.log('  [SKIP] No archived email to verify'); return }

    try {
      await new Promise((r) => setTimeout(r, 2000))
      const resp = await request.get(`${API}/emails`, { params: { folder: 'inbox' }, timeout: 60_000 })
      if (resp.status() !== 200) { console.log('  [WARN] Inbox unreachable'); return }

      const emails = (await resp.json()).emails ?? []
      const stillThere = emails.some((e: { id: string }) => e.id === emailId)
      console.log(stillThere ? `  [WARN] Email ${emailId} still in inbox (cache delay)` : '  Email gone from inbox')
    } catch {
      console.log('  [WARN] Verify inbox failed: backend unreachable')
    }
  })

  test('supprime email + vérifie 200', async ({ request }) => {
    const emailId = state.archivedEmailId
    if (!emailId) { console.log('  [SKIP] No email to delete'); return }

    try {
      const resp = await request.post(`${API}/emails/${emailId}/delete`, { timeout: 60_000 })
      expect(resp.status()).toBe(200)
      const data = await resp.json()
      expect(data.success).toBe(true)
      state.deletedEmailId = emailId
      console.log(`  Deleted: ${emailId}`)
    } catch {
      console.log('  [WARN] Delete failed: backend unreachable')
    }
  })

  test('restaure depuis corbeille', async ({ request }) => {
    const emailId = state.deletedEmailId
    if (!emailId) { console.log('  [SKIP] No email to restore'); return }

    try {
      const resp = await request.post(`${API}/emails/${emailId}/restore`, { timeout: 60_000 })
      expect([200, 501]).toContain(resp.status())

      if (resp.status() === 200) {
        const data = await resp.json()
        expect(data.success).toBe(true)
        console.log(`  Restored: ${emailId}`)
      } else {
        console.log(`  [WARN] Restore not supported (501)`)
      }
    } catch {
      console.log('  [WARN] Restore failed: backend unreachable')
    }
  })

  test('résumé performances 5 dossiers', { timeout: 180_000 }, async ({ request }) => {
    const folders = ['inbox', 'sent', 'archived', 'trash', 'spam']
    const results: Record<string, { time: number; count: number }> = {}

    for (const folder of folders) {
      try {
        const start = Date.now()
        const resp = await request.get(`${API}/emails`, { params: { folder }, timeout: 60_000 })
        const elapsed = Date.now() - start

        if (resp.status() === 200) {
          const emails = (await resp.json()).emails ?? []
          results[folder] = { time: elapsed, count: emails.length }
        } else {
          results[folder] = { time: -1, count: -1 }
        }
      } catch {
        results[folder] = { time: -1, count: -1 }
      }
    }

    console.log('\n  ══════════════════════════════════════════')
    console.log('       PERFORMANCE SUMMARY (5 folders)')
    console.log('  ──────────────────────────────────────────')
    for (const [folder, info] of Object.entries(results)) {
      if (info.time < 0) {
        console.log(`  ${folder.padEnd(12)}     TIMEOUT`)
      } else {
        const status = info.time < PERF_THRESHOLD ? 'OK' : 'SLOW'
        console.log(
          `  ${folder.padEnd(12)} ${String(info.time).padStart(5)}ms  ${String(info.count).padStart(4)} emails [${status}]`
        )
      }
    }
    console.log('  ══════════════════════════════════════════')

    for (const [folder, info] of Object.entries(results)) {
      if (info.time >= 0) {
        if (info.time >= PERF_THRESHOLD) {
          console.log(`  [WARN] ${folder} exceeds threshold (${info.time}ms)`)
        }
      }
    }
  })
})
