import { expect, test } from '@playwright/test'
import { setupBaseMocks, waitForAppReady, isApiRoute } from './support/fixtures/setup'
import { mockEmails } from './support/fixtures/mock-data'

const protectedAttachmentEmail = {
  ...mockEmails[0],
  id: 'protected-attachment-1',
  subject: 'Contrat confidentiel à télécharger',
  sender: 'legal@example.com',
  sender_name: 'Legal',
  received_at: new Date('2026-05-28T09:00:00.000Z').toISOString(),
  has_attachments: true,
  conversation_id: null,
  is_read: false,
  body_preview: 'Le contrat est joint à cet email.',
  body: '<p>Bonjour, le contrat signé est en pièce jointe.</p>',
  body_html: '<p>Bonjour, le contrat signé est en pièce jointe.</p>',
  to: ['test@example.com'],
  cc: [],
  attachments: [
    {
      id: 'att-secret-contract',
      filename: 'contrat-confidentiel.pdf',
      size: 42_000,
      content_type: 'application/pdf',
    },
  ],
}

test('Pièce jointe protégée — téléchargement via API authentifiée', async ({ page }) => {
  let downloadAuthHeader: string | undefined

  await setupBaseMocks(page, {
    emailsResponse: {
      count: 1,
      emails: [protectedAttachmentEmail],
      has_more: false,
      source: 'mock',
    },
  })

  await page.route((url) => isApiRoute(url) && url.pathname === '/api/emails/protected-attachment-1', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(protectedAttachmentEmail),
    })
  })

  await page.route((url) => isApiRoute(url) && url.pathname === '/api/emails/protected-attachment-1/read', (route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
  })

  await page.route((url) => isApiRoute(url) && url.pathname === '/api/emails/protected-attachment-1/thread', (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ thread: [protectedAttachmentEmail] }),
    })
  })

  await page.route(
    (url) =>
      isApiRoute(url) &&
      url.pathname === '/api/emails/protected-attachment-1/attachments/att-secret-contract/download',
    (route) => {
      downloadAuthHeader = route.request().headers().authorization
      route.fulfill({
        status: 200,
        contentType: 'application/pdf',
        body: '%PDF-1.4 protected attachment',
      })
    },
  )

  await page.goto('/')
  await waitForAppReady(page)

  await page.getByTestId('email-item').filter({ hasText: 'Contrat confidentiel à télécharger' }).first().click()

  const attachment = page.locator('.email-attachment-chip').filter({ hasText: 'contrat-confidentiel.pdf' }).first()
  await expect(attachment).toBeVisible({ timeout: 10000 })
  await attachment.click()

  await expect.poll(() => downloadAuthHeader).toBe('Bearer dev:test@example.com')
})
