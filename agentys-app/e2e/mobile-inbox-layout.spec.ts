import { expect, test } from '@playwright/test'
import { mockEmails } from './support/fixtures/mock-data'
import { setupBaseMocks } from './support/fixtures/setup'

test.describe('Mobile inbox layout', () => {
  test('keeps the collapsed nav compact and lets the inbox fill the screen', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await setupBaseMocks(page, {
      emailsResponse: {
        count: mockEmails.length,
        emails: mockEmails,
      },
    })

    await page.goto('/')
    await page.locator('[data-testid="email-list-container"]').waitFor({ state: 'visible' })

    const sidebarBox = await page.locator('[data-testid="sidebar"]').boundingBox()
    const mainBox = await page.locator('[data-testid="app-main"]').boundingBox()
    const listPanelBox = await page.locator('.email-list-panel').boundingBox()
    const listContainerBox = await page.locator('[data-testid="email-list-container"]').boundingBox()

    expect(sidebarBox).not.toBeNull()
    expect(mainBox).not.toBeNull()
    expect(listPanelBox).not.toBeNull()
    expect(listContainerBox).not.toBeNull()

    expect(sidebarBox!.height).toBeLessThanOrEqual(64)
    expect(mainBox!.x).toBeLessThan(8)
    expect(listPanelBox!.height).toBeGreaterThan(760)
    expect(listContainerBox!.y + listContainerBox!.height).toBeGreaterThan(820)

    await page.locator('.sidebar-logo-toggle').click()
    await expect(page.locator('[data-testid="nav-inbox"]')).toBeVisible()

    const expandedSidebarBox = await page.locator('[data-testid="sidebar"]').boundingBox()
    expect(expandedSidebarBox).not.toBeNull()
    expect(expandedSidebarBox!.width).toBeGreaterThan(240)
    expect(expandedSidebarBox!.height).toBeGreaterThan(800)
  })
})
