/**
 * API Client for Agentys Backend
 *
 * Provides typed HTTP communication with the Python backend.
 */

import { API_URL } from '../config'
import { getAuthHeaders } from './authToken'
import i18n from '../i18n'
import { getActiveAccountId, getCachedDraftEmailContext } from '../api/emails'

function normalizeAccountAvatar<T extends { avatar_url?: string | null }>(account: T): T {
  if (!account.avatar_url || !account.avatar_url.startsWith('/')) return account
  return { ...account, avatar_url: `${API_URL}${account.avatar_url}` }
}

export interface AttachmentMeta {
  id: string
  filename: string
  size: number
  content_type: string
}

export interface Email {
  id: string
  sender: string
  sender_name?: string
  subject: string
  received_at: string
  has_attachments?: boolean
  attachments?: AttachmentMeta[]
  conversation_id?: string | null
  body?: string
  is_read?: boolean
  body_preview?: string
  has_pending_draft?: boolean
  labels?: Array<{ name: string; color: string; confidence?: number }>
}

export interface LegalConsentResponse {
  success: boolean
  consent_id: string
  accepted_at: string
}

export interface Draft {
  id: string
  content: string
  confidence: number
}

export interface PipelineDetails {
  draft_v1: string
  critique: {
    is_valid: boolean
    feedback: string
  }
  was_corrected: boolean
}

export interface ConversationHistoryItem {
  sender: string
  subject: string
  date: string
  body_preview?: string
  body?: string
}

export interface PendingDraft {
  id: string
  email_id: string
  email_sender: string
  email_sender_name?: string
  email_subject: string
  email_body: string
  email_received_at?: string
  draft_subject: string
  draft_body: string
  draft_v1: string
  critique: string
  conversation_history?: ConversationHistoryItem[]
  conversation_history_count?: number
  routing_tier?: string
  classification: string
  priority: number
  confidence: number
  smart_suggestions?: string[] | null
  quick_replies?: {
    affirmative: string
    negative: string
  } | null
  specialty_info?: {
    specialty_id: string
    specialty_name: string
    category: string
    expert_ids: string[]
    expert_names: string[]
    risk_level: 'high' | 'medium' | 'low'
    confidence: number
    keyword_hits: number
  } | null
  account_info?: {
    detected: boolean
    action: 'password_reset' | 'email_change' | ''
    requester_email: string
    requester_name: string | null
    wp_user_id: number | null
    wp_username: string | null
    wp_user_email: string | null
    new_email: string | null
    generated_password: string | null
    confidence: number
    reason: string
    status: 'pending' | 'approved' | 'rejected' | 'executed' | 'not_found'
  } | null
  status: 'pending' | 'validated' | 'sent' | 'rejected' | 'modified'
  created_at: string
  processed_at?: string
  gmail_draft_id?: string
  memory_trace?: Record<string, unknown> | null
  classification_reason?: string
  correction_details?: string[]
  pipeline_summary?: string | null
  /** ISO 8601 wake date when the draft is currently snoozed via a
   *  `create_snoozed_followup_draft` Quick Step. Absent when not snoozed
   *  (regular pending drafts or already-promoted ones). */
  snoozed_until?: string
  /** Emoji marker inherited from the SOURCE email's
   *  `emails.emoji_marker_json` — populated by `mark_with_emoji` when it
   *  fired in the same Quick Step chain that created this followup draft.
   *  Server-side join (single source of truth on the email row); the
   *  Drafts list renders it next to the subject with `EmojiMarkerChip`. */
  emoji_marker?: {
    emoji?: string
    text?: string
    include_deadline?: boolean
    color?: string
    chip?: boolean
  } | null
}

export interface PendingDraftsResponse {
  count: number
  pending_count: number
  drafts: PendingDraft[]
}

export interface ContactStyleResponse {
  contact_email: string
  preferred_signature: string | null
  style: {
    email: string
    preferred_signature?: string | null
  } | null
}

// A PendingDraft that is currently snoozed in "Later" via a
// draft_followup reminder. Same shape as PendingDraft plus the wake date
// the SnoozedView needs to render the Snoozed badge + sort the list.
export type SnoozedPendingDraft = PendingDraft & { wake_at: string }

export interface SnoozedFollowupDraftsResponse {
  count: number
  drafts: SnoozedPendingDraft[]
}

// Type for /api/drafts response (draft history)
interface DraftRecord {
  id: string
  email_id: string
  email_sender: string
  email_subject: string
  email_body?: string
  draft_v1?: string
  critique?: string
  draft_final: string
  draft_id?: string
  status: string
  category: string
  priority_score: number
  tokens_used: number
  model?: string
  processing_time_ms: number
  timestamp: string
  feedback?: string | null
  feedback_comment?: string | null
}

export interface DraftRecordsResponse {
  drafts: DraftRecord[]
  total: number
  limit: number
  offset: number
}

export function mapDraftRecordToPendingDraft(record: DraftRecord): PendingDraft {
  return {
    id: record.id,
    email_id: record.email_id,
    email_sender: record.email_sender,
    email_subject: record.email_subject,
    email_body: record.email_body || '',
    draft_subject: `Re: ${record.email_subject}`,
    draft_body: record.draft_final,
    draft_v1: record.draft_v1 || '',
    critique: record.critique || '',
    classification: record.category,
    priority: record.priority_score,
    confidence: record.status.includes('V1') ? 0.85 : 0.65,
    status: 'validated', // Drafts from history are already created in Gmail
    created_at: record.timestamp,
    gmail_draft_id: record.draft_id,
  }
}

export interface PreviewResponse {
  success: boolean
  email_id: string
  classification: string
  priority: number
  status: string
  draft: {
    id: string
    subject: string
    body: string
    tokens_used: number
    confidence: number
  }
  pipeline_details: PipelineDetails
}

export interface ScheduledEmailDTO {
  id: string
  send_at: string  // ISO 8601 UTC
  status: 'pending' | 'sent' | 'failed' | 'cancelled'
  to: string[]
  cc: string[]
  bcc: string[]
  subject: string
  body: string
  is_html: boolean
  reply_to_id: string | null
  thread_id: string | null
  attachments_count: number
  created_at: string | null
  updated_at: string | null
  sent_at: string | null
  sent_message_id: string | null
  error: string | null
}

export interface HealthStatus {
  status: 'healthy' | 'degraded'
  version: string
  services: {
    email: 'connected' | 'disconnected'
    llm: 'connected' | 'disconnected'
  }
  timestamp: string
}

export interface Account {
  id: string
  name: string
  email: string
  provider: 'gmail' | 'outlook' | 'imap_smtp'
  status: 'active' | 'inactive' | 'error' | 'rate_limited'
  is_current?: boolean
  check_interval_minutes?: number
  max_emails_per_batch?: number
  auto_reply_enabled?: boolean
  draft_only?: boolean
  default_language?: string
  signature?: string
  avatar_url?: string | null
  created_at?: string
  last_sync?: string | null
  last_error?: string | null
  email_count?: number
  stats?: AccountStats
}

export interface AccountStats {
  emails_processed: number
  drafts_created: number
  drafts_sent: number
  errors: number
  avg_response_time_seconds: number
}

export interface DraftQualityStats {
  period_days: number
  total_sent: number
  sent_unmodified: number
  unmodified_rate: number
  avg_edit_ratio: number
  by_intent: Record<string, { total: number; unmodified: number; rate: number }>
  by_tier: Record<string, { total: number; unmodified: number; rate: number }>
  daily: Array<{ date: string; total: number; unmodified: number; rate: number }>
}

export interface AccountTokenStatus {
  has_tokens: boolean
  is_valid: boolean
  email?: string
  provider?: string
  expires_in?: number
  has_email?: boolean
  has_calendar?: boolean
  scopes?: string[]
}

// ============================================================================
// CALENDAR TYPES
// ============================================================================

export interface Calendar {
  id: string
  name: string
  description?: string
  color?: string
  isPrimary: boolean
  canEdit: boolean
  providerSource: string
}

/**
 * Dual-shape response returned by `/emails/empty-{trash,spam}`.
 *
 * Below INLINE_THRESHOLD the backend runs the cleanup synchronously and
 * answers `{ success, deleted_count, rescued_count? }`. Above the
 * threshold it enqueues the work into the bulk-jobs queue and answers
 * `{ accepted: true, mode: "async", job_id?, trash_job_id?, rescue_job_id?, target_total }`.
 *
 * Callers branch on `accepted` to decide between the "X deleted" toast
 * and the "queued, see Background Tasks" toast.
 */
export interface EmptyFolderResponse {
  // Sync shape
  success?: boolean
  deleted_count?: number
  rescued_count?: number
  partial?: boolean
  // Async shape
  accepted?: boolean
  mode?: 'async'
  job_id?: string
  trash_job_id?: string | null
  rescue_job_id?: string | null
  target_total?: number
  trashed_target?: number
  rescued_target?: number
}

/**
 * Dual-shape response from the selection-based bulk endpoints
 * (`/emails/bulk-{archive,delete,not-spam,restore}`).
 *
 * At or below INLINE_THRESHOLD the backend runs the operation
 * synchronously and answers `{ success, updated_count, email_ids, partial? }`.
 * Above the threshold it enqueues the work into the rate-limited bulk-jobs
 * queue and answers `202 { accepted: true, mode: "async", job_id, target_total }`.
 *
 * Callers branch on `accepted` to choose the "X done" toast vs the
 * "X queued — see Background Tasks" toast.
 */
export interface BulkActionResponse {
  // Sync shape
  success?: boolean
  updated_count?: number
  email_ids?: string[]
  partial?: boolean
  // Async shape
  accepted?: boolean
  mode?: 'async'
  job_id?: string
  target_total?: number
}

/**
 * Response from `/emails/clean-noise`. Noise labels are always removed
 * synchronously; the provider trashing routes through the bulk-jobs
 * queue (async shape) or runs inline as a fallback (sync shape).
 * `pending: true` means another manual cleanup is already running.
 */
export interface CleanNoiseResponse {
  success: boolean
  archived_count: number
  deleted_count: number
  pending?: boolean
  // Async shape
  accepted?: boolean
  mode?: 'async'
  job_id?: string
  target_total?: number
}

export interface MarkNoiseReadResponse {
  success: boolean
  updated_count: number
  email_ids?: string[]
  is_read: true
  accepted?: boolean
  mode?: 'async'
  job_id?: string
  target_total?: number
}

export interface CalendarEvent {
  id: string
  title: string
  start: string  // ISO 8601
  end: string    // ISO 8601
  isAllDay: boolean
  location?: string
  description?: string
  attendees: string[]
  calendarId: string
  status: 'confirmed' | 'tentative' | 'cancelled'
  providerSource: string
  organizer?: string
  isRecurring: boolean
  htmlLink?: string
  color?: string
  meetLink?: string
  // Followup-specific fields (populated when event_type === 'followup')
  event_type?: string
  is_overdue?: boolean
  email_subject?: string
  email_sender?: string
}

export interface CalendarsResponse {
  calendars: Calendar[]
  count: number
  account_id?: string
  error?: string
  message?: string
}

export interface CalendarEventsResponse {
  events: CalendarEvent[]
  count: number
  start?: string
  end?: string
  account_id?: string
  source?: 'cache' | 'api'
  error?: string
  message?: string
}

export interface CalendarEventResponse {
  event: CalendarEvent
  account_id?: string
  error?: string
}

export interface CalendarStatusResponse {
  ready: boolean
  needs_reauth: boolean
  message?: string
  account_id?: string
  provider?: string
}

export interface AccountsListResponse {
  count: number
  current_account_id: string | null
  accounts: Account[]
}

export interface CreateAccountRequest {
  name: string
  email: string
  provider: 'gmail' | 'outlook' | 'imap_smtp'
  credentials_path?: string
  check_interval_minutes?: number
  max_emails_per_batch?: number
  auto_reply_enabled?: boolean
  draft_only?: boolean
  signature?: string
  default_language?: string
  // IMAP/SMTP settings
  imap_host?: string
  imap_port?: number
  imap_user?: string
  imap_password?: string
  smtp_host?: string
  smtp_port?: number
  smtp_user?: string
  smtp_password?: string
}

export interface UpdateAccountRequest {
  name?: string
  check_interval_minutes?: number
  max_emails_per_batch?: number
  auto_reply_enabled?: boolean
  draft_only?: boolean
  signature?: string
  default_language?: string
}

export interface OutgoingAttachment {
  filename: string
  data_base64: string
  content_type: string
}

export interface MonthlyRecap {
  month: string
  month_label: string
  emails_processed: number
  drafts_generated: number
  time_saved_hours: number
  time_saved_work_days: number
  inbox_zero_days: number
  avg_reply_time_minutes: number
  fastest_reply_minutes: number
  ai_assisted_percent: number
  days_active: number
  comparison: { type: string; delta_hours: number; message: string }
  is_empty?: boolean
  data_quality?: 'empty' | 'partial' | 'complete' | string
  data_notes?: string[]
  best: {
    inbox_zero_days: number
    avg_reply_time_minutes: number
    fastest_reply_minutes: number
    ai_assisted_percent: number
    days_active: number
  }
  feature_breakdown: Array<{ key: string; label: string; minutes: number; detail: string }>
}

export interface InboxStats {
  unread_count: number
  newsletter_count: number
  older_than_30_days: number
  total_count: number
  newsletters_older_7_days: number
  read_older_30_days: number
  notification_unread_count: number
}

export interface CleanupAction {
  type: 'delete_newsletters_older_than' | 'archive_read_older_than' | 'mark_read_notifications'
  days?: number
}

export interface CleanupResult {
  results: Array<{ type: string; count: number }>
  total_handled: number
  estimated_time_saved_minutes: number
}

/**
 * Y001 backend-reachability signals. ConnectionBanner (via useConnectionHealth)
 * listens for these to surface a debounced "reconnecting" strip when the backend
 * goes briefly unreachable (502/503/504, timeout, or network error) — failures
 * that would otherwise be silent (empty views, stale lists, no toast).
 */
function signalBackendReachable(): void {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('api:connection-restored'))
  }
}

/**
 * Audit connectivité 2026-06-13 : the failure cause rides on the event so
 * useConnectionHealth can tag the (debounced) Sentry episode event and
 * distinguish backend-down from client-offline.
 *   - 'gateway' — 502/503/504 with a non-JSON body (Railway edge, upstream down)
 *   - 'timeout' — client-side deadline hit (backend not answering)
 *   - 'network' — fetch TypeError (no network / DNS / CORS-less 5xx)
 */
export type ConnectionLossCause = 'gateway' | 'timeout' | 'network'

function signalBackendUnreachable(cause: ConnectionLossCause): void {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('api:connection-lost', { detail: { cause } }))
  }
}

export class ApiError extends Error {
  status: number
  /** When status === 429, the seconds the client should wait before retrying. */
  retryAfter?: number

  constructor(message: string, status: number, retryAfter?: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    if (retryAfter !== undefined) this.retryAfter = retryAfter
  }
}

// BUG-Y007 mitigation: module-level in-flight de-dup map for the handful of
// endpoints that get hammered by parallel mounts (calendar/upcoming, …).
// Keyed by a logical name so two callers asking for the same query string
// share the same promise. Cleared when the promise settles, so a second call
// after the first one finishes always hits the network again — this is NOT a
// cache, just a stampede guard.
const _apiInflight: Map<string, Promise<unknown>> = new Map()

export class ApiClient {
  private baseUrl: string

  constructor(baseUrl: string = API_URL) {
    this.baseUrl = baseUrl
  }

  async request<T>(
    endpoint: string,
    options: RequestInit = {},
    timeoutMs: number = 30000
  ): Promise<T> {
    return this._requestWithRetryR009<T>(endpoint, options, timeoutMs, 0)
  }

  // Audit R-009 (2026-04-27): one auto-retry on 429 honoring Retry-After
  // (capped at 30s). Without this the client surfaced ApiError.retryAfter
  // but no caller actually waited — users hammered Retry and amplified
  // the rate-limit. Idempotency: only retry on 429 (server explicitly told
  // us to wait); 5xx and network errors still throw without retry.
  private async _requestWithRetryR009<T>(
    endpoint: string,
    options: RequestInit,
    timeoutMs: number,
    attempt: number,
  ): Promise<T> {
    const url = `${this.baseUrl}/api${endpoint}`

    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs)

    try {
      const response = await fetch(url, {
        ...options,
        method: options.method || 'GET',
        cache: 'no-store',
        headers: {
          'Content-Type': 'application/json',
          'Accept-Language': i18n.language?.slice(0, 2) || 'fr',
          ...getAuthHeaders(),
          ...options.headers,
        },
        signal: controller.signal,
      })

      // Safe JSON parsing — backend may return HTML on unhandled errors (e.g. 503)
      const text = await response.text()

      // Auto-retry once on transient 5xx for idempotent (GET) requests.
      // 2026-05-13 incident: backend restart between FE requests surfaced
      // a hard "Server error (500): no response body" on the Drafts page
      // instead of a brief blip. Restricted to GET so POST/PUT/DELETE/
      // PATCH don't double-execute when the original request had
      // already been processed by a half-shut backend.
      const _method = (options.method || 'GET').toUpperCase()
      if (
        _method === 'GET'
        && response.status >= 500
        && response.status < 600
        && attempt === 0
      ) {
        clearTimeout(timeoutId)
        await new Promise((r) => setTimeout(r, 1500))
        return this._requestWithRetryR009<T>(endpoint, options, timeoutMs, attempt + 1)
      }

      let data: Record<string, unknown>
      try {
        data = JSON.parse(text)
        // Y001: a parseable JSON body means the backend itself answered (not a
        // gateway 502 HTML page). Treat <500 as "reachable" so the banner clears.
        if (response.status < 500) signalBackendReachable()
      } catch {
        // Y001: a non-JSON body on a gateway-class status is the Vite/Railway
        // proxy returning an HTML error page because the upstream is down.
        if (response.status >= 502 && response.status <= 504) {
          signalBackendUnreachable('gateway')
        }
        throw new ApiError(
          `Server error (${response.status}): ${text.slice(0, 120) || 'no response body'}`,
          response.status,
        )
      }

      if (!response.ok) {
        // Audit 2026-05-18 i18n sweep: backend now ships `error_code` (UPPER_SNAKE)
        // alongside an English fallback in `error`. The error_code is the source
        // of truth for both the auth-redirect detection AND the user-facing
        // localized message. Old backend deploys without `error_code` still work
        // — we keep substring detection on `data.error` (now English + legacy
        // French) so rolling deploys never break the auth redirect.
        const errorCode = ((data.error_code as string | undefined) || '').toUpperCase()
        const errMsgRaw = (data.error as string | undefined) || ''

        if (response.status === 401) {
          const lowerErr = errMsgRaw.toLowerCase()
          const isAuthError =
            errorCode === 'NOT_AUTHENTICATED'
            || errorCode === 'TOKEN_INVALID_OR_EXPIRED'
            || errorCode === 'TOKEN_EXPIRED'
            // Legacy fallback for backend deploys that don't yet send error_code.
            || lowerErr.includes('non authentifié')
            || lowerErr.includes('token invalide')
            || lowerErr.includes('token expiré')
            // New English fallback strings from migrated endpoints.
            || lowerErr.includes('not authenticated')
            || lowerErr.includes('token invalid')
            || lowerErr.includes('token expired')
            || lowerErr.includes('unauthorized')
          if (isAuthError) {
            window.dispatchEvent(new CustomEvent('auth:unauthorized'))
          }
        }
        // Surface retry_after for 429 so callers can show a countdown
        // (audit Send-MEDIUM "rate-limit silently triggered").
        let retryAfter: number | undefined
        if (response.status === 429) {
          const ra = data.retry_after
          if (typeof ra === 'number' && ra > 0) {
            retryAfter = Math.ceil(ra)
          } else {
            const headerRa = response.headers.get('Retry-After')
            const parsed = headerRa ? parseInt(headerRa, 10) : NaN
            if (!Number.isNaN(parsed)) retryAfter = parsed
          }
        }
        // R-009: on first 429 with Retry-After ≤30s, sleep then retry once.
        if (response.status === 429 && attempt === 0 && retryAfter && retryAfter > 0 && retryAfter <= 30) {
          clearTimeout(timeoutId)
          await new Promise((r) => setTimeout(r, retryAfter * 1000))
          return this._requestWithRetryR009<T>(endpoint, options, timeoutMs, attempt + 1)
        }
        // Build the user-facing message. Priority: i18n via error_code
        // (with optional interpolation context) → English fallback in
        // `data.error` → legacy `data.message` → generic 'Unknown error'.
        const errorContext = (data.error_context as Record<string, unknown> | undefined) || {}
        const fallback = errMsgRaw || (data.message as string | undefined) || 'Unknown error'
        const localizedMessage = errorCode
          ? i18n.t(`errors:${errorCode.toLowerCase()}`, { ...errorContext, defaultValue: fallback })
          : fallback
        throw new ApiError(
          localizedMessage,
          response.status,
          retryAfter,
        )
      }

      return data as T
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        // Y001: a timeout means the backend isn't responding → unreachable.
        signalBackendUnreachable('timeout')
        throw new ApiError('Request timeout', 408)
      }
      // Method-override fallback (2026-06-23). Some embedded-webview HTTP stacks
      // and endpoint-security/AV software silently drop PATCH/PUT/DELETE — the
      // request never reaches the server, so fetch rejects with a network-level
      // TypeError ("Failed to fetch"). POST is unaffected, so retry once tunneling
      // the verb through `X-HTTP-Method-Override`, which the backend rewrites
      // before routing (see app/api/app.py _method_override_middleware). Gated to
      // the network-error path (NOT timeouts) so a request that actually reached
      // the server is never re-executed; the override header gates against loops.
      {
        const _method = (options.method || 'GET').toUpperCase()
        const _alreadyOverridden = !!(options.headers as Record<string, string> | undefined)?.['X-HTTP-Method-Override']
        const _networkError = error instanceof TypeError && /fetch|network|load failed/i.test(error.message)
        if (
          !_alreadyOverridden
          && (_method === 'PATCH' || _method === 'PUT' || _method === 'DELETE')
          && _networkError
        ) {
          clearTimeout(timeoutId)
          return this._requestWithRetryR009<T>(
            endpoint,
            {
              ...options,
              method: 'POST',
              headers: {
                ...(options.headers as Record<string, string> | undefined),
                'X-HTTP-Method-Override': _method,
              },
            },
            timeoutMs,
            attempt,
          )
        }
      }
      // Audit 2026-05-18: a brief Railway-edge blip (WS 502, or 5xx that
      // returns no CORS headers) makes fetch throw `TypeError: Failed to
      // fetch` with no status code. The user-observed effect was a cascade
      // of failures across the whole UI (compose modal couldn't load accounts,
      // contacts, snippets, etc.) until a full reload. We retry once for
      // idempotent GETs to absorb the blip; non-GET stays as-is so we never
      // double-execute a write.
      const _method = (options.method || 'GET').toUpperCase()
      if (
        _method === 'GET'
        && attempt === 0
        && error instanceof TypeError
        && /fetch|network|load failed/i.test(error.message)
      ) {
        clearTimeout(timeoutId)
        await new Promise((r) => setTimeout(r, 800))
        return this._requestWithRetryR009<T>(endpoint, options, timeoutMs, attempt + 1)
      }
      // Y001: network give-up (TypeError after the single GET retry, or any
      // non-GET connectivity failure) → surface the reconnecting banner.
      if (
        error instanceof TypeError
        && /fetch|network|load failed/i.test(error.message)
      ) {
        signalBackendUnreachable('network')
      }
      throw error
    } finally {
      clearTimeout(timeoutId)
    }
  }

  async health(): Promise<HealthStatus> {
    return this.request<HealthStatus>('/health')
  }

  async recordLegalConsent(provider: 'gmail' | 'outlook'): Promise<LegalConsentResponse> {
    return this.request<LegalConsentResponse>('/privacy/consents', {
      method: 'POST',
      body: JSON.stringify({
        accepted: true,
        provider,
        terms_version: '2026-05-30',
        privacy_version: '2026-05-30',
      }),
    })
  }

  async listEmails(limit: number = 50): Promise<{ count: number; emails: Email[] }> {
    return this.request<{ count: number; emails: Email[] }>(`/emails?limit=${limit}`)
  }

  async getEmail(emailId: string): Promise<Email> {
    return this.request<Email>(`/emails/${encodeURIComponent(emailId)}`)
  }

  async generatePreview(emailId: string): Promise<PreviewResponse> {
    return this.request<PreviewResponse>(
      `/emails/${encodeURIComponent(emailId)}/preview`,
      { method: 'POST' }
    )
  }

  async cancelEmailProcess(emailId: string): Promise<{ success: boolean; email_id: string; status: string }> {
    return this.request<{ success: boolean; email_id: string; status: string }>(
      `/emails/${encodeURIComponent(emailId)}/cancel-process`,
      { method: 'POST' }
    )
  }

  async createDraft(
    emailId: string,
    subject: string,
    body: string,
    to?: string[],
    cc?: string[],
    bcc?: string[],
    attachments?: OutgoingAttachment[],
    send?: boolean,
    archive?: boolean,
  ): Promise<{ success: boolean; draft_id: string; sent?: boolean }> {
    const payload: Record<string, unknown> = { subject, body }
    if (to && to.length > 0) payload.to = to
    if (cc && cc.length > 0) payload.cc = cc
    if (bcc && bcc.length > 0) payload.bcc = bcc
    if (attachments && attachments.length > 0) payload.attachments = attachments
    if (send) payload.send = true
    if (archive) payload.archive = true
    return this.request<{ success: boolean; draft_id: string; sent?: boolean }>(
      `/emails/${encodeURIComponent(emailId)}/draft`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
      send ? 60000 : 30000,
    )
  }

  async sendNewEmail(to: string, subject: string, body: string, cc?: string, bcc?: string, attachments?: { filename: string; data: string; content_type: string }[], aiAssisted?: boolean, skipSignature?: boolean, signatureHtml?: string, accountIdOverride?: string, clientSendId?: string): Promise<{ success: boolean }> {
    return this.request<{ success: boolean }>(
      '/emails/send-new',
      {
        method: 'POST',
        body: JSON.stringify({ to, subject, body, cc: cc || '', bcc: bcc || '', attachments: attachments || [], ai_assisted: aiAssisted || false, skip_signature: skipSignature || false, signature_html: signatureHtml || '', client_send_id: clientSendId || '' }),
        // Override X-Account-Id when the send was registered under a specific account
        // (e.g. undo-send rehydration after an account switch).
        ...(accountIdOverride ? { headers: { 'X-Account-Id': accountIdOverride } } : {}),
      },
      60000, // 60s timeout: SMTP send + signature
    )
  }

  async saveNewDraft(
    to: string,
    subject: string,
    body: string,
    cc?: string,
    bcc?: string,
    signatureHtml?: string,
  ): Promise<{ success: boolean; draft_id: string }> {
    return this.request<{ success: boolean; draft_id: string }>(
      '/emails/save-draft',
      {
        method: 'POST',
        body: JSON.stringify({
          to: to || '',
          subject,
          body,
          cc: cc || '',
          bcc: bcc || '',
          skip_signature: true,
          signature_html: signatureHtml || '',
        }),
      },
      15000,
    )
  }

  async sendDraft(draftId: string): Promise<{ success: boolean; message_id: string }> {
    return this.request<{ success: boolean; message_id: string }>(
      `/emails/${encodeURIComponent(draftId)}/send`,
      { method: 'POST' }
    )
  }

  // ─── Schedule send (envoi differe) ──────────────────────────────────────
  async scheduleEmail(payload: {
    to: string
    subject: string
    body: string
    send_at: string  // ISO 8601 UTC
    cc?: string
    bcc?: string
    is_html?: boolean
    reply_to_id?: string
    thread_id?: string
    attachments?: { filename: string; data: string; content_type: string }[]
    skip_signature?: boolean
    signature_html?: string
    from_name?: string
    ai_assisted?: boolean
  }): Promise<{ scheduled_id: string; status: string; send_at: string }> {
    return this.request(
      '/emails/schedule',
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
      30000,
    )
  }

  async listScheduledEmails(status: string = 'pending'): Promise<{
    items: ScheduledEmailDTO[]
    count: number
    // Deep audit 2026-06-02 U: set when the backend store read failed (returned
    // a degraded 200 rather than a 5xx that would trip the connection-lost path).
    degraded?: boolean
  }> {
    return this.request(`/emails/scheduled?status=${encodeURIComponent(status)}`, {
      method: 'GET',
    })
  }

  async cancelScheduledEmail(scheduledId: string): Promise<{ success: boolean; scheduled_id: string }> {
    return this.request(
      `/emails/scheduled/${encodeURIComponent(scheduledId)}`,
      { method: 'DELETE' },
    )
  }

  async sendScheduledNow(scheduledId: string): Promise<{ success: boolean; scheduled: ScheduledEmailDTO }> {
    return this.request(
      `/emails/scheduled/${encodeURIComponent(scheduledId)}/send-now`,
      { method: 'POST' },
      30000,
    )
  }

  async patchScheduledEmail(
    scheduledId: string,
    patch: { send_at?: string; subject?: string; body?: string; to?: string; cc?: string; bcc?: string; is_html?: boolean },
  ): Promise<{ success: boolean; scheduled: ScheduledEmailDTO }> {
    return this.request(
      `/emails/scheduled/${encodeURIComponent(scheduledId)}`,
      {
        method: 'PATCH',
        body: JSON.stringify(patch),
      },
    )
  }

  async skipEmail(emailId: string): Promise<{ success: boolean }> {
    return this.request<{ success: boolean }>(
      `/emails/${encodeURIComponent(emailId)}/skip`,
      { method: 'POST' }
    )
  }

  async submitFeedback(
    draftId: string,
    feedback: 'accepted' | 'rejected' | 'modified',
    comment?: string,
    rating?: number
  ): Promise<{ success: boolean }> {
    const body: Record<string, unknown> = { feedback }
    if (comment) body.comment = comment
    if (rating !== undefined && rating > 0) body.rating = rating
    return this.request<{ success: boolean }>(
      `/drafts/${encodeURIComponent(draftId)}/feedback`,
      {
        method: 'PATCH',
        body: JSON.stringify(body),
      }
    )
  }

  async submitStyleFeedback(
    draftId: string,
    issues: string[],
    correction?: string
  ): Promise<{ success: boolean }> {
    return this.request<{ success: boolean }>(
      `/drafts/${encodeURIComponent(draftId)}/feedback`,
      {
        method: 'PATCH',
        body: JSON.stringify({
          feedback: 'negative',
          comment: `Style issues: ${issues.join(', ')}${correction ? `. Correction: ${correction}` : ''}`,
        }),
      }
    )
  }

  // Account management methods

  async listAccounts(): Promise<AccountsListResponse> {
    const response = await this.request<AccountsListResponse>('/accounts')
    return { ...response, accounts: response.accounts.map(normalizeAccountAvatar) }
  }

  async getAccount(accountId: string): Promise<Account> {
    return normalizeAccountAvatar(await this.request<Account>(`/accounts/${encodeURIComponent(accountId)}`))
  }

  async createAccount(data: CreateAccountRequest): Promise<{ success: boolean; account: Account }> {
    return this.request<{ success: boolean; account: Account }>(
      '/accounts',
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    )
  }

  async updateAccount(
    accountId: string,
    data: UpdateAccountRequest
  ): Promise<{ success: boolean; account: Account }> {
    return this.request<{ success: boolean; account: Account }>(
      `/accounts/${encodeURIComponent(accountId)}`,
      {
        method: 'PATCH',
        body: JSON.stringify(data),
      }
    )
  }

  async deleteAccount(accountId: string): Promise<{ success: boolean }> {
    return this.request<{ success: boolean }>(
      `/accounts/${encodeURIComponent(accountId)}`,
      { method: 'DELETE' }
    )
  }

  async resetAllData(): Promise<{ success: boolean; message: string }> {
    // 1. Delete wizard config (file + memory cache) so onboarding restarts
    await this.request('/wizard/config', { method: 'DELETE' }).catch(() => {})
    // 2. Purge all backend data
    return this.request<{ success: boolean; message: string }>(
      '/dev/reset-all-data',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: 'RESET_ALL_DATA' }),
      }
    )
  }

  async getAccountTokenStatus(accountId: string): Promise<AccountTokenStatus> {
    return this.request<AccountTokenStatus>(`/oauth/tokens/${encodeURIComponent(accountId)}/status`)
  }

  async activateAccount(accountId: string): Promise<{ success: boolean; message: string }> {
    return this.request<{ success: boolean; message: string }>(
      `/accounts/${encodeURIComponent(accountId)}/activate`,
      { method: 'POST' }
    )
  }

  async testAccountConnection(accountId: string): Promise<{ success: boolean; message: string }> {
    return this.request<{ success: boolean; message: string }>(
      `/accounts/${encodeURIComponent(accountId)}/test`,
      { method: 'POST' }
    )
  }

  async getAccountStats(accountId: string): Promise<{ account_id: string; stats: AccountStats }> {
    return this.request<{ account_id: string; stats: AccountStats }>(
      `/accounts/${encodeURIComponent(accountId)}/stats`
    )
  }

  async getDraftQualityStats(days: number = 7): Promise<DraftQualityStats> {
    return this.request<DraftQualityStats>(`/draft-quality/stats?days=${days}`)
  }

  async recordFeature(feature: string, count: number = 1): Promise<void> {
    this.request('/stats/feature', {
      method: 'POST',
      body: JSON.stringify({ feature, count }),
    }).catch(() => { /* fire-and-forget */ })
  }

  async testWizardConnection(params: WizardConnectionParams): Promise<WizardConnectionResult> {
    return this.request<WizardConnectionResult>(
      '/wizard/test-connection',
      {
        method: 'POST',
        body: JSON.stringify(params),
      }
    )
  }

  async testLLMConnection(params: LLMConnectionParams): Promise<LLMConnectionResult> {
    return this.request<LLMConnectionResult>(
      '/wizard/test-llm',
      {
        method: 'POST',
        body: JSON.stringify(params),
      }
    )
  }

  async getLLMSettings(): Promise<LLMSettingsResponse> {
    return this.request<LLMSettingsResponse>('/wizard/llm-settings')
  }

  async saveLLMSettings(params: SaveLLMSettingsParams): Promise<SaveLLMSettingsResponse> {
    return this.request<SaveLLMSettingsResponse>(
      '/wizard/llm-settings',
      {
        method: 'POST',
        body: JSON.stringify(params),
      }
    )
  }

  async analyzeStyle(params: StyleAnalysisParams): Promise<StyleAnalysisResult> {
    return this.request<StyleAnalysisResult>(
      '/wizard/analyze-style',
      {
        method: 'POST',
        body: JSON.stringify(params),
      }
    )
  }

  async saveStyle(params: SaveStyleParams): Promise<{ success: boolean }> {
    return this.request<{ success: boolean }>(
      '/wizard/save-style',
      {
        method: 'POST',
        body: JSON.stringify(params),
      }
    )
  }

  async saveSettings(params: SaveSettingsParams): Promise<{ success: boolean }> {
    return this.request<{ success: boolean }>(
      '/settings',
      {
        method: 'PATCH',
        body: JSON.stringify(params),
      }
    )
  }

  async getEnvConfig(): Promise<EnvConfigResponse> {
    return this.request<EnvConfigResponse>('/wizard/env-config')
  }

  async listDiscordMessages(limit: number = 50, pendingOnly: boolean = true): Promise<DiscordMessagesResponse> {
    return this.request<DiscordMessagesResponse>(
      `/discord/messages?limit=${limit}&pending_only=${pendingOnly}`
    )
  }

  async getDiscordMessage(messageId: string): Promise<DiscordMessage> {
    return this.request<DiscordMessage>(
      `/discord/messages/${encodeURIComponent(messageId)}`
    )
  }

  async suggestDiscordResponse(messageId: string): Promise<DiscordSuggestResponse> {
    return this.request<DiscordSuggestResponse>(
      `/discord/messages/${encodeURIComponent(messageId)}/suggest`,
      { method: 'POST' }
    )
  }

  async respondToDiscordMessage(
    messageId: string,
    content: string
  ): Promise<{ success: boolean; message_id: string; response_content: string }> {
    return this.request<{ success: boolean; message_id: string; response_content: string }>(
      `/discord/messages/${encodeURIComponent(messageId)}/respond`,
      {
        method: 'POST',
        body: JSON.stringify({ content }),
      }
    )
  }

  async skipDiscordMessage(messageId: string): Promise<{ success: boolean }> {
    return this.request<{ success: boolean }>(
      `/discord/messages/${encodeURIComponent(messageId)}/skip`,
      { method: 'POST' }
    )
  }

  async getDiscordConfig(): Promise<DiscordConfig> {
    return this.request<DiscordConfig>('/discord/config')
  }

  async getDiscordStats(): Promise<DiscordStats> {
    return this.request<DiscordStats>('/discord/stats')
  }

  async listTelegramMessages(limit: number = 50, pendingOnly: boolean = true): Promise<TelegramMessagesResponse> {
    return this.request<TelegramMessagesResponse>(
      `/telegram/messages?limit=${limit}&pending_only=${pendingOnly}`
    )
  }

  async getTelegramMessage(messageId: string): Promise<TelegramMessage> {
    return this.request<TelegramMessage>(
      `/telegram/messages/${encodeURIComponent(messageId)}`
    )
  }

  async suggestTelegramResponse(messageId: string): Promise<TelegramSuggestResponse> {
    return this.request<TelegramSuggestResponse>(
      `/telegram/messages/${encodeURIComponent(messageId)}/suggest`,
      { method: 'POST' }
    )
  }

  async respondToTelegramMessage(
    messageId: string,
    content: string,
    send: boolean = false
  ): Promise<{ success: boolean; message_id: string; response_content: string; sent?: boolean; sent_message_id?: string }> {
    return this.request<{ success: boolean; message_id: string; response_content: string; sent?: boolean; sent_message_id?: string }>(
      `/telegram/messages/${encodeURIComponent(messageId)}/respond`,
      {
        method: 'POST',
        body: JSON.stringify({ content, send }),
      }
    )
  }

  async skipTelegramMessage(messageId: string): Promise<{ success: boolean }> {
    return this.request<{ success: boolean }>(
      `/telegram/messages/${encodeURIComponent(messageId)}/skip`,
      { method: 'POST' }
    )
  }

  async getTelegramConfig(): Promise<TelegramConfig> {
    return this.request<TelegramConfig>('/telegram/config')
  }

  async getTelegramStats(): Promise<TelegramStats> {
    return this.request<TelegramStats>('/telegram/stats')
  }

  // Pending Drafts methods

  async listPendingDrafts(limit: number = 50): Promise<PendingDraftsResponse> {
    const path = `/pending-drafts?limit=${limit}`
    const dedupKey = `pending-drafts|${limit}`
    const pending = _apiInflight.get(dedupKey) as Promise<PendingDraftsResponse> | undefined
    if (pending) return pending
    const fresh = this.request<PendingDraftsResponse>(path).finally(() => {
      _apiInflight.delete(dedupKey)
    })
    _apiInflight.set(dedupKey, fresh)
    return fresh
  }

  async listSnoozedFollowupDrafts(): Promise<SnoozedFollowupDraftsResponse> {
    // Drafts created by the `create_snoozed_followup_draft` Quick Step
    // action whose snooze hasn't elapsed yet. Surfaced under "Later" in
    // SnoozedView with a Snoozed badge until the wake date.
    return this.request<SnoozedFollowupDraftsResponse>('/pending-drafts/snoozed')
  }

  async getPendingDraft(draftId: string): Promise<PendingDraft> {
    // Use /api/pending-drafts/:id for drafts created via process_email
    return this.request<PendingDraft>(`/pending-drafts/${encodeURIComponent(draftId)}`)
  }

  // In-flight request deduplication for pending-drafts/by-email.
  // Multiple consumers (useEmailDetailController, EmailDetailModal, ReplyComposer)
  // often request the same email's draft within a few ms of each other, especially
  // under React StrictMode which double-invokes effects in dev.
  // Keying by emailId lets all concurrent callers share a single HTTP round-trip.
  private _pendingDraftInFlight = new Map<string, Promise<PendingDraft | null>>()

  async getPendingDraftByEmailId(emailId: string, subject?: string): Promise<PendingDraft | null> {
    const inFlight = this._pendingDraftInFlight.get(emailId)
    if (inFlight) return inFlight

    const promise = (async (): Promise<PendingDraft | null> => {
      try {
        const params = subject ? `?subject=${encodeURIComponent(subject)}` : ''
        const resp = await this.request<{ draft: PendingDraft | null }>(
          `/pending-drafts/by-email/${encodeURIComponent(emailId)}${params}`
        )
        return resp.draft ?? null
      } catch {
        return null
      }
    })().finally(() => {
      this._pendingDraftInFlight.delete(emailId)
    })

    this._pendingDraftInFlight.set(emailId, promise)
    return promise
  }

  // NB: follow-ups are owned entirely client-side (writeSnoozeEntry + createReminder
  // in PendingDraftDetail / ReplyComposer). The validate route never read a
  // `followup_delay_days` field, so it was dropped from this surface (audit
  // 2026-06-02) rather than left as a dead, misleading parameter.
  async validatePendingDraft(draftId: string, archive?: boolean, attachments?: OutgoingAttachment[], cc?: string[], bcc?: string[]): Promise<{
    success: boolean;
    draft_id: string;
    gmail_draft_id: string;
    sent?: boolean;
    message?: string;
    knowledge_suggestions?: Array<{ question: string; answer: string; context: string }>;
  }> {
    const body: Record<string, unknown> = {}
    if (archive) body.archive = true
    if (attachments && attachments.length > 0) body.attachments = attachments
    if (cc && cc.length > 0) body.cc = cc
    if (bcc && bcc.length > 0) body.bcc = bcc
    return this.request<{
      success: boolean;
      draft_id: string;
      gmail_draft_id: string;
      sent?: boolean;
      message?: string;
      knowledge_suggestions?: Array<{ question: string; answer: string; context: string }>;
    }>(
      `/pending-drafts/${encodeURIComponent(draftId)}/validate`,
      {
        method: 'POST',
        body: JSON.stringify(body),
      },
      60000, // 60s timeout: includes SMTP send + IMAP archive
    )
  }

  async addKnowledgeFact(question: string, answer: string): Promise<{ success: boolean }> {
    return this.request<{ success: boolean }>('/memory/add-fact', {
      method: 'POST',
      body: JSON.stringify({ question, answer }),
    })
  }

  async rejectPendingDraft(draftId: string): Promise<{ success: boolean; draft_id: string }> {
    return this.request<{ success: boolean; draft_id: string }>(
      `/pending-drafts/${encodeURIComponent(draftId)}/reject`,
      { method: 'POST' }
    )
  }

  async trackSuggestionClick(draftId: string, suggestionText: string, suggestionIndex: number): Promise<{ success: boolean }> {
    return this.request<{ success: boolean }>(
      `/pending-drafts/${encodeURIComponent(draftId)}/suggestion-clicked`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ suggestion_text: suggestionText, suggestion_index: suggestionIndex }),
      }
    )
  }

  async purgeAllDrafts(): Promise<{ success: boolean; deleted_count: number }> {
    return this.request<{ success: boolean; deleted_count: number }>(
      '/pending-drafts/purge-all',
      { method: 'POST' }
    )
  }

  async getContactStyle(contactEmail: string): Promise<ContactStyleResponse> {
    return this.request<ContactStyleResponse>(
      `/writing-style/contact-style?contact_email=${encodeURIComponent(contactEmail)}`
    )
  }

  async updateContactSignature(
    contactEmail: string,
    preferredSignature: string | null
  ): Promise<{ success: boolean; contact_email: string }> {
    return this.request<{ success: boolean; contact_email: string }>(
      '/writing-style/contact-style',
      {
        method: 'PUT',
        body: JSON.stringify({
          contact_email: contactEmail,
          preferred_signature: preferredSignature ?? '',
        }),
      }
    )
  }

  async deletePendingDraft(draftId: string): Promise<{ success: boolean; draft_id: string }> {
    return this.request<{ success: boolean; draft_id: string }>(
      `/pending-drafts/${encodeURIComponent(draftId)}`,
      { method: 'DELETE' }
    )
  }

  async upgradeDraft(draftId: string): Promise<PendingDraft> {
    return this.request<PendingDraft>(
      `/pending-drafts/${encodeURIComponent(draftId)}/upgrade`,
      { method: 'POST' },
      120000 // 2 minutes for full LLM generation
    )
  }

  async updatePendingDraft(
    draftId: string,
    subject?: string,
    body?: string
  ): Promise<{ success: boolean; draft_id: string }> {
    const data: { subject?: string; body?: string } = {}
    if (subject !== undefined) data.subject = subject
    if (body !== undefined) data.body = body

    // Use /api/pending-drafts/:id to update pending draft content
    return this.request<{ success: boolean; draft_id: string }>(
      `/pending-drafts/${encodeURIComponent(draftId)}`,
      {
        method: 'PATCH',
        body: JSON.stringify(data),
      }
    )
  }

  async confirmAccountAction(
    draftId: string
  ): Promise<{ success: boolean; action: string; new_password?: string; new_body?: string }> {
    return this.request(`/account/${encodeURIComponent(draftId)}/confirm`, {
      method: 'POST',
    })
  }

  async rejectAccountAction(
    draftId: string,
    reason?: string
  ): Promise<{ success: boolean }> {
    return this.request(`/account/${encodeURIComponent(draftId)}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason: reason || '' }),
    })
  }

  // Uses 3-minute timeout for LLM processing
  async refineDraft(
    draftId: string,
    instruction: string
  ): Promise<{
    success: boolean;
    draft_id: string;
    refined_body: string;
    pipeline_details: {
      draft_v1: string;
      critique: {
        is_valid: boolean;
        feedback: string;
      };
      was_corrected: boolean;
    };
  }> {
    return this.request<{
      success: boolean;
      draft_id: string;
      refined_body: string;
      pipeline_details: {
        draft_v1: string;
        critique: {
          is_valid: boolean;
          feedback: string;
        };
        was_corrected: boolean;
      };
    }>(
      `/drafts/${encodeURIComponent(draftId)}/refine`,
      {
        method: 'POST',
        body: JSON.stringify({ instruction }),
      },
      180000 // 3 minutes for draft refinement
    )
  }

  // Refine user-written text via AI instruction (no draftId needed).
  //
  // Standard mode (Ctrl+I): single Haiku call.
  // Expert mode (Ctrl+Shift+I, opts.useSpecialty=true): two-call flow
  // Sonnet plan → Haiku draft. The draft cites articles INLINE in prose
  // (e.g. "(arts. 1726-1733 CCQ)") — no footnote anymore. Returns
  // `specialty_info` describing the match (with applied_sources for audit)
  // or a warning.
  // Surgical mode (Ctrl+M, opts.surgical=true): minimal-diff edit. The LLM
  // is instructed to change ONLY what the instruction targets and preserve
  // everything else byte-for-byte. Bypasses style/tone/closing enrichment.
  async refineText(
    text: string,
    instruction: string,
    emailId?: string,
    to?: string,
    opts?: { useSpecialty?: boolean; subject?: string; surgical?: boolean; senderName?: string; targetLanguage?: string }
  ): Promise<{
    success: boolean
    refined_text: string
    specialty_info?: import('../types/specialty').SpecialtyInfo
  }> {
    const useSpecialty = !!opts?.useSpecialty
    return this.request<{
      success: boolean
      refined_text: string
      specialty_info?: import('../types/specialty').SpecialtyInfo
    }>(
      '/refine-text',
      {
        method: 'POST',
        body: JSON.stringify({
          text,
          instruction,
          email_id: emailId,
          to,
          sender_name: opts?.senderName || undefined,
          target_language: opts?.targetLanguage || undefined,
          use_specialty: useSpecialty || undefined,
          subject: opts?.subject || undefined,
          surgical: opts?.surgical || undefined,
        }),
      },
      // Expert mode runs two LLM calls (Sonnet + Haiku) so we bump the
      // timeout from 60s to 90s. Standard mode keeps the original 60s.
      useSpecialty ? 90000 : 60000
    )
  }

  // Regenerate Draft with New Instructions (Story 6-4)
  // Uses 3-minute timeout for LLM processing
  async regenerateDraft(
    draftId: string,
    instructions: string
  ): Promise<RegenerateDraftResponse> {
    return this.request<RegenerateDraftResponse>(
      `/drafts/${encodeURIComponent(draftId)}/regenerate`,
      {
        method: 'POST',
        body: JSON.stringify({ instructions }),
      },
      180000 // 3 minutes for draft regeneration
    )
  }

  // Generate AI Draft for an email
  // Uses 3-minute timeout for LLM processing
  async generateDraft(
    emailId: string,
    instructions?: string
  ): Promise<GenerateDraftResponse> {
    const cachedEmail = await getCachedDraftEmailContext(emailId)
    return this.request<GenerateDraftResponse>(
      `/emails/${encodeURIComponent(emailId)}/process`,
      {
        method: 'POST',
        body: JSON.stringify({
          instructions: instructions || '',
          force: true,
          ...(cachedEmail ? { cached_email: cachedEmail } : {}),
        }),
      },
      30000 // 30s — returns 202 immediately, draft arrives via WebSocket
    )
  }

  // Archive email
  async archiveEmail(emailId: string): Promise<{ success: boolean; message: string }> {
    return this.request<{ success: boolean; message: string }>(
      `/emails/${encodeURIComponent(emailId)}/archive`,
      { method: 'POST' }
    )
  }

  // Create follow-up reminder (backend notification)
  async createReminder(emailId: string, subject: string, reminderDate: string): Promise<void> {
    await this.request('/reminders', {
      method: 'POST',
      body: JSON.stringify({ email_id: emailId, subject, reminder_date: reminderDate }),
    })
  }

  // Fetch all pending reminders (for localStorage sync)
  async getReminders(): Promise<Array<{ id: string; email_id: string; subject: string; reminder_date: string; notified: boolean }>> {
    const data = await this.request<{ reminders: Array<{ id: string; email_id: string; subject: string; reminder_date: string; notified: boolean }> }>('/reminders')
    return data.reminders ?? []
  }

  // Delete a reminder by id (called when user unpins a woken followup)
  async deleteReminder(reminderId: string): Promise<void> {
    await this.request(`/reminders/${encodeURIComponent(reminderId)}`, { method: 'DELETE' })
  }

  // Delete email
  async deleteEmail(emailId: string): Promise<{ success: boolean; message: string }> {
    return this.request<{ success: boolean; message: string }>(
      `/emails/${encodeURIComponent(emailId)}/delete`,
      { method: 'POST' }
    )
  }

  // Bulk archive emails
  async bulkArchiveEmails(emailIds: string[]): Promise<BulkActionResponse> {
    return this.request<BulkActionResponse>(
      '/emails/bulk-archive',
      {
        method: 'POST',
        body: JSON.stringify({ email_ids: emailIds }),
      }
    )
  }

  // Bulk delete emails
  async bulkDeleteEmails(emailIds: string[]): Promise<BulkActionResponse> {
    return this.request<BulkActionResponse>(
      '/emails/bulk-delete',
      {
        method: 'POST',
        body: JSON.stringify({ email_ids: emailIds }),
      }
    )
  }

  // Mark email as not spam (move to inbox)
  async moveToNotSpam(emailId: string): Promise<{ success: boolean; email_id: string; message: string }> {
    return this.request<{ success: boolean; email_id: string; message: string }>(
      `/emails/${encodeURIComponent(emailId)}/not-spam`,
      { method: 'POST' }
    )
  }

  // Move email to spam folder (backend auto-learns patterns)
  async moveToSpam(emailId: string, sender?: string): Promise<{ success: boolean; email_id: string; message: string }> {
    return this.request<{ success: boolean; email_id: string; message: string }>(
      `/emails/${encodeURIComponent(emailId)}/move-to-spam`,
      {
        method: 'POST',
        ...(sender ? { body: JSON.stringify({ sender }) } : {}),
      }
    )
  }

  // Unarchive email (move from archive to inbox)
  async unarchiveEmail(emailId: string): Promise<{ success: boolean; email_id: string; message: string }> {
    return this.request<{ success: boolean; email_id: string; message: string }>(
      `/emails/${encodeURIComponent(emailId)}/restore?folder=archived`,
      { method: 'POST' }
    )
  }

  // Bulk mark emails as not spam
  async bulkMoveToNotSpam(emailIds: string[]): Promise<BulkActionResponse> {
    return this.request<BulkActionResponse>(
      '/emails/bulk-not-spam',
      {
        method: 'POST',
        body: JSON.stringify({ email_ids: emailIds }),
      }
    )
  }

  // Empty spam folder.
  //
  // The backend may answer in two shapes (cf. routes_emails.py:empty_spam):
  //   - sync 200 → { success: true, deleted_count, rescued_count }
  //   - async 202 (when wave > INLINE_THRESHOLD) → {
  //       accepted: true, mode: "async",
  //       trash_job_id?: string, rescue_job_id?: string,
  //       target_total: number, ...
  //     }
  // Callers should branch on `accepted` vs `success`.
  async emptySpamFolder(): Promise<EmptyFolderResponse> {
    return this.request<EmptyFolderResponse>(
      '/emails/empty-spam',
      { method: 'POST' },
      120000 // 2 minutes — may need to delete many emails
    )
  }

  // Restore email from trash (move to inbox)
  async restoreFromTrash(emailId: string): Promise<{ success: boolean; email_id: string; message: string }> {
    return this.request<{ success: boolean; email_id: string; message: string }>(
      `/emails/${encodeURIComponent(emailId)}/restore`,
      { method: 'POST' }
    )
  }

  // Bulk restore emails from trash
  async bulkRestoreFromTrash(emailIds: string[]): Promise<BulkActionResponse> {
    return this.request<BulkActionResponse>(
      '/emails/bulk-restore',
      {
        method: 'POST',
        body: JSON.stringify({ email_ids: emailIds }),
      }
    )
  }

  // Empty trash folder. Same dual-shape contract as `emptySpamFolder`.
  // Sync answer carries `deleted_count`; async answer carries `job_id`
  // pointing at the bulk-jobs queue row that's draining the deletes.
  async emptyTrashFolder(): Promise<EmptyFolderResponse> {
    return this.request<EmptyFolderResponse>(
      '/emails/empty-trash',
      { method: 'POST' },
      120000 // 2 minutes — may need to delete many emails
    )
  }

  async cleanNoise(): Promise<CleanNoiseResponse> {
    return this.request<CleanNoiseResponse>(
      '/emails/clean-noise',
      { method: 'POST' },
      10000
    )
  }

  async markNoiseRead(): Promise<MarkNoiseReadResponse> {
    return this.request<MarkNoiseReadResponse>(
      '/emails/mark-noise-read',
      { method: 'POST' },
      10000
    )
  }

  // Folders
  async listFolders(): Promise<FoldersResponse> {
    return this.request<FoldersResponse>('/folders')
  }

  // Calendar methods (Issue #26)

  async listCalendarEvents(params: {
    start?: string
    end?: string
    accountId?: string
    calendarId?: string
    limit?: number
    includeFollowups?: boolean
  } = {}): Promise<CalendarEventsResponse> {
    const searchParams = new URLSearchParams()
    if (params.start) searchParams.set('start', params.start)
    if (params.end) searchParams.set('end', params.end)
    if (params.accountId) searchParams.set('account_id', params.accountId)
    if (params.calendarId) searchParams.set('calendar_id', params.calendarId)
    if (params.limit) searchParams.set('limit', String(params.limit))
    if (params.includeFollowups !== undefined)
      searchParams.set('include_followups', String(params.includeFollowups))

    const query = searchParams.toString()
    return this.request<CalendarEventsResponse>(`/calendar/events${query ? `?${query}` : ''}`)
  }

  async createCalendarEvent(
    data: CreateCalendarEventRequest
  ): Promise<{ success: boolean; event_id: string; meet_link?: string | null; message?: string }> {
    return this.request<{ success: boolean; event_id: string; meet_link?: string | null; message?: string }>(
      '/calendar/events',
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    )
  }

  async updateCalendarEvent(
    eventId: string,
    data: Partial<CreateCalendarEventRequest>
  ): Promise<{ success: boolean; event_id: string; message?: string }> {
    return this.request<{ success: boolean; event_id: string; message?: string }>(
      `/calendar/events/${encodeURIComponent(eventId)}`,
      {
        method: 'PATCH',
        body: JSON.stringify(data),
      }
    )
  }

  async deleteCalendarEvent(
    eventId: string,
    accountId?: string,
    calendarId?: string
  ): Promise<{ success: boolean; message?: string }> {
    const searchParams = new URLSearchParams()
    if (accountId) searchParams.set('account_id', accountId)
    if (calendarId) searchParams.set('calendar_id', calendarId)
    const query = searchParams.toString()

    return this.request<{ success: boolean; message?: string }>(
      `/calendar/events/${encodeURIComponent(eventId)}${query ? `?${query}` : ''}`,
      { method: 'DELETE' }
    )
  }

  async findFreeBusySlots(data: {
    attendees: string[]
    start: string
    end: string
    duration_minutes?: number
    work_hours_only?: boolean
    work_start?: number
    work_end?: number
    tz_offset_minutes?: number
    extra_busy?: { start: string; end: string }[]
  }): Promise<{
    slots: { start: string; end: string }[]
    attendees: string[]
    duration_minutes: number
    /**
     * Per-attendee busy blocks for the timeline view. Optional — backend
     * may omit when no attendees were queried or the field is unsupported.
     * `status` is only populated by the Outlook adapter (busy/tentative/oof);
     * Google omits it, treat as 'busy' by default.
     */
    per_attendee_busy?: Record<string, Array<{
      start: string
      end: string
      status?: 'busy' | 'tentative' | 'oof'
    }>>
  }> {
    return this.request('/calendar/freebusy', {
      method: 'POST',
      body: JSON.stringify({
        ...data,
        tz_offset_minutes: data.tz_offset_minutes ?? new Date().getTimezoneOffset(),
      }),
    })
  }

  async listCalendars(accountId?: string): Promise<CalendarsResponse> {
    const query = accountId ? `?account_id=${encodeURIComponent(accountId)}` : ''
    return this.request<CalendarsResponse>(`/calendar/calendars${query}`)
  }

  // Followups methods (Issue #26)

  async listFollowups(params: {
    accountId?: string
    status?: string
    emailId?: string
  } = {}): Promise<FollowupsResponse> {
    const searchParams = new URLSearchParams()
    if (params.accountId) searchParams.set('account_id', params.accountId)
    if (params.status) searchParams.set('status', params.status)
    if (params.emailId) searchParams.set('email_id', params.emailId)

    const query = searchParams.toString()
    return this.request<FollowupsResponse>(`/calendar/followups${query ? `?${query}` : ''}`)
  }

  async createFollowup(data: CreateFollowupRequest): Promise<{
    success: boolean
    id: string
    followup: Followup
  }> {
    return this.request<{ success: boolean; id: string; followup: Followup }>(
      '/calendar/followups',
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    )
  }

  async updateFollowup(
    followupId: string,
    data: UpdateFollowupRequest
  ): Promise<{ success: boolean; followup: Followup }> {
    return this.request<{ success: boolean; followup: Followup }>(
      `/calendar/followups/${encodeURIComponent(followupId)}`,
      {
        method: 'PATCH',
        body: JSON.stringify(data),
      }
    )
  }

  async deleteFollowup(followupId: string): Promise<{ success: boolean; message?: string }> {
    return this.request<{ success: boolean; message?: string }>(
      `/calendar/followups/${encodeURIComponent(followupId)}`,
      { method: 'DELETE' }
    )
  }

  async getFollowupEmail(followupId: string): Promise<{
    email: {
      id: string
      subject: string
      sender: string
      sender_name?: string
      body: string
      body_html?: string
      received_at?: string
      is_read: boolean
    }
    followup_id: string
  }> {
    return this.request(`/calendar/followups/${encodeURIComponent(followupId)}/email`)
  }

  // AI Commitment Suggestions (Issue #26 — Follow-up Suggestions)

  async getSuggestions(emailId?: string, status?: string): Promise<SuggestionsResponse> {
    const params = new URLSearchParams()
    if (emailId) params.set('email_id', emailId)
    if (status) params.set('status', status)
    const query = params.toString()
    return this.request<SuggestionsResponse>(`/calendar/suggestions${query ? `?${query}` : ''}`)
  }

  async acceptSuggestion(
    suggestionId: string,
    syncToCalendar: boolean = false,
    dueDate?: string
  ): Promise<{ success: boolean; suggestion_id: string; followup_id: string; followup: Followup }> {
    return this.request(`/calendar/suggestions/${encodeURIComponent(suggestionId)}/accept`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sync_to_calendar: syncToCalendar,
        ...(dueDate ? { due_date: dueDate } : {}),
      }),
    })
  }

  async rejectSuggestion(suggestionId: string): Promise<{ success: boolean; suggestion_id: string }> {
    return this.request(`/calendar/suggestions/${encodeURIComponent(suggestionId)}/reject`, {
      method: 'POST',
    })
  }

  // Contact autocomplete
  async getSearchSuggestions(
    query: string,
    accountId?: string,
  ): Promise<{ senders: { email: string; name: string }[]; subjects: string[]; labels: { name: string; color: string }[] }> {
    const params = new URLSearchParams()
    params.set('q', query)
    if (accountId) params.set('account_id', accountId)
    return this.request<{ senders: { email: string; name: string }[]; subjects: string[]; labels: { name: string; color: string }[] }>(
      `/emails/search/suggestions?${params.toString()}`
    )
  }

  async searchContacts(
    query: string,
    accountId?: string,
    opts?: { sentOnly?: boolean; limit?: number; includeSelf?: boolean },
  ): Promise<{name: string, email: string}[]> {
    const params = new URLSearchParams()
    if (query) params.set('q', query)
    const effectiveAccountId = accountId || getActiveAccountId()
    if (effectiveAccountId && effectiveAccountId !== 'default') {
      params.set('account_id', effectiveAccountId)
    }
    if (opts?.sentOnly) params.set('sent_only', 'true')
    if (opts?.includeSelf) params.set('include_self', 'true')
    if (opts?.limit && opts.limit > 0) params.set('limit', String(opts.limit))
    const queryString = params.toString()
    return this.request<{name: string, email: string}[]>(
      `/contacts/autocomplete${queryString ? '?' + queryString : ''}`
    )
  }

  /**
   * Onboarding VIP suggestions: the contacts the user writes to most, ranked by
   * sent volume (received count is a tiebreaker, not a requirement) with
   * noreply/automated senders filtered out server-side. Used by Step 4 to offer
   * one-click VIP chips instead of forcing the user to type names from memory.
   *
   * The endpoint resolves the account from auth context (not a query param),
   * so we don't thread account_id here. Returns [] on any failure so the
   * caller can silently fall back to the manual autocomplete.
   */
  async getSuggestedVipContacts(
    opts?: { limit?: number },
  ): Promise<{ name: string; email: string; sent_count: number; received_count: number }[]> {
    const params = new URLSearchParams()
    if (opts?.limit && opts.limit > 0) params.set('limit', String(opts.limit))
    const queryString = params.toString()
    try {
      const res = await this.request<{
        contacts: { name: string; email: string; sent_count: number; received_count: number }[]
      }>(`/contacts/suggested-vip${queryString ? '?' + queryString : ''}`)
      return res?.contacts ?? []
    } catch {
      return []
    }
  }

  // Contact Groups
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  async listContactGroups(): Promise<{ groups: any[]; total: number }> {
    const accountId = getActiveAccountId()
    const qs = accountId && accountId !== 'default' ? `?account_id=${encodeURIComponent(accountId)}` : ''
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return this.request<{ groups: any[]; total: number }>(`/contact-groups${qs}`)
  }

  async createContactGroup(data: {
    name: string
    emoji?: string
    description?: string
    members: { name: string; email: string }[]
    virtual_meeting?: boolean
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  }): Promise<{ group: any; message: string }> {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return this.request<{ group: any; message: string }>('/contact-groups', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  async updateContactGroup(id: string, data: any): Promise<{ group: any; message: string }> {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return this.request<{ group: any; message: string }>(`/contact-groups/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  }

  async deleteContactGroup(id: string): Promise<{ message: string }> {
    return this.request<{ message: string }>(`/contact-groups/${id}`, {
      method: 'DELETE',
    })
  }

  async recordContactGroupUsage(id: string): Promise<{ group: Record<string, unknown> }> {
    return this.request<{ group: Record<string, unknown> }>(`/contact-groups/${id}/use`, {
      method: 'POST',
    })
  }

  // Compose Email (Story 5-4)
  async composeEmail(
    to: string,
    subject: string,
    instructions: string,
    useHistory: boolean = true,
    body?: string,
    composeId?: string
  ): Promise<ComposeEmailResponse> {
    const payload: Record<string, unknown> = {
      to,
      subject,
      instructions,
      use_history: useHistory,
    }
    if (body) payload.body = body
    if (composeId) payload.compose_id = composeId
    return this.request<ComposeEmailResponse>(
      '/emails/compose',
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
      180000 // 3 minutes timeout for AI generation
    )
  }

  // Suggest a short subject line from generated body text. Timeout matches
  // refineText's post-PR-#743 budget — the auto-call fires right after
  // refine-text lands so the backend container is warm, but the subject LLM
  // call itself can still take 20–40 s on cold starts (audit 2026-05-19
  // round-2 saw ERR_ABORTED at the legacy 30 s ceiling, leaving the Objet
  // input empty and the Envoyer button disabled).
  async suggestSubject(body: string, recipient?: string): Promise<{ success: boolean; subject: string }> {
    return this.request<{ success: boolean; subject: string }>(
      '/compose/suggest-subject',
      {
        method: 'POST',
        body: JSON.stringify({ body, ...(recipient && { recipient }) }),
      },
      90000
    )
  }

  // ============================================================================
  // CALENDAR METHODS
  // ============================================================================

  // Check calendar access status (no Google API call, just token scope check)
  async getCalendarStatus(accountId?: string): Promise<CalendarStatusResponse> {
    const params = accountId ? `?account_id=${encodeURIComponent(accountId)}` : ''
    return this.request<CalendarStatusResponse>(`/calendar/status${params}`)
  }

  async getCalendarBookingLink(): Promise<{ booking_url: string | null; provider?: string; needs_scope?: boolean; unsupported?: boolean; message?: string }> {
    return this.request('/calendar/booking-link')
  }

  async createCalendarBookingLink(title?: string, durationMinutes?: number): Promise<{ booking_url: string | null; needs_scope?: boolean; message?: string }> {
    return this.request('/calendar/booking-link', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: title ?? i18n.t('common:booking_default_title'), duration_minutes: durationMinutes ?? 30 }),
    })
  }

  // Get calendar events
  async getCalendarEvents(
    start?: string,
    end?: string,
    calendarId?: string,
    accountId?: string,
    limit?: number,
    calendarIds?: string[]
  ): Promise<CalendarEventsResponse> {
    const params = new URLSearchParams()
    if (start) params.append('start', start)
    if (end) params.append('end', end)
    if (calendarId) params.append('calendar_id', calendarId)
    // calendar_ids (plural) tells the backend to fetch + merge events from
    // every listed calendar — used by the calendar view so non-primary
    // calendars (holidays, shared calendars) can be filtered via toggles.
    if (calendarIds && calendarIds.length > 0) {
      params.append('calendar_ids', calendarIds.join(','))
    }
    if (accountId) params.append('account_id', accountId)
    if (limit) params.append('limit', limit.toString())
    // Cache-bust: prevent browser HTTP cache from serving stale 400 responses
    params.append('_t', String(Date.now()))

    const queryString = params.toString()
    return this.request<CalendarEventsResponse>(
      `/calendar/events${queryString ? '?' + queryString : ''}`
    )
  }

  // Get single calendar event
  async getCalendarEvent(eventId: string, calendarId?: string, accountId?: string): Promise<CalendarEventResponse> {
    const params = new URLSearchParams()
    if (calendarId) params.append('calendar_id', calendarId)
    if (accountId) params.append('account_id', accountId)

    const queryString = params.toString()
    return this.request<CalendarEventResponse>(
      `/calendar/events/${encodeURIComponent(eventId)}${queryString ? '?' + queryString : ''}`
    )
  }

  // Get today's events
  async getTodayEvents(accountId?: string): Promise<CalendarEventsResponse> {
    const params = accountId ? `?account_id=${encodeURIComponent(accountId)}` : ''
    return this.request<CalendarEventsResponse>(`/calendar/today${params}`)
  }

  // Get upcoming events
  // BUG-Y007 mitigation: first cold call is ~2.4s (backend warms its Google
  // Calendar / Outlook client + DB). Frontend keeps a 30s in-flight de-dup
  // map so the meeting reminder hook + the calendar sidebar don't both
  // launch the cold call back-to-back. Same pattern as useContactGroups.
  async getUpcomingEvents(hours?: number, limit?: number, accountId?: string): Promise<CalendarEventsResponse> {
    const params = new URLSearchParams()
    if (hours) params.append('hours', hours.toString())
    if (limit) params.append('limit', limit.toString())
    if (accountId) params.append('account_id', accountId)

    const queryString = params.toString()
    const path = `/calendar/upcoming${queryString ? '?' + queryString : ''}`
    const dedupKey = `upcoming|${queryString}`
    const pending = _apiInflight.get(dedupKey) as Promise<CalendarEventsResponse> | undefined
    if (pending) return pending
    const fresh = this.request<CalendarEventsResponse>(path).finally(() => {
      _apiInflight.delete(dedupKey)
    })
    _apiInflight.set(dedupKey, fresh)
    return fresh
  }

  // Get holidays for a timezone (Google Calendar, TZ2 legacy)
  async getHolidays(
    timezone: string,
    start?: string,
    end?: string,
  ): Promise<{ holidays: { id: string; title: string; date: string; isAllDay: boolean }[]; timezone: string }> {
    const params = new URLSearchParams()
    params.append('timezone', timezone)
    if (start) params.append('start', start)
    if (end) params.append('end', end)
    return this.request(`/calendar/holidays?${params.toString()}`)
  }

  // Get provincial/regional public holidays via Nager.Date (no OAuth needed)
  async getPublicHolidays(
    opts: { timezone?: string; country?: string; region?: string },
    start?: string,
    end?: string,
  ): Promise<{ holidays: { id: string; title: string; date: string }[]; timezone: string }> {
    const params = new URLSearchParams()
    if (opts.timezone) params.append('timezone', opts.timezone)
    if (opts.country) params.append('country', opts.country)
    if (opts.region) params.append('region', opts.region)
    if (start) params.append('start', start)
    if (end) params.append('end', end)
    return this.request(`/calendar/public-holidays?${params.toString()}`)
  }

  // Detect user's precise timezone/province via IP geolocation (ip-api.com, no auth)
  async detectRegion(): Promise<{ detected: boolean; timezone: string | null; country?: string; region?: string; regionName?: string }> {
    return this.request('/calendar/detect-region')
  }

  // Monthly recap
  async getMonthlyRecap(month?: string): Promise<MonthlyRecap> {
    const params = month ? `?month=${encodeURIComponent(month)}` : ''
    return this.request<MonthlyRecap>(`/recap${params}`)
  }

  async getInboxStats(): Promise<InboxStats> {
    return this.request<InboxStats>('/emails/inbox-stats')
  }

  async bulkCleanup(actions: CleanupAction[]): Promise<CleanupResult> {
    return this.request<CleanupResult>('/emails/bulk-cleanup', {
      method: 'POST',
      body: JSON.stringify({ actions }),
    })
  }

  // ============================================================================
  // ADMIN DASHBOARD
  // ============================================================================

  async adminAggregate(period: string = '30d'): Promise<AdminAggregate> {
    return this.request<AdminAggregate>(`/admin/aggregate?period=${encodeURIComponent(period)}`)
  }

  async adminUsers(params: {
    page?: number
    page_size?: number
    sort_by?: string
    sort_dir?: string
    search?: string
    period?: string
  } = {}): Promise<AdminUsersResponse> {
    const sp = new URLSearchParams()
    if (params.page) sp.set('page', String(params.page))
    if (params.page_size) sp.set('page_size', String(params.page_size))
    if (params.sort_by) sp.set('sort_by', params.sort_by)
    if (params.sort_dir) sp.set('sort_dir', params.sort_dir)
    if (params.search) sp.set('search', params.search)
    if (params.period) sp.set('period', params.period)
    const q = sp.toString()
    return this.request<AdminUsersResponse>(`/admin/users${q ? `?${q}` : ''}`)
  }

  async adminUserDetail(email: string, days: number = 30): Promise<AdminUserDetail> {
    return this.request<AdminUserDetail>(
      `/admin/users/${encodeURIComponent(email)}/detail?days=${days}`
    )
  }

  async adminExport(period: string = '30d', search?: string): Promise<Blob> {
    const sp = new URLSearchParams()
    sp.set('period', period)
    if (search) sp.set('search', search)
    const headers = await getAuthHeaders()
    const resp = await fetch(`${this.baseUrl}/api/admin/export?${sp.toString()}`, { headers })
    if (!resp.ok) throw new Error(`Export failed: ${resp.status}`)
    return resp.blob()
  }
}

export interface WizardConnectionParams {
  imap_host: string
  imap_port: number
  imap_username: string
  imap_password: string
  imap_use_ssl: boolean
  smtp_host: string
  smtp_port: number
  smtp_username: string
  smtp_password: string
  smtp_use_tls: boolean
  smtp_use_ssl: boolean
}

export interface WizardConnectionResult {
  success: boolean
  imap: {
    success: boolean
    response_time_ms?: number
    error?: string
  }
  smtp: {
    success: boolean
    response_time_ms?: number
    error?: string
  }
}

export interface LLMConnectionParams {
  provider: 'claude' | 'ollama' | 'claude-code'
  api_key?: string
  ollama_url?: string
  model: string
}

export interface LLMConnectionResult {
  success: boolean
  provider?: string
  model?: string
  response_time_ms?: number
  error?: string
}

export interface LLMSettingsResponse {
  success: boolean
  llm: {
    provider: 'claude' | 'ollama' | 'claude-code'
    model: string
    ollama_url: string
    has_api_key: boolean
  }
}

export interface SaveLLMSettingsParams {
  provider: 'claude' | 'ollama' | 'claude-code'
  api_key?: string
  ollama_url?: string
  model: string
}

export interface SaveLLMSettingsResponse {
  success: boolean
  message: string
  requires_restart: boolean
}

export interface StyleAnalysisParams {
  // OAuth mode - utilise le provider configuré
  use_oauth?: boolean
  // IMAP mode - requis si use_oauth n'est pas défini
  imap_host?: string
  imap_port?: number
  imap_username?: string
  imap_password?: string
  imap_use_ssl?: boolean
  max_emails?: number
  timeout_sec?: number
}

export interface StyleProfile {
  signature: {
    name: string | null
    title: string | null
    company: string | null
  } | null
  tone: 'formal' | 'informal' | 'neutral' | 'unknown'
  formality_level: 'vous' | 'tu' | 'mixed' | 'unknown'
  avg_response_length: number
  greeting_patterns: string[]
  closing_patterns: string[]
}

export interface StyleAnalysisResult {
  success: boolean
  emails_analyzed?: number
  profile?: StyleProfile
  warning?: string
  error?: string
}

export interface SaveStyleParams {
  profile: StyleProfile
  confirmed: boolean
}

export interface SaveSettingsParams {
  operation_mode?: 'magic' | 'controlled' | 'manual'
  polling_interval_minutes?: number
  notifications_enabled?: boolean
  working_hours_only?: boolean
  working_hours_start?: string
  working_hours_end?: string
}

export interface EnvConfigResponse {
  success: boolean
  has_env: boolean
  message?: string
  error?: string
  email_provider_type?: string
  email?: {
    provider?: string
    configured?: boolean
    // IMAP/SMTP fields
    imap_host?: string
    imap_port?: number
    imap_username?: string
    has_imap_password?: boolean
    imap_use_ssl?: boolean
    smtp_host?: string
    smtp_port?: number
    smtp_username?: string
    has_smtp_password?: boolean
    smtp_use_tls?: boolean
    smtp_use_ssl?: boolean
    // Gmail OAuth fields
    has_client_id?: boolean
    has_client_secret?: boolean
    has_refresh_token?: boolean
    // Outlook OAuth fields
    has_tenant_id?: boolean
    user_id?: string
  }
  llm?: {
    provider?: string
    model?: string
    has_api_key?: boolean
    ollama_url?: string
  }
}

export interface DiscordMessage {
  id: string
  channel: 'discord'
  sender_id: string
  sender_name: string | null
  content: string
  received_at: string
  conversation_id: string | null
  has_attachments: boolean
  channel_id: string
  channel_name: string | null
  guild_id: string | null
  guild_name: string | null
  message_url: string | null
  responded: boolean
  response_content: string | null
}

export interface DiscordMessagesResponse {
  count: number
  messages: DiscordMessage[]
}

export interface DiscordSuggestion {
  content: string
  confidence: number
  agent_id: string
  category?: string
}

export interface DiscordSuggestResponse {
  message_id: string
  suggestion: DiscordSuggestion
  error?: string
}

export interface DiscordConfig {
  configured: boolean
  webhook_url_set: boolean
  bot_name: string
  avatar_url_set: boolean
}

export interface DiscordStats {
  total_messages: number
  pending_messages: number
  responded_messages: number
  open_tickets: number
}

export interface TelegramMessage {
  id: string
  channel: 'telegram'
  sender_id: string
  sender_name: string | null
  content: string
  received_at: string
  conversation_id: string | null
  has_attachments: boolean
  chat_id: string
  chat_type: string | null
  responded: boolean
  response_content: string | null
}

export interface TelegramMessagesResponse {
  count: number
  messages: TelegramMessage[]
}

export interface TelegramSuggestion {
  content: string
  confidence: number
  agent_id: string
  category?: string
}

export interface TelegramSuggestResponse {
  message_id: string
  suggestion: TelegramSuggestion
  error?: string
}

export interface TelegramConfig {
  configured: boolean
  bot_token_set: boolean
  bot_name: string | null
  notifications_chat_id_set: boolean
  support_chat_id_set: boolean
}

export interface TelegramStats {
  total_tickets: number
  open_tickets: number
  resolved_tickets: number
  total_messages: number
  configured: boolean
  enabled: boolean
}

// Folder types
export interface EmailFolder {
  id: string
  name: string
  display_name: string
  type: 'system' | 'user'
  parent_id: string | null
  unread_count: number
  total_count: number
}

export interface FoldersResponse {
  provider: string
  count: number
  folders: EmailFolder[]
}

// Calendar types (Issue #26)
export interface CalendarInfo {
  id: string
  name: string
  primary: boolean
  access_role?: string
  can_edit?: boolean
  background_color?: string
  color?: string
}

export interface CreateCalendarEventRequest {
  title: string
  start_time: string
  end_time: string
  description?: string
  all_day?: boolean
  location?: string
  attendees?: string[]
  reminders?: number[]
  recurrence?: string
  conference?: boolean
  calendar_id?: string
  account_id?: string
  color_id?: string
}

export interface Followup {
  id: string
  email_id: string
  account_id: string
  title: string
  description?: string
  due_date: string
  status: 'pending' | 'completed' | 'snoozed' | 'cancelled'
  created_at?: string
  completed_at?: string
  snoozed_until?: string
  snooze_count?: number
  calendar_event_id?: string
  sync_to_calendar?: boolean
  email_subject?: string
  email_sender?: string
  auto_created?: boolean
  ai_reason?: string
  is_overdue?: boolean
  is_snoozed?: boolean
}

export interface FollowupsResponse {
  count: number
  followups: Followup[]
}

export interface CreateFollowupRequest {
  email_id: string
  title: string
  due_date: string
  description?: string
  sync_to_calendar?: boolean
  email_subject?: string
  email_sender?: string
  account_id?: string
}

export interface UpdateFollowupRequest {
  title?: string
  description?: string
  due_date?: string
  status?: string
  sync_to_calendar?: boolean
  action?: 'complete' | 'snooze' | 'cancel' | 'reopen'
  snooze_until?: string
}

// AI Commitment Suggestion types (Issue #26 — Follow-up Suggestions)
export interface CommitmentSuggestion {
  id: string
  email_id: string
  account_id: string
  description: string
  deadline?: string | null
  status: 'pending' | 'accepted' | 'rejected'
  created_at?: string
  email_subject?: string
  email_sender?: string
  draft_body_preview?: string
}

export interface SuggestionsResponse {
  count: number
  suggestions: CommitmentSuggestion[]
}

// Compose Email types (Story 5-4)
export interface ComposeEmailRequest {
  to: string
  subject: string
  instructions: string
  use_history?: boolean
}

export interface ComposeEmailResponse {
  success: boolean
  final_draft: {
    content: string
    confidence: number
    status: string
  }
  orchestration: {
    status: string
    total_duration_ms: number
    iteration_count: number
    best_score: number
    was_validated: boolean
  }
  has_context: boolean
}

// Generate Draft response (for manual draft generation)
// status="processing" means async (202): draft will arrive via WebSocket
// status="existing" means a cached draft was returned immediately
export interface GenerateDraftResponse {
  success: boolean
  draft_id?: string
  email_id: string
  task_id?: string
  classification?: string
  priority?: number
  status: string
  draft_preview?: string
  instructions?: string
  message?: string
}

// Regenerate Draft types (Story 6-4)
export interface RegenerateDraftResponse {
  success: boolean
  draft_id: string
  regenerated_body: string
  previous_body: string
  instructions_used: string
  pipeline_details: {
    draft_v1: string
    critique: {
      is_valid: boolean
      feedback: string
    }
    was_corrected: boolean
  }
}

// Draft Version for history tracking (Story 6-4)
export interface DraftVersion {
  id: string
  body: string
  instructions: string
  timestamp: Date
  pipelineDetails?: {
    draft_v1: string
    critique: {
      is_valid: boolean
      feedback: string
    }
    was_corrected: boolean
  }
}

// Admin Dashboard types
export interface AdminUser {
  email: string
  registered_at: string
  last_active: string | null
  active_days: number
  total_actions: number
  compose_ai: number
  emails_sent: number
  cost_usd: number
  revenue_usd: number
  margin_usd: number
  churn_risk: number
  sparkline: number[]
}

export interface AdminAggregate {
  total_users: number
  active_users: number
  active_users_change: number
  total_cost_usd: number
  cost_change: number
  total_revenue_usd: number
  revenue_change: number
  margin_usd: number
  margin_change: number
}

export interface AdminUsersResponse {
  users: AdminUser[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface AdminUserDetail {
  email: string
  daily: { date: string; actions: number; cost: number }[]
  actions_breakdown: Record<string, number>
  ai_satisfaction: { avg_score: number | null; count: number }
}

let _apiClient: ApiClient | null = null

export function getApiClient(baseUrl?: string): ApiClient {
  if (!_apiClient || baseUrl) {
    _apiClient = new ApiClient(baseUrl)
  }
  return _apiClient
}

// Singleton instance for direct import
export const apiClient = new ApiClient()

export function resetApiClient(): void {
  _apiClient = null
  _apiInflight.clear()
}

// ── Knowledge Entries ────────────────────────────────────────────────────────

export interface KnowledgeEntry {
  id: string
  account_id: string
  title: string
  content: string
  category: string
  source: string
  created_at: string | null
  updated_at: string | null
}

export function getKnowledgeEntries(category?: string): Promise<KnowledgeEntry[]> {
  const qs = category ? `?category=${category}` : ''
  return apiClient.request<KnowledgeEntry[]>(`/knowledge/entries${qs}`)
}

export function createKnowledgeEntry(data: { title: string; content: string; category?: string }): Promise<KnowledgeEntry> {
  return apiClient.request<KnowledgeEntry>('/knowledge/entries', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export function updateKnowledgeEntry(id: string, data: Partial<{ title: string; content: string; category: string }>): Promise<KnowledgeEntry> {
  return apiClient.request<KnowledgeEntry>(`/knowledge/entries/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
}

export function deleteKnowledgeEntry(id: string): Promise<{ ok: boolean }> {
  return apiClient.request<{ ok: boolean }>(`/knowledge/entries/${id}`, {
    method: 'DELETE',
  })
}

export function importKnowledgeEntries(): Promise<{ ok: boolean; created: number }> {
  return apiClient.request<{ ok: boolean; created: number }>('/knowledge/entries/import', {
    method: 'POST',
  })
}

export function getKnowledgeCategories(): Promise<Record<string, number>> {
  return apiClient.request<Record<string, number>>('/knowledge/categories')
}

// ── Blocked Senders ──────────────────────────────────────────────────────────

export function blockSender(email: string): Promise<{ success: boolean; blocked_senders: string[] }> {
  return apiClient.request<{ success: boolean; blocked_senders: string[] }>('/senders/block', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
}

export function unblockSender(email: string): Promise<{ success: boolean; blocked_senders: string[] }> {
  return apiClient.request<{ success: boolean; blocked_senders: string[] }>('/senders/unblock', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
}

export function getBlockedSenders(): Promise<{ blocked_senders: string[]; blocked_domains: string[] }> {
  return apiClient.request<{ blocked_senders: string[]; blocked_domains: string[] }>('/senders/blocked')
}

// ── Hide Contact from Autocomplete ───────────────────────────────────────────

export function hideContact(email: string): Promise<{ success: boolean; email: string }> {
  return apiClient.request<{ success: boolean; email: string }>('/contacts/hide', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
}

export function unhideContact(email: string): Promise<{ success: boolean; email: string }> {
  return apiClient.request<{ success: boolean; email: string }>('/contacts/unhide', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
}

// ── Spammed Senders (spam learning) ─────────────────────────────────────────

export function getSpammedSenders(): Promise<{ spammed_senders: string[]; spammed_domains: string[] }> {
  return apiClient.request<{ spammed_senders: string[]; spammed_domains: string[] }>('/senders/spammed')
}

export function unspamSender(email: string): Promise<{ success: boolean; spammed_senders: string[]; spammed_domains: string[] }> {
  return apiClient.request<{ success: boolean; spammed_senders: string[]; spammed_domains: string[] }>('/senders/unspam', {
    method: 'POST',
    body: JSON.stringify({ email }),
  })
}

export function unspamDomain(domain: string): Promise<{ success: boolean; spammed_senders: string[]; spammed_domains: string[] }> {
  return apiClient.request<{ success: boolean; spammed_senders: string[]; spammed_domains: string[] }>('/senders/unspam', {
    method: 'POST',
    body: JSON.stringify({ domain }),
  })
}

// ── Bulk-action queue ────────────────────────────────────────────────────────
// Mirrors `app/api/routes_bulk_jobs.py`. The BulkActionsPanel hook talks
// only through these helpers — no other module should hand-craft URLs to
// /api/bulk-jobs/*.

import type {
  BulkJob,
  BulkJobItem,
  BulkJobItemState,
  BulkJobStatus,
} from '../types/bulkJob'

export interface BulkJobsListResponse {
  jobs: BulkJob[]
}

export interface BulkJobItemsResponse {
  job_id: string
  state: BulkJobItemState
  items: BulkJobItem[]
}

export function listBulkJobs(params?: {
  status?: BulkJobStatus
  since?: string
  limit?: number
}): Promise<BulkJobsListResponse> {
  const search = new URLSearchParams()
  if (params?.status) search.set('status', params.status)
  if (params?.since) search.set('since', params.since)
  if (params?.limit) search.set('limit', String(params.limit))
  const qs = search.toString()
  return apiClient.request<BulkJobsListResponse>(
    qs ? `/bulk-jobs?${qs}` : '/bulk-jobs'
  )
}

export function getBulkJob(jobId: string): Promise<{ job: BulkJob }> {
  return apiClient.request<{ job: BulkJob }>(`/bulk-jobs/${jobId}`)
}

export function listBulkJobItems(
  jobId: string,
  state: BulkJobItemState = 'failed',
  limit = 100,
): Promise<BulkJobItemsResponse> {
  const qs = new URLSearchParams({ state, limit: String(limit) }).toString()
  return apiClient.request<BulkJobItemsResponse>(
    `/bulk-jobs/${jobId}/items?${qs}`
  )
}

export function pauseBulkJob(jobId: string): Promise<{ job: BulkJob }> {
  return apiClient.request<{ job: BulkJob }>(`/bulk-jobs/${jobId}/pause`, {
    method: 'POST',
  })
}

export function resumeBulkJob(jobId: string): Promise<{ job: BulkJob }> {
  return apiClient.request<{ job: BulkJob }>(`/bulk-jobs/${jobId}/resume`, {
    method: 'POST',
  })
}

export function cancelBulkJob(jobId: string): Promise<{ job: BulkJob }> {
  return apiClient.request<{ job: BulkJob }>(`/bulk-jobs/${jobId}/cancel`, {
    method: 'POST',
  })
}

export function retryBulkJobFailed(
  jobId: string,
): Promise<{ job: BulkJob; requeued: number }> {
  return apiClient.request<{ job: BulkJob; requeued: number }>(
    `/bulk-jobs/${jobId}/retry-failed`,
    { method: 'POST' },
  )
}

// Dismiss (permanently remove) a terminal job. The webview/AV may drop
// DELETE — apiClient.request transparently falls back to POST +
// X-HTTP-Method-Override on a network error.
export function deleteBulkJob(jobId: string): Promise<{ deleted: boolean }> {
  return apiClient.request<{ deleted: boolean }>(`/bulk-jobs/${jobId}`, {
    method: 'DELETE',
  })
}

// ── Quick Steps ──────────────────────────────────────────────────────────────
// Mirrors app/api/quicksteps.py. All execution is deterministic on the
// backend — no LLM calls. The same idempotency-key pattern as bulk jobs
// dedupes accidental double-clicks within a 60s window.

import type {
  AutoBadgeMap,
  QuickStep,
  QuickStepExecutionReport,
  TriggerCondition,
} from '../types/quickStep'

export interface QuickStepsListResponse {
  quick_steps: QuickStep[]
  // Backend sets warning='transient_load_failure' when load_quick_steps
  // threw and the controller degraded the response to an empty list (see
  // app/api/quicksteps.py:53). The UI must NOT render the Quick-Start
  // template empty-state in that case — the user's saved rules are still
  // on disk, the read just failed transiently (e.g. MemoryError under
  // request burst). Surface an error+retry instead.
  warning?: string
}

export function listQuickSteps(): Promise<QuickStepsListResponse> {
  return apiClient.request<QuickStepsListResponse>('/quicksteps')
}

/**
 * Fetch the ⚡ Auto-badge map for a slice of inbox email IDs. The backend
 * intersects the audit log (source=auto, success=true) with the user's
 * current Quick Steps where `showAutoBadge=true`. Empty `ids` short-
 * circuits to an empty map without a round-trip.
 *
 * The endpoint caps at 200 IDs per call ; pass page-sized slices.
 */
export interface AutoBadgesResponse {
  badges: AutoBadgeMap
  warning?: string
}

export function fetchAutoBadges(ids: string[]): Promise<AutoBadgesResponse> {
  if (!ids.length) return Promise.resolve({ badges: {} })
  const q = encodeURIComponent(ids.join(','))
  return apiClient.request<AutoBadgesResponse>(`/quicksteps/auto-badges?ids=${q}`)
}

export function createQuickStep(step: QuickStep): Promise<QuickStep> {
  return apiClient.request<QuickStep>('/quicksteps', {
    method: 'POST',
    body: JSON.stringify(step),
  })
}

export function updateQuickStep(
  stepId: string,
  patch: Partial<QuickStep>,
): Promise<QuickStep> {
  return apiClient.request<QuickStep>(
    `/quicksteps/${encodeURIComponent(stepId)}`,
    {
      method: 'PATCH',
      body: JSON.stringify(patch),
    },
  )
}

export function deleteQuickStep(stepId: string): Promise<{ success: boolean }> {
  return apiClient.request<{ success: boolean }>(
    `/quicksteps/${encodeURIComponent(stepId)}`,
    { method: 'DELETE' },
  )
}

export function reorderQuickSteps(ids: string[]): Promise<QuickStepsListResponse> {
  return apiClient.request<QuickStepsListResponse>('/quicksteps/order', {
    method: 'PUT',
    body: JSON.stringify({ ids }),
  })
}

export interface QuickStepDryRunResult {
  examined: number
  matched: number
  samples: Array<{ subject: string; sender: string; date: string | null }>
}

export function dryRunQuickStep(
  triggers: TriggerCondition[],
  triggerOperator: 'AND' | 'OR',
): Promise<QuickStepDryRunResult> {
  return apiClient.request<QuickStepDryRunResult>('/quicksteps/dry-run', {
    method: 'POST',
    body: JSON.stringify({ triggers, triggerOperator }),
  })
}

export function executeQuickStep(
  stepId: string,
  emailId: string,
  idempotencyKey?: string,
): Promise<QuickStepExecutionReport> {
  const headers: Record<string, string> = {}
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey
  return apiClient.request<QuickStepExecutionReport>(
    `/quicksteps/${encodeURIComponent(stepId)}/execute`,
    {
      method: 'POST',
      headers,
      body: JSON.stringify({ email_id: emailId }),
    },
  )
}

export interface MeetingRsvpResult {
  ok: boolean
  event_id?: string
  response?: string
  error?: string
}

export function rsvpMeeting(
  emailId: string,
  response: 'accepted' | 'declined' | 'tentative',
  accountId?: string,
): Promise<MeetingRsvpResult> {
  return apiClient.request<MeetingRsvpResult>('/calendar/rsvp', {
    method: 'POST',
    body: JSON.stringify({ email_id: emailId, response, account_id: accountId }),
  })
}

export function fetchPinnedEmailIds(): Promise<{ pinned_ids: string[] }> {
  return apiClient.request<{ pinned_ids: string[] }>('/emails/pinned')
}

// Audit Cluster E (2026-05-11) U-10: the backend toggle response no longer
// includes the full pinned_ids array (unbounded payload). Mount-time list
// still comes from fetchPinnedEmailIds. Toggle responses are slim.
export function pinEmail(emailId: string): Promise<{ ok: boolean; pinned: boolean }> {
  return apiClient.request<{ ok: boolean; pinned: boolean }>(
    `/emails/${encodeURIComponent(emailId)}/pin`,
    { method: 'POST' },
  )
}

export function unpinEmail(emailId: string): Promise<{ ok: boolean; pinned: boolean }> {
  return apiClient.request<{ ok: boolean; pinned: boolean }>(
    `/emails/${encodeURIComponent(emailId)}/pin`,
    { method: 'DELETE' },
  )
}
