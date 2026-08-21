import { expect, test, type Page } from '@playwright/test'
import { mockEmails } from './support/fixtures/mock-data'
import { isApiRoute, setupBaseMocks } from './support/fixtures/setup'

const mobileEmail = {
  ...mockEmails[0],
  id: 'mobile-touch-email-1',
  subject: 'Contrat mobile à ouvrir',
  sender: 'legal@example.com',
  sender_name: 'Legal',
  received_at: new Date('2026-05-31T08:00:00.000Z').toISOString(),
  has_attachments: true,
  conversation_id: null,
  is_read: false,
  body_preview: 'Le contrat est joint à cet email.',
  body: '<p>Bonjour, le contrat est en pièce jointe.</p>',
  body_html: '<p>Bonjour, le contrat est en pièce jointe.</p>',
  to: ['test@example.com'],
  cc: [],
  attachments: [
    {
      id: 'att-mobile-contract',
      filename: 'contrat-mobile.pdf',
      size: 42_000,
      content_type: 'application/pdf',
    },
  ],
}

async function setupMobileEmailMocks(page: Page) {
  let downloadAuthHeader: string | undefined

  await setupBaseMocks(page, {
    emailsResponse: {
      count: 1,
      emails: [mobileEmail],
      has_more: false,
      source: 'mock',
    },
  })

  await page.route((url) => isApiRoute(url) && url.pathname === '/api/emails/mobile-touch-email-1', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mobileEmail),
    })
  })

  await page.route((url) => isApiRoute(url) && url.pathname === '/api/emails/mobile-touch-email-1/read', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
  })

  await page.route((url) => isApiRoute(url) && url.pathname === '/api/emails/mobile-touch-email-1/thread', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ thread: [mobileEmail] }),
    })
  })

  await page.route(
    (url) =>
      isApiRoute(url) &&
      url.pathname === '/api/emails/mobile-touch-email-1/attachments/att-mobile-contract/download',
    (route) => {
      downloadAuthHeader = route.request().headers().authorization
      route.fulfill({
        status: 200,
        contentType: 'application/pdf',
        body: '%PDF-1.4 mobile attachment',
      })
    },
  )

  return {
    getDownloadAuthHeader: () => downloadAuthHeader,
  }
}

test.describe('Mobile touch UX', () => {
  test.use({
    viewport: { width: 390, height: 844 },
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    isMobile: true,
    hasTouch: true,
  })

  test('adapte l’onboarding raccourcis au tactile', async ({ page }) => {
    await setupBaseMocks(page, {
      completeOnboardingV2: false,
      emailsResponse: {
        count: 1,
        emails: [mobileEmail],
        has_more: false,
        source: 'mock',
      },
    })

    await page.goto('/')

    await expect(page.locator('.ob-v2-welcome')).toBeVisible({ timeout: 10000 })
    await page.getByRole('button', { name: "C'est parti" }).click()
    await page.getByRole('button', { name: 'Compris' }).click()

    await expect(page.locator('.ob-v2-card')).toContainText('Sur iPhone, utilisez les boutons')
    await expect(page.locator('.ob-v2-kbd')).toHaveCount(0)

    await page.getByRole('button', { name: 'Ouvrir le composeur' }).click()

    await expect(page.getByTestId('new-message-modal')).toBeVisible({ timeout: 10000 })
    await expect(page.locator('.ob-v2-tip--mobile')).toContainText('Sur mobile, touchez le bouton IA')
    await expect(page.locator('.ob-v2-kbd')).toHaveCount(0)
  })

  test('ouvre un email au premier tap', async ({ page }) => {
    await setupMobileEmailMocks(page)

    await page.goto('/')
    await page.locator('[data-testid="email-list-container"]').waitFor({ state: 'visible' })

    await page.getByTestId('email-item').filter({ hasText: 'Contrat mobile à ouvrir' }).first().click()

    await expect(page.getByRole('region', { name: "Détail de l'email" })).toContainText('Contrat mobile à ouvrir', { timeout: 10000 })
  })

  test('ouvre une pièce jointe PDF en preview mobile avec auth', async ({ page }) => {
    const mocks = await setupMobileEmailMocks(page)

    await page.goto('/')
    await page.locator('[data-testid="email-list-container"]').waitFor({ state: 'visible' })
    await page.getByTestId('email-item').filter({ hasText: 'Contrat mobile à ouvrir' }).first().click()

    const attachment = page.locator('.email-attachment-chip').filter({ hasText: 'contrat-mobile.pdf' }).first()
    await expect(attachment).toBeVisible({ timeout: 10000 })

    const popupPromise = page.waitForEvent('popup')
    await attachment.click()
    const popup = await popupPromise

    await expect.poll(() => mocks.getDownloadAuthHeader()).toBe('Bearer dev:test@example.com')
    await expect.poll(async () => popup.locator('iframe').getAttribute('src')).toContain('blob:')
  })
})
