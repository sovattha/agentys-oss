/**
 * E2E — Snooze badges zzz + Follow-up reminder 🔔
 *
 * Couvre :
 *  1. Badge "zzz" quand un snooze régulier (type:'snooze') est révéillé
 *  2. Badge "🔔" quand un rappel follow-up (type:'followup') est révéillé
 *  3. Emails endormis (date future) cachés de la liste normale
 *  4. Emails réveillés épinglés en haut de la liste
 *  5. Auto-trigger draft au réveil d'un follow-up
 *  6. Rétrocompat : entrée sans champ type → badge zzz (défaut snooze)
 *  7. CSS : .email-badge-zzz et .email-badge-followup ont les bonnes couleurs
 *
 * NOTE : page.addInitScript doit utiliser la signature (fn, arg) pour que les
 * variables capturées soient sérialisées correctement dans le contexte browser.
 */

import { test, expect } from '@playwright/test'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'
const STORAGE_KEY = 'agentys_snoozed'

// ─── Helpers ──────────────────────────────────────────────────────────────────

type SnoozeEntry = { emailId: string; date: string; subject: string; type?: string }

/** Date ISO dans le passé (réveil immédiat). */
function pastISO(minutesAgo = 5): string {
  return new Date(Date.now() - minutesAgo * 60 * 1000).toISOString()
}

/** Date ISO dans le futur (toujours endormi). */
function futureISO(minutesAhead = 60): string {
  return new Date(Date.now() + minutesAhead * 60 * 1000).toISOString()
}

/** Email factice minimal. */
function makeEmail(id: string, subject: string) {
  return {
    id,
    sender: 'test@example.com',
    sender_name: 'Test Sender',
    subject,
    received_at: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
    has_attachments: false,
    conversation_id: null,
    is_read: false,
    body_preview: `Prévisualisation de ${subject}`,
  }
}

const EMAILS = [
  makeEmail('snooze-email', 'Email snoozé simple'),
  makeEmail('followup-email', 'Email rappel follow-up'),
  makeEmail('sleeping-email', 'Email encore endormi'),
  makeEmail('compat-email', 'Email sans type (rétrocompat)'),
  makeEmail('normal-email', 'Email normal sans snooze'),
]

const EMAILS_RESPONSE = { emails: EMAILS, has_more: false, source: 'mock' }

/** Injecte les entrées snooze via la signature (fn, arg) — correctement sérialisée. */
async function injectSnooze(page: import('@playwright/test').Page, entries: SnoozeEntry[]) {
  await page.addInitScript(
    (args: { key: string; entries: SnoozeEntry[] }) => {
      localStorage.setItem(args.key, JSON.stringify(args.entries))
    },
    { key: STORAGE_KEY, entries },
  )
}

// ─── Tests ────────────────────────────────────────────────────────────────────

test.describe('Snooze badges — zzz et 🔔', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page, { emailsResponse: EMAILS_RESPONSE })
  })

  // ── 1. Badge zzz pour snooze régulier révéillé ──────────────────────────────
  test('badge zzz affiché pour un snooze régulier révéillé', async ({ page }) => {
    await injectSnooze(page, [
      { emailId: 'snooze-email', date: pastISO(), subject: 'Email snoozé simple', type: 'snooze' },
    ])

    await page.goto('/')
    await waitForAppReady(page)

    const badge = page.locator('[data-testid="badge-zzz"]').first()
    await expect(badge).toBeVisible({ timeout: 8000 })
    // Badge zzz uses SVG icon (no text content) — just verify presence

    // Aucun badge followup ne doit être présent
    await expect(page.locator('[data-testid="badge-followup"]')).toHaveCount(0)
  })

  // ── 2. Badge 🔔 pour follow-up révéillé ──────────────────────────────────────
  test('badge 🔔 affiché pour un rappel follow-up révéillé', async ({ page }) => {
    await injectSnooze(page, [
      { emailId: 'followup-email', date: pastISO(), subject: 'Email rappel follow-up', type: 'followup' },
    ])

    await page.goto('/')
    await waitForAppReady(page)

    const badge = page.locator('[data-testid="badge-followup"]').first()
    await expect(badge).toBeVisible({ timeout: 8000 })
    // Badge followup uses SVG bell icon (no text content) — just verify presence

    // Aucun badge zzz ne doit être présent
    await expect(page.locator('[data-testid="badge-zzz"]')).toHaveCount(0)
  })

  // ── 3. Les deux badges coexistent pour des emails différents ─────────────────
  test('badges zzz et 🔔 coexistent pour deux emails différents', async ({ page }) => {
    await injectSnooze(page, [
      { emailId: 'snooze-email',   date: pastISO(10), subject: 'Email snoozé simple',     type: 'snooze' },
      { emailId: 'followup-email', date: pastISO(5),  subject: 'Email rappel follow-up',  type: 'followup' },
    ])

    await page.goto('/')
    await waitForAppReady(page)

    await expect(page.locator('[data-testid="badge-zzz"]')).toHaveCount(1, { timeout: 8000 })
    await expect(page.locator('[data-testid="badge-followup"]')).toHaveCount(1)
  })

  // ── 4. Email endormi (date future) absent de la liste ────────────────────────
  test('email avec snooze futur est absent de la liste normale', async ({ page }) => {
    await injectSnooze(page, [
      { emailId: 'sleeping-email', date: futureISO(), subject: 'Email encore endormi', type: 'snooze' },
    ])

    await page.goto('/')
    await waitForAppReady(page)

    // Aucun badge ne doit apparaître
    await expect(page.locator('[data-testid="badge-zzz"]')).toHaveCount(0)
    await expect(page.locator('[data-testid="badge-followup"]')).toHaveCount(0)

    // L'email endormi ne doit pas être visible dans la liste
    await expect(page.locator('[data-email-id="sleeping-email"]')).toHaveCount(0)
  })

  // ── 5. Email réveillé épinglé en haut de la liste ────────────────────────────
  test('email réveillé apparaît en tête de liste (avant les emails normaux)', async ({ page }) => {
    await injectSnooze(page, [
      { emailId: 'snooze-email', date: pastISO(), subject: 'Email snoozé simple', type: 'snooze' },
    ])

    await page.goto('/')
    await waitForAppReady(page)

    const wokeItem   = page.locator('[data-email-id="snooze-email"]')
    const normalItem = page.locator('[data-email-id="normal-email"]')

    await expect(wokeItem).toBeVisible({ timeout: 8000 })
    await expect(normalItem).toBeVisible()

    const wokeBox   = await wokeItem.boundingBox()
    const normalBox = await normalItem.boundingBox()

    expect(wokeBox).not.toBeNull()
    expect(normalBox).not.toBeNull()
    // L'email réveillé doit être plus haut dans la page (y inférieur)
    expect(wokeBox!.y).toBeLessThan(normalBox!.y)
  })

  // ── 6. Rétrocompat : entrée sans type → badge zzz ────────────────────────────
  test('entrée sans champ type affiche badge zzz (rétrocompat)', async ({ page }) => {
    // Pas de champ "type" — ancien format
    await injectSnooze(page, [
      { emailId: 'compat-email', date: pastISO(), subject: 'Email sans type (rétrocompat)' },
    ])

    await page.goto('/')
    await waitForAppReady(page)

    await expect(page.locator('[data-testid="badge-zzz"]')).toHaveCount(1, { timeout: 8000 })
    await expect(page.locator('[data-testid="badge-followup"]')).toHaveCount(0)
  })

  // ── 7. Cliquer sur un email réveillé supprime l'entrée snooze ────────────────
  test('cliquer sur un email réveillé efface son entrée snooze du localStorage', async ({ page }) => {
    await injectSnooze(page, [
      { emailId: 'snooze-email', date: pastISO(), subject: 'Email snoozé simple', type: 'snooze' },
    ])

    // Mock la route de détail pour éviter un 404
    await page.route(
      (url) => url.origin === API && url.pathname === '/api/emails/snooze-email',
      (route) => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ email: EMAILS[0] }),
      }),
    )

    await page.goto('/')
    await waitForAppReady(page)

    // S'assurer que le badge est présent avant le clic
    await expect(page.locator('[data-testid="badge-zzz"]')).toHaveCount(1, { timeout: 8000 })

    // Cliquer sur l'email réveillé
    await page.locator('[data-email-id="snooze-email"]').click()

    // Attendre que le localStorage ne contienne plus l'entrée
    await page.waitForFunction(
      ({ key, emailId }: { key: string; emailId: string }) => {
        try {
          const raw = localStorage.getItem(key) || '[]'
          const entries = JSON.parse(raw) as Array<{ emailId: string }>
          return !entries.some((e) => e.emailId === emailId)
        } catch {
          return false
        }
      },
      { key: STORAGE_KEY, emailId: 'snooze-email' },
      { timeout: 5000 },
    )
  })

  // ── 8. Auto-trigger draft pour follow-up révéillé ────────────────────────────
  test('follow-up révéillé déclenche automatiquement la génération du brouillon', async ({ page }) => {
    await injectSnooze(page, [
      { emailId: 'followup-email', date: pastISO(), subject: 'Email rappel follow-up', type: 'followup' },
    ])

    let processCalled = false
    await page.route(
      (url) => url.origin === API && url.pathname === '/api/emails/followup-email/process',
      (route) => {
        processCalled = true
        route.fulfill({
          status: 202,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, draft_id: 'draft-auto-1' }),
        })
      },
    )

    await page.goto('/')
    await waitForAppReady(page)

    // Wait for the auto-triggered /process request
    await page.waitForResponse(
      (resp) => resp.url().includes('/api/emails/followup-email/process'),
      { timeout: 10000 }
    )

    expect(processCalled).toBe(true)
  })

  // ── 9. CSS : couleurs du badge zzz ───────────────────────────────────────────
  test('badge zzz a les bonnes couleurs CSS (bleu clair)', async ({ page }) => {
    await injectSnooze(page, [
      { emailId: 'snooze-email', date: pastISO(), subject: 'Email snoozé simple', type: 'snooze' },
    ])

    await page.goto('/')
    await waitForAppReady(page)

    const badge = page.locator('[data-testid="badge-zzz"]').first()
    await expect(badge).toBeVisible({ timeout: 8000 })

    const rawStyles = await badge.evaluate((el) => {
      const cs = window.getComputedStyle(el)
      return { bg: cs.backgroundColor, color: cs.color }
    })

    const toRgb = (c: string): [number, number, number] => {
      let m = c.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/)
      if (m) return [+m[1], +m[2], +m[3]]
      m = c.match(/color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\)/)
      if (m) return [Math.round(+m[1]*255), Math.round(+m[2]*255), Math.round(+m[3]*255)]
      return [-1, -1, -1]
    }
    const styles = { bg: toRgb(rawStyles.bg), color: toRgb(rawStyles.color) }
    const close = (a: number[], b: number[], tol = 10) =>
      Math.abs(a[0]-b[0]) <= tol && Math.abs(a[1]-b[1]) <= tol && Math.abs(a[2]-b[2]) <= tol

    // CSS: #c4b5fd → rgb(196, 181, 253) — violet clair
    expect(close(styles.bg, [196, 181, 253])).toBe(true)
    // #fff → rgb(255, 255, 255) — blanc
    expect(close(styles.color, [255, 255, 255])).toBe(true)
  })

  // ── 10. CSS : couleurs du badge 🔔 ────────────────────────────────────────────
  test('badge 🔔 a les bonnes couleurs CSS (ambre)', async ({ page }) => {
    await injectSnooze(page, [
      { emailId: 'followup-email', date: pastISO(), subject: 'Email rappel follow-up', type: 'followup' },
    ])

    await page.goto('/')
    await waitForAppReady(page)

    const badge = page.locator('[data-testid="badge-followup"]').first()
    await expect(badge).toBeVisible({ timeout: 8000 })

    const styles = await badge.evaluate((el) => {
      const cs = window.getComputedStyle(el)
      // Parse any CSS color to [r, g, b] — handles rgb() and color(srgb)
      const toRgb = (c: string): [number, number, number] => {
        let m = c.match(/^rgb\((\d+),\s*(\d+),\s*(\d+)\)$/)
        if (m) return [+m[1], +m[2], +m[3]]
        m = c.match(/color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\)/)
        if (m) return [Math.round(+m[1]*255), Math.round(+m[2]*255), Math.round(+m[3]*255)]
        return [-1, -1, -1]
      }
      return { bg: toRgb(cs.backgroundColor), color: toRgb(cs.color) }
    })
    const close = (a: number[], b: number[], tol = 8) =>
      Math.abs(a[0]-b[0]) <= tol && Math.abs(a[1]-b[1]) <= tol && Math.abs(a[2]-b[2]) <= tol

    // CSS: #fcd34d → rgb(252, 211, 77) — amber
    expect(close(styles.bg, [252, 211, 77])).toBe(true)
    // #fff → rgb(255, 255, 255) — blanc
    expect(close(styles.color, [255, 255, 255])).toBe(true)
  })
})

// ─── Tests API /api/reminders ─────────────────────────────────────────────────

test.describe('API /api/reminders — follow-up backend', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page)
  })

  test('POST /api/reminders accepte email_id + subject + reminder_date', async ({ page }) => {
    let reminderPayload: Record<string, unknown> | null = null

    await page.route(
      (url) => url.origin === API && url.pathname === '/api/reminders',
      async (route) => {
        if (route.request().method() === 'POST') {
          reminderPayload = route.request().postDataJSON()
          await route.fulfill({
            status: 201,
            contentType: 'application/json',
            body: JSON.stringify({ id: 'reminder-test-1', success: true }),
          })
        } else {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ reminders: [] }),
          })
        }
      },
    )

    await page.goto('/')
    await waitForAppReady(page)

    // Appel direct à l'api client depuis le contexte page
    const reminderDate = new Date(Date.now() + 86400000).toISOString()
    await page.evaluate(
      async ({ date }: { date: string }) => {
        const mod = await import('/src/services/api.ts')
        await mod.apiClient.createReminder('test-email-42', 'Sujet du rappel', date)
      },
      { date: reminderDate },
    )

    await page.waitForResponse(
      (resp) => resp.url().includes('/api/reminders'),
      { timeout: 5000 }
    )

    expect(reminderPayload).not.toBeNull()
    expect(reminderPayload!['email_id']).toBe('test-email-42')
    expect(reminderPayload!['subject']).toBe('Sujet du rappel')
    expect(reminderPayload!['reminder_date']).toBe(reminderDate)
  })
})

// ─── Régression : snooze via context menu cache l'email immédiatement ─────────
//
// Reproduit le bug signalé : après un snooze via clic droit, l'email restait
// dans l'inbox car le handler inline écrivait dans localStorage sans dispatcher
// le StorageEvent — useSnooze ne détectait jamais le changement.
//
// Fix : le handler appelle writeSnoozeEntry() qui gère les deux.

test.describe('Régression — snooze via context menu cache l\'email', () => {
  test.beforeEach(async ({ page }) => {
    await setupBaseMocks(page, { emailsResponse: EMAILS_RESPONSE })
  })

  test('après snooze via clic droit, l\'email disparaît immédiatement de la liste', async ({ page }) => {
    await page.goto('/')
    await waitForAppReady(page)

    // L'email cible doit d'abord être visible
    const target = page.locator('[data-email-id="normal-email"]')
    await expect(target).toBeVisible({ timeout: 8000 })

    // Clic droit → context menu
    await target.click({ button: 'right' })
    await expect(page.locator('.email-context-menu')).toBeVisible({ timeout: 3000 })

    // Cliquer sur "Snooze"
    await page.locator('.context-menu-item', { hasText: 'Snooze' }).click()

    // Le calendrier doit apparaître
    await expect(page.locator('.snooze-dropdown')).toBeVisible({ timeout: 3000 })

    // Aller au mois suivant pour garantir que tous les jours sont dans le futur
    await page.locator('.snooze-cal-nav[aria-label="Mois suivant"]').click()

    // Sélectionner le premier jour disponible (tout le mois suivant est futur)
    const futureDay = page.locator('.snooze-cal-day:not([disabled])').first()
    await expect(futureDay).toBeVisible()
    await futureDay.click()

    // Confirmer
    await page.locator('.snooze-cal-confirm').click()

    // L'email doit disparaître de la liste (sleepingIds le filtre)
    await expect(target).toHaveCount(0, { timeout: 3000 })

    // Vérifier que localStorage contient bien l'entrée snooze avec type:'snooze'
    const stored = await page.evaluate(
      (key: string) => {
        try {
          return JSON.parse(localStorage.getItem(key) || '[]')
        } catch { return [] }
      },
      'agentys_snoozed',
    )
    const entry = (stored as Array<{ emailId: string; type?: string; date: string }>)
      .find(e => e.emailId === 'normal-email')
    expect(entry).not.toBeUndefined()
    expect(entry!.type).toBe('snooze')
    // La date doit être dans le futur
    expect(new Date(entry!.date).getTime()).toBeGreaterThan(Date.now())
  })

  test('le StorageEvent est bien dispatché (useSnooze réactif sans reload)', async ({ page }) => {
    await page.goto('/')
    await waitForAppReady(page)

    // Écouter les StorageEvents depuis le contexte page
    await page.evaluate(() => {
      (window as unknown as Record<string, unknown>)._snoozeEventFired = false
      window.addEventListener('storage', (e) => {
        if (e.key === 'agentys_snoozed') {
          (window as unknown as Record<string, unknown>)._snoozeEventFired = true
        }
      })
    })

    const target = page.locator('[data-email-id="normal-email"]')
    await expect(target).toBeVisible({ timeout: 8000 })

    // Snooze via context menu
    await target.click({ button: 'right' })
    await page.locator('.context-menu-item', { hasText: 'Snooze' }).click()
    await expect(page.locator('.snooze-dropdown')).toBeVisible()
    await page.locator('.snooze-cal-day:not([disabled]):not(.past)').first().click()
    await page.locator('.snooze-cal-confirm').click()

    // Vérifier que le StorageEvent a bien été dispatché
    const eventFired = await page.evaluate(
      () => (window as unknown as Record<string, unknown>)._snoozeEventFired,
    )
    expect(eventFired).toBe(true)
  })
})
