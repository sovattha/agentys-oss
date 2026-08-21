/**
 * useBulkJobs — single source of truth for the rate-limited bulk-action queue.
 *
 * Behavior:
 *   1. Initial fetch of the most recent jobs (default 50) via REST.
 *   2. Subscribe to four WS events: enqueued / progress / status / completed.
 *      Each event is folded into a job-id-keyed `Map` so the UI re-renders
 *      incrementally rather than refetching the whole list on every tick.
 *   3. On socket reconnect, refetch — `bulk_job_progress` is intentionally
 *      *not* buffered server-side (see `_BUFFER_EVENT_DENYLIST` in
 *      `app/api/websocket.py`), so a few seconds offline can leave us
 *      stale and a clean resync is cheaper than reasoning about deltas.
 *   4. Action handlers (pause/resume/cancel/retry) call the REST endpoint
 *      and then optimistically merge the returned job snapshot — the WS
 *      `bulk_job_status` event arrives a beat later and re-merges, which
 *      is fine because the merge is idempotent.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  cancelBulkJob,
  deleteBulkJob,
  listBulkJobs,
  pauseBulkJob,
  resumeBulkJob,
  retryBulkJobFailed,
} from '../services/api'
import { getWebSocketClient } from '../services/websocket'
import type { BulkJob, BulkJobStatus } from '../types/bulkJob'
import { isTerminal } from '../types/bulkJob'

interface UseBulkJobsResult {
  jobs: BulkJob[]
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  pause: (jobId: string) => Promise<void>
  resume: (jobId: string) => Promise<void>
  cancel: (jobId: string) => Promise<void>
  retryFailed: (jobId: string) => Promise<{ requeued: number }>
  dismiss: (jobId: string) => Promise<void>
}

const DEFAULT_LIMIT = 50

export function useBulkJobs(opts?: { limit?: number }): UseBulkJobsResult {
  const limit = opts?.limit ?? DEFAULT_LIMIT
  const [jobsById, setJobsById] = useState<Map<string, BulkJob>>(() => new Map())
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  // Keep the latest snapshot reference handy so handlers don't re-run on
  // every state change. Updated inside `setJobsById` callbacks.
  const isMountedRef = useRef(true)
  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
    }
  }, [])

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await listBulkJobs({ limit })
      if (!isMountedRef.current) return
      const map = new Map<string, BulkJob>()
      for (const j of res.jobs) map.set(j.id, j)
      setJobsById(map)
    } catch (e) {
      if (!isMountedRef.current) return
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      if (isMountedRef.current) setLoading(false)
    }
  }, [limit])

  // Initial fetch
  useEffect(() => {
    void refresh()
  }, [refresh])

  // Apply a partial update to a single job. Used by progress / status /
  // completed events. If the job is not yet in our map (race: enqueued
  // event hasn't landed), we create a stub entry so the UI doesn't lose
  // a job that finished before we registered its existence.
  const mergeJobPartial = useCallback(
    (jobId: string, patch: Partial<BulkJob>) => {
      setJobsById((prev) => {
        const current = prev.get(jobId)
        if (!current && !patch.id) {
          // No existing record AND the patch alone isn't enough to
          // hydrate one. Trigger a refresh in the background — cheaper
          // than fabricating a half-complete row.
          void refresh()
          return prev
        }
        const next = new Map(prev)
        next.set(jobId, { ...(current as BulkJob), ...patch, id: jobId })
        return next
      })
    },
    [refresh],
  )

  // Whole-job replacement (used after pause/resume/cancel/retry to merge
  // the server's authoritative snapshot).
  const setJob = useCallback((job: BulkJob) => {
    setJobsById((prev) => {
      const next = new Map(prev)
      next.set(job.id, job)
      return next
    })
  }, [])

  // ── WebSocket wiring ─────────────────────────────────────────────────
  useEffect(() => {
    const ws = getWebSocketClient()
    const unsubscribe = ws.subscribe((event) => {
      switch (event.type) {
        case 'bulk_job_enqueued': {
          const e = event.data
          // We don't have full counters yet; the next progress/completed
          // event will fill them in.
          mergeJobPartial(e.job_id, {
            id: e.job_id,
            account_id: e.account_id,
            job_type: e.job_type,
            source: e.source,
            target_total: e.target_total,
            status: 'queued' as BulkJobStatus,
            succeeded_count: 0,
            failed_count: 0,
            skipped_count: 0,
            // Best-effort — server payload doesn't include these but the
            // UI tolerates nulls/empties.
            user_id: null,
            params: null,
            error_summary: null,
            created_at: new Date().toISOString(),
            started_at: null,
            completed_at: null,
          })
          break
        }
        case 'bulk_job_progress': {
          const e = event.data
          mergeJobPartial(e.job_id, {
            succeeded_count: e.succeeded,
            failed_count: e.failed,
            skipped_count: e.skipped,
            target_total: e.total,
            status: e.status,
          })
          break
        }
        case 'bulk_job_status': {
          mergeJobPartial(event.data.job_id, { status: event.data.status })
          break
        }
        case 'bulk_job_completed': {
          const e = event.data
          mergeJobPartial(e.job_id, {
            status: e.status,
            succeeded_count: e.succeeded,
            failed_count: e.failed,
            skipped_count: e.skipped,
            target_total: e.total,
            completed_at: new Date().toISOString(),
          })
          break
        }
        case 'connectivity_changed':
        case 'back_online': {
          // Resync after the socket reconnects — see header comment.
          void refresh()
          break
        }
        default:
          break
      }
    })
    return () => {
      unsubscribe()
    }
  }, [mergeJobPartial, refresh])

  // ── action helpers ───────────────────────────────────────────────────
  const pause = useCallback(
    async (jobId: string) => {
      try {
        const res = await pauseBulkJob(jobId)
        setJob(res.job)
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        throw e
      }
    },
    [setJob],
  )
  const resume = useCallback(
    async (jobId: string) => {
      try {
        const res = await resumeBulkJob(jobId)
        setJob(res.job)
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        throw e
      }
    },
    [setJob],
  )
  const cancel = useCallback(
    async (jobId: string) => {
      try {
        const res = await cancelBulkJob(jobId)
        setJob(res.job)
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        throw e
      }
    },
    [setJob],
  )
  const retryFailed = useCallback(
    async (jobId: string) => {
      try {
        const res = await retryBulkJobFailed(jobId)
        setJob(res.job)
        return { requeued: res.requeued }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        throw e
      }
    },
    [setJob],
  )
  const dismiss = useCallback(async (jobId: string) => {
    try {
      await deleteBulkJob(jobId)
      // Optimistically drop the row — the job is terminal, so there's no
      // WS event coming to remove it for us.
      setJobsById((prev) => {
        if (!prev.has(jobId)) return prev
        const next = new Map(prev)
        next.delete(jobId)
        return next
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      throw e
    }
  }, [])

  // Sort: active jobs (non-terminal) first, then most-recent terminal.
  const jobs = useMemo<BulkJob[]>(() => {
    const all = Array.from(jobsById.values())
    return all.sort((a, b) => {
      const aActive = !isTerminal(a.status) ? 0 : 1
      const bActive = !isTerminal(b.status) ? 0 : 1
      if (aActive !== bActive) return aActive - bActive
      // Both same activity bucket → newer first.
      return (b.created_at || '').localeCompare(a.created_at || '')
    })
  }, [jobsById])

  return {
    jobs,
    loading,
    error,
    refresh,
    pause,
    resume,
    cancel,
    retryFailed,
    dismiss,
  }
}
