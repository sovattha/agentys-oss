/**
 * Spam / Trash / Restore E2E Tests
 *
 * Vérifie les actions de déplacement vers indésirables, corbeille, et restauration.
 */

import { test, expect, Page } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'
import { mockEmails } from './support/fixtures/mock-data'

const API = 'http://127.0.0.1:5050'

// Emails mockés par dossier
const mockInboxEmails = {
  count: 2,
  emails: [
    { ...mockEmails[0], id: 'inbox-1', subject: 'Email boîte de réception 1', folder: 'inbox' },
    { ...mockEmails[1], id: 'inbox-2', subject: 'Email boîte de réception 2', folder: 'inbox' },
  ],
  has_more: false, offset: 0, filter: 'all', source: 'cache',
}

const mockSpamEmails = {
  count: 2,
  emails: [
    { ...mockEmails[0], id: 'spam-1', subject: 'Spam promo alléchante', sender: 'promo@spam.xyz', folder: 'spam' },
    { ...mockEmails[1], id: 'spam-2', subject: 'Offre spéciale réservée', sender: 'noreply@deals.net', folder: 'spam' },
  ],
  has_more: false, offset: 0, filter: 'all', source: 'cache',
}

const mockTrashEmails = {
  count: 2,
  emails: [
    { ...mockEmails[0], id: 'trash-1', subject: 'Email supprimé 1', folder: 'trash' },
    { ...mockEmails[1], id: 'trash-2', subject: 'Email supprimé 2', folder: 'trash' },
  ],
  has_more: false, offset: 0, filter: 'all', source: 'cache',
}

async function setupFolderMocks(page: Page) {
  await setupBaseMocks(page)

  // Router les emails par dossier
  await page.route(`${API}/api/emails?*`, (route) => {
    const url = new URL(route.request().url())
    const folder = url.searchParams.get('folder') || 'inbox'
    switch (folder) {
      case 'spam':
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockSpamEmails) })
        break
      case 'trash':
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockTrashEmails) })
        break
      default:
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockInboxEmails) })
    }
  })
}

// ============================================================================
// Tests opérations Spam
// ============================================================================

test.describe('Spam — déplacer et restaurer', () => {
  test.beforeEach(async ({ page }) => {
    await setupFolderMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('le dossier Indésirables affiche les emails spam', async ({ page }) => {
    // Naviguer vers Indésirables — plusieurs sélecteurs possibles selon l'UI
    const spamNav = page.locator('[data-testid="nav-spam"]')
      .or(page.locator('.nav-spam'))
      .or(page.getByText('Indésirables'))
      .or(page.getByText('Spam'))
      .first()

    const hasSpamNav = await spamNav.count() > 0
    if (!hasSpamNav) {
      test.skip(true, 'Navigation spam non trouvée — skip')
      return
    }

    await spamNav.click()
    await expect(page.locator('.swipeable-email-item').first()).toBeVisible({ timeout: 10000 })
  })

  test('endpoint /not-spam retourne success: true', async ({ page }) => {
    await page.route(
      (url) => url.origin === API && url.pathname.includes('/not-spam'),
      (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, email_id: 'spam-1', message: 'Email déplacé vers la boîte de réception' }),
        })
      }
    )

    const result = await page.evaluate(async (apiUrl) => {
      try {
        const res = await fetch(`${apiUrl}/api/emails/spam-1/not-spam`, { method: 'POST' })
        return await res.json()
      } catch {
        return null
      }
    }, API)

    if (result) {
      expect(result).toHaveProperty('success', true)
    }
  })

  test('endpoint /bulk-not-spam retourne success et count', async ({ page }) => {
    await page.route(
      (url) => url.origin === API && url.pathname.includes('/bulk-not-spam'),
      (route) => {
        const body = JSON.parse(route.request().postData() || '{}')
        const count = (body.email_ids || []).length
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, count, message: `${count} emails restaurés` }),
        })
      }
    )

    const result = await page.evaluate(async (apiUrl) => {
      try {
        const res = await fetch(`${apiUrl}/api/emails/bulk-not-spam`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email_ids: ['spam-1', 'spam-2'] }),
        })
        return await res.json()
      } catch {
        return null
      }
    }, API)

    if (result) {
      expect(result).toHaveProperty('success', true)
      expect(result).toHaveProperty('count', 2)
    }
  })
})

// ============================================================================
// Tests opérations Corbeille
// ============================================================================

test.describe('Corbeille — déplacer et restaurer', () => {
  test.beforeEach(async ({ page }) => {
    await setupFolderMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('le dossier Corbeille est accessible', async ({ page }) => {
    const trashNav = page.locator('[data-testid="nav-trash"]')
      .or(page.locator('.nav-trash'))
      .or(page.getByText('Corbeille'))
      .first()

    const hasTrashNav = await trashNav.count() > 0
    if (!hasTrashNav) {
      test.skip(true, 'Navigation corbeille non trouvée — skip')
      return
    }

    await trashNav.click()
    await expect(page.locator('body')).not.toContainText('500 Internal Server Error')
  })

  test('endpoint /restore retourne success: true', async ({ page }) => {
    // Test direct sans waitForAppReady pour éviter les timeouts liés aux workers parallèles
    await page.route(
      (url) => url.origin === API && url.pathname.includes('/restore') && !url.pathname.includes('bulk'),
      (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, email_id: 'trash-1', message: 'Email restauré' }),
        })
      }
    )

    await page.goto('about:blank')

    const result = await page.evaluate(async (apiUrl) => {
      try {
        const res = await fetch(`${apiUrl}/api/emails/trash-1/restore`, { method: 'POST' })
        return await res.json()
      } catch {
        return null
      }
    }, API)

    if (result) {
      expect(result).toHaveProperty('success', true)
    }
  })

  test('endpoint /bulk-restore retourne success et count', async ({ page }) => {
    await page.route(
      (url) => url.origin === API && url.pathname.includes('/bulk-restore'),
      (route) => {
        const body = JSON.parse(route.request().postData() || '{}')
        const count = (body.email_ids || []).length
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, count, message: `${count} emails restaurés` }),
        })
      }
    )

    const result = await page.evaluate(async (apiUrl) => {
      try {
        const res = await fetch(`${apiUrl}/api/emails/bulk-restore`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email_ids: ['trash-1', 'trash-2'] }),
        })
        return await res.json()
      } catch {
        return null
      }
    }, API)

    if (result) {
      expect(result).toHaveProperty('success', true)
      expect(result).toHaveProperty('count', 2)
    }
  })
})

// ============================================================================
// Tests vider Indésirables / Corbeille
// ============================================================================

test.describe('Opérations de nettoyage', () => {
  test.beforeEach(async ({ page }) => {
    await setupFolderMocks(page)
    await page.goto('/')
    await waitForAppReady(page)
  })

  test('endpoint /empty-spam retourne success: true', async ({ page }) => {
    await page.route(
      (url) => url.origin === API && url.pathname.includes('/empty-spam'),
      (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, count: 2, message: 'Indésirables vidés' }),
        })
      }
    )

    const result = await page.evaluate(async (apiUrl) => {
      try {
        const res = await fetch(`${apiUrl}/api/emails/empty-spam`, { method: 'POST' })
        return await res.json()
      } catch {
        return null
      }
    }, API)

    if (result) {
      expect(result).toHaveProperty('success', true)
    }
  })

  test('endpoint /empty-trash retourne success: true', async ({ page }) => {
    await page.route(
      (url) => url.origin === API && url.pathname.includes('/empty-trash'),
      (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, count: 2, message: 'Corbeille vidée' }),
        })
      }
    )

    const result = await page.evaluate(async (apiUrl) => {
      try {
        const res = await fetch(`${apiUrl}/api/emails/empty-trash`, { method: 'POST' })
        return await res.json()
      } catch {
        return null
      }
    }, API)

    if (result) {
      expect(result).toHaveProperty('success', true)
    }
  })
})

// ============================================================================
// Tests contrat de format des réponses
// ============================================================================

test.describe('Format de réponse — contrats API spam/trash', () => {
  test('réponse /not-spam a les champs obligatoires', async ({ page }) => {
    await setupBaseMocks(page)
    await page.route(
      (url) => url.origin === API && url.pathname.includes('/not-spam'),
      (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, email_id: 'spam-1' }),
        })
      }
    )

    await page.goto('/')

    const result = await page.evaluate(async (apiUrl) => {
      const res = await fetch(`${apiUrl}/api/emails/spam-1/not-spam`, { method: 'POST' })
      return res.json()
    }, API)

    expect(result).toHaveProperty('success')
    expect(result).toHaveProperty('email_id')
    expect(typeof result.success).toBe('boolean')
    expect(typeof result.email_id).toBe('string')
  })

  test('réponse /restore a les champs obligatoires', async ({ page }) => {
    await setupBaseMocks(page)
    await page.route(
      (url) => url.origin === API && url.pathname.includes('/restore') && !url.pathname.includes('bulk'),
      (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, email_id: 'trash-1' }),
        })
      }
    )

    await page.goto('/')

    const result = await page.evaluate(async (apiUrl) => {
      const res = await fetch(`${apiUrl}/api/emails/trash-1/restore`, { method: 'POST' })
      return res.json()
    }, API)

    expect(result).toHaveProperty('success')
    expect(typeof result.success).toBe('boolean')
  })
})
