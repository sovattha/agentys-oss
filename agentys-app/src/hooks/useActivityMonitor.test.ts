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

import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useActivityMonitor } from './useActivityMonitor'

const wsMock = vi.hoisted(() => {
  const state: {
    handler: ((event: unknown) => void) | null
    unsubscribe: ReturnType<typeof vi.fn>
  } = {
    handler: null,
    unsubscribe: vi.fn(),
  }
  return {
    state,
    subscribe: vi.fn((handler: (event: unknown) => void) => {
      state.handler = handler
      return state.unsubscribe
    }),
  }
})

vi.mock('../services/websocket', () => ({
  getWebSocketClient: () => ({
    subscribe: wsMock.subscribe,
  }),
}))

describe('useActivityMonitor — triage IA', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    wsMock.state.handler = null
    wsMock.state.unsubscribe.mockClear()
    wsMock.subscribe.mockClear()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("garde l'activité classify visible entre started et complete", () => {
    const { result, unmount } = renderHook(() => useActivityMonitor('connected'))

    expect(wsMock.subscribe).toHaveBeenCalledOnce()
    expect(wsMock.state.handler).not.toBeNull()

    act(() => {
      wsMock.state.handler?.({ type: 'labels_classification_started', data: { count: 3 } })
      vi.advanceTimersByTime(500)
    })

    expect(result.current.isActive).toBe(true)
    expect(result.current.primaryActivity?.type).toBe('classify')
    expect(result.current.primaryActivity?.label).toBe('activity_classifying')

    act(() => {
      wsMock.state.handler?.({ type: 'labels_classification_complete', data: { count: 3 } })
      vi.advanceTimersByTime(500)
    })

    expect(result.current.isActive).toBe(false)
    expect(result.current.primaryActivity).toBeNull()
    expect(result.current.justFinished).toBe(true)

    unmount()
  })
})
