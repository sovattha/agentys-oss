import { beforeEach, describe, expect, it, vi } from 'vitest'
import { __resetQueryClientForTests, getQueryClient } from './queryClient'
import { syncUnreadLabelCountsAfterReadStateChange } from './labelCounts'

describe('label count cache', () => {
  beforeEach(() => {
    __resetQueryClientForTests()
  })

  it('met à jour immédiatement les compteurs unread-only quand un email Action devient lu', () => {
    const queryClient = getQueryClient()
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
    const queryKey = ['labelCounts', 'account-1', true] as const
    queryClient.setQueryData(queryKey, {
      __total__: 10,
      Action: 4,
      FYI: 2,
    })

    const changed = syncUnreadLabelCountsAfterReadStateChange({
      is_read: false,
      labels: [{ name: 'Action', color: '#ef4444' }],
    }, true)

    expect(changed).toBe(true)
    expect(queryClient.getQueryData(queryKey)).toEqual({
      __total__: 9,
      Action: 3,
      FYI: 2,
    })
    // The helper must NOT eagerly invalidate/refetch: an immediate refetch
    // races the not-yet-completed mark-read/unread server write and reverts
    // the optimistic patch (QA 2026-06-02). Callers reconcile after the write.
    expect(invalidateSpy).not.toHaveBeenCalled()
  })

  it('ignore les compteurs total quand seul le cache unread-only doit changer', () => {
    const queryClient = getQueryClient()
    const unreadKey = ['labelCounts', 'account-1', true] as const
    const totalKey = ['labelCounts', 'account-1', false] as const
    queryClient.setQueryData(unreadKey, { __total__: 1, Action: 1 })
    queryClient.setQueryData(totalKey, { __total__: 50, Action: 12 })

    syncUnreadLabelCountsAfterReadStateChange({
      is_read: false,
      labels: [{ name: 'Action', color: '#ef4444' }],
    }, true)

    expect(queryClient.getQueryData(unreadKey)).toEqual({ __total__: 0, Action: 0 })
    expect(queryClient.getQueryData(totalKey)).toEqual({ __total__: 50, Action: 12 })
  })
})
