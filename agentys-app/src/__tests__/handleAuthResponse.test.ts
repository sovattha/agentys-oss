/**
 * Regression tests — 9-commit auth chain (chaîne du 2026-04-21)
 *
 * Invariant testé : `handleAuthResponse(response)` escalade un 401 via un
 * CustomEvent `auth:unauthorized` INCONDITIONNELLEMENT. Jamais de garde sur
 * `getStoredToken()`.
 *
 * Cf. tasks/lessons.md §"Architecture — Auth error escalation" (2026-04-21) et
 * Régression historique : onboarding figé à 0% faute de traitement correct
 * de la réponse d'auth.
 *
 * Historique de la régression :
 *   - Commit 94d8af7a ajoute handleAuthResponse (sans garde).
 *   - Commit 1e202a42 introduit un faux garde-fou
 *       `if (response.status === 401 && getStoredToken())`
 *     pensé contre un boot race — mais crée pire : `useAuth` clear le token sur
 *     le 1er /api/auth/me 401, puis 20+ hooks parallèles (settings, specialties,
 *     reminders, accounts, init, wizard/status) reçoivent chacun leur 401
 *     quelques ms plus tard avec `getStoredToken() === null`. Résultat :
 *     38 erreurs 401 empilées dans la console DevTools, aucun logout déclenché,
 *     user bloqué sur l'onboarding à 0% sans redirect vers /login.
 *   - Commit fdda0dd3 revert le garde-fou. Le gating boot-race est remonté
 *     chez le consumer (via `auth.isAuthenticated` sur useEffect), pas dans
 *     le helper. La règle : un helper d'auth doit TOUJOURS escalader, sinon
 *     les callers parallèles se marchent dessus.
 *
 * Si un dev remet un garde `&& getStoredToken()` (ou équivalent : && isAuthed,
 * && hasAccount…) dans handleAuthResponse, ces tests cassent.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { handleAuthResponse } from '../services/authToken'

const STORAGE_KEY = 'agentys_jwt'
const makeResponse = (status: number): Response => new Response(null, { status })

describe('handleAuthResponse — escalade 401 inconditionnelle (lesson 2026-04-21)', () => {
  let dispatchSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    // setup.ts::beforeEach clear déjà localStorage. Spy sur window.dispatchEvent
    // pour observer les CustomEvent('auth:unauthorized').
    dispatchSpy = vi.spyOn(window, 'dispatchEvent')
  })

  afterEach(() => {
    dispatchSpy.mockRestore()
  })

  /** Compte les événements auth:unauthorized dispatchés depuis le spy. */
  const countAuthUnauthorized = () =>
    dispatchSpy.mock.calls.filter(
      ([e]: [Event]) => e instanceof CustomEvent && e.type === 'auth:unauthorized',
    ).length

  it('dispatch auth:unauthorized sur 401 AVEC token stocké', () => {
    localStorage.setItem(STORAGE_KEY, 'valid-token-abc123')
    handleAuthResponse(makeResponse(401))
    expect(countAuthUnauthorized()).toBe(1)
  })

  it('dispatch auth:unauthorized sur 401 SANS token stocké (cœur de la lesson)', () => {
    // Scénario exact de la régression : `useAuth.catch` a déjà clearé le
    // token, et maintenant un 2e hook reçoit son 401. Sans ce dispatch,
    // App.tsx ne reçoit jamais l'événement et le user reste bloqué.
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
    handleAuthResponse(makeResponse(401))
    expect(countAuthUnauthorized()).toBe(1)
  })

  it.each([200, 201, 204, 301, 302, 400, 403, 404, 409, 422, 500, 502, 503])(
    'ne dispatch PAS auth:unauthorized sur status %d (seul 401 est un signal d\'auth)',
    (status) => {
      localStorage.setItem(STORAGE_KEY, 'anything')
      handleAuthResponse(makeResponse(status))
      expect(countAuthUnauthorized()).toBe(0)
    },
  )

  it('retourne la Response INCHANGÉE (les callers chaînent .ok / .json())', () => {
    const original = makeResponse(401)
    const result = handleAuthResponse(original)
    expect(result).toBe(original)
  })

  it('retourne la Response inchangée aussi sur 200 (pas de side-effect accidentel)', () => {
    const original = makeResponse(200)
    const result = handleAuthResponse(original)
    expect(result).toBe(original)
    expect(countAuthUnauthorized()).toBe(0)
  })

  it('20 hooks parallèles recevant chacun un 401 → 20 escalades (aucune avalée)', () => {
    // Reproduit le pattern de la régression décrite en tête de fichier :
    // useLearningProgress + useSettingsCache + refreshAccountData + createSettingHook
    // + App.tsx fetch direct + useWizardStatus + useInitFetch + useAccountsPolling
    // + ... tous fire au boot. Une fois le JWT clearé, chacun reçoit un 401.
    // Le helper doit escalader CHAQUE fois — App.tsx dedup côté listener.
    for (let i = 0; i < 20; i++) {
      handleAuthResponse(makeResponse(401))
    }
    expect(countAuthUnauthorized()).toBe(20)
  })

  it('l\'event est bien un CustomEvent de type auth:unauthorized (contrat App.tsx)', () => {
    handleAuthResponse(makeResponse(401))
    const authCalls = dispatchSpy.mock.calls.filter(
      ([e]: [Event]) => e instanceof Event && e.type === 'auth:unauthorized',
    )
    expect(authCalls).toHaveLength(1)
    const event = authCalls[0][0] as Event
    expect(event).toBeInstanceOf(CustomEvent)
    expect(event.type).toBe('auth:unauthorized')
  })
})
