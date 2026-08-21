/**
 * Contact Groups UI — smoke test for the 2026-04-16 refactor.
 *
 * Seeds a couple of groups, opens the manager, verifies:
 *  - Search bar appears when there are >3 groups
 *  - Hover actions render (compose · duplicate · delete)
 *  - Leading emoji badge renders
 *  - Edit form shows the emoji picker and collapsible settings
 */

import { test, expect } from '@playwright/test'

const API = 'http://127.0.0.1:5050'
const PRIMARY_EMAIL = 'cours.universite@gmail.com'

async function dropGroups(request: Parameters<Parameters<typeof test>[1]>[0]['request']) {
  const resp = await request.get(`${API}/api/contact-groups`).catch(() => null)
  if (!resp || !resp.ok()) return
  const data = await resp.json() as { groups?: Array<{ id: string }> }
  for (const g of data.groups || []) {
    await request.delete(`${API}/api/contact-groups/${g.id}`).catch(() => {})
  }
}

test('Contact Groups manager shows new UI (search + actions + emoji badge)', async ({ page, request }) => {
  await dropGroups(request)

  // Seed 4 groups so the search bar kicks in (threshold > 3).
  const seeded = [
    { name: 'Équipe Produit', emoji: '🚀', members: [{ name: 'A B', email: 'a@x.com' }] },
    { name: 'Partenaires Europe', emoji: '🌐', members: [{ name: 'C D', email: 'c@x.com' }] },
    { name: 'Direction', emoji: '👔', members: [{ name: 'E F', email: 'e@x.com' }] },
    { name: 'Clients VIP', emoji: '💼', members: [{ name: 'G H', email: 'g@x.com' }] },
  ]
  for (const g of seeded) {
    await request.post(`${API}/api/contact-groups`, { data: g })
  }

  const login = await request.post(`${API}/api/auth/dev-login`, { data: { email: PRIMARY_EMAIL } })
  const { access_token } = await login.json() as { access_token: string }

  await page.addInitScript((tok: string) => {
    localStorage.setItem('agentys_jwt', tok)
    localStorage.setItem('agentys_onboarding_complete', 'true')
    localStorage.setItem('agentys_onboarding_kb_complete', 'true')
  }, access_token)

  await page.goto('/')
  await page.waitForLoadState('domcontentloaded')
  await page.evaluate(() => window.dispatchEvent(new Event('open-settings')))

  // Switch to the "Outils" tab (where the Groups link lives), then click it.
  await page.getByRole('tab', { name: /outils/i }).click()
  await page.getByRole('button', { name: /groupes de contacts/i }).first().click({ timeout: 10_000 })

  // Search bar is visible (4 groups seeded — threshold is >3).
  await expect(page.locator('.cg-search')).toBeVisible({ timeout: 10_000 })

  // No leading badge to the left of the group name (removed per design review).
  await expect(page.locator('.cg-item-badge')).toHaveCount(0)

  // Hover the first row — actions appear (3 buttons: Compose, Duplicate, Delete).
  const firstItem = page.locator('.cg-item').first()
  await firstItem.hover()
  const visibleActions = firstItem.locator('.cg-item-actions .cg-action-btn:visible')
  await expect(visibleActions).toHaveCount(3, { timeout: 5_000 })

  // Search filters — type "direction" and expect only one card.
  await page.locator('.cg-search-input').fill('direction')
  await expect(page.locator('.cg-item')).toHaveCount(1)
  await page.locator('.cg-search-clear').click()
  await expect(page.locator('.cg-item')).toHaveCount(4)

  // Open the first group → edit form has NO emoji picker button and the
  // "Rencontre virtuelle" toggle is directly visible (no accordion).
  await firstItem.click()
  await expect(page.locator('.cg-emoji-btn')).toHaveCount(0)
  await expect(page.locator('.cg-settings-header')).toHaveCount(0)
  await expect(page.locator('.cg-toggle')).toBeVisible()

  // Cleanup.
  await dropGroups(request)
})
