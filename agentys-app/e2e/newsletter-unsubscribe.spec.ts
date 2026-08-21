/**
 * Newsletter Unsubscribe E2E Tests
 *
 * Vérifie que le bouton X appelle POST /newsletters/unsubscribe-and-purge
 * qui enchaîne unsubscribe distant (cascade POST RFC 8058 → POST vide → GET
 * → mailto), blocage local du sender, et purge des emails.
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

const mockNewsletters = {
  newsletters: [
    {
      domain: 'uber.com',
      sender: 'noreply@uber.com',
      service_name: 'Uber',
      email_count: 5,
      last_subject: 'Des proches se déplacent? Prenez-les en main!',
      unsubscribe_url: 'https://uber.com/unsubscribe?id=abc123',
      unsubscribe_mailto: '',
      can_auto_unsubscribe: true,
    },
    {
      domain: 'email.claude.com',
      sender: 'no-reply@email.claude.com',
      service_name: 'Claude Team',
      email_count: 4,
      last_subject: 'Introducing Claude Sonnet 4.6',
      unsubscribe_url: 'https://email.claude.com/unsubscribe?id=xyz',
      unsubscribe_mailto: '',
      can_auto_unsubscribe: false, // manual unsubscribe only
    },
    {
      domain: 'paypal.com',
      sender: 'service@paypal.com',
      service_name: 'PayPal',
      email_count: 3,
      last_subject: 'Votre relevé mensuel',
      unsubscribe_url: '', // no unsubscribe URL
      unsubscribe_mailto: '',
      can_auto_unsubscribe: false,
    },
  ],
}

const bothOrigins = (url: URL) => url.origin === API || url.origin === 'http://localhost:5050'

async function setupMocks(page: Page) {
  await setupBaseMocks(page)

  await page.route((url) => bothOrigins(url) && url.pathname === '/api/settings', (route) => {
    route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(route.request().method() === 'GET' ? { auto_draft_enabled: true, theme: 'default' } : { success: true }),
    })
  })
  await page.route((url) => bothOrigins(url) && url.pathname === '/api/my-style', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ style: null }) })
  })
}

async function openSettings(page: Page) {
  await page.keyboard.press('Control+,')
  await page.locator('.settings-modal, [data-testid="settings-modal"]').first().waitFor({ state: 'visible', timeout: 10000 })
}

async function openNewslettersModal(page: Page) {
  await openSettings(page)
  // Navigate to Tools section (id='outils') — text varies by locale
  const toolsTab = page.locator('.settings-sidebar-item').nth(2) // Tools is 3rd sidebar item (index 2)
  await toolsTab.click()
  // Click the newsletters button — match any locale (FR: Infolettres, EN: Newsletters, DE: Newsletter, ES: Boletines)
  const newslettersBtn = page.locator('.settings-link-btn').filter({ hasText: /newsletter|infolettre|boletine/i })
  await newslettersBtn.waitFor({ state: 'visible', timeout: 5000 })
  await newslettersBtn.click()
  await page.locator('.newsletters-modal').waitFor({ state: 'visible', timeout: 10000 })
}

test.describe('Newsletter Unsubscribe — X button flow', () => {
  test('clicking X on auto-unsubscribable newsletter calls POST /newsletters/unsubscribe-and-purge with sender + url', async ({ page }) => {
    await setupMocks(page)

    await page.route((url) => bothOrigins(url) && url.pathname === '/api/newsletters', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockNewsletters) })
      }
    })

    const purgeCalls: { url: string; body: string }[] = []
    await page.route((url) => bothOrigins(url) && url.pathname === '/api/newsletters/unsubscribe-and-purge', (route) => {
      purgeCalls.push({ url: route.request().url(), body: route.request().postData() || '' })
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          unsubscribe_method: 'rfc8058_post',
          status_code: 200,
          blocked: true,
          deleted_count: 5,
          message: 'Désabonnement confirmé (RFC 8058)',
        }),
      })
    })

    await page.goto('/')
    await waitForAppReady(page)
    await openNewslettersModal(page)

    const uberItem = page.locator('.nl-item').filter({ hasText: 'Uber' })
    await expect(uberItem).toBeVisible()

    await uberItem.locator('.nl-unsub-btn').click()
    await expect(uberItem).toBeHidden({ timeout: 10000 })

    expect(purgeCalls).toHaveLength(1)
    const body = JSON.parse(purgeCalls[0].body)
    expect(body.sender).toBe('noreply@uber.com')
    expect(body.unsubscribe_url).toBe('https://uber.com/unsubscribe?id=abc123')
  })

  test('clicking X on newsletter WITHOUT unsubscribe URL still calls /unsubscribe-and-purge (backend handles block+delete)', async ({ page }) => {
    await setupMocks(page)

    await page.route((url) => bothOrigins(url) && url.pathname === '/api/newsletters', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockNewsletters) })
      }
    })

    const purgeCalls: string[] = []
    await page.route((url) => bothOrigins(url) && url.pathname === '/api/newsletters/unsubscribe-and-purge', (route) => {
      purgeCalls.push(route.request().postData() || '')
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          unsubscribe_method: 'blocked_only',
          status_code: null,
          blocked: true,
          deleted_count: 3,
          message: 'Désabonnement distant impossible — expéditeur bloqué localement',
        }),
      })
    })

    await page.goto('/')
    await waitForAppReady(page)
    await openNewslettersModal(page)

    const paypalItem = page.locator('.nl-item').filter({ hasText: 'PayPal' })
    await expect(paypalItem).toBeVisible()
    await paypalItem.locator('.nl-unsub-btn').click()
    await expect(paypalItem).toBeHidden({ timeout: 10000 })

    expect(purgeCalls).toHaveLength(1)
    const body = JSON.parse(purgeCalls[0])
    expect(body.sender).toBe('service@paypal.com')
    expect(body.unsubscribe_url).toBeUndefined()
  })

  test('newsletter with unsubscribe_url but can_auto_unsubscribe=false sends the URL to the server (cascade decides)', async ({ page }) => {
    await setupMocks(page)

    await page.route((url) => bothOrigins(url) && url.pathname === '/api/newsletters', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockNewsletters) })
      }
    })

    const purgeCalls: string[] = []
    await page.route((url) => bothOrigins(url) && url.pathname === '/api/newsletters/unsubscribe-and-purge', (route) => {
      purgeCalls.push(route.request().postData() || '')
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          unsubscribe_method: 'http_get',
          status_code: 200,
          blocked: true,
          deleted_count: 4,
          message: 'Désabonnement confirmé (GET)',
        }),
      })
    })

    await page.goto('/')
    await waitForAppReady(page)
    await openNewslettersModal(page)

    const claudeItem = page.locator('.nl-item').filter({ hasText: 'Claude Team' })
    await expect(claudeItem).toBeVisible()
    await claudeItem.locator('.nl-unsub-btn').click()
    await expect(claudeItem).toBeHidden({ timeout: 10000 })

    expect(purgeCalls).toHaveLength(1)
    const body = JSON.parse(purgeCalls[0])
    expect(body.sender).toBe('no-reply@email.claude.com')
    expect(body.unsubscribe_url).toBe('https://email.claude.com/unsubscribe?id=xyz')
  })

  test('bulk delete button calls /newsletters/bulk-delete for all newsletters', async ({ page }) => {
    await setupMocks(page)

    // Always return newsletters for GET
    await page.route((url) => bothOrigins(url) && url.pathname === '/api/newsletters', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockNewsletters) })
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) })
      }
    })

    const bulkDeleteCalls: string[] = []
    await page.route((url) => bothOrigins(url) && url.pathname === '/api/newsletters/bulk-delete', (route) => {
      bulkDeleteCalls.push(route.request().postData() || '')
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ deleted_count: 12, message: '12 emails deleted' }) })
    })

    await page.goto('/')
    await waitForAppReady(page)
    await openNewslettersModal(page)

    // Click the red bulk delete button (2 clicks needed — first shows confirm, second executes)
    const bulkBtn = page.locator('.nl-bulk-delete-btn')
    await expect(bulkBtn).toBeVisible()
    await bulkBtn.click()
    // Confirm step
    const [bulkDeleteResponse] = await Promise.all([
      page.waitForResponse((resp) => resp.url().includes('/api/newsletters/bulk-delete')),
      bulkBtn.click(),
    ])
    expect(bulkDeleteResponse.status()).toBe(200)

    // ASSERT: bulk-delete was called with older_than_days: 0 (delete all)
    expect(bulkDeleteCalls).toHaveLength(1)
    expect(JSON.parse(bulkDeleteCalls[0]).older_than_days).toBe(0)
  })
})
