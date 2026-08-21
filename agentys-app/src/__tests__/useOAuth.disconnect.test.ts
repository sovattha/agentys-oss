/**
 * Regression test — issue #176
 *
 * Cliquer sur "Déconnecter" (useOAuth) ne doit PAS purger le cache emails
 * côté frontend : la BDD serveur reste source de vérité, les données
 * doivent rester visibles (read-only) jusqu'à suppression explicite du compte.
 *
 * Garde-fou :
 *  - disconnect() n'appelle pas `invalidateEmailCache`
 *  - L'accountId est conservé dans le state (les vues filtrées par compte
 *    continuent donc d'afficher l'historique chargé depuis la BDD)
 *  - Le status bascule bien à 'disconnected'
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

const { invalidateEmailCacheMock, checkTokenStatusMock } = vi.hoisted(() => ({
  invalidateEmailCacheMock: vi.fn(),
  checkTokenStatusMock: vi.fn().mockResolvedValue({
    hasTokens: true,
    isValid: true,
    email: 'alice@example.com',
  }),
}))

vi.mock('../api/emails', () => ({
  invalidateEmailCache: invalidateEmailCacheMock,
}))

vi.mock('../services/tokenStorage', () => ({
  isTauri: () => false,
  checkTokenStatus: checkTokenStatusMock,
}))

vi.mock('../config', () => ({
  API_URL: 'http://localhost:5050',
  IS_CLOUD: false,
}))

import { renderHook, act, waitFor } from '@testing-library/react'
import { useOAuth } from '../hooks/useOAuth'

describe('useOAuth.disconnect — issue #176', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 })
    )
  })

  it('ne purge pas le cache emails à la déconnexion', async () => {
    const { result } = renderHook(() => useOAuth('gmail', 'acct-123'))

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
      expect(result.current.status).toBe('connected')
    })

    await act(async () => {
      await result.current.disconnect()
    })

    expect(invalidateEmailCacheMock).not.toHaveBeenCalled()
  })

  it('conserve l\'accountId après déconnexion (mode read-only)', async () => {
    const { result } = renderHook(() => useOAuth('gmail', 'acct-123'))

    await waitFor(() => {
      expect(result.current.status).toBe('connected')
    })

    await act(async () => {
      await result.current.disconnect()
    })

    expect(result.current.status).toBe('disconnected')
    expect(result.current.accountId).toBe('acct-123')
    expect(result.current.token).toBeNull()
    expect(result.current.error).toBeNull()
  })

  it('notifie le backend pour révoquer les tokens OAuth', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    const { result } = renderHook(() => useOAuth('gmail', 'acct-123'))

    await waitFor(() => {
      expect(result.current.status).toBe('connected')
    })
    fetchSpy.mockClear()

    await act(async () => {
      await result.current.disconnect()
    })

    expect(fetchSpy).toHaveBeenCalledWith(
      'http://localhost:5050/api/oauth/acct-123/disconnect',
      expect.objectContaining({ method: 'POST' })
    )
  })
})
