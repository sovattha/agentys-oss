import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { ToastContainer, useToast } from './Toast'

/** Window inside which two `agentys:toast` dispatches with identical message+type
 * are treated as a duplicate (e.g. ReplyComposer's local "Archivé: …" + the
 * backend's `quickstep_fired` WS toast for the same auto-archive rule). The WS
 * layer already dedups WS↔WS via step_name::email_id (websocket.ts:769); this
 * catches local↔WS. */
const TOAST_DEDUP_WINDOW_MS = 5000
const TOAST_DEDUP_PRUNE_MS = 60_000

/**
 * Hôte de toasts globaux — écoute les CustomEvent `agentys:send-failed` (et
 * futurs `agentys:*-failed`) émis par des composants qui peuvent être démontés
 * avant que l'erreur remonte (ex: NewMessageModal après fermeture + undo-send
 * delay). Silent-failure infrastructure (issue #311).
 *
 * Monté une seule fois au niveau App racine. Zéro dépendance métier, juste un
 * dispatcher d'événement → toast UI.
 */

type SendFailedDetail = {
  error?: string
  to?: string
  subject?: string
  validation?: boolean
  /** usePendingSends a restauré le contenu en brouillon local (audit U-02). */
  draftRestored?: boolean
}

type GenericToastDetail = {
  message: string
  type?: 'success' | 'error' | 'info' | 'warning'
  duration?: number
  action?: { label: string; onClick: () => void }
  detail?: string
}

type ReminderCreateFailedDetail = {
  error?: string
  emailId?: string
  reminderType?: string
}

export function GlobalToastHost() {
  const { toasts, addToast, dismissToast } = useToast()
  const { t } = useTranslation('common')
  const recentToastsRef = useRef<Map<string, number>>(new Map())

  useEffect(() => {
    const onSendFailed = (evt: Event) => {
      const detail = (evt as CustomEvent<SendFailedDetail>).detail || {}
      const subj = detail.subject || t('toasts.no_subject')
      const reason = detail.error || t('toasts.unknown_reason')
      const prefix = detail.validation
        ? `⚠️ ${t('toasts.send_warning_prefix')}`
        : `❌ ${t('toasts.send_failed_prefix')}`
      const restored = detail.draftRestored ? ` ${t('toasts.send_failed_draft_restored')}` : ''
      addToast(`${prefix} — ${subj} : ${reason}${restored}`, 'error', { duration: 8000 })
    }

    const onGenericToast = (evt: Event) => {
      const detail = (evt as CustomEvent<GenericToastDetail>).detail
      if (!detail?.message) return
      const type = detail.type ?? 'info'
      const dedupKey = `${type}::${detail.message}`
      const now = Date.now()
      const recent = recentToastsRef.current
      const lastSeen = recent.get(dedupKey) ?? 0
      if (now - lastSeen < TOAST_DEDUP_WINDOW_MS) return
      recent.set(dedupKey, now)
      // Opportunistic pruning so the map doesn't grow forever in long sessions.
      for (const [k, ts] of recent) {
        if (now - ts > TOAST_DEDUP_PRUNE_MS) recent.delete(k)
      }
      addToast(detail.message, type, {
        duration: detail.duration ?? 5000,
        action: detail.action,
        detail: detail.detail,
      })
    }

    // Audit Cluster D (2026-05-11) F-01/F-02 : ReplyComposer et NewMessageModal
    // dispatchent `reminder:create-failed` quand 3 retries d'apiClient.createReminder
    // ratent. Sans listener, le user croit son follow-up armé alors que le
    // backend a échoué — le rappel Windows ne se déclenchera jamais. Le
    // snooze local crée l'illusion. On surfaçe un toast warning ici.
    const onReminderCreateFailed = (evt: Event) => {
      const detail = (evt as CustomEvent<ReminderCreateFailedDetail>).detail || {}
      const reason = detail.error || t('toasts.unknown_reason')
      addToast(
        `⏰ ${t('toasts.reminder_create_failed', { detail: reason })}`,
        'warning',
        { duration: 8000 },
      )
    }

    window.addEventListener('agentys:send-failed', onSendFailed)
    window.addEventListener('agentys:toast', onGenericToast)
    window.addEventListener('reminder:create-failed', onReminderCreateFailed)
    return () => {
      window.removeEventListener('agentys:send-failed', onSendFailed)
      window.removeEventListener('agentys:toast', onGenericToast)
      window.removeEventListener('reminder:create-failed', onReminderCreateFailed)
    }
  }, [addToast, t])

  return <ToastContainer toasts={toasts} onDismiss={dismissToast} />
}
