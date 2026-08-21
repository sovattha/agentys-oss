/**
 * Quick Step types — mirror the Python schema in app/quicksteps/schema.py.
 *
 * Keep these in sync with the backend grammar; if you add an action type
 * here you MUST add a handler in app/quicksteps/registry.py and an entry in
 * the validator's _ALLOWED_ACTION_TYPES set.
 */
import i18n from '../i18n'

export type QuickStepActionType =
  | 'archive'
  | 'unarchive'
  | 'delete'
  | 'mark_read'
  | 'move_to_spam'
  | 'pin'
  | 'reply_template'
  | 'forward'
  | 'rsvp_meeting'
  | 'create_snoozed_followup_draft'
  | 'mark_with_emoji'
  | 'apply_label'
  | 'create_reminder'
  | 'create_calendar_event'

export type TriggerConditionType =
  | 'sender'
  | 'sender_domain'
  | 'recipient'
  | 'email_text'
  | 'has_attachment'
  | 'has_deadline_detected'
  | 'has_label'
  | 'is_read'
  | 'calendar_invite'
  | 'email_older_than_days'
  | 'no_reply_after_days'
  | 'is_new_thread'
  | 'thread_has_user_reply'
  | 'previously_auto_actioned_by'
  | 'has_emoji_marker'

/**
 * Polymorphic per-condition match operator. Present only on the five
 * "operator-bearing" condition types; the value vocabulary is
 * type-specific (see TRIGGER_MATCH_MODES). Mirrors _MATCH_MODE_VALUES in
 * app/quicksteps/schema.py.
 *   sender / sender_domain / recipient → is | contains | matches
 *   email_text                         → anywhere | subject | body
 *   calendar_invite                    → any | free
 */
export type TriggerMatchMode =
  | 'is'
  | 'contains'
  | 'matches'
  | 'anywhere'
  | 'subject'
  | 'body'
  | 'any'
  | 'free'

/**
 * Allowed `match_mode` values per condition type, in display order. An
 * empty list means the type takes no match_mode. Keep in sync with
 * `_MATCH_MODE_VALUES` in app/quicksteps/schema.py.
 */
export const TRIGGER_MATCH_MODES: Record<TriggerConditionType, TriggerMatchMode[]> = {
  sender: ['is', 'contains', 'matches'],
  sender_domain: ['is', 'contains', 'matches'],
  recipient: ['is', 'contains', 'matches'],
  email_text: ['anywhere', 'subject', 'body'],
  calendar_invite: ['any', 'free'],
  has_attachment: [],
  has_deadline_detected: [],
  has_label: [],
  is_read: [],
  email_older_than_days: [],
  no_reply_after_days: [],
  is_new_thread: [],
  thread_has_user_reply: [],
  previously_auto_actioned_by: [],
  has_emoji_marker: [],
}

/** True iff this condition type carries a `match_mode`. */
export function triggerTypeHasMatchMode(type: TriggerConditionType): boolean {
  return TRIGGER_MATCH_MODES[type].length > 0
}

/**
 * Default `match_mode` for a freshly-picked condition type — the first
 * (most common) entry in its allowed set, or undefined for types that
 * take no match_mode.
 */
export function defaultTriggerMatchMode(
  type: TriggerConditionType,
): TriggerMatchMode | undefined {
  const modes = TRIGGER_MATCH_MODES[type]
  return modes.length > 0 ? modes[0] : undefined
}

/**
 * Default ``value`` string for a freshly-picked condition type. Numeric
 * conditions get a sensible day count so the user only has to tweak; boolean
 * conditions get "true" so the badge renders correctly until the user
 * touches the row.
 */
export function defaultTriggerValue(type: TriggerConditionType): string {
  switch (type) {
    case 'calendar_invite':
    case 'has_attachment':
    case 'is_read':
    case 'is_new_thread':
    case 'thread_has_user_reply':
    case 'has_deadline_detected':
    case 'has_emoji_marker':
      return 'true'
    case 'email_older_than_days':
      return '7'
    case 'no_reply_after_days':
      return '3'
    default:
      return ''
  }
}

export interface TriggerCondition {
  type: TriggerConditionType
  /**
   * Polymorphic match operator — present only on the five operator-
   * bearing types (sender, sender_domain, recipient, email_text,
   * calendar_invite). See `TRIGGER_MATCH_MODES`.
   */
  match_mode?: TriggerMatchMode
  value: string
  negate?: boolean
}

/**
 * Legacy v1 condition types (pre-2026-05-14) folded into a
 * `{type, match_mode}` pair. Mirrors `_LEGACY_CONDITION_ALIASES` in
 * app/quicksteps/schema.py.
 */
const LEGACY_CONDITION_ALIASES: Record<string, [TriggerConditionType, TriggerMatchMode]> = {
  sender_regex: ['sender', 'matches'],
  sender_domain_regex: ['sender_domain', 'matches'],
  subject_keyword: ['email_text', 'subject'],
  content_keyword: ['email_text', 'body'],
  subject_or_body_keyword: ['email_text', 'anywhere'],
  is_calendar_invite: ['calendar_invite', 'any'],
  available_for_invite: ['calendar_invite', 'free'],
}

/** Legacy types that keep their key but gain an implicit `match_mode`. */
const LEGACY_IMPLICIT_MATCH_MODE: Record<string, TriggerMatchMode> = {
  sender: 'is',
  sender_domain: 'is',
  recipient: 'contains',
}

/**
 * Upgrade a pre-`match_mode` trigger condition to the current shape.
 * Total + idempotent — mirrors `migrate_legacy_condition` in
 * app/quicksteps/schema.py. The backend already migrates on read, so
 * this is defense-in-depth for optimistic updates, cached responses, or
 * persisted draft state that predates the v2 refactor.
 */
export function migrateLegacyCondition(raw: TriggerCondition): TriggerCondition {
  if (!raw || typeof raw !== 'object') return raw
  const out: TriggerCondition = { ...raw }
  const legacyType = out.type as string
  const alias = LEGACY_CONDITION_ALIASES[legacyType]
  if (alias) {
    out.type = alias[0]
    if (out.match_mode === undefined) out.match_mode = alias[1]
  } else if (LEGACY_IMPLICIT_MATCH_MODE[legacyType] && out.match_mode === undefined) {
    out.match_mode = LEGACY_IMPLICIT_MATCH_MODE[legacyType]
  }
  // calendar_invite is a badge condition — it needs a truthy value so the
  // backend matcher's empty-value guard doesn't drop it.
  if (out.type === 'calendar_invite' && !out.value) out.value = 'true'
  return out
}

/**
 * Per-action guard. When present and non-empty, the engine evaluates these
 * conditions against the email and SKIPS the action if they don't match.
 * Reuses the same condition vocabulary as the step-level auto-trigger so
 * users only ever learn one mental model.
 *
 * IMPORTANT: ``triggers`` and ``operator`` are *both* required at the type
 * level. Do NOT make them optional — the editor and chain preview read
 * ``guard.triggers.length`` directly. Any value coming from the backend
 * MUST go through ``normalizeQuickStep`` first, which fills in safe
 * defaults if the persisted record is partial.
 */
export interface ActionGuard {
  triggers: TriggerCondition[]
  operator: 'AND' | 'OR'
}

export interface MarkReadPayload {
  value: boolean
}

export interface ReplyTemplatePayload {
  body: string
  replyAll: boolean
  includeQuoted: boolean
  snippet_id?: string
}

export interface ForwardPayload {
  to: string[]
  to_groups?: string[]
  subject_prefix?: string
  body?: string
}

export interface RsvpMeetingPayload {
  response: 'accepted' | 'declined' | 'tentative'
}

/**
 * Curated set of emojis the `mark_with_emoji` action accepts. Keep in sync
 * with `_EMOJI_MARKER_WHITELIST` in app/quicksteps/schema.py — the backend
 * validator rejects anything outside this set, so a divergence here means
 * the editor offers a choice that fails on save.
 */
export const QUICK_STEP_EMOJI_WHITELIST = [
  '🔥', '🚨', '⚠️', '⏰',
  '✅', '📌',
  '💰', '💼', '📋', '🎯',
  '⭐', '🤝',
  '📞', '💬',
  '🎉', '🔒', '📊',
  '🔁',
] as const

export type QuickStepEmoji = (typeof QUICK_STEP_EMOJI_WHITELIST)[number]

export interface MarkWithEmojiPayload {
  /**
   * One of `QUICK_STEP_EMOJI_WHITELIST`, or `''` for a text-only marker
   * (the "No emoji" tile). When empty, `text` must be non-empty — the
   * schema/handler reject a marker with neither emoji nor text.
   */
  emoji: QuickStepEmoji | ''
  /** Short companion label (≤24 chars). Optional. */
  text?: string
  /**
   * When true and the email also has `deadline_at`, the marker chip
   * renders the date alongside the emoji+text (e.g. "💰 Stripe · Mar 15")
   * and the standalone clock chip is suppressed on that row.
   */
  include_deadline?: boolean
  /**
   * Optional marker color — a `LABEL_COLORS` member (mirror of
   * `_EMOJI_MARKER_COLOR_WHITELIST` in app/quicksteps/schema.py). Tints the
   * chip background + border + text. Omit for the default monochrome chip.
   */
  color?: string
  /**
   * Render the marker as a chip (pill) — default true. When false the
   * emoji + text render bare, with no background or border.
   */
  chip?: boolean
}

export interface CreateSnoozedFollowupDraftPayload {
  /**
   * Template body for the follow-up draft. Supports two placeholders
   * (no Jinja, no LLM): `{{recipient_name}}` (humanised local-part of the
   * recipient address) and `{{original_subject}}` (the subject of the
   * sent email being followed up on).
   */
  body: string
  /** Days the draft stays snoozed in "Later" before promotion to Drafts. */
  delay_days: number
}

export interface ApplyLabelPayload {
  /**
   * Label name to add to the email. A default-category name
   * (Action/FYI/Noise) replaces the email's category; any other name is
   * added as a custom label — see app/quicksteps/handlers/apply_label.py.
   */
  label: string
}

export interface CreateReminderPayload {
  /**
   * Days before the detected deadline to fire the reminder. 0 = on the
   * deadline day. Validated 0..365 by app/quicksteps/schema.py.
   */
  days_before: number
}

export interface CreateCalendarEventPayload {
  /** Days before the detected deadline to schedule the event. 0..365. */
  days_before: number
  /** Event length in minutes. 1..1440 (24 h). */
  duration_minutes: number
}

export type QuickStepAction =
  | { type: 'archive'; payload?: Record<string, never>; if?: ActionGuard }
  | { type: 'unarchive'; payload?: Record<string, never>; if?: ActionGuard }
  | { type: 'delete'; payload?: Record<string, never>; if?: ActionGuard }
  | { type: 'mark_read'; payload: MarkReadPayload; if?: ActionGuard }
  | { type: 'move_to_spam'; payload?: Record<string, never>; if?: ActionGuard }
  | { type: 'pin'; payload?: Record<string, never>; if?: ActionGuard }
  | { type: 'reply_template'; payload: ReplyTemplatePayload; if?: ActionGuard }
  | { type: 'forward'; payload: ForwardPayload; if?: ActionGuard }
  | { type: 'rsvp_meeting'; payload: RsvpMeetingPayload; if?: ActionGuard }
  | { type: 'create_snoozed_followup_draft'; payload: CreateSnoozedFollowupDraftPayload; if?: ActionGuard }
  | { type: 'mark_with_emoji'; payload: MarkWithEmojiPayload; if?: ActionGuard }
  | { type: 'apply_label'; payload: ApplyLabelPayload; if?: ActionGuard }
  | { type: 'create_reminder'; payload: CreateReminderPayload; if?: ActionGuard }
  | { type: 'create_calendar_event'; payload: CreateCalendarEventPayload; if?: ActionGuard }

export interface QuickStep {
  id: string
  name: string
  /**
   * Optional free-text description shown on the card instead of the
   * auto-generated trigger summary. When non-empty, the card renders
   * this verbatim; when empty/absent, the card falls back to the
   * auto-summary (joined trigger badges). 200-char cap matches the
   * backend validator in app/quicksteps/schema.py.
   */
  description?: string
  icon: string | null
  shortcut: string | null
  actions: QuickStepAction[]
  enabled: boolean
  confirmBeforeRun: boolean
  autoEnabled: boolean
  /**
   * Show a ⚡ Auto badge on emails this rule auto-actioned. Default true so
   * new rules are transparent ; user toggles off per-rule when the badge
   * contradicts intent (e.g. silent label-only rule). Only surfaces in the
   * UI when `autoEnabled=true` — a manual-only rule has no auto-execution
   * to badge.
   */
  showAutoBadge: boolean
  triggerOperator: 'AND' | 'OR'
  triggers: TriggerCondition[]
  /**
   * Which mail flow the auto-trigger evaluates against.
   * - `received` (default): incoming inbox — every legacy step
   * - `sent`: outgoing — pairs with the `create_snoozed_followup_draft`
   *   action to follow up on emails the user sent that got no reply
   */
  firesOn: 'received' | 'sent'
}

/**
 * Map returned by GET /api/quicksteps/auto-badges — one entry per email
 * that was auto-actioned by a rule with `showAutoBadge=true`. Used by the
 * inbox list to render the ⚡ Auto chip.
 */
export interface AutoBadge {
  stepId: string
  stepName: string
  executedAt: string | null
}

export type AutoBadgeMap = Record<string, AutoBadge>

export interface QuickStepActionStatus {
  type: string
  ok: boolean
  error?: string | null
}

export interface QuickStepExecutionReport {
  success: boolean
  step_id: string
  email_id: string
  executed: number
  actions: QuickStepActionStatus[]
  error?: string | null
  idempotent_replay: boolean
}

/**
 * Available template variables — match build_context() in template.py.
 * `token` is the raw value inserted into the body ; `label` is the friendly
 * chip text (French default) ; `labelKey` resolves the translated label.
 */
export const QUICK_STEP_TEMPLATE_VARIABLES = [
  { token: 'sender.firstname', labelKey: 'quicksteps_var_sender_firstname', label: 'Prénom expéditeur' },
  { token: 'sender.lastname', labelKey: 'quicksteps_var_sender_lastname', label: 'Nom expéditeur' },
  { token: 'sender.name', labelKey: 'quicksteps_var_sender_name', label: 'Nom complet expéditeur' },
  { token: 'sender.email', labelKey: 'quicksteps_var_sender_email', label: 'Email expéditeur' },
  { token: 'subject', labelKey: 'quicksteps_var_subject', label: 'Sujet' },
  { token: 'date', labelKey: 'quicksteps_var_date', label: 'Date' },
  { token: 'me.firstname', labelKey: 'quicksteps_var_me_firstname', label: 'Mon prénom' },
  { token: 'me.name', labelKey: 'quicksteps_var_me_name', label: 'Mon nom' },
  { token: 'me.email', labelKey: 'quicksteps_var_me_email', label: 'Mon email' },
] as const

export type QuickStepTemplateVariable = (typeof QUICK_STEP_TEMPLATE_VARIABLES)[number]['token']

export const QUICK_STEP_ACTION_TYPES: readonly QuickStepActionType[] = [
  'archive',
  'unarchive',
  'pin',
  'mark_read',
  'reply_template',
  'forward',
  'move_to_spam',
  'delete',
  'rsvp_meeting',
  'create_snoozed_followup_draft',
  'mark_with_emoji',
  'apply_label',
  'create_reminder',
  'create_calendar_event',
]

/**
 * Localized default body for the follow-up draft action, kept in sync with the
 * backend seed (`_followup_body_html` in app/quicksteps/defaults.py).
 *
 * Authored as editor HTML so the recipient's first name renders as a `{x}`
 * chip and the lines survive the rich editor — the backend `_render_body`
 * resolves the chip and flattens the `<div>`/`<br>` structure to plain text at
 * draft time. The chip *label* is cosmetic (resolved by token, not label) and
 * tracks the `{x}`-menu label per locale.
 */
function followupDraftBodyHtml(
  greeting: string, firstNameLabel: string, line: string, closing: string,
): string {
  const chip =
    `<span class="ar-token" data-ar-token="recipient_first_name" ` +
    `contenteditable="false">${firstNameLabel}</span>`
  return (
    `<div>${greeting} ${chip},</div>` +
    '<div><br></div>' +
    `<div>${line}</div>` +
    '<div><br></div>' +
    `<div>${closing}</div>`
  )
}

export const FOLLOWUP_DRAFT_BODY_BY_LANG: Record<string, string> = {
  fr: followupDraftBodyHtml(
    'Bonjour', 'Prénom du destinataire',
    'Petite relance sur mon dernier email. Faites-moi signe si vous avez besoin de quoi que ce soit de mon côté.',
    'Cordialement,',
  ),
  en: followupDraftBodyHtml(
    'Hi', 'First name',
    'Just wanted to follow up on my last email. Let me know if you need anything from my side.',
    'Sincerely,',
  ),
  es: followupDraftBodyHtml(
    'Hola', 'First name',
    'Solo quería hacer un seguimiento de mi último correo. Avísame si necesitas algo de mi parte.',
    'Atentamente,',
  ),
}

function followupDraftDefaultBody(): string {
  const lang = (
    (typeof localStorage !== 'undefined' ? localStorage.getItem('agentys_language') : null)
    ?? i18n.language ?? 'fr'
  ).slice(0, 2)
  return FOLLOWUP_DRAFT_BODY_BY_LANG[lang] ?? FOLLOWUP_DRAFT_BODY_BY_LANG.fr
}

/** Every locale's untouched follow-up seed — used to detect a pristine body. */
const FOLLOWUP_PRISTINE_BODIES: ReadonlySet<string> = new Set(
  Object.values(FOLLOWUP_DRAFT_BODY_BY_LANG),
)

/**
 * Re-localize a follow-up draft body that is still the untouched seed.
 *
 * The seed is persisted ONCE at seed time in the account's `preferred_language`
 * (DB default `'fr'`), so an English-UI user whose writing language was never
 * set sees a French template ("Bonjour … Cordialement,") that never updates
 * (reported 2026-06-23). When the stored body is byte-identical to a known seed
 * in ANY locale — i.e. the user hasn't edited it — swap it for the current UI
 * language's seed. A user-edited body (not in the seed set) is left untouched,
 * so we never clobber real edits. Mirrors the auto-reply pristine-relocalize.
 */
export function relocalizePristineFollowupBody(body: string): string {
  if (!body) return body
  return FOLLOWUP_PRISTINE_BODIES.has(body) ? followupDraftDefaultBody() : body
}

export function defaultActionPayload(type: QuickStepActionType): QuickStepAction['payload'] {
  switch (type) {
    case 'mark_read':
      return { value: true }
    case 'reply_template':
      return { body: '', replyAll: false, includeQuoted: true }
    case 'forward':
      return { to: [] }
    case 'rsvp_meeting':
      return { response: 'accepted' }
    case 'create_snoozed_followup_draft':
      return {
        body: followupDraftDefaultBody(),
        delay_days: 7,
      }
    case 'mark_with_emoji':
      return { emoji: '⏰', text: '', include_deadline: false, chip: true }
    case 'apply_label':
      return { label: '' }
    case 'create_reminder':
      return { days_before: 2 }
    case 'create_calendar_event':
      return { days_before: 2, duration_minutes: 30 }
    default:
      return undefined
  }
}

export function makeAction(type: QuickStepActionType): QuickStepAction {
  const payload = defaultActionPayload(type)
  // Cast is safe because defaultActionPayload returns the right shape per type.
  // Audit 2026-05-11 F-02: per-row uid keeps React from confusing TipTap /
  // ContactAutocomplete state across rows when the user drags to reorder.
  // The uid is purely client-side — backend ignores unknown fields.
  const uid =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `act-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  // Cast is safe because defaultActionPayload returns the right shape per type.
  return { type, payload, uid } as QuickStepAction & { uid: string }
}

/**
 * Defensive: backend responses can omit optional collections (e.g. `triggers`,
 * `triggerOperator`, `autoEnabled`) when they're empty / falsy, but the editor
 * components access `.length` on `triggers` and `actions` unconditionally.
 * Normalize on read so consumers always see a complete `QuickStep` shape.
 *
 * Likewise, action-level guards (`if.triggers`) and forward payloads
 * (`payload.to`) are coerced to safe defaults to avoid `.length` / `.join`
 * crashes against legacy stored data.
 */
export function normalizeQuickStep(raw: Partial<QuickStep> & { id: string; name: string }): QuickStep {
  const actions = (raw.actions ?? []).map(action => {
    const next = { ...action } as QuickStepAction
    if (next.if) {
      next.if = {
        operator: next.if.operator ?? 'AND',
        triggers: Array.isArray(next.if.triggers)
          ? next.if.triggers.map(migrateLegacyCondition)
          : [],
      }
    }
    if (next.type === 'forward') {
      const p = (next.payload ?? {}) as Partial<ForwardPayload>
      next.payload = {
        to: Array.isArray(p.to) ? p.to : [],
        to_groups: p.to_groups,
        subject_prefix: p.subject_prefix,
        body: p.body,
      }
    }
    if (next.type === 'reply_template') {
      const p = (next.payload ?? {}) as Partial<ReplyTemplatePayload>
      next.payload = {
        body: p.body ?? '',
        replyAll: p.replyAll ?? false,
        // includeQuoted is no longer user-toggleable in the editor —
        // quoting the original is implicit. Force-true on every load so
        // legacy rules with `false` persisted get corrected on next save.
        includeQuoted: true,
        snippet_id: p.snippet_id,
      }
    }
    if (next.type === 'apply_label') {
      const p = (next.payload ?? {}) as Partial<ApplyLabelPayload>
      next.payload = { label: typeof p.label === 'string' ? p.label : '' }
    }
    if (next.type === 'create_snoozed_followup_draft') {
      const p = (next.payload ?? {}) as Partial<CreateSnoozedFollowupDraftPayload>
      // Relocalize an untouched seed to the current UI language so a French
      // template doesn't linger in an English app (2026-06-23). Edited bodies
      // are preserved.
      next.payload = {
        body: relocalizePristineFollowupBody(typeof p.body === 'string' ? p.body : ''),
        delay_days: typeof p.delay_days === 'number' ? p.delay_days : 7,
      }
    }
    return next
  })
  const firesOn = raw.firesOn === 'sent' ? 'sent' : 'received'
  const description = typeof raw.description === 'string' ? raw.description : undefined
  return {
    id: raw.id,
    name: raw.name,
    description,
    icon: raw.icon ?? null,
    shortcut: raw.shortcut ?? null,
    actions,
    enabled: raw.enabled ?? true,
    confirmBeforeRun: raw.confirmBeforeRun ?? false,
    autoEnabled: raw.autoEnabled ?? false,
    // Default true: a legacy rule loaded without the field has its
    // ⚡ Auto badge enabled — mirrors the backend default. Toggling off
    // in the editor sets it to false explicitly.
    showAutoBadge: raw.showAutoBadge ?? true,
    triggerOperator: raw.triggerOperator ?? 'AND',
    triggers: Array.isArray(raw.triggers)
      ? raw.triggers.map(migrateLegacyCondition)
      : [],
    firesOn,
  }
}
