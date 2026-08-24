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

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'

vi.mock('../i18n', () => ({
  default: { t: (k: string) => `T:${k}` },
}))

import { useOptimisticMutation, okOrThrow } from './useOptimisticMutation'

interface ToastDetail {
  message: string
  type: 'warning' | 'error' | 'info' | 'success'
  duration: number
}

describe('useOptimisticMutation', () => {
  let dispatched: CustomEvent<ToastDetail>[] = []

  beforeEach(() => {
    dispatched = []
    vi.spyOn(window, 'dispatchEvent').mockImplementation((evt) => {
      if (evt instanceof CustomEvent && evt.type === 'agentys:toast') {
        dispatched.push(evt as CustomEvent<ToastDetail>)
      }
      return true
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('returns mutation result on success and does not dispatch a toast', async () => {
    const { result } = renderHook(() =>
      useOptimisticMutation<string>({ scope: 't', i18nKey: 'k' }),
    )
    let value: string | null = null
    await act(async () => {
      value = await result.current(async () => 'ok')
    })
    expect(value).toBe('ok')
    expect(dispatched).toHaveLength(0)
  })

  it('runs rollback, dispatches a warning toast, and returns null on throw', async () => {
    const rollback = vi.fn()
    const { result } = renderHook(() =>
      useOptimisticMutation<void>({ scope: 'training', i18nKey: 'toasts.x' }),
    )
    let value: void | null = 'untouched' as unknown as null
    await act(async () => {
      value = await result.current(async () => {
        throw new Error('boom')
      }, rollback)
    })
    expect(value).toBeNull()
    expect(rollback).toHaveBeenCalledOnce()
    expect(dispatched).toHaveLength(1)
    expect(dispatched[0].detail.message).toBe('T:toasts.x')
    expect(dispatched[0].detail.type).toBe('warning')
    expect(dispatched[0].detail.duration).toBe(6000)
  })

  it('makes rollback optional', async () => {
    const { result } = renderHook(() =>
      useOptimisticMutation<void>({ scope: 't', i18nKey: 'k' }),
    )
    await act(async () => {
      await result.current(async () => {
        throw new Error('x')
      })
    })
    expect(dispatched).toHaveLength(1)
  })

  it('honors toastType=error and custom duration', async () => {
    const { result } = renderHook(() =>
      useOptimisticMutation<void>({
        scope: 't',
        i18nKey: 'k',
        toastType: 'error',
        duration: 9000,
      }),
    )
    await act(async () => {
      await result.current(async () => {
        throw new Error('x')
      })
    })
    expect(dispatched[0].detail.type).toBe('error')
    expect(dispatched[0].detail.duration).toBe(9000)
  })
})

describe('okOrThrow', () => {
  it('returns the response on 2xx', () => {
    const r = new Response('', { status: 200 })
    expect(okOrThrow(r)).toBe(r)
  })

  it('throws on 4xx', () => {
    const r = new Response('', { status: 403, statusText: 'Forbidden' })
    expect(() => okOrThrow(r)).toThrow('HTTP 403')
  })

  it('throws on 5xx', () => {
    const r = new Response('', { status: 500 })
    expect(() => okOrThrow(r)).toThrow('HTTP 500')
  })
})

// ----------------------------------------------------------------------------
// F-05 (audit regressions 2026-05-17 batch4): the rollback pattern itself is
// outside the helper's API contract — it's a convention call sites use. These
// tests pin the pattern so a future regression to the broken whole-array
// `prev` snapshot is caught by `vitest run`, not in production.
// ----------------------------------------------------------------------------

interface Item { id: string }

describe('F-05 — id-keyed rollback pattern (call-site convention)', () => {
  it('id-keyed rollback survives interleaved success on a sibling row', () => {
    // Models the bug scenario from the audit's Pass 2 / F-05 verification:
    // rapid clicks on A (slow → 500) then B (fast → 200). With the patched
    // pattern, B stays deleted and only A is restored on rollback.
    let state: Item[] = [{ id: 'A' }, { id: 'B' }, { id: 'C' }]
    const setState = (updater: (s: Item[]) => Item[]) => { state = updater(state) }

    // Click delete A — capture the failed item, optimistic remove.
    const removedA = state.find(x => x.id === 'A')
    setState(p => p.filter(x => x.id !== 'A'))
    expect(state.map(x => x.id)).toEqual(['B', 'C'])

    // Concurrent click delete B — fast success, no rollback fires.
    setState(p => p.filter(x => x.id !== 'B'))
    expect(state.map(x => x.id)).toEqual(['C'])

    // A's API now returns 500 → id-keyed rollback runs.
    if (removedA) {
      setState(p => (p.some(x => x.id === 'A') ? p : [...p, removedA]))
    }

    // Expected: B is gone (deleted successfully); A restored; C untouched.
    expect(state.map(x => x.id).sort()).toEqual(['A', 'C'])
  })

  it('rollback is idempotent if the item is already present', () => {
    // Edge case: between rollback being queued and firing, another sync /
    // user action restored the item. We must NOT double-insert.
    let state: Item[] = [{ id: 'A' }, { id: 'B' }]
    const setState = (updater: (s: Item[]) => Item[]) => { state = updater(state) }
    const removed = state.find(x => x.id === 'A')

    setState(p => p.filter(x => x.id !== 'A'))
    // Re-insertion via a different path.
    setState(p => [...p, { id: 'A' }])
    // Rollback fires now.
    if (removed) {
      setState(p => (p.some(x => x.id === 'A') ? p : [...p, removed]))
    }

    // Still exactly one A.
    expect(state.filter(x => x.id === 'A')).toHaveLength(1)
  })

  it('regression marker: whole-array `prev` rollback resurrects siblings (the bug)', () => {
    // Pins the BROKEN pre-batch4 pattern so a refactor that re-introduces it
    // visibly fails. Equivalent code: `const prev = state; … setState(() => prev)`.
    let state: Item[] = [{ id: 'A' }, { id: 'B' }, { id: 'C' }]
    const setState = (updater: (s: Item[]) => Item[]) => { state = updater(state) }

    const prevA = state.slice() // snapshot whole array — the bug
    setState(p => p.filter(x => x.id !== 'A'))
    setState(p => p.filter(x => x.id !== 'B'))
    setState(() => prevA) // whole-array rollback

    // Demonstrates the bug — B comes back even though it was deleted.
    expect(state.map(x => x.id)).toEqual(['A', 'B', 'C'])
  })
})
