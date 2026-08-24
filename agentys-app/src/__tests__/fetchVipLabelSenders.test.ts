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

/**
 * F08 (MEDIUM) — silent-failure regression guard for DeepWorkPanel VIP fetch.
 *
 * Pure-helper tests for `fetchVipLabelSenders`. Designed to run in Vitest's
 * `node` environment without jsdom — only minimal globals are stubbed.
 *
 * Pre-patch: `/api/labels/vip` 401/500 was masked as `null` → empty VIP
 * suggestion list. User thought they had no VIP senders to surface.
 * Post-patch: typed errors propagate, 401 fires `auth:unauthorized`.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Stub `window` BEFORE importing anything that touches it (authToken does).
// Note : avant le canary vitest (jsdom), ce test tournait en environnement
// `node` pur sans `window`. Maintenant jsdom fournit `window`, donc le shim
// `globalThis.window = …` ne prend pas effet (l'expression `||` shortcircuit).
// Solution : spy explicite sur window.dispatchEvent quel que soit l'env.
const mockDispatch = vi.fn()
const mockLocalStorage = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => { store[k] = v },
    removeItem: (k: string) => { delete store[k] },
    clear: () => { store = {} },
  }
})()

if (typeof (globalThis as any).window === 'undefined') {
  // Env node pur — créer un window minimaliste.
  ;(globalThis as any).window = { dispatchEvent: mockDispatch }
} else {
  // Env jsdom — spy sur window.dispatchEvent existant.
  vi.spyOn(window, 'dispatchEvent').mockImplementation(mockDispatch)
}
;(globalThis as any).localStorage = mockLocalStorage
;(globalThis as any).CustomEvent =
  (globalThis as any).CustomEvent ||
  class CustomEvent {
    type: string
    detail: any
    constructor(type: string, init?: { detail?: any }) {
      this.type = type
      this.detail = init?.detail
    }
  }

import { fetchVipLabelSenders } from '../components/DeepWorkPanel'

const fetchMock = vi.fn()

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockReset()
  mockDispatch.mockReset()
  mockLocalStorage.clear()
  mockLocalStorage.setItem('agentys_jwt', 'tkn')
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function makeResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const countAuthUnauthorized = () =>
  mockDispatch.mock.calls.filter(
    (call: any[]) => call[0]?.type === 'auth:unauthorized',
  ).length

describe('fetchVipLabelSenders — silent failure surface (F08)', () => {
  it('200 with vip_senders list → returns parsed payload (control)', async () => {
    fetchMock.mockResolvedValueOnce(
      makeResponse({ vip_senders: ['boss@corp.com', 'ceo@corp.com'] }),
    )
    const out = await fetchVipLabelSenders()
    expect(out.vipSenders).toEqual(['boss@corp.com', 'ceo@corp.com'])
  })

  it('200 with empty payload → returns empty list', async () => {
    fetchMock.mockResolvedValueOnce(makeResponse({ vip_senders: [] }))
    const out = await fetchVipLabelSenders()
    expect(out.vipSenders).toEqual([])
  })

  it('200 with malformed payload (no vip_senders key) → coerces safely', async () => {
    fetchMock.mockResolvedValueOnce(makeResponse({}))
    const out = await fetchVipLabelSenders()
    expect(out.vipSenders).toEqual([])
  })

  it('200 with non-array vip_senders → coerces to empty', async () => {
    fetchMock.mockResolvedValueOnce(makeResponse({ vip_senders: 'oops' }))
    const out = await fetchVipLabelSenders()
    expect(out.vipSenders).toEqual([])
  })

  it('401 → throws unauthorized AND dispatches auth:unauthorized', async () => {
    fetchMock.mockResolvedValueOnce(
      makeResponse({ error: 'Unauthorized' }, 401),
    )
    await expect(fetchVipLabelSenders()).rejects.toMatchObject({
      message: 'unauthorized',
      kind: 'unauthorized',
    })
    expect(countAuthUnauthorized()).toBe(1)
  })

  it('500 → throws HTTP error (NOT silent empty)', async () => {
    fetchMock.mockResolvedValueOnce(makeResponse({ error: 'boom' }, 500))
    await expect(fetchVipLabelSenders()).rejects.toMatchObject({
      kind: 'http',
      status: 500,
    })
    expect(countAuthUnauthorized()).toBe(0)
  })

  it('502 → throws HTTP 502', async () => {
    fetchMock.mockResolvedValueOnce(makeResponse({ error: 'bad gw' }, 502))
    await expect(fetchVipLabelSenders()).rejects.toMatchObject({
      kind: 'http',
      status: 502,
    })
  })

  it('network failure → propagates the underlying error', async () => {
    fetchMock.mockRejectedValueOnce(new Error('net'))
    await expect(fetchVipLabelSenders()).rejects.toThrow('net')
  })

  it('AbortSignal threading: passing a signal works', async () => {
    fetchMock.mockResolvedValueOnce(makeResponse({ vip_senders: [] }))
    const ctrl = new AbortController()
    await fetchVipLabelSenders(ctrl.signal)
    const callArgs = fetchMock.mock.calls[0][1]
    expect(callArgs?.signal).toBe(ctrl.signal)
  })
})
