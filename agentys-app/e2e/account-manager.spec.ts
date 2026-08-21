/**
 * Account Manager E2E Tests
 *
 * Tests for the account management modal: display, account list,
 * add/remove accounts.
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

async function setupAccountMocks(page: Page) {
  await setupBaseMocks(page)

  // Mock /api/accounts with multiple accounts
  await page.route(`${API}/api/accounts`, (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        accounts: [
          { id: 1, email: 'test@gmail.com', provider: 'gmail', status: 'active' },
          { id: 2, email: 'work@outlook.com', provider: 'outlook', status: 'active' },
        ],
      }),
    })
  })
}

async function openAccountManager(page: Page) {
  // Open Settings first, then navigate to Accounts
  await page.keyboard.press('Control+,')
  await expect(page.getByTestId('settings-modal')).toBeVisible()

  // Click on "Compte utilisateur" link in settings (Compte section)
  const accountsLink = page.locator('text=Compte utilisateur').first()
  await accountsLink.click()
}

test.describe('Account Manager - Display', () => {
  test.beforeEach(async ({ page }) => {
    await setupAccountMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should open account manager from settings', async ({ page }) => {
    await openAccountManager(page)

    const accountPanel = page.locator('.account-manager')
    await expect(accountPanel).toBeVisible({ timeout: 5000 })
  })

  test('should display account list', async ({ page }) => {
    await openAccountManager(page)

    const accountPanel = page.locator('.account-manager')
    await expect(accountPanel).toBeVisible({ timeout: 5000 })

    const accountItems = page.locator('.account-item')
    const count = await accountItems.count()
    expect(count).toBeGreaterThan(0)
  })

  test('should display account email and status', async ({ page }) => {
    await openAccountManager(page)

    const accountPanel = page.locator('.account-manager')
    await expect(accountPanel).toBeVisible({ timeout: 5000 })

    await expect(page.locator('text=test@gmail.com')).toBeVisible()
  })

  test('should close account manager with close button', async ({ page }) => {
    await openAccountManager(page)

    const accountPanel = page.locator('.account-manager')
    await expect(accountPanel).toBeVisible({ timeout: 5000 })

    const closeBtn = page.getByLabel('Fermer')
    await closeBtn.click()
    await expect(accountPanel).not.toBeVisible()
  })
})

test.describe('Account Manager - Empty State', () => {
  test('should show empty state when no accounts', async ({ page }) => {
    await setupBaseMocks(page)

    // Override with empty accounts
    await page.route(`${API}/api/accounts`, (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ accounts: [] }),
      })
    })

    await page.goto('/')
    await waitForAppReady(page)
    await openAccountManager(page)

    const accountPanel = page.locator('.account-manager')
    await expect(accountPanel).toBeVisible({ timeout: 5000 })

    const emptyState = page.locator('.account-empty')
    await expect(emptyState).toBeVisible()
  })
})
