/**
 * Types for the rate-limited bulk-action queue.
 *
 * Mirrors `app/services/bulk_jobs/repository.py` + `app/db/models/bulk_job.py`
 * one-to-one. If the backend evolves (new job_type, new status, new field
 * on the Job/Item shape), update this file in the same PR — these types
 * are consumed by the BulkActionsPanel UI and the websocket handlers.
 */

export type BulkJobStatus =
  | 'queued'
  | 'running'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type BulkJobItemState =
  | 'pending'
  | 'in_progress'
  | 'succeeded'
  | 'failed'
  | 'skipped'

export type BulkJobSource = 'manual' | 'api' | 'auto_deletion'

export type BulkJobType =
  | 'mark_read'
  | 'mark_unread'
  | 'archive'
  | 'move_to_trash'
  | 'restore_from_trash'
  | 'move_to_inbox'
  | 'add_label'
  | 'delete_forever'

export interface BulkJob {
  id: string
  user_id: number | null
  account_id: number
  job_type: BulkJobType
  source: BulkJobSource
  status: BulkJobStatus
  target_total: number
  succeeded_count: number
  failed_count: number
  skipped_count: number
  params: Record<string, unknown> | null
  error_summary: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface BulkJobItem {
  id: number
  job_id: string
  provider_msg_id: string
  state: BulkJobItemState
  attempts: number
  last_error: string | null
  updated_at: string
}

// ── WebSocket payloads ─────────────────────────────────────────────────
export interface BulkJobEnqueuedEvent {
  job_id: string
  account_id: number
  job_type: BulkJobType
  source: BulkJobSource
  target_total: number
}

export interface BulkJobProgressEvent {
  job_id: string
  succeeded: number
  failed: number
  skipped: number
  total: number
  status: BulkJobStatus
}

export interface BulkJobStatusEvent {
  job_id: string
  status: BulkJobStatus
}

export interface BulkJobCompletedEvent {
  job_id: string
  status: BulkJobStatus
  succeeded: number
  failed: number
  skipped: number
  total: number
}

// ── Helpers (UI-side derivations) ──────────────────────────────────────
export const BULK_JOB_TERMINAL_STATUSES: ReadonlyArray<BulkJobStatus> = [
  'completed',
  'failed',
  'cancelled',
]

export function isTerminal(status: BulkJobStatus): boolean {
  return (BULK_JOB_TERMINAL_STATUSES as ReadonlyArray<string>).includes(status)
}

export function progressPercent(job: BulkJob): number {
  if (job.target_total <= 0) return 0
  const done = job.succeeded_count + job.failed_count + job.skipped_count
  return Math.min(100, Math.round((done / job.target_total) * 100))
}
