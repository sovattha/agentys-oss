/**
 * One-off screenshot script for search bar visual review
 */
import { chromium } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050';

(async () => {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })

  await setupBaseMocks(page)

  // Mock search-specific routes
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

  await page.goto('http://localhost:1420')
  await waitForAppReady(page)

  // Open search bar via keyboard shortcut
  await page.locator('body').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press('/')

  const input = page.locator('[data-testid="smart-search-input"]').first()
  await input.waitFor({ state: 'visible', timeout: 8000 })
  await input.click()

  // Wait for dropdown
  const dropdown = page.locator('.search-suggestions-dropdown')
  await dropdown.waitFor({ state: 'visible', timeout: 5000 })

  // Screenshot of full page
  await page.screenshot({ path: 'C:/Users/Alexa/desktop/search-open-full.png', fullPage: false })

  // Screenshot zoomed on the search bar + dropdown area
  const searchBar = page.locator('.smart-search-bar')
  await searchBar.screenshot({ path: 'C:/Users/Alexa/desktop/search-open-zoomed.png' })

  // Also screenshot the dropdown specifically
  await dropdown.screenshot({ path: 'C:/Users/Alexa/desktop/search-dropdown.png' })

  await browser.close()
  console.log('Screenshots saved.')
})()
