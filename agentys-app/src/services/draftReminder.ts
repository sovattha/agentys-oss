/**
 * Draft Reminder Service for Agentys
 *
 * Tracks pending drafts and sends reminder notifications
 * when drafts remain unvalidated for too long.
 */

export const DEFAULT_REMINDER_DELAY_MS = 2 * 60 * 60 * 1000 // 2 hours
const CHECK_INTERVAL_MS = 60 * 1000 // 1 minute

export interface PendingDraft {
  emailId: string
  sender: string
  draftId: string
  createdAt: number
  reminderSent: boolean
}

export interface DraftReminderConfig {
  onReminder: (draft: PendingDraft) => void
  reminderDelayMs?: number
}

export interface DraftReminderService {
  trackDraft(draft: Omit<PendingDraft, 'createdAt' | 'reminderSent'>): void
  untrackDraft(draftId: string): void
  getPendingDrafts(): PendingDraft[]
  checkReminders(): void
  start(): void
  stop(): void
}

export function createDraftReminderService(
  config: DraftReminderConfig
): DraftReminderService {
  const { onReminder, reminderDelayMs = DEFAULT_REMINDER_DELAY_MS } = config
  const pendingDrafts = new Map<string, PendingDraft>()
  let intervalId: ReturnType<typeof setInterval> | null = null

  function checkReminders(): void {
    const now = Date.now()
    for (const draft of pendingDrafts.values()) {
      if (draft.reminderSent) continue
      const elapsed = now - draft.createdAt
      if (elapsed >= reminderDelayMs) {
        draft.reminderSent = true
        onReminder(draft)
      }
    }
  }

  return {
    trackDraft(draft): void {
      if (pendingDrafts.has(draft.draftId)) return
      pendingDrafts.set(draft.draftId, {
        ...draft,
        createdAt: Date.now(),
        reminderSent: false,
      })
    },

    untrackDraft(draftId): void {
      pendingDrafts.delete(draftId)
    },

    getPendingDrafts(): PendingDraft[] {
      return Array.from(pendingDrafts.values())
    },

    checkReminders,

    start(): void {
      if (intervalId) return
      intervalId = setInterval(checkReminders, CHECK_INTERVAL_MS)
    },

    stop(): void {
      if (intervalId) {
        clearInterval(intervalId)
        intervalId = null
      }
    },
  }
}

let draftReminderService: DraftReminderService | null = null

export function getDraftReminderService(
  config?: DraftReminderConfig
): DraftReminderService | null {
  if (!draftReminderService && config) {
    draftReminderService = createDraftReminderService(config)
  }
  return draftReminderService
}

export function resetDraftReminderService(): void {
  if (draftReminderService) {
    draftReminderService.stop()
    draftReminderService = null
  }
}
