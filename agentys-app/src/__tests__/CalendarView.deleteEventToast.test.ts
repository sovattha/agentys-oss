import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Regression: deleting a calendar event that fails on the provider used to call
// setError(...), which the `if (error) return <calendar-error>` branch (~2163)
// turns into a fatal FULL-PAGE error that replaces the whole calendar.
// The fix replaces that setError with a non-fatal agentys:toast (matching the
// create/update error toasts). This test reproduces the exact delete-failure
// callback closure from CalendarView.tsx (~3030) and proves it now dispatches a
// toast and never sets the fatal error state.

interface ToastDetail { message: string; type: string; duration: number }

interface CalEvent { id: string }

// Mirrors the inline onClick closure in CalendarView's delete-confirm button.
// `tc` is useTranslation('common').t — keyed under common:toasts.*.
function runDeleteEventFailurePath(deps: {
  eventId: string
  events: CalEvent[]
  setEvents: (updater: (prev: CalEvent[]) => CalEvent[]) => void
  setError: (msg: string) => void
  tc: (k: string) => string
  deleteCalendarEvent: (id: string) => Promise<void>
}): Promise<void> {
  const { eventId, events, setEvents, tc, deleteCalendarEvent } = deps
  const removed = events.find(ev => ev.id === eventId)
  setEvents(prev => prev.filter(ev => ev.id !== eventId))
  return deleteCalendarEvent(eventId).catch(() => {
    if (removed) setEvents(prev => [...prev, removed])
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: {
          message: tc('toasts.calendar_event_delete_failed'),
          type: 'error',
          duration: 6000,
        },
      }))
    }
    // NOTE: the bug was `setError(t('delete_event_error'))` here.
  })
}

describe('CalendarView delete-event failure (non-fatal toast)', () => {
  let dispatched: CustomEvent[] = []

  beforeEach(() => {
    dispatched = []
    vi.spyOn(window, 'dispatchEvent').mockImplementation((evt) => {
      if (evt instanceof CustomEvent) dispatched.push(evt)
      return true
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('dispatches a non-fatal error toast and does NOT set the fatal error state on delete failure', async () => {
    const setError = vi.fn()
    const setEvents = vi.fn()
    const tc = (k: string) => `common:${k}`

    await runDeleteEventFailurePath({
      eventId: 'evt-1',
      events: [{ id: 'evt-1' }, { id: 'evt-2' }],
      setEvents,
      setError,
      tc,
      deleteCalendarEvent: () => Promise.reject(new Error('provider delete failed')),
    })

    // The fatal full-page error must NOT be triggered.
    expect(setError).not.toHaveBeenCalled()

    // A non-fatal toast must be dispatched instead.
    const toastEvt = dispatched.find(e => e.type === 'agentys:toast')
    expect(toastEvt).toBeDefined()
    const detail = (toastEvt as CustomEvent<ToastDetail>).detail
    expect(detail.type).toBe('error')
    expect(detail.message).toBe('common:toasts.calendar_event_delete_failed')
    expect(detail.duration).toBe(6000)

    // Optimistic removal is rolled back so the event reappears.
    expect(setEvents).toHaveBeenCalledTimes(2)
  })

  it('does not dispatch a toast when the delete succeeds', async () => {
    const setError = vi.fn()
    const setEvents = vi.fn()

    await runDeleteEventFailurePath({
      eventId: 'evt-1',
      events: [{ id: 'evt-1' }],
      setEvents,
      setError,
      tc: (k: string) => k,
      deleteCalendarEvent: () => Promise.resolve(),
    })

    expect(setError).not.toHaveBeenCalled()
    expect(dispatched.find(e => e.type === 'agentys:toast')).toBeUndefined()
  })
})
