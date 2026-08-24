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

import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ACCOUNT_INVALID_EVENT, getActiveAccountId, setActiveAccountId } from '../api/emails'
import { ONBOARDING_COMPLETE_KEY } from '../lib/storageKeys'
import { useBackendConnection } from './useBackendConnection'

const mockFetch = vi.fn()

function okJson(data: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => data,
  }
}

describe('useBackendConnection account recovery', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', mockFetch)
    localStorage.clear()
    localStorage.setItem('agentys_jwt', 'jwt-test')
    localStorage.setItem(ONBOARDING_COMPLETE_KEY, 'true')
    setActiveAccountId('default')
  })

  afterEach(() => {
    setActiveAccountId('default')
    localStorage.clear()
    vi.clearAllMocks()
    vi.unstubAllGlobals()
  })

  it('refreshes account data when the active account header is rejected', async () => {
    let initCalls = 0
    mockFetch.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/ping')) {
        return okJson({ version: 'test' })
      }
      if (url.includes('/api/init')) {
        initCalls += 1
        const id = initCalls === 1 ? 13 : 14
        return okJson({
          current_account_id: `hash-${id}`,
          accounts: [{
            id,
            hash_id: `hash-${id}`,
            email: 'nat@example.com',
            status: 'active',
          }],
        })
      }
      throw new Error(`Unexpected fetch: ${url}`)
    })

    const { result } = renderHook(() => useBackendConnection())

    await waitFor(() => expect(result.current.accountId).toBe(13))
    expect(getActiveAccountId()).toBe('13')

    await act(async () => {
      window.dispatchEvent(new CustomEvent(ACCOUNT_INVALID_EVENT))
    })

    await waitFor(() => expect(result.current.accountId).toBe(14))
    expect(getActiveAccountId()).toBe('14')
  })
})
