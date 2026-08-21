import { useEffect, useRef } from 'react'
import i18n from '../i18n'
import { getWebSocketClient, type WebSocketEvent } from '../services/websocket'
import { getNotificationService } from '../services/notifications'
import { playUISound } from '../services/uiSounds'
import { invalidateEmailCache, getActiveAccountId } from '../api/emails'
import { resolveToIntString } from '../lib/accountIdMap'
import { getQueryClient } from '../lib/queryClient'
import { invalidateLabelCounts } from '../lib/labelCounts'
import type { Email } from '../types/email'

// ============================================================================
// Draft streaming cache — stores streaming chunks for active email
// ============================================================================

export interface DraftCritiqueState {
  decision: 'valid' | 'reject'
  score: number
  suggestions: string[]
  motive?: string
}

interface DraftStreamState {
  emailId: string
  accumulatedText: string
  isComplete: boolean
  progressPercent: number
  stageName?: string
  stageLabel?: string
  /** Incremented each time the Critic rejects and a new version starts streaming. V1 = 1. */
  versionIndex: number
  /** Internal flag: next draft_chunk starts a new version (reset accumulated text). */
  expectsNewVersion: boolean
  /** Latest critique verdict + score, used by ThoughtStream and RecapBanner. */
  critique?: DraftCritiqueState
  /** Score of the very first critique (V1 → v2 delta). */
  initialCritiqueScore?: number
  /** True when the backend cut the draft off (token limit). UI warns the user
   * to review before sending (launch audit 2026-05-30 — was dropped silently). */
  truncated?: boolean
  /**
   * Non-destructive revision proposal (2026-05-05).
   *
   * Populated when the backend `STREAM_V1_BEFORE_CRITIC_NONDESTRUCTIVE` flag
   * is on and the critic rejected V1 — instead of silently overwriting V1
   * with V2, the backend emits `draft_revised` with both versions. The UI
   * surfaces a toggle ("View improved version") so the user keeps any
   * mid-edit changes if they choose.
   *
   * `undefined` = no revision proposed (or user dismissed).
   */
  revision?: {
    v1: string
    v2: string
    summary: string
  }
}

/**
 * Extract a short motive keyword from critique suggestions.
 * Maps English/French critic vocabulary onto i18n suffix keys consumed by
 * `compose.story_motive_*` in translations. Keeps the storytelling labels
 * short and specific rather than dumping the raw critique text.
 */
function _deriveMotive(suggestions: string[] = [], explanation?: string): string | undefined {
  const blob = [...suggestions, explanation || ''].join(' ').toLowerCase()
  if (!blob.trim()) return undefined
  if (/\b(ton|tone|sec|abrupt|direct|tranchant|froid)\b/.test(blob)) return 'direct'
  if (/\b(long|longueur|verbeux|verbose|wordy|redondan)\b/.test(blob)) return 'long'
  if (/\b(clair|clarity|confus|flou|vague|ambigu)\b/.test(blob)) return 'blurred'
  if (/\b(polit|respect|formule|greeting|courtois|chaleur)\b/.test(blob)) return 'abrupt'
  if (/\b(formel|formal|raide|stiff|guindé)\b/.test(blob)) return 'formal'
  return 'default'
}

const STAGE_LABELS: Record<string, string> = {
  classification: 'Classification',
  redaction: 'AI drafting',
  critique: 'Quality check',
  revision: 'Improving',
  optimisation: 'Optimizing',
  finalisation: 'Finalizing',
}

function emailFromNewEmailEvent(data: Extract<WebSocketEvent, { type: 'new_email' }>['data']): Email | null {
  if (data.email) return data.email
  if (!data.email_id) return null
  return {
    id: data.email_id,
    sender: data.sender || '',
    sender_name: data.sender_name ?? null,
    subject: data.subject || '',
    received_at: data.received_at || new Date().toISOString(),
    is_read: data.is_read ?? false,
    has_attachments: data.has_attachments ?? false,
    conversation_id: data.conversation_id ?? null,
    body_preview: data.body_preview || data.snippet || '',
    labels: [],
    has_pending_draft: false,
    draft_skipped: false,
  }
}

const _draftStreamCache = new Map<string, DraftStreamState>()
const _draftStreamListeners = new Set<(state: DraftStreamState) => void>()
const STREAM_CACHE_EVICT_MS = 60_000 // Evict completed entries after 60s
// Tracks pending auto-evict timers so they can be cancelled when a new
// stream event arrives for the same email or when the host hook unmounts.
// Without this, every completed stream left a dangling timer reference.
const _pendingEvictTimers = new Map<string, ReturnType<typeof setTimeout>>()

export function getDraftStreamState(emailId: string): DraftStreamState | undefined {
  return _draftStreamCache.get(emailId)
}

export function clearDraftStreamState(emailId: string): void {
  _draftStreamCache.delete(emailId)
  const pending = _pendingEvictTimers.get(emailId)
  if (pending) {
    clearTimeout(pending)
    _pendingEvictTimers.delete(emailId)
  }
}

export function subscribeDraftStream(listener: (state: DraftStreamState) => void): () => void {
  _draftStreamListeners.add(listener)
  return () => { _draftStreamListeners.delete(listener) }
}

function _scheduleDraftStreamEviction(emailId: string): void {
  const existing = _pendingEvictTimers.get(emailId)
  if (existing) clearTimeout(existing)
  const handle = setTimeout(() => {
    _pendingEvictTimers.delete(emailId)
    const cached = _draftStreamCache.get(emailId)
    if (cached?.isComplete) {
      _draftStreamCache.delete(emailId)
    }
  }, STREAM_CACHE_EVICT_MS)
  _pendingEvictTimers.set(emailId, handle)
}

function _cancelAllDraftStreamEvictions(): void {
  // CRITICAL: this clears timers GLOBALLY across every useWebSocketSync
  // instance. Today `<App>` only mounts one, so the simplification is fine.
  // If a second concurrent instance is ever added (split-pane, modal, etc.),
  // switch `_pendingEvictTimers` to a per-instance ref and drop this helper.
  for (const handle of _pendingEvictTimers.values()) {
    clearTimeout(handle)
  }
  _pendingEvictTimers.clear()
}

// Throttle draft chunk notifications to one per animation frame to avoid
// flooding the renderer with rapid state updates during streaming.
let _pendingDraftStreamNotify: DraftStreamState | null = null
let _draftStreamRafId: number | null = null

function _notifyDraftStreamListeners(state: DraftStreamState) {
  // Completion events are dispatched immediately so consumers can finalize.
  if (state.isComplete) {
    if (_draftStreamRafId !== null) {
      cancelAnimationFrame(_draftStreamRafId)
      _draftStreamRafId = null
      _pendingDraftStreamNotify = null
    }
    _draftStreamListeners.forEach((fn) => fn(state))
    _scheduleDraftStreamEviction(state.emailId)
    return
  }

  // For intermediate chunks, coalesce into a single RAF callback.
  _pendingDraftStreamNotify = state
  if (_draftStreamRafId === null) {
    _draftStreamRafId = requestAnimationFrame(() => {
      _draftStreamRafId = null
      const pending = _pendingDraftStreamNotify
      _pendingDraftStreamNotify = null
      if (pending) {
        _draftStreamListeners.forEach((fn) => fn(pending))
      }
    })
  }
}

// ============================================================================
// WebSocket sync hook
// ============================================================================

interface UseWebSocketSyncOptions {
  backendStatus: 'checking' | 'connected' | 'disconnected'
  onRefresh: () => void
  // Gate the socket on app-level auth. The cloud /daemon namespace rejects the
  // handshake when no JWT is present (server-side disconnect), which surfaces
  // as a `wss://…/socket.io/ Invalid frame header` console error plus a
  // reconnect storm on the login page. We only need the real-time inbox feed
  // once the user is past the login screen, so don't open the socket until
  // `isAuthenticated` flips true (QA 2026-05-19).
  isAuthenticated: boolean
}

export function useWebSocketSync({ backendStatus, onRefresh, isAuthenticated }: UseWebSocketSyncOptions) {
  const wasConnectedRef = useRef(false)
  // Grace period after connection — suppress notifications for initial sync emails
  const connectedAtRef = useRef(0)
  const NOTIFICATION_GRACE_MS = 15_000

  useEffect(() => {
    if (backendStatus !== 'connected') return
    if (!isAuthenticated) return

    // onRefresh is already debounced by App.tsx (500ms) — no double debounce needed
    const ws = getWebSocketClient()
    const unsubscribe = ws.subscribe((event: WebSocketEvent) => {
      if (event.type === 'connection_status') {
        const isConnected = event.data.connected
        if (isConnected && wasConnectedRef.current === false) {
          // Reconnection detected (or first connection) — clear stale IndexedDB then refresh
          invalidateEmailCache()
          onRefresh()
          connectedAtRef.current = Date.now()
        }
        wasConnectedRef.current = isConnected
        return
      }

      if (event.type === 'new_email') {
        // Suppress notifications during initial sync grace period — user already sees the inbox
        const inGracePeriod = Date.now() - connectedAtRef.current < NOTIFICATION_GRACE_MS
        // F06 (MEDIUM): cross-account leakage guard. If the backend daemon
        // sync fires a `new_email` for account B while the user is focused
        // on account A, the toast must not pop up for B (the email won't
        // even appear in the visible inbox). Backend payloads include an
        // optional `account_id` (number) that we compare to the active
        // account's id-or-hash. When backend doesn't include it (legacy
        // events), we keep the legacy behaviour and notify — parity safe.
        const eventAccountId = (event.data as { account_id?: string | number })?.account_id
        const activeAccountId = getActiveAccountId()
        // Audit F-03 (2026-05-17 deep-audit): backend always emits the
        // int account_id; the FE active-account store can hold either
        // form (int-string from /api/init, or hex from AccountManager
        // when the user clicks an inactive account). Fold the active
        // id to its int-string form before comparing so legit events
        // for the active account aren't dropped as "cross-account"
        // after every secondary account switch. Fallback to the raw
        // string when the resolver has no pair (boot race / unknown
        // account) — at worst we keep the previous behaviour.
        const normalizedActiveAccountId =
          resolveToIntString(activeAccountId) ?? activeAccountId
        const isCrossAccount =
          eventAccountId !== undefined &&
          normalizedActiveAccountId !== 'default' &&
          String(eventAccountId) !== String(normalizedActiveAccountId)
        if (!isCrossAccount) {
          const email = emailFromNewEmailEvent(event.data)
          if (email) {
            const shouldFallbackRefresh = window.dispatchEvent(
              new CustomEvent('agentys:email-upsert', {
                cancelable: true,
                detail: { email },
              })
            )
            if (shouldFallbackRefresh) onRefresh()
          } else {
            onRefresh()
          }
        }
        if (event.data.email_id && !inGracePeriod && !isCrossAccount) {
          const notif = getNotificationService()
          notif.notifyNewEmail({
            emailId: event.data.email_id,
            sender: event.data.sender,
            subject: event.data.subject,
          })
        }
      } else if (event.type === 'draft_ready') {
        onRefresh()
        playUISound('draftReady')
      } else if (event.type === 'draft_skipped') {
        onRefresh()
      } else if (event.type === 'draft_stage') {
        // Pipeline stage update: show which step is active
        const { email_id, stage, progress_percent } = event.data
        if (email_id) {
          const existing = _draftStreamCache.get(email_id)
          const state: DraftStreamState = {
            ...(existing || { emailId: email_id, accumulatedText: '', isComplete: false, progressPercent: 0, versionIndex: 1, expectsNewVersion: false }),
            emailId: email_id,
            stageName: stage,
            stageLabel: STAGE_LABELS[stage] || stage,
            progressPercent: progress_percent || existing?.progressPercent || 0,
          }
          _draftStreamCache.set(email_id, state)
          _notifyDraftStreamListeners(state)
        }
      } else if (event.type === 'critique_start') {
        // Critic evaluation started — maps to 'optimisation' stage (labeled "Critique" in UI)
        const { email_id } = event.data
        if (email_id) {
          const existing = _draftStreamCache.get(email_id)
          const state: DraftStreamState = {
            ...(existing || { emailId: email_id, accumulatedText: '', isComplete: false, progressPercent: 0, versionIndex: 1, expectsNewVersion: false }),
            emailId: email_id,
            stageName: 'optimisation',
            stageLabel: STAGE_LABELS['critique'],
            progressPercent: 75,
          }
          _draftStreamCache.set(email_id, state)
          _notifyDraftStreamListeners(state)
        }
      } else if (event.type === 'critique_complete') {
        // Critic verdict: store score + decision so ThoughtStream/RecapBanner can narrate.
        // On reject, flip `expectsNewVersion` so the next draft_chunk opens a fresh version
        // instead of concatenating/overwriting the V1 text visible in the editor.
        const { email_id, decision, overall_score, suggestions } = event.data
        if (email_id) {
          const existing = _draftStreamCache.get(email_id)
          const base = existing || { emailId: email_id, accumulatedText: '', isComplete: false, progressPercent: 0, versionIndex: 1, expectsNewVersion: false }
          const normalizedDecision: 'valid' | 'reject' = decision === 'reject' ? 'reject' : 'valid'
          const critique: DraftCritiqueState = {
            decision: normalizedDecision,
            score: overall_score ?? 0,
            suggestions: suggestions || [],
            motive: _deriveMotive(suggestions || [], undefined),
          }
          const initialScore = base.initialCritiqueScore ?? (base.versionIndex === 1 ? (overall_score ?? 0) : undefined)
          const state: DraftStreamState = {
            ...base,
            emailId: email_id,
            critique,
            initialCritiqueScore: initialScore,
            stageName: normalizedDecision === 'reject' ? 'redaction' : base.stageName,
            stageLabel: normalizedDecision === 'reject' ? STAGE_LABELS['revision'] : base.stageLabel,
            progressPercent: normalizedDecision === 'reject' ? 55 : (base.progressPercent || 85),
            expectsNewVersion: normalizedDecision === 'reject',
          }
          _draftStreamCache.set(email_id, state)
          _notifyDraftStreamListeners(state)
        }
      } else if (event.type === 'draft_chunk') {
        // Streaming: accumulate draft chunks for progressive display.
        // Two transport modes are in use (see backend app/smart_routing.py):
        //   1. True streaming — each chunk carries only the delta (`chunk`) and
        //      `accumulated_text` is omitted until the final chunk.
        //   2. Instant draft — backend calls `_emit_instant_draft` after a revision
        //      and sends ONE chunk with `accumulated_text` = full V2 text.
        // When a critique_complete with decision=reject has flipped
        // `expectsNewVersion`, we treat whatever comes next as the start of a new
        // version and reset `accumulatedText` so the editor does not briefly show
        // V1 concatenated with (or replaced by) V2 mid-stream.
        //
        // Note: do NOT set isComplete here — draft_complete event carries the
        // post-processed (cleaned) text and is the sole completion signal.
        const { email_id, chunk, accumulated_text, progress_percent } = event.data
        if (email_id) {
          const existing = _draftStreamCache.get(email_id)
          const shouldRollover = !!existing?.expectsNewVersion
          const baseText = shouldRollover ? '' : (existing?.accumulatedText || '')
          const newText = accumulated_text ?? (baseText + (chunk || ''))
          const state: DraftStreamState = {
            emailId: email_id,
            accumulatedText: newText,
            isComplete: false,
            progressPercent: progress_percent || 0,
            stageName: existing?.stageName,
            stageLabel: existing?.stageLabel,
            versionIndex: shouldRollover ? ((existing?.versionIndex || 1) + 1) : (existing?.versionIndex || 1),
            expectsNewVersion: false,
            critique: existing?.critique,
            initialCritiqueScore: existing?.initialCritiqueScore,
          }
          _draftStreamCache.set(email_id, state)
          _notifyDraftStreamListeners(state)
        }
      } else if (event.type === 'draft_error') {
        // Streaming failed — unblock 'generating' state using whatever was
        // accumulated so far, AND surface the backend's classified error to the
        // user instead of silently degrading to a generic 'finalisation' state
        // (launch audit 2026-05-30: mid-stream LLM failure showed nothing).
        const { email_id, error } = event.data
        if (email_id) {
          const existing = _draftStreamCache.get(email_id)
          const state: DraftStreamState = {
            emailId: email_id,
            accumulatedText: existing?.accumulatedText || '',
            isComplete: true,
            progressPercent: 100,
            stageName: 'finalisation',
            stageLabel: STAGE_LABELS['finalisation'],
            versionIndex: existing?.versionIndex || 1,
            expectsNewVersion: false,
            critique: existing?.critique,
            initialCritiqueScore: existing?.initialCritiqueScore,
          }
          _draftStreamCache.set(email_id, state)
          _notifyDraftStreamListeners(state)
          window.dispatchEvent(new CustomEvent('agentys:toast', {
            detail: {
              message: (typeof error === 'string' && error)
                ? error
                : i18n.t('drafts:toasts.draft_generation_failed', 'La génération du brouillon a échoué. Réessayez.'),
              type: 'error',
              duration: 8000,
            },
          }))
        }
      } else if (event.type === 'processing_error') {
        const { error } = event.data
        window.dispatchEvent(new CustomEvent('llm:error', { detail: { error } }))
      } else if (event.type === 'auth:token_expired') {
        const { account_id, email, provider } = event.data
        window.dispatchEvent(new CustomEvent('auth:token_expired', { detail: { account_id, email, provider } }))
      } else if (event.type === 'labels_updated' || event.type === 'relabel_complete') {
        // Labels changed — refresh list to show updated labels/filtering
        onRefresh()
        // Audit F-04 (2026-05-17 deep-audit): the TanStack labels/labelCounts
        // caches default to `staleTime: 30_000` (lib/queryClient.ts:22),
        // and `refetchOnWindowFocus` is off, so without an explicit
        // invalidation the sidebar shows up to 30 s of stale color/count
        // after a labels_updated WS event — inbox rows update via the
        // per-email patch path but the sidebar lags, which looks like a
        // sync bug across tabs. Invalidate by resource prefix so the
        // accountId segment doesn't have to match exactly.
        try {
          const qc = getQueryClient()
          qc.invalidateQueries({ queryKey: ['labels'] })
          qc.invalidateQueries({ queryKey: ['labelCounts'] })
        } catch {
          // QueryClient unavailable in some test builds; ignore.
        }
      } else if (event.type === 'email_archived') {
        // Incremental: remove from inbox list without full refetch
        window.dispatchEvent(new CustomEvent('agentys:email-remove', { detail: { email_id: event.data.email_id } }))
        // QA 2026-06-10: server-side archives (Quick Step auto-rules, other
        // devices) only reach the UI through this event — without a counts
        // refetch the header badge ("Inbox 292") stayed frozen while rows
        // visibly left the list. User-initiated archives already invalidate
        // in EmailList's handler; doing it here too is a cheap no-op then.
        invalidateLabelCounts()
      } else if (event.type === 'email_restored') {
        // Undo of an archive/delete — full refresh so the email reappears
        // at its correct position. There is no incremental "insert" path
        // and the row's metadata (folder, labels) may have shifted.
        onRefresh()
        invalidateLabelCounts()
      } else if (event.type === 'email_deleted') {
        // Incremental: remove from list without full refetch
        window.dispatchEvent(new CustomEvent('agentys:email-remove', { detail: { email_id: event.data.email_id } }))
        invalidateLabelCounts() // QA 2026-06-10: same staleness as email_archived
      } else if (event.type === 'email_updated') {
        // Incremental: merge partial patch into list state
        window.dispatchEvent(new CustomEvent('agentys:email-patch', {
          detail: { email_id: event.data.email_id, updates: event.data.updates },
        }))
        if (Object.prototype.hasOwnProperty.call(event.data.updates ?? {}, 'is_read')) {
          invalidateLabelCounts()
        }
      } else if (event.type === 'sync_complete') {
        // Audit 2026-05-17: the prior gate `newEmails > 0` made secondary
        // folders (spam, trash, archived) stuck on the skeleton for the
        // full 12s cold-start fallback. Reason: `_run_sync_job` emits
        // `sync_complete` with hardcoded `new_emails: 0` for those folders
        // (sync_jobs.py:631), so a user opening Spam saw the backend
        // finish in 1-2s but the FE didn't know to refresh until the
        // 12s timer.
        //
        // The presence of `job_id` indicates an explicit user-triggered
        // sync (vs the periodic full-sync that genuinely reports new
        // counts) — always refresh in that case. The periodic path keeps
        // its `> 0` guard so a quiet sync tick doesn't refetch for nothing.
        const data = event.data as { new_emails?: number; job_id?: string }
        const newEmails = data?.new_emails ?? 0
        if (data?.job_id || newEmails > 0) onRefresh()
      } else if (event.type === 'back_online') {
        // Backend recovered connectivity — refresh inbox
        onRefresh()
      } else if (event.type === 'noise_cleanup_complete') {
        // Noise cleanup complete (manual or auto) — always refresh the list
        invalidateEmailCache()
        onRefresh()
        window.dispatchEvent(new CustomEvent('agentys:noise-cleanup', { detail: event.data }))
      } else if (event.type === 'bulk_job_completed') {
        // BUG-O001 fix: background bulk jobs (e.g. "Mark all as read") silently failed —
        // the result was only visible in Settings > Automation, with no inbox notification.
        // Toast a warning when at least one action failed so the user knows without digging.
        const { failed, total, status } = event.data
        if ((failed ?? 0) > 0) {
          const failedCount = failed ?? 0
          const totalCount = total ?? failedCount
          window.dispatchEvent(new CustomEvent('agentys:toast', {
            detail: {
              message: i18n.t('common:toasts.bulk_action_partial_failure', { count: failedCount, total: totalCount }),
              type: 'warning',
              duration: 8000,
            },
          }))
        } else if (status === 'failed') {
          // Job-level failure (not individual items) — e.g. auth error cascaded
          window.dispatchEvent(new CustomEvent('agentys:toast', {
            detail: {
              message: i18n.t('common:toasts.bulk_action_failed'),
              type: 'error',
              duration: 8000,
            },
          }))
        }
      } else if (event.type === 'draft_complete') {
        // Final draft: update cache and trigger refresh. If the critic already
        // announced a V2 revision, this draft_complete is only the V1 handoff;
        // keep the stream open so the UI does not freeze on a rejected stub.
        const { email_id, draft, truncated } = event.data
        if (email_id) {
          const existing = _draftStreamCache.get(email_id)
          const waitingForRevision = !!existing?.expectsNewVersion
          // Defensive: if the final `draft` payload is empty (over-aggressive
          // backend cleanup can occasionally strip a draft down to nothing),
          // keep whatever was streamed instead of erasing the visible text.
          // User-reported 2026-05-13: generated draft displayed then disappeared.
          const finalText = (draft && draft.length > 0) ? draft : (existing?.accumulatedText || '')
          const isTruncated = !!truncated && !waitingForRevision
          const state: DraftStreamState = {
            emailId: email_id,
            accumulatedText: finalText,
            isComplete: !waitingForRevision,
            progressPercent: waitingForRevision ? 95 : 100,
            stageName: waitingForRevision ? 'revision' : 'finalisation',
            stageLabel: waitingForRevision ? STAGE_LABELS['revision'] : STAGE_LABELS['finalisation'],
            versionIndex: existing?.versionIndex || 1,
            expectsNewVersion: waitingForRevision,
            critique: existing?.critique,
            initialCritiqueScore: existing?.initialCritiqueScore,
            truncated: isTruncated,
            // `revision` is intentionally not carried — draft_complete
            // means the streaming/critic path finished cleanly. If a
            // `draft_revised` event arrived earlier, it set its own
            // state and the user has already had a chance to act.
          }
          _draftStreamCache.set(email_id, state)
          _notifyDraftStreamListeners(state)
          if (isTruncated) {
            // The backend hit the token cap mid-draft (launch audit 2026-05-30:
            // this flag was dropped, so a half-sentence draft could be sent
            // without warning). Warn the user to review before sending.
            window.dispatchEvent(new CustomEvent('agentys:toast', {
              detail: {
                message: i18n.t('drafts:toasts.draft_truncated', "Le brouillon a été coupé (limite atteinte) — relisez-le avant de l'envoyer."),
                type: 'warning',
                duration: 9000,
              },
            }))
          }
        }
        if (!getDraftStreamState(email_id)?.expectsNewVersion) {
          onRefresh()
          playUISound('draftReady')
        }
      } else if (event.type === 'draft_revised') {
        // 2026-05-17: apply V2 immediately for the composer stream. The toggle
        // UI promised by the non-destructive contract is not mounted here yet;
        // keeping V1 in accumulatedText leaves users with rejected drafts.
        const { email_id, v1, v2, critique_summary } = event.data
        if (email_id && v1 && v2 && v1 !== v2) {
          const existing = _draftStreamCache.get(email_id)
          const state: DraftStreamState = {
            emailId: email_id,
            accumulatedText: v2,
            isComplete: true,
            progressPercent: 100,
            stageName: 'critique',
            stageLabel: STAGE_LABELS['critique'],
            versionIndex: existing?.versionIndex || 1,
            expectsNewVersion: false,
            critique: existing?.critique,
            initialCritiqueScore: existing?.initialCritiqueScore,
            revision: {
              v1: String(v1),
              v2: String(v2),
              summary: String(critique_summary || ''),
            },
          }
          _draftStreamCache.set(email_id, state)
          _notifyDraftStreamListeners(state)
          // The final persisted draft_complete emitted by the API route will
          // refresh lists and play the ready sound.
        }
      }
    })
    ws.connect()

    // No polling fallback: reconnection is handled by the `connection_status` branch above,
    // which invalidates cache and triggers onRefresh on (re)connect. Incremental events
    // (email_updated, email_deleted, email_archived) keep the list in sync otherwise.
    return () => {
      unsubscribe()
      // Drop any pending draft-stream auto-evict timers so they don't fire
      // against a dead component / stale cache.
      _cancelAllDraftStreamEvictions()
      // Do NOT call ws.disconnect() — it destroys the global singleton client,
      // preventing reconnection after navigation/remount. Unsubscribe is enough.
    }
  }, [backendStatus, onRefresh, isAuthenticated])
}
