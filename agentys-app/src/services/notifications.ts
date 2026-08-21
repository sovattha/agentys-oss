/**
 * Notification Service for Agentys
 *
 * Provides native OS notifications via Tauri plugin when running in Tauri,
 * or falls back to Web Notifications API in browser mode.
 * Used to notify users about new emails and ready drafts.
 * Supports click handling to navigate to specific emails.
 */

import { shouldNotify } from './workHours'
import { isTauri } from './tokenStorage'
import i18n from '../i18n'

export const NOTIFICATION_ACTION_TYPE_ID = 'agentys-email'
export const NOTIFICATION_GROUP_ID = 'agentys-new-emails'
export const MEETING_ACTION_TYPE_ID = 'agentys-meeting-reminders'

// Storage keys for notification settings
const STORAGE_KEYS = {
  SOUND_ENABLED: 'agentys_notification_sound_enabled',
  SOUND_NAME: 'agentys_notification_sound_name',
} as const

// Default sound (platform will use system default)
const DEFAULT_SOUND = 'default'

export interface NotificationSoundSettings {
  soundEnabled: boolean
  soundName: string
}

export interface NotificationOptions {
  title: string
  body: string
  actionTypeId?: string
  extra?: Record<string, string>
}

export interface NewEmailNotification {
  emailId: string
  sender: string
  subject: string
}

export interface DraftReadyNotification {
  emailId: string
  sender: string
  confidence: number
}

export interface DraftReminderNotification {
  emailId: string
  sender: string
  draftId: string
}

export interface DraftQuickReplyNotification {
  emailId: string
  draftId: string
  sender: string
  confidence: number
  draftContent: string
}

export interface MeetingReminderNotification {
  eventId: string
  title: string
  /** Minutes until event start at the moment of firing (e.g. 10, 1) */
  minutesUntilStart: number
  /** Formatted start time (e.g. "12h00") for the body */
  startTimeLabel: string
  /** Optional video conferencing URL if detected */
  videoLink?: string
}

export type QuickReplyAction = 'validate' | 'reject' | 'open'

export interface QuickReplyActionData {
  action: QuickReplyAction
  emailId: string
  draftId: string
}

export type NotificationClickCallback = (emailId: string) => void
export type QuickReplyActionCallback = (data: QuickReplyActionData) => void

export const DRAFT_ACTION_TYPE_ID = 'agentys-draft-actions'

export interface NotificationService {
  checkPermission(): Promise<boolean>
  requestPermission(): Promise<boolean>
  notifyNewEmail(data: NewEmailNotification): Promise<void>
  notifyNewEmailsBatch(emails: NewEmailNotification[]): Promise<void>
  notifyDraftReady(data: DraftReadyNotification): Promise<void>
  notifyDraftReminder(data: DraftReminderNotification): Promise<void>
  notifyDraftReadyWithQuickReply(data: DraftQuickReplyNotification): Promise<void>
  notifyMeetingReminder(data: MeetingReminderNotification): Promise<void>
  setEnabled(enabled: boolean): void
  isEnabled(): boolean
  getSoundSettings(): NotificationSoundSettings
  setSoundSettings(settings: NotificationSoundSettings): void
  onNotificationClick(callback: NotificationClickCallback): Promise<() => void>
  onQuickReplyAction(callback: QuickReplyActionCallback): Promise<() => void>
  registerNotificationActions(): Promise<void>
  registerQuickReplyActions(): Promise<void>
}

const MAX_SUBJECT_LENGTH = 50
const MAX_SENDERS_IN_SUMMARY = 3

function truncateSubject(subject: string): string {
  if (subject.length <= MAX_SUBJECT_LENGTH) {
    return subject
  }
  return `${subject.substring(0, MAX_SUBJECT_LENGTH - 3)}...`
}

function loadSoundSettings(): NotificationSoundSettings {
  try {
    const soundEnabled = localStorage.getItem(STORAGE_KEYS.SOUND_ENABLED)
    const soundName = localStorage.getItem(STORAGE_KEYS.SOUND_NAME)
    return {
      soundEnabled: soundEnabled === null ? true : soundEnabled === 'true',
      soundName: soundName || DEFAULT_SOUND,
    }
  } catch {
    return { soundEnabled: true, soundName: DEFAULT_SOUND }
  }
}

function saveSoundSettings(settings: NotificationSoundSettings): void {
  try {
    localStorage.setItem(STORAGE_KEYS.SOUND_ENABLED, String(settings.soundEnabled))
    localStorage.setItem(STORAGE_KEYS.SOUND_NAME, settings.soundName)
  } catch {
    // localStorage not available, ignore
  }
}

function getSoundOption(settings: NotificationSoundSettings): string | undefined {
  if (!settings.soundEnabled) {
    return undefined
  }
  return settings.soundName === DEFAULT_SOUND ? undefined : settings.soundName
}

function formatBatchSummary(emails: NewEmailNotification[]): string {
  const senders = [...new Set(emails.map((e) => e.sender))]
  if (senders.length <= MAX_SENDERS_IN_SUMMARY) {
    return senders.join(', ')
  }
  const displayed = senders.slice(0, MAX_SENDERS_IN_SUMMARY)
  const remaining = senders.length - MAX_SENDERS_IN_SUMMARY
  // CP-02: was hardcoded French ("et N autres") in every locale's OS toast.
  return `${displayed.join(', ')} ${i18n.t('settings:notification_others', { count: remaining })}`
}

// Dynamic imports for Tauri plugins (only loaded when needed)
async function getTauriNotification() {
  if (!isTauri()) return null
  try {
    return await import('@tauri-apps/plugin-notification')
  } catch (e) {
    console.warn('[notifications] Tauri notification plugin not available:', e)
    return null
  }
}

// Web Notifications fallback
async function showWebNotification(title: string, body: string): Promise<void> {
  if (!('Notification' in window)) return

  if (Notification.permission === 'granted') {
    new Notification(title, { body })
  } else if (Notification.permission !== 'denied') {
    const permission = await Notification.requestPermission()
    if (permission === 'granted') {
      new Notification(title, { body })
    }
  }
}

export function createNotificationService(): NotificationService {
  let enabled = true
  let soundSettings = loadSoundSettings()

  return {
    async checkPermission(): Promise<boolean> {
      const tauri = await getTauriNotification()
      if (tauri) {
        return tauri.isPermissionGranted()
      }
      // Web fallback
      return 'Notification' in window && Notification.permission === 'granted'
    },

    async requestPermission(): Promise<boolean> {
      const tauri = await getTauriNotification()
      if (tauri) {
        const permission = await tauri.requestPermission()
        return permission === 'granted'
      }
      // Web fallback
      if (!('Notification' in window)) return false
      const permission = await Notification.requestPermission()
      return permission === 'granted'
    },

    async notifyNewEmail(data: NewEmailNotification): Promise<void> {
      if (!enabled || !shouldNotify()) return

      const truncatedSubject = truncateSubject(data.subject)
      const title = i18n.t('settings:notification_new_email')
      const body = `${data.sender}: ${truncatedSubject}`

      const tauri = await getTauriNotification()
      if (tauri) {
        const sound = getSoundOption(soundSettings)
        await tauri.sendNotification({
          title,
          body,
          actionTypeId: NOTIFICATION_ACTION_TYPE_ID,
          extra: { emailId: data.emailId, type: 'new_email' },
          group: NOTIFICATION_GROUP_ID,
          sound,
          silent: !soundSettings.soundEnabled,
        })
      } else {
        await showWebNotification(title, body)
      }
    },

    async notifyNewEmailsBatch(emails: NewEmailNotification[]): Promise<void> {
      if (!enabled || !shouldNotify() || emails.length === 0) return

      // For a single email, use the standard notification
      if (emails.length === 1) {
        await this.notifyNewEmail(emails[0])
        return
      }

      const title = i18n.t('settings:notification_new_emails', { count: emails.length })
      const senderSummary = formatBatchSummary(emails)
      const body = i18n.t('settings:notification_from', { senders: senderSummary })

      const tauri = await getTauriNotification()
      if (tauri) {
        const sound = getSoundOption(soundSettings)
        await tauri.sendNotification({
          title,
          body,
          actionTypeId: NOTIFICATION_ACTION_TYPE_ID,
          extra: { type: 'new_email_batch', count: String(emails.length) },
          group: NOTIFICATION_GROUP_ID,
          groupSummary: true,
          sound,
          silent: !soundSettings.soundEnabled,
        })
      } else {
        await showWebNotification(title, body)
      }
    },

    async notifyDraftReady(data: DraftReadyNotification): Promise<void> {
      if (!enabled || !shouldNotify()) return

      const confidencePercent = Math.round(data.confidence * 100)
      const title = i18n.t('settings:notification_draft_ready')
      const body = i18n.t('settings:notification_suggested_reply', { sender: data.sender, confidence: confidencePercent })

      const tauri = await getTauriNotification()
      if (tauri) {
        await tauri.sendNotification({
          title,
          body,
          actionTypeId: NOTIFICATION_ACTION_TYPE_ID,
          extra: { emailId: data.emailId, type: 'draft_ready' },
        })
      } else {
        await showWebNotification(title, body)
      }
    },

    async notifyDraftReminder(data: DraftReminderNotification): Promise<void> {
      if (!enabled || !shouldNotify()) return

      const title = i18n.t('settings:notification_draft_reminder')
      const body = i18n.t('settings:notification_draft_awaiting', { sender: data.sender })

      const tauri = await getTauriNotification()
      if (tauri) {
        await tauri.sendNotification({
          title,
          body,
          actionTypeId: NOTIFICATION_ACTION_TYPE_ID,
          extra: { emailId: data.emailId, type: 'draft_reminder' },
        })
      } else {
        await showWebNotification(title, body)
      }
    },

    async notifyDraftReadyWithQuickReply(
      data: DraftQuickReplyNotification
    ): Promise<void> {
      if (!enabled || !shouldNotify()) return

      const confidencePercent = Math.round(data.confidence * 100)
      const truncatedContent = truncateSubject(data.draftContent)
      const title = i18n.t('settings:notification_draft_ready')
      const body = `${data.sender} (${confidencePercent}%) : ${truncatedContent}`

      const tauri = await getTauriNotification()
      if (tauri) {
        await tauri.sendNotification({
          title,
          body,
          actionTypeId: DRAFT_ACTION_TYPE_ID,
          extra: {
            emailId: data.emailId,
            draftId: data.draftId,
            type: 'draft_quick_reply',
          },
        })
      } else {
        await showWebNotification(title, body)
      }
    },

    async notifyMeetingReminder(data: MeetingReminderNotification): Promise<void> {
      if (!enabled || !shouldNotify()) return

      const titleKey = data.minutesUntilStart <= 1
        ? 'calendar:reminder_starting_now'
        : 'calendar:reminder_upcoming'
      const title = i18n.t(titleKey, { title: data.title, minutes: data.minutesUntilStart })
      const body = data.videoLink
        ? i18n.t('calendar:reminder_body_with_link', { time: data.startTimeLabel })
        : i18n.t('calendar:reminder_body', { time: data.startTimeLabel })

      const tauri = await getTauriNotification()
      if (tauri) {
        const sound = getSoundOption(soundSettings)
        await tauri.sendNotification({
          title,
          body,
          actionTypeId: MEETING_ACTION_TYPE_ID,
          extra: {
            eventId: data.eventId,
            type: 'meeting_reminder',
            videoLink: data.videoLink ?? '',
          },
          sound,
          silent: !soundSettings.soundEnabled,
        })
      } else {
        await showWebNotification(title, body)
      }
    },

    setEnabled(value: boolean): void {
      enabled = value
    },

    isEnabled(): boolean {
      return enabled
    },

    getSoundSettings(): NotificationSoundSettings {
      return { ...soundSettings }
    },

    setSoundSettings(settings: NotificationSoundSettings): void {
      soundSettings = { ...settings }
      saveSoundSettings(soundSettings)
    },

    async onNotificationClick(
      callback: NotificationClickCallback
    ): Promise<() => void> {
      const tauri = await getTauriNotification()
      if (!tauri) {
        // Web fallback - no click handling available
        return () => {}
      }

      const listener = await tauri.onAction((notification) => {
        const extra = (notification as { notification?: { extra?: { emailId?: string } } })
          ?.notification?.extra
        if (extra?.emailId) {
          callback(extra.emailId)
        }
      })
      return () => void listener.unregister()
    },

    async onQuickReplyAction(
      callback: QuickReplyActionCallback
    ): Promise<() => void> {
      const tauri = await getTauriNotification()
      if (!tauri) {
        // Web fallback - no action handling available
        return () => {}
      }

      const listener = await tauri.onAction((notification) => {
        const actionId = (notification as { actionId?: string })?.actionId
        const extra = (
          notification as {
            notification?: {
              extra?: { emailId?: string; draftId?: string; type?: string }
            }
          }
        )?.notification?.extra

        if (extra?.type !== 'draft_quick_reply') return
        if (!extra?.emailId || !extra?.draftId || !actionId) return

        const validActions: QuickReplyAction[] = ['validate', 'reject', 'open']
        if (!validActions.includes(actionId as QuickReplyAction)) return

        callback({
          action: actionId as QuickReplyAction,
          emailId: extra.emailId,
          draftId: extra.draftId,
        })
      })
      return () => void listener.unregister()
    },

    async registerNotificationActions(): Promise<void> {
      const tauri = await getTauriNotification()
      if (!tauri) return

      await tauri.registerActionTypes([
        {
          id: NOTIFICATION_ACTION_TYPE_ID,
          actions: [
            {
              id: 'open',
              title: i18n.t('calendar:reminder_action_open'),
            },
          ],
        },
        {
          id: MEETING_ACTION_TYPE_ID,
          actions: [
            {
              id: 'open',
              title: i18n.t('calendar:reminder_action_open'),
            },
            {
              id: 'join',
              title: i18n.t('calendar:reminder_action_join'),
            },
          ],
        },
      ])
    },

    async registerQuickReplyActions(): Promise<void> {
      const tauri = await getTauriNotification()
      if (!tauri) return

      await tauri.registerActionTypes([
        {
          id: DRAFT_ACTION_TYPE_ID,
          actions: [
            {
              id: 'validate',
              title: i18n.t('settings:notification_action_validate'),
            },
            {
              id: 'reject',
              title: i18n.t('settings:notification_action_reject'),
            },
            {
              id: 'open',
              title: i18n.t('calendar:reminder_action_open'),
            },
          ],
        },
      ])
    },
  }
}

let notificationService: NotificationService | null = null

export function getNotificationService(): NotificationService {
  if (!notificationService) {
    notificationService = createNotificationService()
  }
  return notificationService
}

export function resetNotificationService(): void {
  notificationService = null
}
