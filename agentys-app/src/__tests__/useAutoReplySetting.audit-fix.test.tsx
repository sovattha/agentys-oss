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

import { renderHook, waitFor, act } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// i18n.t returns the key so assertions don't depend on locale JSON.
vi.mock('../i18n', () => ({
  default: { t: (key: string) => key },
}))

const cacheMocks = vi.hoisted(() => ({
  fetchSettingsCached: vi.fn(),
  invalidateSettingsCache: vi.fn(),
  patchSettingsCache: vi.fn(),
}))

vi.mock('../hooks/useSettingsCache', () => ({
  fetchSettingsCached: cacheMocks.fetchSettingsCached,
  invalidateSettingsCache: cacheMocks.invalidateSettingsCache,
  patchSettingsCache: cacheMocks.patchSettingsCache,
}))

vi.mock('../services/authToken', () => ({
  getAuthHeaders: () => ({}),
}))

import { useAutoReplySetting } from '../hooks/useAutoReplySetting'

function errorToasts(spy: ReturnType<typeof vi.spyOn>): Array<{ message?: string; type?: string }> {
  return spy.mock.calls
    .map((c: unknown[]) => c[0] as Event)
    .filter(
      (e: Event): e is CustomEvent =>
        e instanceof CustomEvent &&
        e.type === 'agentys:toast' &&
        (e.detail as { type?: string })?.type === 'error',
    )
    .map((e: CustomEvent) => e.detail as { message?: string; type?: string })
}

describe('useAutoReplySetting toggleAutoReply failure feedback (F-01)', () => {
  let dispatchSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    localStorage.clear()
    cacheMocks.fetchSettingsCached.mockReset()
    cacheMocks.invalidateSettingsCache.mockReset()
    cacheMocks.patchSettingsCache.mockReset()
    // Resolve the mount-time settings load with neutral data.
    cacheMocks.fetchSettingsCached.mockResolvedValue({})
    dispatchSpy = vi.spyOn(window, 'dispatchEvent')
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('dispatches an error toast when the PATCH returns a non-ok response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: () => Promise.resolve({}),
    })
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useAutoReplySetting())
    await waitFor(() => expect(cacheMocks.fetchSettingsCached).toHaveBeenCalled())

    await act(async () => {
      result.current.toggleAutoReply()
    })

    await waitFor(() => {
      const errors = errorToasts(dispatchSpy)
      expect(errors.some((d) => d.message === 'common:toasts.autoreply_save_failed')).toBe(true)
    })

    vi.unstubAllGlobals()
  })

  it('dispatches an error toast when the PATCH rejects (network error)', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('network down'))
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useAutoReplySetting())
    await waitFor(() => expect(cacheMocks.fetchSettingsCached).toHaveBeenCalled())

    await act(async () => {
      result.current.toggleAutoReply()
    })

    await waitFor(() => {
      const errors = errorToasts(dispatchSpy)
      expect(errors.some((d) => d.message === 'common:toasts.autoreply_save_failed')).toBe(true)
    })

    vi.unstubAllGlobals()
  })
})

describe('useAutoReplySetting loaded flag', () => {
  beforeEach(() => {
    localStorage.clear()
    cacheMocks.fetchSettingsCached.mockReset()
    cacheMocks.invalidateSettingsCache.mockReset()
    cacheMocks.patchSettingsCache.mockReset()
    vi.spyOn(console, 'error').mockImplementation(() => {})
    // No fetch needed: the mount-time load resolves via the cache mock and the
    // calendar sync is best-effort (its fetch failing is swallowed).
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('no network')))
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('starts false and flips true once the settings load resolves', async () => {
    cacheMocks.fetchSettingsCached.mockResolvedValue({ auto_reply_message: '' })

    const { result } = renderHook(() => useAutoReplySetting())
    // Synchronously, before the async load resolves, it must read false so the
    // pre-fill consumer can't mistake "not loaded yet" for "loaded empty".
    expect(result.current.loaded).toBe(false)

    await waitFor(() => expect(result.current.loaded).toBe(true))
  })

  it('stays false when the settings load rejects (server state unknown)', async () => {
    cacheMocks.fetchSettingsCached.mockRejectedValue(new Error('load failed'))

    const { result } = renderHook(() => useAutoReplySetting())
    await waitFor(() => expect(cacheMocks.fetchSettingsCached).toHaveBeenCalled())
    // A failed load leaves the stored message unknown — never signal "loaded"
    // or the consumer might pre-fill over a real (unfetched) message.
    expect(result.current.loaded).toBe(false)
  })
})
