import { test, expect } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

test('can type in contact groups member input — edit existing group', async ({ page }) => {
  await setupBaseMocks(page)

  await page.route((url) => url.origin === API && url.pathname === '/api/contact-groups', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        groups: [
          {
            id: 'grp_agentys',
            name: 'Agentys',
            emoji: null,
            description: null,
            label_name: null,
            virtual_meeting: true,
            members: [{ name: 'Alex', email: 'alexandre.simon@hotmail.com' }],
            created_at: '2026-04-01T00:00:00Z',
            updated_at: '2026-04-01T00:00:00Z',
            use_count: 0,
          },
        ],
        total: 1,
      }),
    })
  })

  await page.route((url) => url.origin === API && url.pathname === '/api/contacts/autocomplete', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  })

  await page.route((url) => url.origin === API && url.pathname === '/api/labels', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ labels: [] }) })
  })

  await page.goto('/')
  await waitForAppReady(page)

  await page.keyboard.press('Control+,')
  await page.waitForSelector('.settings-modal, [data-testid="settings-modal"]', { timeout: 5000 })

  await page.locator('.settings-sidebar-item').filter({ hasText: /outils|tools/i }).first().click()
  await page.waitForTimeout(300)

  const groupsBtn = page.locator('.settings-link-btn').filter({ hasText: /groupes de contacts|contact groups/i }).first()
  await groupsBtn.waitFor({ state: 'visible', timeout: 5000 })
  await groupsBtn.scrollIntoViewIfNeeded()
  await groupsBtn.click()

  // Click the existing group card to enter edit mode
  const groupCard = page.locator('.cg-modal').getByText('Agentys').first()
  await groupCard.waitFor({ state: 'visible', timeout: 5000 })
  await groupCard.click()

  // Member input should be visible in edit mode (ContactAutocomplete inside cg-form-card)
  const memberInput = page.locator('.cg-form-member-autocomplete input')
  await memberInput.waitFor({ state: 'visible', timeout: 3000 })
  await memberInput.click()
  await page.waitForTimeout(100)
  // Real keystroke simulation — critical: fill() bypasses keyboard events and would hide focus-trap bugs
  await page.keyboard.type('bob@test.com', { delay: 20 })

  await expect(memberInput).toHaveValue('bob@test.com')
})
