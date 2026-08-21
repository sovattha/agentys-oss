/**
 * One-off screenshot for search visual review
 */
import { test } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

test('capture search bar screenshot', async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    deviceScaleFactor: 2,
  })
  const page = await context.newPage()

  await setupBaseMocks(page)
  await page.route(
    (url) => url.origin === API && url.pathname === '/api/contacts/autocomplete',
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )
  await page.route(
    (url) => url.origin === API && url.pathname === '/api/emails/search/suggestions',
    (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ success: true, senders: [], subjects: [], labels: [] }),
    }),
  )

  await page.goto('/')
  await waitForAppReady(page)

  // Open search
  await page.locator('body').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press('/')
  const input = page.locator('[data-testid="smart-search-input"]').first()
  await input.waitFor({ state: 'visible', timeout: 8000 })
  await input.click()

  const dropdown = page.locator('.search-suggestions-dropdown')
  await dropdown.waitFor({ state: 'visible', timeout: 5000 })

  // Full page @2x
  await page.screenshot({ path: 'C:/Users/Alexa/desktop/search-full-2x.png' })
  // Dropdown only @2x
  await dropdown.screenshot({ path: 'C:/Users/Alexa/desktop/search-dropdown-2x.png' })

  await context.close()
})
