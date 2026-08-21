/**
 * FAQ import — UI smoke check.
 *
 * Logs in via /api/auth/dev-login as the primary account, pre-seeds FAQ
 * entries directly in knowledge_entries (simulating what the fixed
 * importFaq handler writes), opens the Training page via the Settings
 * modal, and verifies the seeded FAQs are visible in the Savoir pillar.
 *
 * This proves the read-side fix in TrainingPage.fetchMemory — without it,
 * the seeded FAQs would be invisible because they live in SQLite but not
 * in memoire.md.
 */

import { test, expect } from '@playwright/test'

const API = 'http://127.0.0.1:5050'
const PRIMARY_EMAIL = 'cours.universite@gmail.com'

test('Training page shows FAQs stored in knowledge_entries', async ({ page, request }) => {
  // 1. Clear + seed FAQ rows under the primary account (same account the
  //    dev-server session will land on when Playwright hits the API).
  const before = await request.get(`${API}/api/knowledge/entries?category=FAQ`)
  if (before.ok()) {
    const rows = await before.json() as Array<{ id: string }>
    for (const r of rows) await request.delete(`${API}/api/knowledge/entries/${r.id}`)
  }

  const seedTitles = [
    'Smoke: horaires ouverture',
    'Smoke: remboursement process',
    'Smoke: livraison internationale',
  ]
  for (const title of seedTitles) {
    const r = await request.post(`${API}/api/knowledge/entries`, {
      data: { title, content: `Réponse pour ${title}`, category: 'FAQ' },
    })
    expect(r.ok()).toBeTruthy()
  }

  // 2. Dev-login — produces a JWT the frontend recognizes.
  const loginResp = await request.post(`${API}/api/auth/dev-login`, {
    data: { email: PRIMARY_EMAIL },
  })
  const { access_token } = await loginResp.json() as { access_token: string }

  // 3. Inject the token + onboarding-complete flags so we land on the app shell.
  await page.addInitScript((token: string) => {
    localStorage.setItem('agentys_jwt', token)
    localStorage.setItem('agentys_onboarding_complete', 'true')
    localStorage.setItem('agentys_onboarding_kb_complete', 'true')
  }, access_token)

  await page.goto('/')

  // 4. Open Settings via the custom window event App.tsx listens for.
  await page.waitForLoadState('domcontentloaded')
  await page.evaluate(() => window.dispatchEvent(new Event('open-settings')))

  // 5. Switch to the "Personnalisation" section (where the Training card lives).
  await page.getByRole('tab', { name: /personnalisation/i }).click()

  // 6. Click the Training card inside Settings (first one — the Training card
  //    is the first .settings-training-card in that section).
  const trainingCard = page.locator('.settings-training-card').first()
  await trainingCard.waitFor({ state: 'visible', timeout: 10_000 })
  await trainingCard.click()

  // 7. Switch to the Savoir pillar (PillarNav button).
  const savoirTab = page.getByRole('button', { name: /savoir|knowledge/i }).first()
  await savoirTab.click().catch(() => { /* may already be active */ })

  // 8. Expect all three seeded FAQ titles to appear as .savoir-question inputs.
  await expect.poll(
    async () => page.locator('.savoir-question').evaluateAll(
      (els) => (els as HTMLInputElement[]).map((el) => el.value),
    ),
    { timeout: 15_000, message: 'FAQs from knowledge_entries never showed up in Savoir' },
  ).toEqual(expect.arrayContaining(seedTitles))

  // 9. Cleanup.
  const after = await request.get(`${API}/api/knowledge/entries?category=FAQ`)
  const rows = await after.json() as Array<{ id: string; title: string }>
  for (const r of rows) {
    if (seedTitles.includes(r.title)) await request.delete(`${API}/api/knowledge/entries/${r.id}`)
  }
})
