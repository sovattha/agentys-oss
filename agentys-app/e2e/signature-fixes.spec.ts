/**
 * Signature Fixes — Tests E2E
 *
 * Valide les 4 corrections du système de signatures :
 *
 *  Bug #1 — stripEmbeddedSignature (frontend) :
 *    regex non-greedy s'arrêtait au premier </div> et laissait des résidus
 *    quand la signature avait des divs imbriqués → double signature visible.
 *
 *  Bug #2 — Faux positif côté backend :
 *    `sig_text in body_text` déclenchait si le corps mentionnait le nom
 *    du signataire → signature non ajoutée par le backend.
 *    (testé côté frontend : corps contenant le nom du signataire ne bloque pas l'injection)
 *
 *  Bug #3 — Fallback plain-text (backend model) :
 *    get_signature(html=False) retournait None si seulement signature_html définie.
 *    Frontend : compte avec seulement signature_html → signature quand même affichée.
 *
 *  Bug #4 — account_id hardcodé à 1 (backend) :
 *    Frontend : current_account_id correct → bonne signature récupérée.
 */

import { test, expect, Page } from '@playwright/test'
import { mockEmailsResponse, mockEmailDetails } from './support/fixtures/mock-data'
import { setupBaseMocks, waitForAppReady } from './support/fixtures/setup'

const API = 'http://127.0.0.1:5050'
const API_LOCALHOST = 'http://localhost:5050'

// ── Données de test ──────────────────────────────────────────────────────────

/** Signature avec divs imbriqués (cas Bug #1) */
const SIGNATURE_NESTED =
  '<div><strong>Alexandre Savageau</strong></div>' +
  '<div>CEO, Agentys</div>' +
  '<div>alexandre@agentys.io</div>'

/** Même signature, version simple sans imbrication */
const SIGNATURE_SIMPLE = '<strong>Alexandre Savageau</strong><br>CEO, Agentys'

/** Bloc signature tel que le backend l'injecte dans draft_body */
function makeSignatureBlock(sigHtml: string): string {
  return `<div class="agentys-signature" style="margin-top:16px;padding-top:12px;border-top:1px solid #e0e0e0">${sigHtml}</div>`
}

/** Corps de draft AI simulant un draft généré avec signature déjà incluse (divs imbriqués) */
const DRAFT_BODY_WITH_NESTED_SIG =
  '<p>Bonjour Marie, merci pour votre message.</p>' +
  makeSignatureBlock(SIGNATURE_NESTED)

/** Corps avec signature simple (cas contrôle) */
const DRAFT_BODY_WITH_SIMPLE_SIG =
  '<p>Merci pour votre email.</p>' +
  makeSignatureBlock(SIGNATURE_SIMPLE)

/**
 * Corps qui mentionne "Alexandre Savageau" dans le texte (pas comme signature).
 * Simule le cas Bug #2 : le backend ne devait pas confondre ce nom avec la signature.
 */
const DRAFT_BODY_MENTIONS_SIGNER =
  '<p>Bonjour, vous pouvez contacter Alexandre Savageau pour plus d\'informations.</p>'

/** Réponse /api/accounts avec signature_html ET signature (cas normal) */
const ACCOUNT_FULL_SIGNATURE = {
  current_account_id: '1',
  accounts: [{
    id: '1',
    email: 'test@example.com',
    status: 'active',
    signature: 'Alexandre Savageau\nCEO, Agentys',
    signature_html: SIGNATURE_NESTED,
    has_signature: true,
  }],
}

/** Réponse /api/accounts avec seulement signature_html — pas de signature text (Bug #3) */
const ACCOUNT_HTML_ONLY_SIGNATURE = {
  current_account_id: '1',
  accounts: [{
    id: '1',
    email: 'test@example.com',
    status: 'active',
    signature: '',          // texte vide — simule le bug #3
    signature_html: SIGNATURE_NESTED,
    has_signature: true,
  }],
}

/** Réponse /api/accounts avec DEUX comptes — current_account_id pointe vers id='42' (Bug #4) */
const ACCOUNT_MULTI_WRONG_DEFAULT = {
  current_account_id: '42',
  accounts: [
    {
      id: '1',
      email: 'autre@example.com',
      status: 'active',
      signature: 'Mauvaise Signature\nNe doit pas apparaître',
      signature_html: '<strong>Mauvaise Signature</strong><br>Ne doit pas apparaître',
      has_signature: true,
    },
    {
      id: '42',
      email: 'test@example.com',
      status: 'active',
      signature: 'Alexandre Savageau\nCEO, Agentys',
      signature_html: SIGNATURE_NESTED,
      has_signature: true,
    },
  ],
}

/** Réponse /api/accounts sans signature configurée */
const ACCOUNT_NO_SIGNATURE = {
  current_account_id: '1',
  accounts: [{
    id: '1',
    email: 'test@example.com',
    status: 'active',
    signature: '',
    signature_html: '',
    has_signature: false,
  }],
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Injecte un brouillon de réponse sauvegardé en localStorage pour email-1 */
function injectSavedReplyDraft(page: Page, body: string) {
  return page.addInitScript((draftBody: string) => {
    const draft = {
      type: 'reply',
      id: 'draft_test_sig',
      emailId: 'email-1',
      emailSubject: 'Rapport trimestriel Q4 2025',
      emailSender: 'marie.dupont@example.com',
      body: draftBody,
      savedAt: new Date().toISOString(),
    }
    localStorage.setItem('agentys_saved_drafts', JSON.stringify([draft]))
  }, body)
}

/** Mocks de base + override /api/accounts avec les données fournies */
async function setupWithAccount(page: Page, accountData: object) {
  await setupBaseMocks(page, { emailsResponse: mockEmailsResponse })

  // Override /api/accounts sur les deux origins (127.0.0.1 + localhost, priorité LIFO)
  const accountBody = JSON.stringify(accountData)
  const accountHandler = (route: import('@playwright/test').Route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: accountBody })
  }
  await page.route(`${API}/api/accounts`, accountHandler)
  await page.route(`${API_LOCALHOST}/api/accounts`, accountHandler)

  // Override /api/init pour inclure les comptes avec signature (utilisé au boot de l'app)
  const initAccountsList = (accountData as { accounts: unknown[] }).accounts || []
  const initBody = JSON.stringify({
    emails: mockEmailsResponse,
    label_counts: { counts: {}, total: 0 },
    pending_drafts: { drafts: [], pending_count: 0 },
    accounts: initAccountsList,
  })
  const initHandler = (route: import('@playwright/test').Route) => {
    route.fulfill({ status: 200, contentType: 'application/json', body: initBody })
  }
  await page.route(`${API}/api/init`, initHandler)
  await page.route(`${API_LOCALHOST}/api/init`, initHandler)

  // Mocks supplémentaires pour l'ouverture d'email + reply
  await page.route(
    (url) => url.origin === API && url.pathname.match(/^\/api\/emails\/email-\d+$/) !== null,
    (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockEmailDetails['email-1']),
      })
    }
  )
  await page.route(
    (url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/read$/) !== null,
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) })
  )
  await page.route(
    (url) => url.origin === API && url.pathname.match(/\/api\/emails\/[^/]+\/thread$/) !== null,
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ count: 1, emails: [] }) })
  )
  await page.route(
    (url) => url.origin === API && url.pathname.startsWith('/api/pending-drafts/by-email'),
    (route) => route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: 'No draft' }) })
  )
  await page.route(
    (url) => url.origin === API && url.pathname.startsWith('/api/contacts'),
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  )
}

/** Ouvre le reply composer pour le premier email de la liste */
async function openReplyComposer(page: Page) {
  // Cliquer sur le premier email pour ouvrir le détail
  await page.locator('[data-testid="email-item"]').first().click()
  await page.locator('.email-detail-body').first().waitFor({ state: 'visible', timeout: 10000 })
  // Ouvrir le reply composer
  await page.keyboard.press('r')
  await page.locator('[data-testid="reply-composer"]').waitFor({ state: 'visible', timeout: 10000 })
  // Attendre que l'éditeur ait du contenu (signature injectée via fetch async + effect)
  await page.locator('[data-testid="reply-composer"] .draft-editor-content').waitFor({ state: 'visible', timeout: 5000 })
}

/** Retourne le texte brut affiché dans l'éditeur TipTap du reply composer */
async function getEditorText(page: Page): Promise<string> {
  const editor = page.locator('[data-testid="reply-composer"] .draft-editor-content').first()
  return (await editor.textContent()) ?? ''
}

/** Compte le nombre d'occurrences d'une chaîne dans un texte */
function countOccurrences(text: string, needle: string): number {
  let count = 0
  let pos = 0
  while ((pos = text.indexOf(needle, pos)) !== -1) {
    count++
    pos += needle.length
  }
  return count
}

// ── Tests ────────────────────────────────────────────────────────────────────

test.describe('Bug #1 — stripEmbeddedSignature : pas de signature dupliquée', () => {
  /**
   * Scénario : l'utilisateur a un brouillon sauvegardé (localStorage) dont le corps
   * contient déjà une signature avec des <div> imbriqués (structure réelle du backend).
   * À l'ouverture du ReplyComposer, stripEmbeddedSignature() doit enlever TOUT le bloc,
   * puis l'effet d'injection ajoute UNE seule copie propre.
   */
  test('signature avec divs imbriqués → une seule occurrence dans l\'éditeur', async ({ page }) => {
    await injectSavedReplyDraft(page, DRAFT_BODY_WITH_NESTED_SIG)
    await setupWithAccount(page, ACCOUNT_FULL_SIGNATURE)
    await page.goto('/')
    await waitForAppReady(page)
    await openReplyComposer(page)

    const text = await getEditorText(page)
    const occurrences = countOccurrences(text, 'Alexandre Savageau')

    expect(
      occurrences,
      `"Alexandre Savageau" doit apparaître exactement 1 fois (trouvé ${occurrences} fois). ` +
      `Texte éditeur : ${text.slice(0, 300)}`
    ).toBe(1)
  })

  /**
   * Cas contrôle : signature simple (sans divs imbriqués).
   * Doit aussi produire exactement une signature — vérifie que le cas de base fonctionne.
   */
  test('signature simple → une seule occurrence dans l\'éditeur', async ({ page }) => {
    await injectSavedReplyDraft(page, DRAFT_BODY_WITH_SIMPLE_SIG)
    await setupWithAccount(page, ACCOUNT_FULL_SIGNATURE)
    await page.goto('/')
    await waitForAppReady(page)
    await openReplyComposer(page)

    const text = await getEditorText(page)
    const occurrences = countOccurrences(text, 'Alexandre Savageau')

    expect(
      occurrences,
      `"Alexandre Savageau" doit apparaître exactement 1 fois (trouvé ${occurrences} fois)`
    ).toBe(1)
  })

  /**
   * Cas brouillon vide : aucun draft sauvegardé, le corps est vide.
   * La signature doit quand même être injectée une seule fois quand
   * l'utilisateur passe en mode 'editing'.
   * Note : sans draft sauvegardé, state = 'idle' (pas 'editing') → signature injectée
   * seulement après que l'utilisateur écrit ou génère. On vérifie au moins que
   * le reply composer s'ouvre correctement.
   */
  test('brouillon vide → reply composer opérationnel', async ({ page }) => {
    await setupWithAccount(page, ACCOUNT_FULL_SIGNATURE)
    await page.goto('/')
    await waitForAppReady(page)
    await openReplyComposer(page)

    await expect(page.locator('[data-testid="reply-composer"]')).toBeVisible()
  })
})

test.describe('Bug #2 — Corps mentionnant le signataire → signature quand même affichée', () => {
  /**
   * Scénario : le corps du draft mentionne "Alexandre Savageau" dans le texte (pas comme
   * signature). L'ancien code backend aurait détecté ce nom et sauté l'injection.
   * Le frontend doit toujours injecter la signature dans ce cas.
   */
  test('corps contenant le nom du signataire → signature présente dans l\'éditeur', async ({ page }) => {
    await injectSavedReplyDraft(page, DRAFT_BODY_MENTIONS_SIGNER)
    await setupWithAccount(page, ACCOUNT_FULL_SIGNATURE)
    await page.goto('/')
    await waitForAppReady(page)
    await openReplyComposer(page)

    const text = await getEditorText(page)
    // Le texte doit contenir "Alexandre Savageau" au moins une fois
    // (une fois dans le corps + une fois dans la signature injectée = 2 occurrences)
    const occurrences = countOccurrences(text, 'Alexandre Savageau')

    expect(
      occurrences,
      `Le nom dans le corps + la signature injectée doivent donner ≥ 2 occurrences, trouvé ${occurrences}. ` +
      `Texte : ${text.slice(0, 300)}`
    ).toBeGreaterThanOrEqual(2)
  })
})

test.describe('Bug #3 — Compte avec seulement signature_html → signature affichée', () => {
  /**
   * Scénario : le compte n'a pas de signature texte (champ `signature` vide),
   * seulement `signature_html`. Le hook useAccountSignature dérive le texte depuis
   * le HTML → la signature doit s'afficher dans l'éditeur.
   */
  test('signature HTML uniquement → texte de signature visible dans l\'éditeur', async ({ page }) => {
    await injectSavedReplyDraft(page, '<p>Bonjour, merci pour votre message.</p>')
    await setupWithAccount(page, ACCOUNT_HTML_ONLY_SIGNATURE)
    await page.goto('/')
    await waitForAppReady(page)
    await openReplyComposer(page)

    const text = await getEditorText(page)
    expect(
      text,
      `La signature HTML doit être convertie en texte et injectée. Texte éditeur : ${text.slice(0, 300)}`
    ).toContain('Alexandre Savageau')
  })

  /**
   * Idem pour NewMessageModal : vérifier que la signature HTML-seulement s'affiche.
   */
  test('NewMessage — signature HTML uniquement → signature visible dans la modale', async ({ page }) => {
    await setupWithAccount(page, ACCOUNT_HTML_ONLY_SIGNATURE)

    // Mock routes supplémentaires pour NewMessage
    await page.route((url) => url.origin === API && url.pathname === '/api/emails/compose', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, message_id: 'msg-1' }) })
    })
    await page.route((url) => url.origin === API && url.pathname === '/api/refine-text', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, refined_text: 'Texte.' }) })
    })

    await page.goto('/')
    await waitForAppReady(page)

    // Ouvrir la modale via le raccourci N
    await page.locator('body').click({ position: { x: 10, y: 10 } })
    await page.keyboard.press('n')
    await page.locator('.new-message-modal').first().waitFor({ state: 'visible', timeout: 10000 })

    const modal = page.locator('.new-message-modal')
    await expect(
      modal,
      'La signature HTML doit être affichée dans NewMessageModal même sans signature_text'
    ).toContainText('Alexandre Savageau', { timeout: 5000 })
  })
})

test.describe('Bug #4 — current_account_id correct → bonne signature affichée', () => {
  /**
   * Scénario : deux comptes configurés. current_account_id pointe vers id='42'.
   * L'id='1' a une signature différente ("Mauvaise Signature").
   * La signature affichée doit être celle du compte id='42', pas du compte id='1'.
   */
  test('signature du compte actif (id=42) et non du compte par défaut (id=1)', async ({ page }) => {
    await injectSavedReplyDraft(page, '<p>Bonjour, voici ma réponse.</p>')
    await setupWithAccount(page, ACCOUNT_MULTI_WRONG_DEFAULT)
    await page.goto('/')
    await waitForAppReady(page)
    await openReplyComposer(page)

    const text = await getEditorText(page)

    expect(
      text,
      `La signature du compte actif (id=42) doit être présente. Texte : ${text.slice(0, 300)}`
    ).toContain('Alexandre Savageau')

    expect(
      text,
      `La signature du mauvais compte (id=1) ne doit PAS être présente. Texte : ${text.slice(0, 300)}`
    ).not.toContain('Mauvaise Signature')
  })

  /**
   * NewMessageModal — même vérification avec current_account_id=42.
   */
  test('NewMessage — signature du compte actif (id=42) affichée', async ({ page }) => {
    await setupWithAccount(page, ACCOUNT_MULTI_WRONG_DEFAULT)
    await page.route((url) => url.origin === API && url.pathname === '/api/emails/compose', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, message_id: 'msg-1' }) })
    })

    await page.goto('/')
    await waitForAppReady(page)

    await page.locator('body').click({ position: { x: 10, y: 10 } })
    await page.keyboard.press('n')
    await page.locator('.new-message-modal').first().waitFor({ state: 'visible', timeout: 10000 })

    const modal = page.locator('.new-message-modal')
    await expect(modal).toContainText('Alexandre Savageau', { timeout: 5000 })
    await expect(modal).not.toContainText('Mauvaise Signature')
  })
})

test.describe('Régression — comportement global des signatures', () => {
  /**
   * Aucune signature configurée → l'éditeur n'affiche pas de signature.
   */
  test('pas de signature si aucune signature configurée', async ({ page }) => {
    await injectSavedReplyDraft(page, '<p>Bonjour, voici ma réponse.</p>')
    await setupWithAccount(page, ACCOUNT_NO_SIGNATURE)
    await page.goto('/')
    await waitForAppReady(page)
    await openReplyComposer(page)

    const text = await getEditorText(page)
    expect(
      text,
      `Aucune signature ne doit être injectée. Texte : ${text.slice(0, 300)}`
    ).not.toContain('Alexandre Savageau')
  })

  /**
   * Le reply composer s'ouvre sans erreur avec une signature normale.
   * Test de smoke pour valider l'ensemble du flux.
   */
  test('smoke — reply composer avec signature s\'ouvre sans erreur', async ({ page }) => {
    await setupWithAccount(page, ACCOUNT_FULL_SIGNATURE)
    await page.goto('/')
    await waitForAppReady(page)

    await page.locator('[data-testid="email-item"]').first().click()
    await page.locator('.email-detail-body').first().waitFor({ state: 'visible', timeout: 10000 })
    await page.keyboard.press('r')

    await expect(
      page.locator('[data-testid="reply-composer"]')
    ).toBeVisible({ timeout: 10000 })

    // Pas d'erreur JS visible dans la page
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.waitForLoadState('networkidle')
    expect(errors.filter(e => e.toLowerCase().includes('signature')), 'Pas d\'erreur JS liée à la signature').toHaveLength(0)
  })
})
