import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { act, renderHook } from '@testing-library/react'

import { useNavigationController } from './useNavigationController'

const KEY_PREFIX = 'agentys-inbox-active-label'

describe('useNavigationController F-03 — per-account activeLabel scoping', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  afterEach(() => {
    window.localStorage.clear()
  })

  it('persists the label under an account-scoped key', () => {
    const { result } = renderHook(() => useNavigationController(42))
    act(() => result.current.setActiveLabel('Action'))
    expect(window.localStorage.getItem(`${KEY_PREFIX}:42`)).toBe('Action')
    // Pre-batch4 global key must remain untouched so old installs don't
    // accidentally inherit a leaked value on next read.
    expect(window.localStorage.getItem(KEY_PREFIX)).toBeNull()
  })

  it('reads the correct per-account value on mount', () => {
    window.localStorage.setItem(`${KEY_PREFIX}:42`, 'Action')
    window.localStorage.setItem(`${KEY_PREFIX}:99`, 'FYI')
    const { result: a } = renderHook(() => useNavigationController(42))
    const { result: b } = renderHook(() => useNavigationController(99))
    expect(a.current.activeLabel).toBe('Action')
    expect(b.current.activeLabel).toBe('FYI')
  })

  it('resets activeLabel when accountId changes (the leak the audit caught)', () => {
    // Account A has "Action" pinned. Account B has no persisted label.
    window.localStorage.setItem(`${KEY_PREFIX}:42`, 'Action')

    const { result, rerender } = renderHook(
      ({ accountId }) => useNavigationController(accountId),
      { initialProps: { accountId: 42 as number | null } },
    )
    expect(result.current.activeLabel).toBe('Action')

    rerender({ accountId: 99 })

    // Before the fix this stayed "Action" and EmailList fetched empty inbox.
    expect(result.current.activeLabel).toBeNull()
  })

  it('does not leak filter into another account via the bootstrap key', () => {
    // Mount with no accountId yet (bootstrap window), set a label.
    const initialProps: { accountId: number | null } = { accountId: null }
    const { result, rerender } = renderHook(
      ({ accountId }: { accountId: number | null }) => useNavigationController(accountId),
      { initialProps },
    )
    act(() => result.current.setActiveLabel('Action'))
    expect(window.localStorage.getItem(`${KEY_PREFIX}:__none__`)).toBe('Action')

    // /api/init resolves: real accountId arrives. Bootstrap value MUST NOT
    // leak into the real account's key.
    rerender({ accountId: 42 })
    expect(window.localStorage.getItem(`${KEY_PREFIX}:42`)).toBeNull()
    expect(result.current.activeLabel).toBeNull()
  })

  it('clears the per-account key when label set to null', () => {
    window.localStorage.setItem(`${KEY_PREFIX}:42`, 'Action')
    const { result } = renderHook(() => useNavigationController(42))
    expect(result.current.activeLabel).toBe('Action')
    act(() => result.current.setActiveLabel(null))
    expect(window.localStorage.getItem(`${KEY_PREFIX}:42`)).toBeNull()
  })

  it('does not write the global `agentys-inbox-active-label` key', () => {
    const { result } = renderHook(() => useNavigationController(42))
    act(() => result.current.setActiveLabel('Action'))
    act(() => result.current.setActiveLabel('FYI'))
    act(() => result.current.setActiveLabel(null))
    expect(window.localStorage.getItem(KEY_PREFIX)).toBeNull()
  })
})
