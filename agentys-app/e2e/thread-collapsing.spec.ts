/**
 * Thread Collapsing E2E Tests
 *
 * Vérifie le regroupement Gmail-style des threads dans l'inbox :
 * - Les emails d'un même conversation_id sont regroupés en une seule ligne
 * - Le badge thread count affiche le nombre correct
 * - Les emails sans conversation_id restent individuels
 * - Le clic sur un thread ouvre le détail
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'

const hoursAgo = (hours: number): string => {
  const date = new Date()
  date.setHours(date.getHours() - hours)
  return date.toISOString()
}

// Thread A: 3 emails in same conversation (only latest should show)
// Thread B: 2 emails in same conversation
// Standalone: 2 emails with no conversation_id
const threadEmails = [
  {
    id: 'thread-a-3',
    sender: 'alice@example.com',
    sender_name: 'Alice',
    subject: 'Re: Re: Projet Alpha',
    received_at: hoursAgo(1),
    has_attachments: false,
    conversation_id: 'conv-alpha',
    is_read: true,
    body_preview: 'Troisième message du thread Alpha',
  },
  {
    id: 'thread-a-2',
    sender: 'bob@example.com',
    sender_name: 'Bob',
    subject: 'Re: Projet Alpha',
    received_at: hoursAgo(3),
    has_attachments: false,
    conversation_id: 'conv-alpha',
    is_read: false,
    body_preview: 'Deuxième message du thread Alpha',
  },
  {
    id: 'thread-a-1',
    sender: 'alice@example.com',
    sender_name: 'Alice',
    subject: 'Projet Alpha',
    received_at: hoursAgo(5),
    has_attachments: false,
    conversation_id: 'conv-alpha',
    is_read: false,
    body_preview: 'Premier message du thread Alpha',
  },
  {
    id: 'thread-b-2',
    sender: 'carol@example.com',
    sender_name: 'Carol',
    subject: 'Re: Budget Q1',
    received_at: hoursAgo(2),
    has_attachments: false,
    conversation_id: 'conv-budget',
    is_read: false,
    body_preview: 'Deuxième message du thread Budget',
  },
  {
    id: 'thread-b-1',
    sender: 'dave@example.com',
    sender_name: 'Dave',
    subject: 'Budget Q1',
    received_at: hoursAgo(4),
    has_attachments: true,
    conversation_id: 'conv-budget',
    is_read: true,
    body_preview: 'Premier message du thread Budget',
  },
  {
    id: 'standalone-1',
    sender: 'eve@example.com',
    sender_name: 'Eve',
    subject: 'Rappel formation',
    received_at: hoursAgo(6),
    has_attachments: false,
    conversation_id: null,
    is_read: true,
    body_preview: 'Email sans thread',
  },
  {
    id: 'standalone-2',
    sender: 'frank@example.com',
    sender_name: 'Frank',
    subject: 'Invitation événement',
    received_at: hoursAgo(7),
    has_attachments: false,
    conversation_id: null,
    is_read: true,
    body_preview: 'Autre email sans thread',
  },
]

const threadEmailsResponse = {
  count: threadEmails.length,
  emails: threadEmails,
}

async function setupThreadMocks(page: Page) {
  await setupBaseMocks(page, { emailsResponse: threadEmailsResponse })

  // Mock email detail for any email
  await page.route(
    (url) => url.origin === API && url.pathname.match(/^\/api\/emails\/[^/]+$/) !== null,
    (route, request) => {
      const emailId = new URL(request.url()).pathname.match(/\/api\/emails\/([^/?]+)$/)?.[1]
      const email = threadEmails.find((e) => e.id === emailId) || threadEmails[0]
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...email,
          body: `<p>${email.body_preview}</p>`,
          to: ['test@example.com'],
          cc: [],
        }),
      })
    }
  )

  // Mock thread endpoint
  await page.route(
    (url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/thread$/) !== null,
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ count: 1, emails: [] }),
      })
    }
  )

  // Mock mark read
  await page.route(
    (url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/read$/) !== null,
    (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
    }
  )

  // Mock pending drafts
  await page.route(
    (url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts/by-email'),
    (route) => {
      route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: 'No draft' }) })
    }
  )

  // Mock contacts
  await page.route(
    (url) => url.origin === API && url.pathname.startsWith('/api/contacts'),
    (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
    }
  )
}

test.describe('Thread Collapsing — Gmail-style', () => {
  test.beforeEach(async ({ page }) => {
    await setupThreadMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('affiche uniquement le dernier email de chaque thread', async ({ page }) => {
    const items = page.locator('[data-testid="email-item"]')
    await expect(items.first()).toBeVisible({ timeout: 10000 })

    // 7 emails total, but collapsed: thread-a (3→1) + thread-b (2→1) + 2 standalone = 4 rows
    await expect(items).toHaveCount(4)
  })

  test('le badge thread count affiche le nombre correct', async ({ page }) => {
    const badges = page.locator('.thread-count-badge')
    await expect(page.locator('[data-testid="email-item"]').first()).toBeVisible({ timeout: 10000 })

    // Only 2 badges: thread-a (3) and thread-b (2). Standalone emails have no badge.
    await expect(badges).toHaveCount(2)

    // Get badge texts (sorted for stable assertion)
    const texts = await badges.allTextContents()
    const sorted = texts.map(Number).sort((a, b) => a - b)
    expect(sorted).toEqual([2, 3])
  })

  test('le représentant du thread est le plus récent', async ({ page }) => {
    await expect(page.locator('[data-testid="email-item"]').first()).toBeVisible({ timeout: 10000 })

    // thread-a representative should be "Re: Re: Projet Alpha" (most recent, hoursAgo(1))
    await expect(page.locator('text=Re: Re: Projet Alpha')).toBeVisible()

    // thread-b representative should be "Re: Budget Q1" (most recent, hoursAgo(2))
    await expect(page.locator('text=Re: Budget Q1')).toBeVisible()

    // Older thread members should NOT be visible
    await expect(page.locator('.email-subject:has-text("Projet Alpha")').filter({ hasNotText: 'Re:' })).toHaveCount(0)
    await expect(page.locator('.email-subject:has-text("Budget Q1")').filter({ hasNotText: 'Re:' })).toHaveCount(0)
  })

  test('les emails sans conversation_id restent visibles individuellement', async ({ page }) => {
    await expect(page.locator('[data-testid="email-item"]').first()).toBeVisible({ timeout: 10000 })

    await expect(page.locator('text=Rappel formation')).toBeVisible()
    await expect(page.locator('text=Invitation événement')).toBeVisible()
  })

  test('un thread avec un membre non lu apparaît comme non lu', async ({ page }) => {
    // thread-a: latest (thread-a-3) is read, but thread-a-2 and thread-a-1 are unread
    // The collapsed row should show as unread (merged status)
    const threadARow = page.locator('[data-testid="email-item"]').filter({ hasText: 'Re: Re: Projet Alpha' })
    await expect(threadARow).toBeVisible({ timeout: 10000 })

    // Should have 'unread' class (because unread members exist in the thread)
    const classes = await threadARow.getAttribute('class') || ''
    expect(classes).toContain('unread')
  })

  test('clic sur un thread collapsed ouvre le détail', async ({ page }) => {
    const threadRow = page.locator('[data-testid="email-item"]').filter({ hasText: 'Re: Re: Projet Alpha' })
    await expect(threadRow).toBeVisible({ timeout: 10000 })
    await threadRow.click()

    // Email detail should open (title visible)
    await expect(page.locator('.email-detail-title').first()).toBeVisible({ timeout: 10000 })
  })
})
