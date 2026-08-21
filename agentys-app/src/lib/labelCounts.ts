import { getQueryClient } from './queryClient'
import type { Email } from '../types/email'

type LabelCounts = Record<string, number>

function clampCount(value: number): number {
  return Math.max(0, value)
}

export function invalidateLabelCounts(): void {
  void getQueryClient().invalidateQueries({ queryKey: ['labelCounts'] })
}

/**
 * Optimistically adjust the cached unread-only label counts when an email's
 * read state flips. Returns true when a delta was applied.
 *
 * IMPORTANT: this performs the optimistic cache patch ONLY — it deliberately
 * does NOT invalidate/refetch the counts query. Invalidating here re-fetched
 * `/api/labels/counts` immediately, which raced the not-yet-completed
 * `markEmailRead`/`markEmailUnread` server write: the refetch returned the
 * pre-change count and reverted the optimistic patch, so e.g. "Mark as unread"
 * left the badge stale until a full reload (QA 2026-06-02). Callers must
 * reconcile by calling `invalidateLabelCounts()` AFTER their server write
 * resolves (and `syncUnread...` again with the inverse delta on rollback).
 */
export function syncUnreadLabelCountsAfterReadStateChange(
  email: Pick<Email, 'is_read' | 'labels'> | null | undefined,
  nextIsRead: boolean,
): boolean {
  if (typeof email?.is_read !== 'boolean' || email.is_read === nextIsRead) {
    return false
  }

  const delta = nextIsRead ? -1 : 1
  const labelNames = Array.from(new Set((email.labels ?? []).map(label => label.name).filter(Boolean)))

  getQueryClient().setQueriesData<LabelCounts>(
    {
      queryKey: ['labelCounts'],
      predicate: query => query.queryKey[0] === 'labelCounts' && query.queryKey[2] === true,
    },
    previous => {
      if (!previous) return previous

      const next = { ...previous }
      if (typeof next.__total__ === 'number') {
        next.__total__ = clampCount(next.__total__ + delta)
      }

      for (const labelName of labelNames) {
        next[labelName] = clampCount((next[labelName] ?? 0) + delta)
      }

      return next
    },
  )
  return true
}
