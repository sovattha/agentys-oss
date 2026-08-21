import { expect, Page, test } from '@playwright/test'
import { AppPage } from './pages/AppPage'
import { setupBaseMocks, isApiRoute } from './support/fixtures/setup'
import { mockEmails } from './support/fixtures/mock-data'

type Folder = 'inbox' | 'spam' | 'trash' | 'removed'

const makeJourneyEmail = (id: string, subject: string, sender: string, folder: Folder = 'inbox') => ({
  ...mockEmails[0],
  id,
  subject,
  sender,
  sender_name: sender.split('@')[0],
  folder,
  received_at: new Date('2026-05-28T08:30:00.000Z').toISOString(),
  has_attachments: false,
  conversation_id: null,
  is_read: false,
  body_preview: 'Message utilisé pour vérifier un parcours complet entre dossiers.',
})

async function setupFolderJourneyMocks(page: Page) {
  const emailsById = new Map<string, ReturnType<typeof makeJourneyEmail>>([
    ['folder-spam-loop', makeJourneyEmail('folder-spam-loop', 'Signalement spam à vérifier', 'fraud-alert@example.net')],
    ['folder-trash-loop', makeJourneyEmail('folder-trash-loop', 'Suppression à restaurer', 'client-important@example.com')],
  ])

  const responseFor = (folder: Folder) => {
    const emails = Array.from(emailsById.values()).filter(email => email.folder === folder)
    return { count: emails.length, emails, has_more: false, offset: 0, filter: 'all', source: 'mock' }
  }

  await setupBaseMocks(page, { emailsResponse: responseFor('inbox') })

  await page.route((url) => isApiRoute(url) && url.pathname === '/api/emails', (route) => {
    const url = new URL(route.request().url())
    const folder = (url.searchParams.get('folder') || 'inbox') as Folder
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(responseFor(folder)),
    })
  })

  await page.route((url) => isApiRoute(url) && /^\/api\/emails\/[^/]+\/move-to-spam$/.test(url.pathname), async (route) => {
    const id = route.request().url().match(/\/api\/emails\/([^/]+)\/move-to-spam$/)?.[1]
    const email = id ? emailsById.get(decodeURIComponent(id)) : undefined
    if (email) {
      email.folder = 'spam'
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, email_id: id, message: 'Moved to spam' }),
    })
  })

  await page.route((url) => isApiRoute(url) && /^\/api\/emails\/[^/]+\/not-spam$/.test(url.pathname), async (route) => {
    const id = route.request().url().match(/\/api\/emails\/([^/]+)\/not-spam$/)?.[1]
    const email = id ? emailsById.get(decodeURIComponent(id)) : undefined
    if (email) {
      email.folder = 'inbox'
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, email_id: id, message: 'Moved to inbox' }),
    })
  })

  await page.route((url) => isApiRoute(url) && /^\/api\/emails\/[^/]+\/delete$/.test(url.pathname), async (route) => {
    const id = route.request().url().match(/\/api\/emails\/([^/]+)\/delete$/)?.[1]
    const email = id ? emailsById.get(decodeURIComponent(id)) : undefined
    if (email) {
      email.folder = email.folder === 'trash' ? 'removed' : 'trash'
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, email_id: id, message: 'Deleted' }),
    })
  })

  await page.route((url) => isApiRoute(url) && /^\/api\/emails\/[^/]+\/restore$/.test(url.pathname), async (route) => {
    const id = route.request().url().match(/\/api\/emails\/([^/]+)\/restore$/)?.[1]
    const email = id ? emailsById.get(decodeURIComponent(id)) : undefined
    if (email) {
      email.folder = 'inbox'
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, email_id: id, message: 'Restored' }),
    })
  })

  return {
    getFolder: (id: string) => emailsById.get(id)?.folder,
  }
}

async function rowBySubject(page: Page, subject: string) {
  return page.getByTestId('email-item').filter({ hasText: subject }).first()
}

async function openContextMenu(page: Page, subject: string) {
  const row = await rowBySubject(page, subject)
  await expect(row).toBeVisible({ timeout: 10000 })
  await row.click({ button: 'right' })
  await expect(page.locator('.email-context-menu')).toBeVisible({ timeout: 5000 })
}

test.describe('Parcours complets dossiers/actions', () => {
  test('Inbox → Spam → Pas un indésirable → Inbox', async ({ page }) => {
    const state = await setupFolderJourneyMocks(page)

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    await openContextMenu(page, 'Signalement spam à vérifier')
    await page.getByRole('menuitem', { name: /signaler comme spam/i }).click()
    await expect.poll(() => state.getFolder('folder-spam-loop')).toBe('spam')
    await expect(await rowBySubject(page, 'Signalement spam à vérifier')).toBeHidden({ timeout: 5000 })

    await app.navigateToSpam()
    await expect(await rowBySubject(page, 'Signalement spam à vérifier')).toBeVisible({ timeout: 10000 })

    await openContextMenu(page, 'Signalement spam à vérifier')
    await page.getByRole('menuitem', { name: /pas un indésirable/i }).click()
    await expect.poll(() => state.getFolder('folder-spam-loop')).toBe('inbox')
    await expect(await rowBySubject(page, 'Signalement spam à vérifier')).toBeHidden({ timeout: 5000 })

    await app.navigateToInbox()
    await expect(await rowBySubject(page, 'Signalement spam à vérifier')).toBeVisible({ timeout: 10000 })
  })

  test('Inbox → Corbeille → Restaurer → Inbox', async ({ page }) => {
    const state = await setupFolderJourneyMocks(page)

    const app = new AppPage(page)
    await app.goto()
    await app.waitForReady()

    await openContextMenu(page, 'Suppression à restaurer')
    await page.getByRole('menuitem', { name: /^supprimer$/i }).click()
    await expect.poll(() => state.getFolder('folder-trash-loop')).toBe('trash')
    await expect(await rowBySubject(page, 'Suppression à restaurer')).toBeHidden({ timeout: 5000 })

    await app.navigateToTrash()
    await expect(await rowBySubject(page, 'Suppression à restaurer')).toBeVisible({ timeout: 10000 })

    await openContextMenu(page, 'Suppression à restaurer')
    await page.getByRole('menuitem', { name: /restaurer/i }).click()
    await expect.poll(() => state.getFolder('folder-trash-loop')).toBe('inbox')
    await expect(await rowBySubject(page, 'Suppression à restaurer')).toBeHidden({ timeout: 5000 })

    await app.navigateToInbox()
    await expect(await rowBySubject(page, 'Suppression à restaurer')).toBeVisible({ timeout: 10000 })
  })
})
