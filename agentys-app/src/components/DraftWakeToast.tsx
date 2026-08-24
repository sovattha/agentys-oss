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
 * Floating toast that announces follow-up drafts whose snooze window has
 * elapsed and which are now ready to send.
 *
 * Visual pattern mirrors `MeetingImminentBanner` (icon + text + action
 * buttons) but lives at the bottom-right so it cannot overlap with a
 * concurrent meeting banner at the top.
 *
 * Two layouts:
 *   - Singular (1 draft): rich row with `[Send]`, `[Open]`, `[Snooze ▾]`,
 *     `[×]`. Sending goes through a short client-side UNDO window: clicking
 *     Send swaps the row for `[Undo send (n)] [×]` and only fires the real
 *     send when the countdown elapses. Cancelling (or ×) before then never
 *     hits the API. The text shows the recipient (protected from truncation —
 *     it wraps) plus a secondary line carrying the subject and a "no reply for
 *     Nd" signal so the user knows *why* the nudge fired without opening it.
 *   - Batched (≥ 2 drafts): summary row with `[Review N]`, `[Snooze all]`,
 *     `[×]`. The toast doesn't try to render each draft inline — the
 *     `[Review N]` button hands off to the Drafts tab for triage.
 *
 * The leading circular-arrow `FollowUpIcon` matches the follow-up Quick Step
 * on the Drafts row — a pencil/edit icon would mislabel a relance.
 *
 * Dedup, dismiss, and snooze decisions are owned by `useDraftWakeToasts`;
 * this component is presentation + intent-emitter only.
 */
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import type { PendingDraft } from '../services/api'
import { CloseIcon, ChevronDownIcon, FollowUpIcon } from './icons/ActionIcons'
import './DraftWakeToast.css'

const DAY_MS = 24 * 60 * 60 * 1000

/** Seconds the "Undo send" window stays open before the real send fires.
 *  Mirrors Gmail's buffered-send pattern; short enough not to feel laggy. */
const UNDO_WINDOW_S = 5

/** Snooze durations offered by the per-draft `Snooze ▾` popover. The hook's
 *  `snoozeOne(id, ms)` re-fires the toast after `ms`, so these map straight
 *  through. Labels live in i18n (`wake_toast.snooze_*`). */
const SNOOZE_OPTIONS: ReadonlyArray<{ id: string; key: string; ms: number }> = [
  { id: '1d', key: 'snooze_1d', ms: DAY_MS },
  { id: '3d', key: 'snooze_3d', ms: 3 * DAY_MS },
  { id: '1w', key: 'snooze_1w', ms: 7 * DAY_MS },
]

/** Mirrors `humaniseSender` in `PendingDraftList.tsx` so the recipient
 *  label renders identically across surfaces. Local copy keeps the toast
 *  bundle decoupled from PendingDraftList. */
function humaniseSender(raw: string): string {
  if (!raw) return raw
  const atIdx = raw.indexOf('@')
  const local = atIdx > 0 ? raw.substring(0, atIdx) : raw
  if (!local) return raw
  const parts = local
    .split(/[._\-+]/)
    .filter((p) => p.length > 0)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1).toLowerCase())
  return parts.join(' ') || local
}

function getRecipientLabel(d: PendingDraft): string {
  const name = (d.email_sender_name || '').trim()
  if (name) {
    return name.includes('.') && !name.includes(' ') ? humaniseSender(name) : name
  }
  return humaniseSender(d.email_sender || '')
}

/** Whole days since `iso`. For a follow-up draft `created_at` is set when the
 *  triggering email was sent, so this is "days the recipient has gone without
 *  replying". Returns null when unknown or < 1 day (no useful signal yet). */
function daysSinceNoReply(iso?: string): number | null {
  if (!iso) return null
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return null
  const days = Math.floor((Date.now() - t) / DAY_MS)
  return days >= 1 ? days : null
}

/** Per-draft "Snooze ▾" popover. Plain tab-navigable buttons (no `role=menu`
 *  semantics we don't fully honour): focus moves to the first option on open,
 *  Escape closes and returns focus to the trigger, outside-pointer closes. */
function SnoozeMenu({
  draftId,
  disabled,
  onSnooze,
  t,
}: {
  draftId: string
  disabled: boolean
  onSnooze: (draftId: string, ms?: number) => void
  t: TFunction
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const firstItemRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const onDocPointerDown = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        triggerRef.current?.focus()
      }
    }
    document.addEventListener('pointerdown', onDocPointerDown)
    document.addEventListener('keydown', onKeyDown)
    // Move focus into the popover so keyboard users land on the first option.
    firstItemRef.current?.focus()
    return () => {
      document.removeEventListener('pointerdown', onDocPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  return (
    <div className="draft-wake-toast__snooze" ref={ref}>
      <button
        ref={triggerRef}
        type="button"
        className="draft-wake-toast__btn draft-wake-toast__btn--menu"
        onClick={() => setOpen((o) => !o)}
        disabled={disabled}
        aria-haspopup="true"
        aria-expanded={open}
        data-testid="draft-wake-toast-snooze"
      >
        {t('wake_toast.action_snooze')}
        <ChevronDownIcon size={12} />
      </button>
      {open && (
        <div
          className="draft-wake-toast__snooze-menu"
          role="group"
          aria-label={t('wake_toast.action_snooze')}
          data-testid="draft-wake-toast-snooze-menu"
        >
          {SNOOZE_OPTIONS.map((opt, i) => (
            <button
              key={opt.id}
              ref={i === 0 ? firstItemRef : undefined}
              type="button"
              className="draft-wake-toast__snooze-item"
              onClick={() => {
                setOpen(false)
                onSnooze(draftId, opt.ms)
              }}
              data-testid={`draft-wake-toast-snooze-${opt.id}`}
            >
              {t(`wake_toast.${opt.key}`)}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export interface DraftWakeToastProps {
  drafts: PendingDraft[]
  /** Resolves on successful send. Throwing surfaces the inline error state. */
  onSend: (draft: PendingDraft) => Promise<void>
  /** Open the draft in its detail view. Parent handles routing. */
  onOpen: (draft: PendingDraft) => void
  /** Switch to the Drafts tab for batched triage. */
  onReviewAll: () => void
  /** Re-fire this draft's toast after `ms` (default 24h in the hook). */
  onSnoozeOne: (draftId: string, ms?: number) => void
  onSnoozeAll: () => void
  onDismissOne: (draftId: string) => void
  onDismissAll: () => void
  /** Auto-dismiss after this many ms. Pass 0 to disable. Default 0 — a
   *  decision-requiring toast should not vanish on a timer. */
  autoDismissMs?: number
}

export function DraftWakeToast({
  drafts,
  onSend,
  onOpen,
  onReviewAll,
  onSnoozeOne,
  onSnoozeAll,
  onDismissOne,
  onDismissAll,
  autoDismissMs = 0,
}: DraftWakeToastProps) {
  const { t } = useTranslation('drafts')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Buffered send: the draft currently in its undo window + the live count.
  const [pendingSendId, setPendingSendId] = useState<string | null>(null)
  const [undoSecs, setUndoSecs] = useState(UNDO_WINDOW_S)
  const sendTimerRef = useRef<number | null>(null)
  const countdownRef = useRef<number | null>(null)

  const clearSendTimers = () => {
    if (sendTimerRef.current !== null) window.clearTimeout(sendTimerRef.current)
    if (countdownRef.current !== null) window.clearInterval(countdownRef.current)
    sendTimerRef.current = null
    countdownRef.current = null
  }

  const doSend = async (draft: PendingDraft) => {
    clearSendTimers()
    setPendingSendId(null)
    setBusy(draft.id)
    setError(null)
    try {
      await onSend(draft)
      onDismissOne(draft.id)
    } catch {
      // Don't dismiss on failure — user retries from Drafts list or by
      // clicking Send again once the inline error clears.
      setError(t('wake_toast.error_send_failed'))
    } finally {
      setBusy(null)
    }
  }

  const startPendingSend = (draft: PendingDraft) => {
    clearSendTimers()
    setError(null)
    setPendingSendId(draft.id)
    setUndoSecs(UNDO_WINDOW_S)
    countdownRef.current = window.setInterval(() => {
      setUndoSecs((s) => (s > 0 ? s - 1 : 0))
    }, 1000)
    sendTimerRef.current = window.setTimeout(() => {
      void doSend(draft)
    }, UNDO_WINDOW_S * 1000)
  }

  const cancelPendingSend = () => {
    clearSendTimers()
    setPendingSendId(null)
  }

  // Reset transient state whenever the visible draft set changes (e.g. parent
  // dismissed one and a new one took its place). Also abandons any in-flight
  // undo window — we never want a countdown started for draft A to fire its
  // send after draft B has taken the row.
  const firstId = drafts[0]?.id ?? ''
  useEffect(() => {
    setError(null)
    setBusy(null)
    clearSendTimers()
    setPendingSendId(null)
  }, [firstId, drafts.length])

  // Clear timers on unmount. Closing the toast (or the app) inside the undo
  // window therefore cancels the send rather than firing it from a teardown —
  // the draft stays in Drafts, so nothing is silently sent or lost.
  useEffect(() => () => clearSendTimers(), [])

  useEffect(() => {
    if (autoDismissMs <= 0) return
    if (drafts.length === 0) return
    const id = window.setTimeout(() => {
      onDismissAll()
    }, autoDismissMs)
    return () => window.clearTimeout(id)
  }, [drafts.length, firstId, autoDismissMs, onDismissAll])

  if (drafts.length === 0) return null

  if (drafts.length === 1) {
    const d = drafts[0]
    const recipient = getRecipientLabel(d) || d.email_sender || ''
    const subject = d.draft_subject || d.email_subject || ''
    const noReplyDays = daysSinceNoReply(d.created_at)
    const isBusy = busy === d.id
    const isPending = pendingSendId === d.id

    return (
      <div
        className="draft-wake-toast"
        role="status"
        aria-live="polite"
        data-testid="draft-wake-toast"
      >
        <div className="draft-wake-toast__icon" aria-hidden="true">
          <FollowUpIcon size={18} />
        </div>
        <div className="draft-wake-toast__text">
          <strong className="draft-wake-toast__title">
            {t('wake_toast.title_singular', { recipient })}
          </strong>
          {(subject || noReplyDays != null) && (
            <span className="draft-wake-toast__meta">
              {subject && (
                <span className="draft-wake-toast__subject">{subject}</span>
              )}
              {noReplyDays != null && (
                <>
                  {subject && (
                    <span className="draft-wake-toast__sep" aria-hidden="true">
                      ·
                    </span>
                  )}
                  <span className="draft-wake-toast__noreply">
                    {t('wake_toast.no_reply_since', { count: noReplyDays })}
                  </span>
                </>
              )}
            </span>
          )}
          {error && (
            <span className="draft-wake-toast__error" role="alert">
              {error}
            </span>
          )}
        </div>
        {isPending ? (
          <div className="draft-wake-toast__actions">
            <button
              type="button"
              className="draft-wake-toast__btn draft-wake-toast__btn--primary"
              onClick={cancelPendingSend}
              data-testid="draft-wake-toast-undo"
            >
              {`${t('wake_toast.action_undo')} (${undoSecs})`}
            </button>
            <button
              type="button"
              className="draft-wake-toast__btn draft-wake-toast__btn--ghost"
              onClick={() => {
                cancelPendingSend()
                onDismissOne(d.id)
              }}
              aria-label={t('wake_toast.action_dismiss')}
              data-testid="draft-wake-toast-dismiss"
            >
              <CloseIcon size={14} />
            </button>
          </div>
        ) : (
          <div className="draft-wake-toast__actions">
            <button
              type="button"
              className="draft-wake-toast__btn draft-wake-toast__btn--primary"
              onClick={() => startPendingSend(d)}
              disabled={isBusy}
              data-testid="draft-wake-toast-send"
            >
              {isBusy ? t('sending') : t('wake_toast.action_send')}
            </button>
            <button
              type="button"
              className="draft-wake-toast__btn"
              onClick={() => {
                onOpen(d)
                onDismissOne(d.id)
              }}
              disabled={isBusy}
              data-testid="draft-wake-toast-open"
            >
              {t('wake_toast.action_open')}
            </button>
            <SnoozeMenu
              draftId={d.id}
              disabled={isBusy}
              onSnooze={onSnoozeOne}
              t={t}
            />
            <button
              type="button"
              className="draft-wake-toast__btn draft-wake-toast__btn--ghost"
              onClick={() => onDismissOne(d.id)}
              aria-label={t('wake_toast.action_dismiss')}
              data-testid="draft-wake-toast-dismiss"
            >
              <CloseIcon size={14} />
            </button>
          </div>
        )}
      </div>
    )
  }

  // Batched layout (≥ 2 drafts)
  return (
    <div
      className="draft-wake-toast"
      role="status"
      aria-live="polite"
      data-testid="draft-wake-toast-batched"
    >
      <div className="draft-wake-toast__icon" aria-hidden="true">
        <FollowUpIcon size={18} />
      </div>
      <div className="draft-wake-toast__text">
        <strong className="draft-wake-toast__title">
          {t('wake_toast.title_batched', { count: drafts.length })}
        </strong>
      </div>
      <div className="draft-wake-toast__actions">
        <button
          type="button"
          className="draft-wake-toast__btn draft-wake-toast__btn--primary"
          onClick={() => {
            onReviewAll()
            onDismissAll()
          }}
          data-testid="draft-wake-toast-review-all"
        >
          {t('wake_toast.action_review_all')}
        </button>
        <button
          type="button"
          className="draft-wake-toast__btn"
          onClick={onSnoozeAll}
          data-testid="draft-wake-toast-snooze-all"
        >
          {t('wake_toast.action_snooze_all_1d')}
        </button>
        <button
          type="button"
          className="draft-wake-toast__btn draft-wake-toast__btn--ghost"
          onClick={onDismissAll}
          aria-label={t('wake_toast.action_dismiss')}
          data-testid="draft-wake-toast-dismiss-all"
        >
          <CloseIcon size={14} />
        </button>
      </div>
    </div>
  )
}
