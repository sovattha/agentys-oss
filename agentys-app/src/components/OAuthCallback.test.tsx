import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OAuthCallback } from './OAuthCallback'

describe('OAuthCallback', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
    window.history.replaceState({}, '', '/')
  })

  it('uses the captured OAuth query if the app route rewrote the current URL', async () => {
    window.history.replaceState({}, '', '/inbox')
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ready: true, needs_reauth: false, problem: null }),
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <OAuthCallback
        onComplete={vi.fn()}
        initialSearch="?provider=gmail&success=true&email=safari%40gmail.com&account_id=acc_1&token=jwt_race"
      />
    )

    await expect(
      screen.findByRole('heading', { name: /^(Connected!|Connecté !)$/ })
    ).resolves.toBeInTheDocument()
    await expect(screen.findByText(/safari@gmail\.com/)).resolves.toBeInTheDocument()
    await waitFor(() => {
      expect(localStorage.getItem('agentys_jwt')).toBe('jwt_race')
    })
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/oauth/tokens/acc_1/readiness'),
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer jwt_race' }),
      })
    )
  })

  it('blocks app access and asks for reauth when OAuth scopes are incomplete', async () => {
    const onComplete = vi.fn()
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ready: false,
        needs_reauth: true,
        problem: 'missing_scopes',
        provider: 'gmail',
        email: 'safari@gmail.com',
        account_id: 'acc_1',
        missing_scope_labels: ['Lecture des emails', 'Envoi des emails'],
        repair_url: 'https://myaccount.google.com/permissions',
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <OAuthCallback
        onComplete={onComplete}
        initialSearch="?provider=gmail&success=true&email=safari%40gmail.com&account_id=acc_1&token=jwt_partial"
      />
    )

    await expect(
      screen.findByRole('heading', { name: /Incomplete connection|Connexion incomplète/i })
    ).resolves.toBeInTheDocument()
    expect(screen.getByText('Lecture des emails')).toBeInTheDocument()
    expect(screen.getByText('Envoi des emails')).toBeInTheDocument()
    expect(localStorage.getItem('agentys_jwt')).toBeNull()
    expect(onComplete).not.toHaveBeenCalled()
  })
})
