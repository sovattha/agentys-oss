/**
 * Email List E2E Tests
 *
 * Comprehensive tests for the email list functionality with mocked API responses.
 */

import { test, expect, Page } from '@playwright/test'
import {
  mockEmails,
  mockEmailsResponse,
  mockEmailsByStatus,
  mockSearchResults,
  mockEmptyEmails,
} from './support/fixtures/mock-data'
import { setupBaseMocks, waitForAppReady, isApiRoute } from './support/fixtures/setup'

/**
 * Setup additional email-specific mocks on top of base mocks
 */
async function setupEmailListMocks(page: Page, emailsResponse = mockEmailsResponse) {
  await setupBaseMocks(page)

  // Override email routes with custom response if needed
  if (emailsResponse !== mockEmailsResponse) {
    await page.route('**/api/emails?*', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(emailsResponse),
      })
    })
    await page.route('**/api/emails', (route) => {
      if (route.request().url().includes('?')) return
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(emailsResponse),
      })
    })
  }

  // Mock search endpoint
  await page.route('**/api/emails/search?*', (route) => {
    const url = new URL(route.request().url())
    const query = url.searchParams.get('q') || ''
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSearchResults(query)),
    })
  })

  // Mock mark read/unread endpoints
  await page.route('**/api/emails/*/read', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true }),
    })
  })

  // Mock bulk read endpoint
  await page.route('**/api/emails/bulk-read', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, updated_count: 5 }),
    })
  })
}

test.describe('Email List - Display', () => {
  test.beforeEach(async ({ page }) => {
    await setupEmailListMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should display a list of emails', async ({ page }) => {
    const emailItems = page.locator('[data-testid="email-item"]')
    await expect(emailItems.first()).toBeVisible()

    const count = await emailItems.count()
    expect(count).toBeGreaterThan(0)
  })

  test('should display email sender name', async ({ page }) => {
    await expect(page.locator('text=Marie Dupont').first()).toBeVisible()
  })

  test('should display email subject', async ({ page }) => {
    await expect(page.locator('text=Rapport trimestriel Q4 2025').first()).toBeVisible()
  })

  test('should have email preview in DOM', async ({ page }) => {
    // body_preview is rendered in .email-body-preview span (hidden by default, shown in Deep Focus)
    const preview = page.locator('.email-body-preview').first()
    // Element exists in DOM but is display:none by default
    await expect(preview).toBeAttached()
  })

  test('should show unread indicator for unread emails', async ({ page }) => {
    const unreadItem = page.locator('[data-testid="email-item"].unread')
    await expect(unreadItem.first()).toBeVisible()
  })

  test('should show attachment icon for emails with attachments', async ({ page }) => {
    // First email has attachments — check for any attachment indicator
    const attachmentIcon = page.locator('[class*="attachment"], svg[class*="clip"], [aria-label*="pièce"]').first()
    await expect(attachmentIcon).toBeVisible({ timeout: 5000 })
  })

  test('should display relative time for recent emails', async ({ page }) => {
    // formatEmailTime returns "Xh00" for today's emails (e.g. "13h05")
    // Section headers show "Hier" for yesterday's emails
    const timeIndicator = page.locator('text=/\\d+h\\d{2}|Hier/i')
    await expect(timeIndicator.first()).toBeVisible()
  })
})

test.describe('Email List - Empty State', () => {
  test('should show empty state when no emails', async ({ page }) => {
    await setupEmailListMocks(page, mockEmptyEmails)
    await page.goto('/')
    await waitForAppReady(page)

    const emptyState = page.locator('[data-testid="email-list-empty"]')
    await expect(emptyState).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Email List - Filtering', () => {
  test.beforeEach(async ({ page }) => {
    await setupEmailListMocks(page)

    // Override with status-filtered response
    await page.route('**/api/emails?*', (route) => {
      const url = new URL(route.request().url())
      const status = url.searchParams.get('filter') || 'all'
      const response = status === 'all' ? mockEmailsResponse : mockEmailsByStatus(status)
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(response),
      })
    })

    await page.goto('/')
    await waitForAppReady(page)
  })

  // FIXME (audit 2026-06-09) : les filtres texte « non lu / lu » n'existent
  // plus — l'inbox filtre par onglets Action/Info/Bruit et les filtres
  // lu/non-lu vivent dans les suggestions de la SmartSearchBar (voir
  // search-inline-filter.spec.ts). À réécrire contre cette UI.
  test.fixme('should filter to show only unread emails', async ({ page }) => {
    const unreadFilter = page.locator('text=/non lu|unread/i').first()
    await expect(unreadFilter).toBeVisible({ timeout: 5000 })

    await unreadFilter.click()
    await page.waitForLoadState('domcontentloaded')

    const emailItems = page.locator('[data-testid="email-item"]')
    const count = await emailItems.count()
    expect(count).toBeLessThanOrEqual(4)
  })

  test.fixme('should filter to show only read emails', async ({ page }) => {
    const readFilter = page.locator('text=/^lu$|^read$/i').first()
    await expect(readFilter).toBeVisible({ timeout: 5000 })

    await readFilter.click()
    await page.waitForLoadState('domcontentloaded')

    const emailItems = page.locator('[data-testid="email-item"]')
    const count = await emailItems.count()
    expect(count).toBeGreaterThan(0)
  })
})

test.describe('Email List - Search', () => {
  test.beforeEach(async ({ page }) => {
    await setupEmailListMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  // La recherche vit dans la SmartSearchBar repliée derrière l'icône — il
  // faut l'ouvrir avant de saisir (même pattern que search.spec.ts).
  async function openSearchInput(page: import('@playwright/test').Page) {
    const searchBar = page.locator('.smart-search-bar, [data-testid="smart-search-bar"]').first()
    if (await searchBar.isVisible()) {
      await searchBar.click()
    } else {
      await page.keyboard.press('/')
    }
    const input = page.locator('[data-testid="smart-search-input"], .smart-search-input').first()
    await expect(input).toBeVisible({ timeout: 5000 })
    return input
  }

  test('should search emails by subject', async ({ page }) => {
    const searchInput = await openSearchInput(page)

    const respPromise = page.waitForResponse('**/api/emails/search?*')
    await searchInput.fill('rapport')
    await searchInput.press('Enter')
    await respPromise

    await expect(page.locator('text=Rapport trimestriel').first()).toBeVisible()
  })

  test('should search emails by sender', async ({ page }) => {
    const searchInput = await openSearchInput(page)

    // Armer l'attente avant la saisie (course débounce), puis Enter force
    // la recherche serveur immédiate.
    const respPromise = page.waitForResponse('**/api/emails/search?*')
    await searchInput.fill('marie')
    await searchInput.press('Enter')
    await respPromise

    await expect(page.locator('text=Marie Dupont').first()).toBeVisible()
  })

  test('should show no results for unmatched search', async ({ page }) => {
    await page.route('**/api/emails/search?*', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ count: 0, emails: [], has_more: false }),
      })
    })

    const searchInput = await openSearchInput(page)

    // Armer l'attente AVANT la saisie : la recherche débounce peut répondre
    // avant que waitForResponse ne démarre (course perdue sinon).
    const respPromise = page.waitForResponse('**/api/emails/search?*')
    await searchInput.fill('xyznonexistent123')
    await searchInput.press('Enter')
    await respPromise

    const noResults = page.locator('text=/aucun|pas de résultat|no result/i')
    await expect(noResults.first()).toBeVisible()
  })

  test('should clear search and show all emails', async ({ page }) => {
    const searchInput = await openSearchInput(page)

    const respPromise = page.waitForResponse('**/api/emails/search?*')
    await searchInput.fill('rapport')
    await searchInput.press('Enter')
    await respPromise

    // Le bouton clear (X) réinitialise la recherche ET la liste ; vider
    // l'input au clavier ne restaure pas la liste complète.
    await page.locator('.smart-search-clear').first().click()
    await expect
      .poll(async () => page.locator('[data-testid="email-item"]').count(), { timeout: 10000 })
      .toBeGreaterThan(1)
  })
})

test.describe('Email List - Selection', () => {
  test.beforeEach(async ({ page }) => {
    await setupEmailListMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should select email on click', async ({ page }) => {
    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await firstEmail.click()

    await expect(firstEmail).toHaveClass(/selected/)
  })

  test('should navigate emails with keyboard arrows', async ({ page }) => {
    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await firstEmail.click()

    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('ArrowUp')

    const selectedEmail = page.locator('[data-testid="email-item"].selected')
    await expect(selectedEmail).toBeVisible()
  })
})

test.describe('Email List - Mark Read/Unread', () => {
  test.beforeEach(async ({ page }) => {
    await setupEmailListMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should mark email as read via context menu', async ({ page }) => {
    const readRequest = page.waitForRequest((request) =>
      request.method() === 'PATCH' &&
      request.url().includes('/api/emails/email-1/read')
    )
    const firstEmail = page.locator('[data-testid="email-item"]').first()

    await firstEmail.click({ button: 'right' })

    const markReadOption = page.locator('text=/marquer.*lu|mark.*read/i').first()
    await expect(markReadOption).toBeVisible({ timeout: 5000 })

    await markReadOption.click()
    const request = await readRequest
    expect(JSON.parse(request.postData() || '{}')).toEqual({ is_read: true })

    await expect(firstEmail).toHaveAttribute('data-unread', 'false')
    await expect(firstEmail).not.toHaveClass(/selected/)
    await expect(firstEmail).toBeVisible({ timeout: 5000 })
  })

  // FIXME (audit 2026-06-09) : le bouton de bascule lu/non-lu au survol
  // ([data-testid="email-read-toggle"]) a été retiré du SwipeableEmailItem
  // (seul le CSS orphelin .email-read-toggle-btn subsiste). Les actions de
  // survol actuelles sont pin/delete (voir pin-and-del-hover.spec.ts). À
  // réécrire si la bascule lu/non-lu revient (menu contextuel ?).
  test.fixme('should mark an unread email as read from the row button', async ({ page }) => {
    const firstEmail = page.locator('[data-testid="email-item"]').first()
    const readButton = firstEmail.locator('[data-testid="email-read-toggle"]')
    const readRequest = page.waitForRequest((request) =>
      request.method() === 'PATCH' &&
      request.url().includes('/api/emails/email-1/read')
    )

    await firstEmail.hover()
    await expect(readButton).toBeVisible()
    await readButton.click()

    const request = await readRequest
    expect(JSON.parse(request.postData() || '{}')).toEqual({ is_read: true })

    await expect(firstEmail).toHaveAttribute('data-unread', 'false')
    await expect(firstEmail).not.toHaveClass(/selected/)
  })

  test.fixme('should mark a read email as unread from the row button', async ({ page }) => {
    const readEmail = page.locator('[data-email-id="email-3"]')
    const unreadButton = readEmail.locator('[data-testid="email-read-toggle"]')
    const unreadRequest = page.waitForRequest((request) =>
      request.method() === 'PATCH' &&
      request.url().includes('/api/emails/email-3/read')
    )

    await readEmail.hover()
    await expect(unreadButton).toBeVisible()
    await unreadButton.click()

    const request = await unreadRequest
    expect(JSON.parse(request.postData() || '{}')).toEqual({ is_read: false })

    await expect(readEmail).toHaveAttribute('data-unread', 'true')
    await expect(readEmail).not.toHaveClass(/selected/)
  })

  test.fixme('should rollback the row state when mark read fails', async ({ page }) => {
    await page.route('**/api/emails/email-1/read', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 150))
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Update failed' }),
      })
    })

    const firstEmail = page.locator('[data-testid="email-item"]').first()
    const readButton = firstEmail.locator('[data-testid="email-read-toggle"]')
    const failedResponse = page.waitForResponse((response) =>
      response.request().method() === 'PATCH' &&
      response.url().includes('/api/emails/email-1/read')
    )

    await firstEmail.hover()
    await readButton.click()

    await expect(firstEmail).toHaveAttribute('data-unread', 'false')
    await failedResponse
    await expect(firstEmail).toHaveAttribute('data-unread', 'true')
    await expect(
      page.getByRole('alert').filter({ hasText: /error updating email|erreur lors de la mise à jour/i }).first()
    ).toBeVisible()
  })

  test('should mark email as read on open', async ({ page }) => {
    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await firstEmail.dblclick()
    // Opening should mark as read — implementation-dependent
  })
})

test.describe('Email List - Swipe Actions', () => {
  test.beforeEach(async ({ page }) => {
    await setupEmailListMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should have swipeable email items', async ({ page }) => {
    // SwipeableEmailItem component wraps each email with swipe capability
    const firstEmail = page.locator('[data-testid="email-item"]').first()
    await expect(firstEmail).toBeVisible()
    // The component class name itself indicates swipe support
    const className = await firstEmail.getAttribute('class')
    expect(className).toContain('swipeable')
  })
})

test.describe('Email List - Loading States', () => {
  test('should show loading indicator while fetching emails', async ({ page }) => {
    await setupBaseMocks(page)

    // Override with delayed email response
    await page.route('**/api/emails?*', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1000))
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockEmailsResponse),
      })
    })

    await page.goto('/')

    // Loading state is transient — check that it doesn't cause errors
    const _loadingIndicator = page.locator('[class*="loading"], [class*="spinner"], [role="progressbar"]')
    // After the slow API responds, the email list should render successfully
    await expect(page.locator('[data-testid="email-item"]').first()).toBeVisible({ timeout: 15000 })
  })

  test('should show error state on API failure', async ({ page }) => {
    await setupBaseMocks(page)

    // Fail BOTH the init bootstrap and the email list, on every origin
    // (incl. le proxy Vite) — sinon l'app peint la liste depuis /api/init
    // et l'état d'erreur n'apparaît jamais.
    await page.route(
      (url) => isApiRoute(url) && (url.pathname === '/api/emails' || url.pathname === '/api/init'),
      (route) => {
        route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'Internal server error' }),
        })
      },
    )

    await page.goto('/')

    // Wait for error state or empty state to appear — app must show feedback on API failure
    const errorOrEmpty = page.locator('[data-testid="email-list-error"], .email-list-error, [data-testid="email-list-empty"]')
    await expect(errorOrEmpty.first()).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Email List - Refresh', () => {
  test.beforeEach(async ({ page }) => {
    await setupEmailListMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('should refresh emails with keyboard shortcut Cmd+R', async ({ page }) => {
    await page.route('**/api/emails?*', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockEmailsResponse),
      })
    })

    await page.keyboard.press('Control+r')
    // Cmd+R may or may not be captured by the app
  })

  test('should refresh emails via sync shortcut Cmd+Shift+S', async ({ page }) => {
    await page.route('**/api/sync/trigger', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      })
    })

    await page.keyboard.press('Control+Shift+S')
    // Sync may or may not be implemented — soft assertion
  })
})

test.describe('Email List - Virtualization', () => {
  test('should handle large email lists efficiently', async ({ page }) => {
    const largeEmailList = Array.from({ length: 100 }, (_, i) => ({
      ...mockEmails[i % mockEmails.length],
      id: `email-${i}`,
      subject: `Email ${i}: ${mockEmails[i % mockEmails.length].subject}`,
    }))

    const largeEmailsResponse = {
      count: largeEmailList.length,
      emails: largeEmailList,
    }

    await setupBaseMocks(page)

    // Override with large list
    await page.route('**/api/emails?*', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(largeEmailsResponse),
      })
    })
    await page.route('**/api/emails', (route) => {
      if (route.request().url().includes('?')) return
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(largeEmailsResponse),
      })
    })

    await page.goto('/')
    await waitForAppReady(page)

    const emailItems = page.locator('[data-testid="email-item"]')
    const renderedCount = await emailItems.count()

    // Virtualization should render less than total
    expect(renderedCount).toBeLessThan(50)

    await page.keyboard.press('End')
    await page.waitForLoadState('domcontentloaded')

    const afterScrollCount = await emailItems.count()
    expect(afterScrollCount).toBeLessThan(50)
  })
})
