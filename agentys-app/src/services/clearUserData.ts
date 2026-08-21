/**
 * Fonctions de nettoyage des données utilisateur.
 *
 * - clearLocalData() : logout léger — efface localStorage, sessionStorage,
 *   IndexedDB. Les comptes backend sont conservés (re-login instantané).
 * - clearAllUserData() : reset total — supprime aussi les comptes backend.
 *   Réservé à une future fonctionnalité "Réinitialiser Agentys".
 */

import { cacheInvalidatePrefix } from '../api/cache'
import { clearEmailBodyCache } from '../api/emailBodyCache'
import { API_URL } from '../config'
import {
  ONBOARDING_COMPLETE_KEY,
  ONBOARDING_KB_COMPLETE_KEY,
  FORCE_ONBOARDING_KEY,
} from '../lib/storageKeys'

/**
 * Liste exhaustive des clés localStorage à nettoyer au logout.
 * Organisées par catégorie pour faciliter l'audit.
 */
const USER_DATA_KEYS: readonly string[] = [
  // Auth
  'agentys_jwt',

  // Drafts & instructions
  'agentys_saved_drafts',
  'agentys_instructions_history',

  // Subscription & trial
  'agentys_trial_email',
  'agentys_trial_start',
  'agentys_trial_end',
  'agentys_trial_welcome_sent',
  'agentys_trial_expiration_notified',
  'agentys_trial_data_deletion_warning',

  // Stripe
  'agentys_stripe_subscription_id',
  'agentys_stripe_customer_id',
  'agentys_stripe_subscription_status',
  'agentys_stripe_current_period_end',
  'agentys_stripe_checkout_pending',
  'agentys_stripe_cancel_at_period_end',

  // Usage & stats
  'agentys_usage_daily_draft_count',
  'agentys_usage_last_reset_date',
  'agentys_stats_emails_processed',
  'agentys_stats_drafts_generated',
  'agentys_stats_monthly_reset',
  'agentys_monthly_history',

  // Payment issues
  'agentys_payment_issue_date',
  'agentys_payment_reminders_sent',
  'agentys_payment_suspended',

  // Referral
  'agentys_referral_code',
  'agentys_referrals_count',

  // Specialties — legacy marketplace install registry kept here so existing
  // users get the orphaned localStorage entry wiped on logout.
  'agentys_specialty_purchases',
  'agentys_agent_installs',

  // Onboarding
  ONBOARDING_COMPLETE_KEY,
  ONBOARDING_KB_COMPLETE_KEY,
  'agentys_premium_onboarding',
  'agentys_onboarding_v2_complete',
  FORCE_ONBOARDING_KEY,

  // UI preferences
  'agentys_language',
  'agentys_theme',
  'agentys-theme',
  'agentys_email_view_mode',
  'agentys_tooltips_enabled',
  'agentys_custom_shortcuts',
  'agentys_skip_send_confirmation',
  'agentys_ui_sounds_enabled',
  'agentys_notification_sound_enabled',
  'agentys_notification_sound_name',
  'agentys_detail_panel_width',
  'agentys_tour_completed',
  'agentys_tips_disabled',
  'agentys_milestones_seen',
  'agentys_first_draft_celebrated',

  // Automation settings
  'agentys_auto_empty_trash_30d',
  'agentys_auto_empty_spam_30d',
  'agentys_hide_noise_from_inbox',

  // Work hours & quiet hours
  'agentys_work_hours_only',
  'agentys_work_hours_start',
  'agentys_work_hours_end',
  'agentys_quiet_hours_enabled',
  'agentys_quiet_hours_start',
  'agentys_quiet_hours_end',
  'agentys_quiet_hours_days',
  'agentys_focus_mode_enabled',
  'agentys_focus_mode_end_time',

  // Search & snippets
  'agentys_saved_searches',
  'agentys_recent_searches',
  'agentys_snippets',

  // AI command menu — legacy global key (pre-account-scoping)
  'ai-cmd-saved',

  // Labels & contacts
  'agentys_favorite_labels_order',
  'agentys_contact_groups',
  'agentys_cross_channel_rules',

  // Pinned & snoozed
  'agentys_pinned',
  'agentys_snoozed',
  // Local-only pins for saved (compose/reply) drafts (defined in
  // PendingDraftList). No backend mirror, so logout must wipe it here.
  'agentys:pinned-saved-drafts',

  // Calendar
  'agentys-calendar-tz2',
  'agentys-calendar-tz2-color',
  'agentys-visible-calendars',
  'agentys-calendar-event-labels',
  'agentys-calendar-view-mode',
  'agentys-calendar-tz2-holidays',
  'agentys-calendar-primary-holidays',
  'agentys-auto-reply-event-id',
  'agentys_dw_snooze_day',
  'agentys_dw_streak_dates',

  // Deep Focus
  'df-goals',
  'df-session-history',
  'df-label-priorities',

  // Approval audit
  'agentys-approval-audit',

  // Notification prefs
  'agentys_notif_new_emails',
  'agentys_notif_draft_ready',
  'agentys_notif_sync_errors',

  // Update checker
  'agentys_last_update_check',
  'agentys_update_dismissed_version',
]

/**
 * Patterns de clés dynamiques (préfixes) qui doivent aussi être nettoyées.
 * Ex: pkce_verifier_xxx, draft-backup-xxx, etc.
 */
const DYNAMIC_KEY_PREFIXES: readonly string[] = [
  'pkce_verifier_',
  'pkce_provider_',
  'draft-backup-',
  'agentys_emails_',
  'agentys_detail_',
  // AI command menu — account-scoped saved instructions (ai-cmd-saved:<accountId>)
  'ai-cmd-saved:',
  // Contact groups — account-scoped cache (agentys_contact_groups_<accountId>)
  'agentys_contact_groups_',
  // Snippets — account-scoped localStorage fallback (agentys_snippets:<accountId>)
  'agentys_snippets:',
  // Approval audit — account-scoped audit log (agentys-approval-audit:<accountId>)
  'agentys-approval-audit:',
]

/**
 * Supprime toutes les données utilisateur du localStorage.
 */
function clearLocalStorage(): void {
  try {
    // 1. Supprimer les clés connues
    for (const key of USER_DATA_KEYS) {
      localStorage.removeItem(key)
    }

    // 2. Supprimer les clés dynamiques par préfixe
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const key = localStorage.key(i)
      if (!key) continue
      for (const prefix of DYNAMIC_KEY_PREFIXES) {
        if (key.startsWith(prefix)) {
          localStorage.removeItem(key)
          break
        }
      }
    }
  } catch {
    // localStorage indisponible (ex: Safari mode privé)
  }
}

/**
 * Vide les caches IndexedDB locaux.
 */
async function clearIndexedDBCache(): Promise<void> {
  try {
    await Promise.allSettled([
      cacheInvalidatePrefix(''),
      clearEmailBodyCache(),
    ])
  } catch {
    // IndexedDB indisponible — pas grave
  }
}

/**
 * Supprime aussi le sessionStorage.
 */
function clearSessionStorage(): void {
  try {
    sessionStorage.clear()
  } catch {
    // sessionStorage indisponible
  }
}

/**
 * Supprime tous les comptes email côté backend (SQLite + config).
 * Chaque DELETE /api/accounts/:id supprime aussi les emails en CASCADE.
 * Best-effort : si le backend est injoignable, on continue le logout.
 */
async function deleteAllBackendAccounts(token: string | null): Promise<void> {
  try {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (token) headers['Authorization'] = `Bearer ${token}`

    const res = await fetch(`${API_URL}/api/accounts`, { headers })
    if (!res.ok) return

    const data = await res.json()
    const accounts: { id: string }[] = data.accounts || data || []
    if (!accounts.length) return

    await Promise.allSettled(
      accounts.map(acc =>
        fetch(`${API_URL}/api/accounts/${encodeURIComponent(acc.id)}`, {
          method: 'DELETE',
          headers,
        })
      )
    )
  } catch {
    // Backend injoignable — on continue le logout côté frontend
  }
}

/**
 * Nettoyage des données locales uniquement (logout léger).
 * Ne touche PAS aux comptes backend — au re-login, tout est conservé.
 * Nettoie localStorage, sessionStorage, IndexedDB côté frontend.
 */
export async function clearLocalData(): Promise<void> {
  clearLocalStorage()
  clearSessionStorage()
  await clearIndexedDBCache()
  // Drop in-memory contact-photo blob URLs (the photos belong to the
  // logged-out user's address book and shouldn't bleed into the next session).
  try {
    const { clearContactAvatarCache } = await import('../hooks/useContactAvatar')
    clearContactAvatarCache()
  } catch {
    /* hook not loaded yet — no cache to clear */
  }
}

/**
 * Nettoyage complet de toutes les données utilisateur (reset total).
 * Supprime les comptes backend + données locales.
 * Réservé à une future fonctionnalité "Réinitialiser Agentys".
 */
export async function clearAllUserData(token?: string | null): Promise<void> {
  await deleteAllBackendAccounts(token ?? localStorage.getItem('agentys_jwt'))
  clearLocalStorage()
  clearSessionStorage()
  await clearIndexedDBCache()
}
