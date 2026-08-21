/**
 * BulkActionsPanel — Settings → "Background Tasks" section.
 *
 * Renders the live state of the bulk-action queue (`useBulkJobs`) with
 * inline pause / resume / cancel / retry controls. Designed to be
 * dropped into `Settings.tsx` next to "Automatic Deletion".
 *
 * All user-visible strings come from i18n (settings namespace, keys
 * prefixed `bulk_*`). Adding a new locale only requires updating the
 * matching JSON file under `agentys-app/src/i18n/locales/<lang>/settings.json`.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'

import i18n from '../../i18n'
import { formatShortDateFromDate, formatHourMinute } from '../../utils/dateFormat'
import { useBulkJobs } from '../../hooks/useBulkJobs'
import type { BulkJob, BulkJobStatus, BulkJobType } from '../../types/bulkJob'
import { isTerminal, progressPercent } from '../../types/bulkJob'
import { CloseIcon } from '../icons/ActionIcons'
import './BulkActionsPanel.css'

type TFn = (key: string, options?: Record<string, unknown>) => string

function jobTypeLabel(t: TFn, jobType: BulkJobType | string): string {
  // Falls through to the raw enum value for unknown types so a backend
  // that ships a new job_type doesn't render an empty cell.
  const key = `bulk_type_${jobType}`
  const label = t(key)
  return label === key ? String(jobType) : label
}

function statusLabel(t: TFn, status: BulkJobStatus | string): string {
  const key = `bulk_status_${status}`
  const label = t(key)
  return label === key ? String(status) : label
}

function sourceLabel(t: TFn, source: string): string {
  const key = `bulk_source_${source}`
  const label = t(key)
  return label === key ? source : label
}

function formatAbsolute(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  // Active UI language (not the browser locale) + ordinal house style:
  // "May 27th, 15:50" (EN) / "27 mai, 15h50" (FR).
  return `${formatShortDateFromDate(d, i18n.language)}, ${formatHourMinute(d, i18n.language)}`
}

function formatRelative(t: TFn, iso: string | null): string {
  if (!iso) return ''
  const ts = Date.parse(iso)
  if (Number.isNaN(ts)) return ''
  const deltaSec = Math.max(0, Math.floor((Date.now() - ts) / 1000))
  if (deltaSec < 60) return t('bulk_relative_now')
  if (deltaSec < 3600) return t('bulk_relative_minutes', { n: Math.floor(deltaSec / 60) })
  if (deltaSec < 86400) return t('bulk_relative_hours', { n: Math.floor(deltaSec / 3600) })
  return t('bulk_relative_days', { n: Math.floor(deltaSec / 86400) })
}

// A failure is non-retryable when retrying it is a guaranteed dead-end —
// today that's a missing-OAuth-scope permanent-delete job (the backend
// error_summary reads "insufficient OAuth scope: …"). For these we hide
// "Retry failures" (it would just 403 again) and offer "Dismiss" instead.
// The matched string is a server-generated diagnostic, not localized.
function isNonRetryable(job: BulkJob): boolean {
  const s = job.error_summary
  if (!s) return false
  return /insufficient oauth scope|permanent delete/i.test(s)
}

// Visual accent (hue) per job_type — drives the icon tile background.
// Falls back to neutral slate when an unknown type comes through.
function jobAccent(jobType: BulkJobType | string): string {
  switch (jobType) {
    case 'archive':
    case 'move_to_inbox':
    case 'restore_from_trash':
      return 'blue'
    case 'mark_read':
    case 'mark_unread':
      return 'violet'
    case 'add_label':
      return 'amber'
    case 'move_to_trash':
      return 'orange'
    case 'delete_forever':
      return 'red'
    default:
      return 'slate'
  }
}

// SVG glyph per job_type. Stroke-only, 18×18, inherits currentColor so
// the icon tile owns the hue.
function JobTypeIcon({ jobType }: { jobType: BulkJobType | string }) {
  const common = {
    width: 18,
    height: 18,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  }
  switch (jobType) {
    case 'archive':
      return (
        <svg {...common}>
          <rect x="3" y="4" width="18" height="4" rx="1" />
          <path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8" />
          <path d="M10 12h4" />
        </svg>
      )
    case 'move_to_trash':
      return (
        <svg {...common}>
          <path d="M3 6h18" />
          <path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
          <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
        </svg>
      )
    case 'delete_forever':
      return (
        <svg {...common}>
          <path d="M3 6h18" />
          <path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
          <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
          <path d="M10 11l4 6m0-6l-4 6" />
        </svg>
      )
    case 'restore_from_trash':
      return (
        <svg {...common}>
          <path d="M3 6h18" />
          <path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
          <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
          <path d="M9 14l3-3 3 3M12 11v6" />
        </svg>
      )
    case 'move_to_inbox':
      return (
        <svg {...common}>
          <path d="M22 12h-6l-2 3h-4l-2-3H2" />
          <path d="M5 4h14l3 8v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6l3-8z" />
        </svg>
      )
    case 'mark_read':
      return (
        <svg {...common}>
          <path d="M4 6h16v12H4z" />
          <path d="M4 6l8 7 8-7" />
          <path d="M9 14l2 2 4-4" />
        </svg>
      )
    case 'mark_unread':
      return (
        <svg {...common}>
          <path d="M4 6h16v12H4z" />
          <path d="M4 6l8 7 8-7" />
          <circle cx="19" cy="6" r="2.5" fill="currentColor" stroke="none" />
        </svg>
      )
    case 'add_label':
      return (
        <svg {...common}>
          <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" />
          <circle cx="7.5" cy="6.5" r="1.5" fill="currentColor" stroke="none" />
        </svg>
      )
    default:
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3 2" />
        </svg>
      )
  }
}

interface RowProps {
  job: BulkJob
  busy: boolean
  onPause: (id: string) => Promise<void>
  onResume: (id: string) => Promise<void>
  onCancel: (id: string) => Promise<void>
  onRetry: (id: string) => Promise<void>
  onDismiss: (id: string) => Promise<void>
  onSelect: (job: BulkJob) => void
}

function BulkJobRow({ job, busy, onPause, onResume, onCancel, onRetry, onDismiss, onSelect }: RowProps) {
  const { t } = useTranslation('settings')
  const percent = progressPercent(job)
  const done = job.succeeded_count + job.failed_count + job.skipped_count
  const remaining = Math.max(0, job.target_total - done)
  const terminal = isTerminal(job.status)
  const accent = jobAccent(job.job_type)

  // Past-tense summary keyed by job_type ("35 messages permanently deleted"),
  // falling back to the generic count when no specific key exists. Computed
  // once and reused as the hero summary line.
  const summary =
    job.succeeded_count > 0
      ? t(`bulk_done_${job.job_type}`, {
          count: job.succeeded_count,
          defaultValue: t('bulk_count_succeeded', { n: job.succeeded_count }),
        })
      : t(`bulk_type_${job.job_type}`, { defaultValue: String(job.job_type) })

  const successRate =
    terminal && job.target_total > 0
      ? Math.round((job.succeeded_count / job.target_total) * 100)
      : null

  const showBreakdown =
    terminal && (job.failed_count > 0 || job.skipped_count > 0 || !!job.error_summary)

  return (
    <div
      className={`bulk-job-row bulk-job-row--${job.status}`}
      data-accent={accent}
      role="button"
      tabIndex={0}
      onClick={() => onSelect(job)}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(job) } }}
    >
      {/* Hero line: icon tile + summary stack + status/time stack */}
      <div className="bulk-job-row__hero">
        <div className="bulk-job-row__icon" aria-hidden="true">
          <JobTypeIcon jobType={job.job_type} />
        </div>

        <div className="bulk-job-row__main">
          <div className="bulk-job-row__title">
            {jobTypeLabel(t, job.job_type)}
          </div>
          <div className="bulk-job-row__summary">{summary}</div>
        </div>

        <div className="bulk-job-row__meta">
          <span className={`bulk-job-row__status bulk-job-row__status--${job.status}`}>
            {statusLabel(t, job.status)}
          </span>
          <span className="bulk-job-row__time">
            {formatRelative(t, job.completed_at || job.started_at || job.created_at)}
          </span>
        </div>
      </div>

      {!terminal && (
        <div className="bulk-job-row__progress-wrap">
          <div className="bulk-job-row__progress" aria-label={t('bulk_progress_aria')}>
            <div
              className="bulk-job-row__progress-bar"
              style={{ width: `${percent}%` }}
            />
          </div>
          <span className="bulk-job-row__progress-text">
            {t('bulk_progress_text', { percent, done, total: job.target_total, remaining })}
          </span>
        </div>
      )}

      {/* Breakdown strip — hidden for clean runs to keep the card tight */}
      {(showBreakdown || successRate !== null) && (
        <div className="bulk-job-row__chips">
          <span className="bulk-job-row__chip bulk-job-row__chip--source">
            {sourceLabel(t, job.source)}
          </span>
          {successRate !== null && job.failed_count === 0 && job.skipped_count === 0 && (
            <span className="bulk-job-row__chip bulk-job-row__chip--ok">
              {successRate}%
            </span>
          )}
          {job.failed_count > 0 && (
            <span className="bulk-job-row__chip bulk-job-row__chip--err">
              {t('bulk_done_failed', { count: job.failed_count })}
            </span>
          )}
          {job.skipped_count > 0 && (
            <span className="bulk-job-row__chip bulk-job-row__chip--skip">
              {t('bulk_done_skipped', { count: job.skipped_count })}
            </span>
          )}
          {job.error_summary && (
            <span
              className="bulk-job-row__chip bulk-job-row__chip--err-detail"
              title={job.error_summary}
            >
              {job.error_summary}
            </span>
          )}
        </div>
      )}

      {/* Source-only chip when nothing else to show but we still want context */}
      {!showBreakdown && successRate === null && (
        <div className="bulk-job-row__chips">
          <span className="bulk-job-row__chip bulk-job-row__chip--source">
            {sourceLabel(t, job.source)}
          </span>
          <span className="bulk-job-row__chip bulk-job-row__chip--count">
            {job.target_total}
          </span>
        </div>
      )}

      {(job.status === 'running' ||
        job.status === 'paused' ||
        terminal ||
        (!terminal && job.status !== 'queued')) && (
        <div className="bulk-job-row__actions">
          {job.status === 'running' && (
            <button
              className="bulk-job-row__btn"
              disabled={busy}
              onClick={() => onPause(job.id)}
            >
              {t('bulk_action_pause')}
            </button>
          )}
          {job.status === 'paused' && (
            <button
              className="bulk-job-row__btn"
              disabled={busy}
              onClick={() => onResume(job.id)}
            >
              {t('bulk_action_resume')}
            </button>
          )}
          {!terminal && (
            <button
              className="bulk-job-row__btn bulk-job-row__btn--danger"
              disabled={busy}
              onClick={() => onCancel(job.id)}
            >
              {t('bulk_action_cancel')}
            </button>
          )}
          {terminal && job.failed_count > 0 && !isNonRetryable(job) && (
            <button
              className="bulk-job-row__btn"
              disabled={busy}
              onClick={() => onRetry(job.id)}
            >
              {t('bulk_action_retry_failed')}
            </button>
          )}
          {terminal && (
            <button
              className="bulk-job-row__btn"
              disabled={busy}
              onClick={(e) => { e.stopPropagation(); void onDismiss(job.id) }}
            >
              {t('bulk_action_dismiss')}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

interface DetailModalProps {
  job: BulkJob
  busy: boolean
  onClose: () => void
  onPause: (id: string) => Promise<void>
  onResume: (id: string) => Promise<void>
  onCancel: (id: string) => Promise<void>
  onRetry: (id: string) => Promise<void>
  onDismiss: (id: string) => Promise<void>
}

function BulkJobDetailModal({ job, busy, onClose, onPause, onResume, onCancel, onRetry, onDismiss }: DetailModalProps) {
  const { t } = useTranslation('settings')
  const percent = progressPercent(job)
  const terminal = isTerminal(job.status)
  const accent = jobAccent(job.job_type)

  const summary =
    job.succeeded_count > 0
      ? t(`bulk_done_${job.job_type}`, {
          count: job.succeeded_count,
          defaultValue: t('bulk_count_succeeded', { n: job.succeeded_count }),
        })
      : t(`bulk_type_${job.job_type}`, { defaultValue: String(job.job_type) })

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.stopImmediatePropagation(); onClose() }
    }
    window.addEventListener('keydown', handleEsc, true)
    return () => window.removeEventListener('keydown', handleEsc, true)
  }, [onClose])

  return createPortal(
    <div className="bulk-detail-backdrop" onClick={onClose}>
      <div
        className="bulk-detail-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={t('bulk_detail_aria')}
      >
        {/* Header */}
        <div className="bulk-detail-header">
          <div className="bulk-detail-header__icon" data-accent={accent}>
            <JobTypeIcon jobType={job.job_type} />
          </div>
          <div className="bulk-detail-header__main">
            <span className="bulk-detail-header__title">{jobTypeLabel(t, job.job_type)}</span>
            <span className="bulk-detail-header__summary">{summary}</span>
          </div>
          <span className={`bulk-job-row__status bulk-job-row__status--${job.status}`}>
            {statusLabel(t, job.status)}
          </span>
          <button className="bulk-detail-close" onClick={onClose} aria-label={t('bulk_detail_close')}>
            <CloseIcon size={16} />
          </button>
        </div>

        {/* Timestamps */}
        <div className="bulk-detail-timestamps">
          <div className="bulk-detail-ts">
            <span className="bulk-detail-ts__label">{t('bulk_detail_created')}</span>
            <span className="bulk-detail-ts__value">{formatAbsolute(job.created_at)}</span>
          </div>
          <div className="bulk-detail-ts">
            <span className="bulk-detail-ts__label">{t('bulk_detail_started')}</span>
            <span className="bulk-detail-ts__value">{formatAbsolute(job.started_at)}</span>
          </div>
          <div className="bulk-detail-ts">
            <span className="bulk-detail-ts__label">{t('bulk_detail_completed')}</span>
            <span className="bulk-detail-ts__value">{formatAbsolute(job.completed_at)}</span>
          </div>
        </div>

        {/* Counts */}
        <div className="bulk-detail-counts">
          <div className="bulk-detail-count bulk-detail-count--ok">
            <span className="bulk-detail-count__n">{job.succeeded_count}</span>
            <span className="bulk-detail-count__label">{t('bulk_detail_succeeded')}</span>
          </div>
          <div className="bulk-detail-count bulk-detail-count--err">
            <span className="bulk-detail-count__n">{job.failed_count}</span>
            <span className="bulk-detail-count__label">{t('bulk_detail_failed')}</span>
          </div>
          <div className="bulk-detail-count bulk-detail-count--skip">
            <span className="bulk-detail-count__n">{job.skipped_count}</span>
            <span className="bulk-detail-count__label">{t('bulk_detail_skipped')}</span>
          </div>
          <div className="bulk-detail-count">
            <span className="bulk-detail-count__n">{job.target_total}</span>
            <span className="bulk-detail-count__label">{t('bulk_detail_total')}</span>
          </div>
        </div>

        {/* Progress — only when active */}
        {!terminal && (
          <div className="bulk-detail-progress">
            <div className="bulk-job-row__progress">
              <div className="bulk-job-row__progress-bar" style={{ width: `${percent}%` }} />
            </div>
            <span className="bulk-job-row__progress-text">
              {t('bulk_progress_text', {
                percent,
                done: job.succeeded_count + job.failed_count + job.skipped_count,
                total: job.target_total,
                remaining: Math.max(0, job.target_total - job.succeeded_count - job.failed_count - job.skipped_count),
              })}
            </span>
          </div>
        )}

        {/* Error summary */}
        {job.error_summary && (
          <div className="bulk-detail-error">
            <span className="bulk-detail-error__label">{t('bulk_detail_error')}</span>
            <span className="bulk-detail-error__text">{job.error_summary}</span>
          </div>
        )}

        {/* Source chip + job id */}
        <div className="bulk-detail-meta">
          <span className="bulk-job-row__chip bulk-job-row__chip--source">{sourceLabel(t, job.source)}</span>
          <span className="bulk-detail-meta__id" title={job.id}>{job.id.slice(0, 8)}…</span>
        </div>

        {/* Actions */}
        {(job.status === 'running' || job.status === 'paused' || (!terminal && job.status !== 'queued') || terminal) && (
          <div className="bulk-detail-actions">
            {job.status === 'running' && (
              <button className="bulk-job-row__btn" disabled={busy} onClick={() => onPause(job.id)}>
                {t('bulk_action_pause')}
              </button>
            )}
            {job.status === 'paused' && (
              <button className="bulk-job-row__btn" disabled={busy} onClick={() => onResume(job.id)}>
                {t('bulk_action_resume')}
              </button>
            )}
            {!terminal && (
              <button className="bulk-job-row__btn bulk-job-row__btn--danger" disabled={busy} onClick={() => onCancel(job.id)}>
                {t('bulk_action_cancel')}
              </button>
            )}
            {terminal && job.failed_count > 0 && !isNonRetryable(job) && (
              <button className="bulk-job-row__btn" disabled={busy} onClick={() => onRetry(job.id)}>
                {t('bulk_action_retry_failed')}
              </button>
            )}
            {terminal && (
              <button
                className="bulk-job-row__btn"
                disabled={busy}
                onClick={async () => { await onDismiss(job.id); onClose() }}
              >
                {t('bulk_action_dismiss')}
              </button>
            )}
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}

export function BulkActionsPanel() {
  const { t } = useTranslation('settings')
  const { jobs, loading, error, pause, resume, cancel, retryFailed, dismiss } =
    useBulkJobs({ limit: 50 })

  const [busyId, setBusyId] = useState<string | null>(null)
  const [selectedJob, setSelectedJob] = useState<BulkJob | null>(null)

  const wrap = useCallback(
    (op: (id: string) => Promise<unknown>) =>
      async (jobId: string) => {
        setBusyId(jobId)
        try {
          await op(jobId)
        } finally {
          setBusyId((prev) => (prev === jobId ? null : prev))
        }
      },
    [],
  )

  const handlers = useMemo(
    () => ({
      onPause: wrap(pause),
      onResume: wrap(resume),
      onCancel: wrap(cancel),
      onRetry: wrap(async (id: string) => {
        await retryFailed(id)
      }),
      onDismiss: wrap(dismiss),
    }),
    [wrap, pause, resume, cancel, retryFailed, dismiss],
  )

  return (
    <section className="bulk-actions-panel">
      <header className="bulk-actions-panel__header">
        <h3>{t('bulk_actions_title')}</h3>
      </header>

      {error && (
        <div className="bulk-actions-panel__error" role="alert">
          {error}
        </div>
      )}

      {jobs.length > 0 && (
        <div className="bulk-actions-panel__list">
          {jobs.map((job) => (
            <BulkJobRow
              key={job.id}
              job={job}
              busy={busyId === job.id}
              onPause={handlers.onPause}
              onResume={handlers.onResume}
              onCancel={handlers.onCancel}
              onRetry={handlers.onRetry}
              onDismiss={handlers.onDismiss}
              onSelect={setSelectedJob}
            />
          ))}
        </div>
      )}

      {/* Empty state only when the fetch genuinely succeeded with no jobs.
          Never alongside an error: a failed fetch tells us nothing about
          whether tasks exist, so "No active task" would be a lie (the bug
          where users saw "Failed to fetch" stacked on "No active task"). */}
      {!loading && !error && jobs.length === 0 && (
        <div className="bulk-actions-panel__empty">
          {t('bulk_actions_empty')}
        </div>
      )}

      {selectedJob && (
        <BulkJobDetailModal
          job={selectedJob}
          busy={busyId === selectedJob.id}
          onClose={() => setSelectedJob(null)}
          onPause={handlers.onPause}
          onResume={handlers.onResume}
          onCancel={handlers.onCancel}
          onRetry={handlers.onRetry}
          onDismiss={handlers.onDismiss}
        />
      )}
    </section>
  )
}
