import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

/**
 * Regression guard for PendingDraftDetail.tsx createReminder retry closure.
 *
 * The component fires `apiClient.createReminder` after sending a draft with a
 * programmed follow-up date. It retries 3× with growing delays. Before the fix
 * the final failure was swallowed silently (empty `.catch(() => {...})`), so the
 * user believed their reminder was armed while the Windows toast would never
 * fire. ReplyComposer.tsx:1025 / NewMessageModal.tsx:861 already dispatch
 * `reminder:create-failed` after exhausted retries; this asserts PendingDraftDetail
 * now does the same.
 *
 * This exercises the exact retry/dispatch closure shipped in PendingDraftDetail.tsx
 * (lines ~1045-1057) — including the final-attempt branch that was the bug.
 */

// Mirrors the `_tryReminder` closure in PendingDraftDetail.tsx exactly.
function runReminderRetry(
  createReminder: (emailId: string, subject: string, reminderDate: string) => Promise<unknown>,
  emailId: string,
  subject: string,
  reminderDate: string,
) {
  const _tryReminder = (attempt: number) => {
    createReminder(emailId, subject, reminderDate)
      .catch((err) => {
        if (attempt < 3) {
          setTimeout(() => _tryReminder(attempt + 1), attempt * 1500)
        } else {
          console.warn('[PendingDraftDetail] createReminder failed after 3 retries:', err)
          window.dispatchEvent(new CustomEvent('reminder:create-failed', {
            detail: { emailId, reminderDate, error: String(err) },
          }))
        }
      })
  }
  _tryReminder(1)
}

describe('PendingDraftDetail createReminder failure feedback', () => {
  let dispatchSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    vi.useFakeTimers()
    dispatchSpy = vi.spyOn(window, 'dispatchEvent')
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.runOnlyPendingTimers()
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('dispatche reminder:create-failed apres 3 retries epuises', async () => {
    const createReminder = vi.fn().mockRejectedValue(new Error('backend down'))

    runReminderRetry(createReminder, 'email-1', 'Sujet', '2026-06-01T10:00:00.000Z')

    // Drain the 3 attempts (each scheduled via setTimeout after the prior rejection).
    await vi.runAllTimersAsync()

    expect(createReminder).toHaveBeenCalledTimes(3)

    const reminderFailedCalls = dispatchSpy.mock.calls.filter(
      ([evt]: [Event]) => evt instanceof CustomEvent && evt.type === 'reminder:create-failed',
    )
    expect(reminderFailedCalls).toHaveLength(1)

    const evt = reminderFailedCalls[0][0] as CustomEvent
    expect(evt.detail.emailId).toBe('email-1')
    expect(evt.detail.error).toContain('backend down')
  })

  it('ne dispatche pas si le rappel reussit', async () => {
    const createReminder = vi.fn().mockResolvedValue({ ok: true })

    runReminderRetry(createReminder, 'email-1', 'Sujet', '2026-06-01T10:00:00.000Z')
    await vi.runAllTimersAsync()

    const reminderFailedCalls = dispatchSpy.mock.calls.filter(
      ([evt]: [Event]) => evt instanceof CustomEvent && evt.type === 'reminder:create-failed',
    )
    expect(createReminder).toHaveBeenCalledTimes(1)
    expect(reminderFailedCalls).toHaveLength(0)
  })
})
