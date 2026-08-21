/**
 * Socket.IO Client for Agentys Backend
 *
 * Provides real-time event handling for email updates via Flask-SocketIO.
 * Uses the /daemon namespace to receive daemon events.
 */

import { io, Socket } from 'socket.io-client'
import { API_URL } from '../config'
import { getStoredToken } from './authToken'
import type { Email } from '../types/email'
import i18n from '../i18n'

/**
 * Orchestration events from the backend (Story 5-3 backend, Story 5-6 frontend)
 */
export interface OrchestrationStartData {
  email_id: string
  max_iterations: number
  quality_threshold: number
  status: string
}

export interface OrchestrationIterationStartData {
  email_id: string
  iteration_number: number
  is_revision: boolean
  status: string
}

export interface OrchestrationIterationCompleteData {
  email_id: string
  iteration_number: number
  score: number
  decision: 'valid' | 'reject'
  duration_ms: number
}

export interface OrchestrationCompleteData {
  email_id: string
  draft: string
  final_score: number
  total_iterations: number
  total_duration_ms: number
  was_validated: boolean
  status: string
}

export interface OrchestrationTimeoutData {
  email_id: string
  draft: string | null
  best_score: number
  completed_iterations: number
  total_duration_ms: number
  status: string
}

export interface OrchestrationErrorData {
  email_id: string
  error: string
  completed_iterations: number
  draft: string | null
  best_score: number
  status: string
}

export interface DraftChunkData {
  email_id: string
  chunk: string
  chunk_index: number
  accumulated_text?: string
  progress_percent: number
  is_final: boolean
}

export interface DraftCompleteData {
  email_id: string
  draft: string
  confidence: number
  generation_time_ms: number
  tokens_used: number
  tone_detected?: string
  /** Backend cut the draft off at the token cap — UI warns before sending. */
  truncated?: boolean
}

export interface DraftErrorData {
  email_id: string
  error: string
  retry_count: number
}

export interface DraftStageData {
  email_id: string
  stage: string
  stage_index: number
  total_stages: number
  progress_percent: number
}

/**
 * Partial patch applied incrementally to an email in the list state.
 * Only fields that can change after initial fetch and matter for list rendering.
 */
export interface EmailPatch {
  is_read: boolean
  labels: string[]
  has_pending_draft: boolean
  /** ISO-8601 UTC; populated automatically by the ingest-time deadline
   *  extractor (regex on the body). Null means no deadline detected. */
  deadline_at: string | null
  /** Stamped by the `mark_with_emoji` Quick Step action. `emoji` is optional
   *  (text-only marker); `color`/`chip` carry the per-rule styling. */
  emoji_marker: {
    emoji?: string; text?: string; include_deadline?: boolean;
    color?: string; chip?: boolean
  } | null
}

/**
 * Payload for the `draft_revised` event (2026-05-05).
 *
 * Backend `app/api/websocket.py:emit_draft_revised` emits this when
 * the critic produces a V2 that differs from the streamed V1. Frontend
 * surfaces it as a non-destructive toggle so user mid-edits to V1 are
 * preserved.
 */
export interface DraftRevisedData {
  email_id: string
  v1: string
  v2: string
  critique_summary: string
}

export type WebSocketEvent =
  | { type: 'new_email'; data: {
      email_id: string
      sender: string
      sender_name?: string | null
      subject: string
      received_at?: string
      is_read?: boolean
      has_attachments?: boolean
      conversation_id?: string | null
      body_preview?: string
      snippet?: string
      account_id?: string | number
      email?: Email
    } }
  | { type: 'draft_ready'; data: { email_id: string; draft_id: string; confidence: number } }
  | { type: 'draft_skipped'; data: { email_id: string; reason: string } }
  | { type: 'processing_started'; data: { email_id: string } }
  | { type: 'processing_error'; data: { email_id: string; error: string } }
  | { type: 'connection_status'; data: { connected: boolean; error?: string } }
  // Draft streaming events
  | { type: 'draft_chunk'; data: DraftChunkData }
  | { type: 'draft_complete'; data: DraftCompleteData }
  | { type: 'draft_error'; data: DraftErrorData }
  | { type: 'draft_stage'; data: DraftStageData }
  // Draft revision (non-destructive V2, 2026-05-05). Fired when the
  // backend `STREAM_V1_BEFORE_CRITIC_NONDESTRUCTIVE` flag is on and the
  // critic produced a V2 that differs from the streamed V1. Frontend
  // chooses whether to show a toggle or auto-apply.
  | { type: 'draft_revised'; data: DraftRevisedData }
  // Critique events
  | { type: 'critique_start'; data: { email_id: string; draft_id?: string } }
  | { type: 'critique_complete'; data: { email_id: string; decision: string; overall_score: number; draft_id?: string; suggestions?: string[] } }
  | { type: 'critique_error'; data: { email_id: string; draft_id?: string; error: string; retry_count?: number } }
  // Orchestration events (Story 5-6)
  | { type: 'orchestration_start'; data: OrchestrationStartData }
  | { type: 'orchestration_iteration_start'; data: OrchestrationIterationStartData }
  | { type: 'orchestration_iteration_complete'; data: OrchestrationIterationCompleteData }
  | { type: 'orchestration_complete'; data: OrchestrationCompleteData }
  | { type: 'orchestration_timeout'; data: OrchestrationTimeoutData }
  | { type: 'orchestration_error'; data: OrchestrationErrorData }
  | { type: 'email_archived'; data: { email_id: string } }
  | { type: 'email_deleted'; data: { email_id: string } }
  | { type: 'email_updated'; data: { email_id: string; updates: Partial<EmailPatch> } }
  | { type: 'email_restored'; data: { email_id: string } }
  | { type: 'email_spam_changed'; data: { email_id: string; is_spam: boolean } }
  | { type: 'email_body_ready'; data: { email_id: string } }
  | { type: 'labels_classification_started'; data: { count?: number } }
  | { type: 'labels_classification_complete'; data: { count?: number; failed?: number } }
  | { type: 'labels_updated'; data: { updates: Record<string, unknown> } }
  | { type: 'relabel_complete'; data: { relabeled: number } }
  // Onboarding events (Issue #33)
  | { type: 'onboarding:learning_started'; data: Record<string, unknown> }
  | { type: 'onboarding:waiting_for_sync'; data: Record<string, unknown> }
  | { type: 'onboarding:progress_updated'; data: Record<string, unknown> }
  | { type: 'onboarding:discovery'; data: Record<string, unknown> }
  | { type: 'onboarding:learning_completed'; data: Record<string, unknown> }
  | { type: 'onboarding:insights_generated'; data: Record<string, unknown> }
  // Learning auto-refresh events
  | { type: 'learning:correction_recorded'; data: { email_id: string; had_correction: boolean; edit_ratio: number } }
  | { type: 'learning:label_corrected'; data: { email_id: string; old_label: string; new_label: string } }
  | { type: 'learning:analysis_completed'; data: { patterns_count: number; new_adjustments: number } }
  | { type: 'learning:refresh_completed'; data: { account_id: number; refresh_type: string; summary: string } }
  // Sync events
  | { type: 'sync_complete'; data: { new_emails?: number; job_id?: string; duration_ms?: number } }
  // Connectivity events
  | { type: 'connectivity_changed'; data: { online: boolean } }
  | { type: 'back_online'; data: { message: string } }
  // Noise cleanup events
  | { type: 'noise_cleanup_complete'; data: { archived_count: number; deleted_count: number } }
  // Auth events
  | { type: 'auth:token_expired'; data: { account_id: string; email: string; provider: string } }
  // Schedule send events
  | { type: 'email_scheduled'; data: { scheduled_id: string; send_at: string } }
  | { type: 'email_sent_scheduled'; data: { scheduled_id: string; sent_message_id: string } }
  | { type: 'email_schedule_canceled'; data: { scheduled_id: string } }
  | { type: 'email_schedule_updated'; data: { scheduled_id: string; send_at: string } }
  // Bulk-action queue events (cf. types/bulkJob.ts).
  // `bulk_job_progress` is intentionally unbuffered server-side — the UI
  // resyncs from /api/bulk-jobs on reconnect rather than replaying a
  // potentially-large progress backlog.
  | {
      type: 'bulk_job_enqueued'
      data: import('../types/bulkJob').BulkJobEnqueuedEvent
    }
  | {
      type: 'bulk_job_progress'
      data: import('../types/bulkJob').BulkJobProgressEvent
    }
  | {
      type: 'bulk_job_status'
      data: import('../types/bulkJob').BulkJobStatusEvent
    }
  | {
      type: 'bulk_job_completed'
      data: import('../types/bulkJob').BulkJobCompletedEvent
    }

export type EventHandler = (event: WebSocketEvent) => void

export interface WebSocketClientOptions {
  reconnectionAttempts?: number
  reconnectionDelay?: number
}

const DEFAULT_OPTIONS: Required<WebSocketClientOptions> = {
  // BUG-Y001 mitigation: desktop app should still reconnect when the
  // backend bounces, but Infinity caused the QA tracker to count 18 ×
  // /socket.io/ 502 in 9 min during a transient backend slowdown.
  // Cap at 1000 attempts — at the 30s reconnectionDelayMax that's ~8h
  // of continuous polling before giving up, plenty for a real backend
  // restart, while still letting the loop terminate eventually if the
  // backend stays permanently dead.
  reconnectionAttempts: 1000,
  reconnectionDelay: 1000,  // 1s initial, socket.io applique exponential backoff automatiquement
}

type SocketTransport = 'websocket' | 'polling'

function isLoopbackSocketUrl(url: string): boolean {
  if (!url) {
    return true
  }

  try {
    const base =
      typeof window !== 'undefined' && window.location?.origin
        ? window.location.origin
        : 'http://127.0.0.1'
    const parsed = new URL(url, base)
    const hostname = parsed.hostname.toLowerCase()
    return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1' || hostname === '[::1]'
  } catch {
    return false
  }
}

export function getSocketTransportOptions(url: string): {
  transports: SocketTransport[]
  upgrade: boolean
} {
  if (isLoopbackSocketUrl(url)) {
    // BUG-S010 fix (Session AA, 9th session of silent WS): the Vite dev
    // server's proxy already declares `ws: true` for `/socket.io`, and the
    // backend's simple-websocket worker handles upgrades fine. Forcing
    // 'polling' here meant the loopback client NEVER instantiated a real
    // WebSocket — confirmed by 9 sessions of `window.__wsLog.length === 0`
    // in the QA tracker (which wraps `window.WebSocket`).
    //
    // We now try WebSocket FIRST with polling as a transparent fallback,
    // and explicitly opt-in to upgrade so the engine can re-handshake if
    // it had to start on polling.
    return {
      transports: ['websocket', 'polling'],
      upgrade: true,
    }
  }

  // Prod web should hold one real WebSocket, not a long-polling XHR cycle.
  // Flask-SocketIO in threading mode supports this through simple-websocket.
  return {
    transports: ['websocket'],
    upgrade: false,
  }
}

interface DaemonEventPayload {
  type: string
  email_id: string
  timestamp: string
  payload: Record<string, unknown>
}

/**
 * Maps backend `action_type` values (see schema._ALLOWED_ACTION_TYPES in
 * `app/quicksteps/schema.py`) to a localized past-tense verb. The backend
 * no longer ships any human-readable label in the payload (the legacy
 * French `action_label` field was removed in audit 2026-05-18), so this
 * map is the SOLE source of truth for what the user sees in the toast.
 * Unknown action types fall back to the raw `action_type` identifier
 * (e.g. "archive", "apply_label") — English-y and language-neutral, so
 * adding a new action type without updating this map degrades gracefully
 * instead of leaking French.
 */
const QUICKSTEP_VERB_KEY: Record<string, string> = {
  archive: 'qs_archived',
  unarchive: 'qs_unarchived',
  delete: 'qs_deleted',
  mark_read: 'qs_marked_read',
  move_to_spam: 'qs_moved_spam',
  pin: 'qs_pinned',
  reply_template: 'qs_replied',
  forward: 'qs_forwarded',
  rsvp_meeting: 'qs_rsvp',
  follow_up: 'qs_followup',
  create_snoozed_followup_draft: 'qs_snoozed_followup_draft',
  mark_with_emoji: 'qs_emoji_marked',
  apply_label: 'qs_label_applied',
}

/**
 * Returns an Undo callback for reversible quickstep actions, or `undefined`
 * for irreversible ones (reply_template, forward, …). The dynamic import
 * keeps the WebSocket bundle from pulling in the whole apiClient on init.
 */
function buildQuickstepUndoHandler(
  actionType: string,
  emailId: string,
): (() => void) | undefined {
  if (!emailId) return undefined
  switch (actionType) {
    case 'archive':
      return () => {
        import('./api').then(({ apiClient }) =>
          apiClient.unarchiveEmail(emailId).catch((err) =>
            reportQuickstepUndoFailed('archive', err),
          ),
        )
      }
    case 'delete':
      return () => {
        import('./api').then(({ apiClient }) =>
          apiClient.restoreFromTrash(emailId).catch((err) =>
            reportQuickstepUndoFailed('delete', err),
          ),
        )
      }
    case 'mark_read':
      return () => {
        import('../api/emails').then(({ markEmailUnread }) =>
          markEmailUnread(emailId).catch((err) =>
            reportQuickstepUndoFailed('mark_read', err),
          ),
        )
      }
    default:
      return undefined
  }
}

/**
 * Audit Cluster D (2026-05-17) F-02: undo failures used to log to console
 * only. The Undo animation in the toast left the row visible in the
 * optimistic list, but the next refresh wiped it again with zero
 * explanation — pure trust killer.
 *
 * We now surface the failure as a toast AND invalidate the email cache so
 * the next fetch reflects the real backend state instead of the optimistic
 * lie.
 */
function reportQuickstepUndoFailed(
  actionType: 'archive' | 'delete' | 'mark_read',
  err: unknown,
): void {
  console.warn(`[quickstep-undo] ${actionType} failed:`, err)
  if (typeof window === 'undefined') return
  const key =
    actionType === 'archive'
      ? 'toasts.undo_failed_archive'
      : actionType === 'delete'
        ? 'toasts.undo_failed_delete'
        : 'toasts.undo_failed_mark_read'
  window.dispatchEvent(
    new CustomEvent('agentys:toast', {
      detail: {
        message: i18n.t(key, { ns: 'common' }),
        type: 'error',
        duration: 6000,
      },
    }),
  )
  import('../api/emails')
    .then(({ invalidateEmailCache }) => invalidateEmailCache())
    .catch(() => {
      /* cache module unavailable — nothing we can do, toast already shown */
    })
}

export class WebSocketClient {
  private socket: Socket | null = null
  private url: string
  private options: Required<WebSocketClientOptions>
  private handlers: Set<EventHandler> = new Set()
  private debounceTimers: Map<string, ReturnType<typeof setTimeout>> = new Map()
  // Dedup window for the `quickstep_fired` toast — see mapDaemonEvent.
  // Key: `${step_name}::${email_id}`. Value: epoch ms of last dispatch.
  private _quickstepFiredAt: Map<string, number> = new Map()

  private debounce(key: string, fn: () => void, ms: number): void {
    const existing = this.debounceTimers.get(key)
    if (existing) clearTimeout(existing)
    this.debounceTimers.set(key, setTimeout(() => {
      this.debounceTimers.delete(key)
      fn()
    }, ms))
  }

  constructor(url: string = API_URL, options: WebSocketClientOptions = {}) {
    this.url = url
    this.options = { ...DEFAULT_OPTIONS, ...options }
  }

  connect(): void {
    if (this.socket) {
      return
    }

    try {
      // En prod web (non-loopback), le serveur exige un JWT en query param
      // pour autoriser la connexion et router vers la bonne room (= email
      // utilisateur). Sans ça, le handler `on_daemon_connect` disconnect()
      // le client → 0 event délivré → onboarding figé à 0%.
      // Tauri desktop (loopback) fonctionne sans token, le serveur fallback
      // sur un room `local_<sid>` — on envoie quand même le token s'il
      // existe pour bénéficier du routage par email en mode hybride.
      const token = getStoredToken()
      this.socket = io(`${this.url}/daemon`, {
        reconnection: true,
        reconnectionAttempts: this.options.reconnectionAttempts,
        reconnectionDelay: this.options.reconnectionDelay,
        // Cloud reconnects should be calmer during Railway deploy rotations;
        // local/Tauri stays snappier for the desktop dev loop, but BUG-Y001
        // showed that a 5s cap let us hammer Vite's proxy ~12 times during
        // a 60s backend hiccup. Bumping loopback to 15s keeps reconnects
        // responsive on a clean restart while halving the 502 noise during
        // transient slowdowns.
        reconnectionDelayMax: isLoopbackSocketUrl(this.url) ? 15000 : 30000,
        ...getSocketTransportOptions(this.url),
        // FIX WS-002 (audit P1): pass JWT via `auth` (POST body during
        // handshake) instead of `query` (URL). Previously every polling
        // request URL contained `&token=<jwt>`, leaking the bearer to
        // every reverse-proxy / observability access log. The backend
        // handshake now reads token from the auth dict.
        ...(token ? { auth: { token } } : {}),
      })

      this.setupEventHandlers()
    } catch (err) {
      console.error('[WebSocket] Failed to connect:', err)
      this.notifyHandlers({ type: 'connection_status', data: { connected: false } })
    }
  }

  private setupEventHandlers(): void {
    if (!this.socket) return

    this.socket.on('connect', () => {
      const transportName = this.socket?.io?.engine?.transport?.name
      if (!isLoopbackSocketUrl(this.url) && transportName && transportName !== 'websocket') {
        console.warn(
          `[WebSocket] Unexpected Socket.IO transport in production: ${transportName}. Expected websocket.`,
        )
      }
      this.notifyHandlers({ type: 'connection_status', data: { connected: true } })
    })

    this.socket.on('disconnect', (reason?: string) => {
      this.notifyHandlers({
        type: 'connection_status',
        data: reason
          ? { connected: false, error: `disconnected: ${reason}` }
          : { connected: false },
      })
    })

    // Silent-failure fix (issue #317) : si le backend refuse la connexion
    // (token expiré, CORS, 5xx au namespace /daemon), Socket.IO émet
    // `connect_error`. Sans handler, l'UI restait en état stagnant sans
    // jamais prévenir l'utilisateur que le flux temps réel était mort.
    //
    // F04 (HIGH): also detect auth failures explicitly. Pre-fix, an expired
    // JWT made the client reconnect every 1-5s forever silently. Now we
    // sniff the connect_error message for unauthorized markers, dispatch
    // `auth:unauthorized` (same path as the HTTP layer), and stop the
    // socket.io reconnection loop so we don't burn battery/server resources
    // hammering with a dead token.
    this.socket.on('connect_error', (err: Error) => {
      const msg = err?.message || 'connect_error'
      const isAuthFailure =
        /unauthor|unauthorized|forbidden|jwt|token|auth/i.test(msg) ||
        // Socket.IO surfaces server-side `disconnect()` from /daemon as a
        // `xhr poll error` after a 401 handshake — sniff for that too.
        /401|403/.test(msg)
      if (isAuthFailure) {
        // Notify UI once with auth-specific error then stop reconnecting
        // so the user can re-login cleanly. The reconnect loop resumes via
        // the next call to `connect()` after re-auth.
        this.notifyHandlers({
          type: 'connection_status',
          data: { connected: false, error: `unauthorized: ${msg}` },
        })
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('auth:unauthorized'))
        }
        try {
          // Disable further reconnection attempts on this socket. Without
          // this socket.io would keep trying every 1-5s indefinitely.
          // socket.io-client's Socket exposes `io: Manager` whose `opts`
          // includes `reconnection`. Using the typed accessor avoids the
          // `as any` ESLint warnings while still being defensive in case
          // the underlying manager has been torn down already.
          const manager = this.socket?.io
          if (manager?.opts) {
            manager.opts.reconnection = false
          }
          const socket = this.socket
          socket?.disconnect()
          socket?.removeAllListeners()
          if (this.socket === socket) {
            this.socket = null
          }
        } catch {
          // Defensive: socket may have already torn down.
        }
        return
      }
      this.notifyHandlers({
        type: 'connection_status',
        data: { connected: false, error: msg },
      })
    })

    this.socket.on('daemon_event', (data: DaemonEventPayload) => {
      const event = this.mapDaemonEvent(data)
      if (event) {
        if (event.type === 'labels_updated') {
          this.debounce('labels_updated', () => this.notifyHandlers(event), 300)
        } else {
          this.notifyHandlers(event)
        }
      }
    })

    this.socket.on('labels_updated', (data: { updates?: Record<string, unknown>; reclassified?: number; source?: string }) => {
      this.debounce('labels_updated', () => {
        this.notifyHandlers({ type: 'labels_updated', data: { updates: data.updates || {} } })
      }, 300)
    })

    // Draft streaming events - emitted directly from backend
    this.socket.on('draft_chunk', (data: DraftChunkData) => {
      this.notifyHandlers({ type: 'draft_chunk', data })
    })

    this.socket.on('draft_complete', (data: DraftCompleteData) => {
      this.notifyHandlers({ type: 'draft_complete', data })
    })

    this.socket.on('draft_error', (data: DraftErrorData) => {
      this.notifyHandlers({ type: 'draft_error', data })
    })

    this.socket.on('draft_stage', (data: DraftStageData) => {
      this.notifyHandlers({ type: 'draft_stage', data })
    })

    // 2026-05-05 — non-destructive V2 revision. Backend emits this
    // instead of `draft_complete` when the critic produces a V2 that
    // differs from the streamed V1. The handler in useWebSocketSync
    // stashes both versions on the draft state cache so the UI can
    // render a "View improved version" toggle instead of mutating the
    // editor in place. Backwards-compat: when the backend flag
    // STREAM_V1_BEFORE_CRITIC_NONDESTRUCTIVE is OFF (default), this
    // event never fires and the legacy draft_complete path runs.
    this.socket.on('draft_revised', (data: DraftRevisedData) => {
      this.notifyHandlers({ type: 'draft_revised', data })
    })

    // Critique events
    this.socket.on('critique_start', (data: { email_id: string; draft_id?: string }) => {
      this.notifyHandlers({ type: 'critique_start', data })
    })

    this.socket.on('critique_complete', (data: { email_id: string; decision: string; overall_score: number; draft_id?: string; suggestions?: string[] }) => {
      this.notifyHandlers({ type: 'critique_complete', data })
    })

    this.socket.on('critique_error', (data: { email_id: string; draft_id?: string; error: string; retry_count?: number }) => {
      this.notifyHandlers({ type: 'critique_error', data })
    })

    // Orchestration events (Story 5-6) - emitted directly from backend.
    // NOTE (2026-04-16 audit): backend emit_orchestration_* functions are defined
    // in app/api/websocket.py but not currently called from the pipeline — these
    // handlers are reserved infrastructure and fire no-op until the backend
    // wires the emits (tracked separately). `useActivityMonitor` consumes them.
    this.socket.on('orchestration_start', (data: OrchestrationStartData) => {
      this.notifyHandlers({ type: 'orchestration_start', data })
    })

    this.socket.on('orchestration_iteration_start', (data: OrchestrationIterationStartData) => {
      this.notifyHandlers({ type: 'orchestration_iteration_start', data })
    })

    this.socket.on('orchestration_iteration_complete', (data: OrchestrationIterationCompleteData) => {
      this.notifyHandlers({ type: 'orchestration_iteration_complete', data })
    })

    this.socket.on('orchestration_complete', (data: OrchestrationCompleteData) => {
      this.notifyHandlers({ type: 'orchestration_complete', data })
    })

    this.socket.on('orchestration_timeout', (data: OrchestrationTimeoutData) => {
      this.notifyHandlers({ type: 'orchestration_timeout', data })
    })

    this.socket.on('orchestration_error', (data: OrchestrationErrorData) => {
      this.notifyHandlers({ type: 'orchestration_error', data })
    })

    // Post-send archive event
    this.socket.on('email_archived', (data: { email_id: string }) => {
      this.notifyHandlers({ type: 'email_archived', data })
    })

    // Email moved to trash — remove from list incrementally
    this.socket.on('email_deleted', (data: { email_id: string }) => {
      this.notifyHandlers({ type: 'email_deleted', data })
    })

    // Email field changed (is_read, labels...) — merge patch into list state
    this.socket.on('email_updated', (data: { email_id: string; updates: Partial<EmailPatch> }) => {
      this.notifyHandlers({ type: 'email_updated', data })
    })

    // Email restored from trash or unarchived
    this.socket.on('email_restored', (data: { email_id: string }) => {
      this.notifyHandlers({ type: 'email_restored', data })
    })

    // Email marked as spam or not-spam
    this.socket.on('email_spam_changed', (data: { email_id: string; is_spam: boolean }) => {
      this.notifyHandlers({ type: 'email_spam_changed', data })
    })

    // Email body ready (background IMAP fetch complete)
    this.socket.on('email_body_ready', (data: { email_id: string }) => {
      this.notifyHandlers({ type: 'email_body_ready', data })
    })

    // Sync complete — new emails available after background sync.
    // `job_id` is present when emitted from `_run_sync_job` (per-folder
    // user-triggered sync); absent for the periodic full-sync emit.
    this.socket.on('sync_complete', (data: { new_emails?: number; job_id?: string; duration_ms?: number }) => {
      this.notifyHandlers({ type: 'sync_complete', data })
    })

    // Backend connectivity events — backend detects provider connection loss/recovery
    this.socket.on('connectivity_changed', (data: { online: boolean }) => {
      this.notifyHandlers({ type: 'connectivity_changed', data })
    })
    this.socket.on('back_online', (data: { message: string }) => {
      this.notifyHandlers({ type: 'back_online', data })
    })
    this.socket.on('noise_cleanup_complete', (data: { archived_count: number; deleted_count: number }) => {
      this.notifyHandlers({ type: 'noise_cleanup_complete', data })
    })

    // Label reclassification complete — debounced to avoid storm of re-renders
    this.socket.on('relabel_complete', (data: { relabeled: number }) => {
      this.debounce('relabel_complete', () => {
        this.notifyHandlers({ type: 'relabel_complete', data })
      }, 300)
    })

    this.socket.on('labels_classification_started', (data: { count?: number }) => {
      this.notifyHandlers({ type: 'labels_classification_started', data })
    })

    this.socket.on('labels_classification_complete', (data: { count?: number; failed?: number }) => {
      this.notifyHandlers({ type: 'labels_classification_complete', data })
    })

    // Onboarding events (Issue #33)
    // Keep this list in sync with the handlers in `useLearningProgress.ts` and
    // with the backend `_emit(...)` call sites — any new event must appear in
    // all three places or it will be silently dropped (cf. lessons.md).
    const onboardingEvents = [
      'onboarding:learning_started',
      'onboarding:waiting_for_sync',
      'onboarding:progress_updated',
      'onboarding:discovery',
      'onboarding:learning_completed',
      'onboarding:insights_generated',
    ] as const
    for (const eventName of onboardingEvents) {
      this.socket.on(eventName, (data: Record<string, unknown>) => {
        this.notifyHandlers({ type: eventName, data } as WebSocketEvent)
      })
    }

    // Learning auto-refresh events
    const learningEvents = [
      'learning:correction_recorded',
      'learning:label_corrected',
      'learning:analysis_completed',
      'learning:refresh_completed',
    ] as const
    for (const eventName of learningEvents) {
      this.socket.on(eventName, (data: Record<string, unknown>) => {
        this.notifyHandlers({ type: eventName, data } as WebSocketEvent)
      })
    }

    // Auth events
    this.socket.on('auth:token_expired', (data: { account_id: string; email: string; provider: string }) => {
      this.notifyHandlers({ type: 'auth:token_expired', data })
    })

    // Bulk-action queue events. The four events have very different
    // cadences (progress is 1/s, the others are once-per-job state
    // transitions), but they all carry job_id-keyed payloads — the
    // BulkActionsPanel hook reduces them into a single state map.
    this.socket.on('bulk_job_enqueued', (data: import('../types/bulkJob').BulkJobEnqueuedEvent) => {
      this.notifyHandlers({ type: 'bulk_job_enqueued', data })
    })
    this.socket.on('bulk_job_progress', (data: import('../types/bulkJob').BulkJobProgressEvent) => {
      this.notifyHandlers({ type: 'bulk_job_progress', data })
    })
    this.socket.on('bulk_job_status', (data: import('../types/bulkJob').BulkJobStatusEvent) => {
      this.notifyHandlers({ type: 'bulk_job_status', data })
    })
    this.socket.on('bulk_job_completed', (data: import('../types/bulkJob').BulkJobCompletedEvent) => {
      this.notifyHandlers({ type: 'bulk_job_completed', data })
    })
  }

  private mapDaemonEvent(data: DaemonEventPayload): WebSocketEvent | null {
    if (!data || typeof data !== 'object') {
      console.warn('[WS] Événement daemon malformé reçu (payload undefined ou non-objet)', data);
      return null;
    }
    const { type, email_id, payload: rawPayload } = data
    if (!type) {
      console.warn('[WS] Événement daemon sans type', data);
      return null;
    }
    // Guard against undefined payload — some daemon events may omit it
    const payload: Record<string, unknown> = rawPayload ?? {}

    switch (type) {
      case 'new_email':
        {
          const email: Email | undefined = email_id ? {
            id: email_id,
            sender: (payload.sender as string) || '',
            sender_name: (payload.sender_name as string | null | undefined) ?? null,
            subject: (payload.subject as string) || '',
            received_at: (payload.received_at as string) || new Date().toISOString(),
            is_read: Boolean(payload.is_read),
            has_attachments: Boolean(payload.has_attachments),
            conversation_id: (payload.conversation_id as string | null | undefined) ?? null,
            body_preview: (payload.body_preview as string) || (payload.snippet as string) || '',
            labels: [],
            has_pending_draft: false,
            draft_skipped: false,
          } : undefined
          return {
            type: 'new_email',
            data: {
              email_id,
              sender: (payload.sender as string) || '',
              sender_name: (payload.sender_name as string | null | undefined) ?? null,
              subject: (payload.subject as string) || '',
              received_at: (payload.received_at as string) || '',
              is_read: Boolean(payload.is_read),
              has_attachments: Boolean(payload.has_attachments),
              conversation_id: (payload.conversation_id as string | null | undefined) ?? null,
              body_preview: (payload.body_preview as string) || (payload.snippet as string) || '',
              snippet: (payload.snippet as string) || '',
              account_id: payload.account_id as string | number | undefined,
              email,
            },
          }
        }
      case 'draft_ready':
        return {
          type: 'draft_ready',
          data: {
            email_id,
            draft_id: (payload.draft_id as string) || '',
            confidence: (payload.confidence as number) || 0,
          },
        }
      case 'draft_skipped':
        return {
          type: 'draft_skipped',
          data: {
            email_id,
            reason: (payload.reason as string) || 'noise',
          },
        }
      case 'processing_started':
        return { type: 'processing_started', data: { email_id } }
      case 'faq_auto_sent':
        return { type: 'email_archived', data: { email_id } }
      case 'processing_error':
        return {
          type: 'processing_error',
          data: { email_id, error: (payload.error as string) || 'Unknown error' },
        }
      case 'labels_classification_started':
        return {
          type: 'labels_classification_started',
          data: { count: payload.count as number | undefined },
        }
      case 'labels_classification_complete':
        return {
          type: 'labels_classification_complete',
          data: {
            count: payload.count as number | undefined,
            failed: payload.failed as number | undefined,
          },
        }
      case 'labels_updated':
        return {
          type: 'labels_updated',
          data: { updates: (payload.updates as Record<string, unknown>) || {} },
        }
      case 'quickstep_fired': {
        // Bottom-right toast confirming an auto-Quick-Step just ran.
        // We dispatch directly via the global toast bus instead of
        // routing through the typed `WebSocketEvent` channel — no other
        // consumer cares about this event, so the round-trip would be
        // dead weight. Returning null tells the switch we handled it.
        //
        // Dedup window: `emit_to_account` broadcasts to every socket in
        // the account room, so if the user has multiple Agentys tabs
        // open they each fire the same toast. Key by (step_name +
        // email_id) and skip a re-emission within 10s. The map is
        // pruned opportunistically below; survival across reloads is
        // not required.
        //
        // Audit F-06 (2026-05-13 deep-audit pass): window was 2s. Under
        // 3G throttling or backend restart the emit-to-toast-render
        // latency exceeded 2s and duplicate events arrived outside the
        // window, surfacing two toasts. Widened to 10s — the "different
        // rule fires on same email within 10s" case is essentially zero
        // in practice (auto_trigger.py caps to one fire per (step, email)
        // via `_step_fired_on_email`).
        const stepNameRaw = (payload.step_name as string) || ''
        const actionType = (payload.action_type as string) || ''
        const subject = ((payload.subject as string) || '').trim()
        const dedupKey = `${stepNameRaw}::${email_id || ''}`
        const now = Date.now()
        const lastFired = this._quickstepFiredAt.get(dedupKey) ?? 0
        if (now - lastFired < 10_000) {
          return null
        }
        this._quickstepFiredAt.set(dedupKey, now)
        // Prune entries older than 60s so the map doesn't grow forever
        // in a long-lived session. Cheap — runs every dispatch.
        for (const [k, t] of this._quickstepFiredAt) {
          if (now - t > 60_000) this._quickstepFiredAt.delete(k)
        }

        // Build the toast text. Primary = "{Verb}: {subject}" (verb localized
        // from action_type so it matches the user's UI language). Unknown
        // action types degrade to the English-y action_type identifier — the
        // legacy French `action_label` fallback was removed in audit 2026-05-18
        // to eliminate stealth French leakage on en/es/de UIs.
        // Secondary = step_name when the user named the rule; omitted for the
        // generic "Quick Step" default so we don't show a useless second line.
        const verbKey = QUICKSTEP_VERB_KEY[actionType]
        const verb = verbKey ? i18n.t(`inbox:${verbKey}`) : (actionType || 'Quick Step')
        const subjectPart = subject || i18n.t('inbox:qs_no_subject')
        const message = `${verb}: ${subjectPart}`
        const stepName = stepNameRaw && stepNameRaw !== 'Quick Step' ? stepNameRaw : undefined

        // Reversible actions get an Undo button + countdown spinner. The 5s
        // duration matches the post-reply auto-archive toast in ReplyComposer
        // so every "an auto-action just touched your inbox" cue is identical.
        // Keep the action_type list in sync with auto_trigger._ACTION_TOAST_LABEL.
        const undoHandler = buildQuickstepUndoHandler(actionType, email_id)
        const action = undoHandler
          ? { label: i18n.t('common:undo_label'), onClick: undoHandler }
          : undefined

        try {
          window.dispatchEvent(new CustomEvent('agentys:toast', {
            detail: { message, detail: stepName, type: 'success', duration: 5000, action },
          }))
        } catch {
          // ignore — window not available in unit-test mode
        }
        return null
      }
      default:
        // Forward onboarding:* events from daemon_event
        if (type.startsWith('onboarding:')) {
          return { type, data: { ...payload, email_id } } as WebSocketEvent
        }
        return null
    }
  }

  disconnect(): void {
    this.debounceTimers.forEach(t => clearTimeout(t))
    this.debounceTimers.clear()
    if (this.socket) {
      this.socket.removeAllListeners()
      this.socket.disconnect()
      this.socket = null
      // Notify handlers that connection is closed before clearing them
      this.notifyHandlers({ type: 'connection_status', data: { connected: false } })
    }
    this.handlers.clear()
  }

  isConnected(): boolean {
    return this.socket !== null && this.socket.connected
  }

  subscribe(handler: EventHandler): () => void {
    this.handlers.add(handler)
    return () => this.handlers.delete(handler)
  }

  private notifyHandlers(event: WebSocketEvent): void {
    this.handlers.forEach((handler) => {
      try {
        handler(event)
      } catch (err) {
        // F14 (LOW): pre-fix, handler exceptions were swallowed silently which
        // made WS-driven bug debugging painful (e.g. setState-on-unmounted).
        // Logging now exposes the offending event type + error so the cause
        // is reachable via DevTools console.
        // We still don't rethrow — one buggy handler must not break the others
        // in the Set; that contract is intentional.

        console.error(`[WS] handler threw on event "${event.type}":`, err)
      }
    })
  }
}

let wsClient: WebSocketClient | null = null
let wsClientUrl: string | null = null

export function getWebSocketClient(url?: string): WebSocketClient {
  const requestedUrl = url || API_URL
  if (!wsClient || wsClientUrl !== requestedUrl) {
    if (wsClient) {
      wsClient.disconnect()
    }
    wsClient = new WebSocketClient(requestedUrl)
    wsClientUrl = requestedUrl
  }
  return wsClient
}

export function resetWebSocketClient(): void {
  if (wsClient) {
    wsClient.disconnect()
    wsClient = null
    wsClientUrl = null
  }
}
