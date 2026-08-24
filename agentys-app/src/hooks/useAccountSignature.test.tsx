/*
 * Agentys — voice-first email assistant.
 * Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version. See the LICENSE file for details.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

import { render, screen, waitFor, act } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

describe('useAccountSignature', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('re-fetches the signature after an account change', async () => {
    const fetchAccounts = vi.fn()
      .mockResolvedValueOnce({
        current_account_id: 'a',
        accounts: [{ id: 'a', signature: 'Signature A', signature_html: '' }],
      })
      .mockResolvedValueOnce({
        current_account_id: 'b',
        accounts: [{ id: 'b', signature: 'Signature B', signature_html: '' }],
      })

    vi.doMock('../api/accounts', () => ({ fetchAccounts }))
    vi.doMock('../services/authToken', () => ({ getStoredToken: () => 'jwt' }))

    const { useAccountSignature } = await import('./useAccountSignature')
    const { ACCOUNT_CHANGED, appEvents } = await import('../lib/appEvents')

    function Probe() {
      const signature = useAccountSignature()
      return <div>{signature.text || 'none'}</div>
    }

    render(<Probe />)
    await screen.findByText('Signature A')

    act(() => {
      appEvents.dispatchEvent(new Event(ACCOUNT_CHANGED))
    })

    await waitFor(() => expect(screen.getByText('Signature B')).toBeInTheDocument())
    expect(fetchAccounts).toHaveBeenCalledTimes(2)
  })

  it('does not pin an empty prefetch before login', async () => {
    let token: string | null = null
    const fetchAccounts = vi.fn().mockResolvedValue({
      current_account_id: 'a',
      accounts: [{ id: 'a', signature: 'Signature A', signature_html: '' }],
    })

    vi.doMock('../api/accounts', () => ({ fetchAccounts }))
    vi.doMock('../services/authToken', () => ({ getStoredToken: () => token }))

    const { prefetchAccountSignature, useAccountSignature } = await import('./useAccountSignature')

    prefetchAccountSignature()
    token = 'jwt'

    function Probe() {
      const signature = useAccountSignature()
      return <div>{signature.text || 'none'}</div>
    }

    render(<Probe />)

    await screen.findByText('Signature A')
    expect(fetchAccounts).toHaveBeenCalledTimes(1)
  })

  it('falls back to the is_current account when current_account_id does not match exposed ids', async () => {
    const fetchAccounts = vi.fn().mockResolvedValue({
      current_account_id: '4',
      accounts: [
        { id: 'hash-a', signature: 'Signature A', signature_html: '', is_current: false },
        { id: 'hash-b', signature: 'Signature B', signature_html: '', is_current: true },
      ],
    })

    vi.doMock('../api/accounts', () => ({ fetchAccounts }))
    vi.doMock('../services/authToken', () => ({ getStoredToken: () => 'jwt' }))

    const { useAccountSignature } = await import('./useAccountSignature')

    function Probe() {
      const signature = useAccountSignature()
      return <div>{signature.text || 'none'}</div>
    }

    render(<Probe />)

    await screen.findByText('Signature B')
  })

  it('prefers the requested reply account email over the global current account', async () => {
    const fetchAccounts = vi.fn().mockResolvedValue({
      current_account_id: 'hash-a',
      accounts: [
        {
          id: 'hash-a',
          email: 'active@example.com',
          signature: '',
          signature_html: '',
          is_current: true,
        },
        {
          id: 'hash-b',
          email: 'reply@example.com',
          signature: 'Reply Signature',
          signature_html: '',
          is_current: false,
        },
      ],
    })

    vi.doMock('../api/accounts', () => ({ fetchAccounts }))
    vi.doMock('../services/authToken', () => ({ getStoredToken: () => 'jwt' }))

    const { useAccountSignature } = await import('./useAccountSignature')

    function Probe() {
      const signature = useAccountSignature('reply@example.com')
      return <div>{signature.text || 'none'}</div>
    }

    render(<Probe />)

    await screen.findByText('Reply Signature')
  })
})
