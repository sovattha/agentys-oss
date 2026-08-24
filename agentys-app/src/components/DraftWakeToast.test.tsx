/*
 * Agentys — voice-first email assistant.
 * Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version. See the LICENSE file for details.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

import { render, screen, fireEvent, act } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from 'i18next'
import { DraftWakeToast } from './DraftWakeToast'
import type { PendingDraft } from '../services/api'

// Use the real i18n stack from setup.ts. Pin to English so assertions match
// the keys defined in en/drafts.json (the global setup defaults to fr).
beforeEach(async () => {
  await i18n.changeLanguage('en')
})

function buildDraft(overrides: Partial<PendingDraft> = {}): PendingDraft {
  return {
    id: 'd1',
    email_id: 'email-d1',
    email_sender: 'alex.doe@acme.com',
    email_sender_name: 'Alex Doe',
    email_subject: 'Project briefing',
    email_body: '',
    draft_subject: 'Re: Project briefing',
    draft_body: 'Hi Alex, just checking in…',
    draft_v1: '',
    critique: '',
    classification: '',
    priority: 50,
    confidence: 0.85,
    routing_tier: 'followup',
    status: 'pending',
    created_at: '2026-05-19T09:00:00Z',
    ...overrides,
  } as PendingDraft
}

function buildHandlers() {
  return {
    onSend: vi.fn().mockResolvedValue(undefined),
    onOpen: vi.fn(),
    onReviewAll: vi.fn(),
    onSnoozeOne: vi.fn(),
    onSnoozeAll: vi.fn(),
    onDismissOne: vi.fn(),
    onDismissAll: vi.fn(),
  }
}

describe('DraftWakeToast', () => {
  beforeEach(() => {
    vi.useRealTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders nothing when there are no drafts', () => {
    const handlers = buildHandlers()
    const { container } = render(
      <DraftWakeToast drafts={[]} {...handlers} />,
    )
    expect(container.firstChild).toBeNull()
  })

  describe('singular layout', () => {
    it('renders title with humanised recipient and subject', () => {
      const draft = buildDraft({
        email_sender: 'support@stripe.com',
        email_sender_name: undefined,
        draft_subject: 'Re: Invoice question',
      })
      const handlers = buildHandlers()
      render(<DraftWakeToast drafts={[draft]} {...handlers} />)

      const toast = screen.getByTestId('draft-wake-toast')
      expect(toast).toHaveTextContent(/Support/)
      expect(toast).toHaveTextContent('Re: Invoice question')
    })

    it('uses email_sender_name as-is when it already has a space', () => {
      const draft = buildDraft({
        email_sender_name: 'Alex Doe',
        email_sender: 'alex.doe@acme.com',
      })
      const handlers = buildHandlers()
      render(<DraftWakeToast drafts={[draft]} {...handlers} />)
      expect(screen.getByTestId('draft-wake-toast')).toHaveTextContent('Alex Doe')
    })

    it('humanises a dotted email_sender_name like "Alex.Doe"', () => {
      const draft = buildDraft({
        email_sender_name: 'Alex.Doe',
        email_sender: 'alex.doe@acme.com',
      })
      const handlers = buildHandlers()
      render(<DraftWakeToast drafts={[draft]} {...handlers} />)
      expect(screen.getByTestId('draft-wake-toast')).toHaveTextContent('Alex Doe')
    })

    it('Send opens a 5s undo window first — it does NOT call onSend immediately', () => {
      vi.useFakeTimers()
      const draft = buildDraft({ id: 'send-ok' })
      const handlers = buildHandlers()
      render(<DraftWakeToast drafts={[draft]} {...handlers} />)

      fireEvent.click(screen.getByTestId('draft-wake-toast-send'))
      expect(handlers.onSend).not.toHaveBeenCalled()
      // The row swaps to an "Undo send" control while the window is open.
      expect(screen.getByTestId('draft-wake-toast-undo')).toBeInTheDocument()
      expect(screen.queryByTestId('draft-wake-toast-send')).toBeNull()
    })

    it('Send → after the undo window, calls onSend then onDismissOne', async () => {
      vi.useFakeTimers()
      const draft = buildDraft({ id: 'send-ok' })
      const handlers = buildHandlers()
      render(<DraftWakeToast drafts={[draft]} {...handlers} />)

      fireEvent.click(screen.getByTestId('draft-wake-toast-send'))
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000)
      })
      expect(handlers.onSend).toHaveBeenCalledWith(draft)
      expect(handlers.onDismissOne).toHaveBeenCalledWith('send-ok')
    })

    it('Undo within the window cancels the send entirely', async () => {
      vi.useFakeTimers()
      const draft = buildDraft({ id: 'undo-id' })
      const handlers = buildHandlers()
      render(<DraftWakeToast drafts={[draft]} {...handlers} />)

      fireEvent.click(screen.getByTestId('draft-wake-toast-send'))
      fireEvent.click(screen.getByTestId('draft-wake-toast-undo'))
      // Back to the normal Send button…
      expect(screen.getByTestId('draft-wake-toast-send')).toBeInTheDocument()
      // …and the deferred send never fires, even past the original deadline.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10000)
      })
      expect(handlers.onSend).not.toHaveBeenCalled()
      expect(handlers.onDismissOne).not.toHaveBeenCalled()
    })

    it('× during the undo window cancels the send AND dismisses', async () => {
      vi.useFakeTimers()
      const draft = buildDraft({ id: 'x-undo' })
      const handlers = buildHandlers()
      render(<DraftWakeToast drafts={[draft]} {...handlers} />)

      fireEvent.click(screen.getByTestId('draft-wake-toast-send'))
      fireEvent.click(screen.getByTestId('draft-wake-toast-dismiss'))
      expect(handlers.onDismissOne).toHaveBeenCalledWith('x-undo')
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10000)
      })
      expect(handlers.onSend).not.toHaveBeenCalled()
    })

    it('Send failure (after the window) → inline error and does NOT dismiss', async () => {
      vi.useFakeTimers()
      const draft = buildDraft({ id: 'send-fail' })
      const handlers = buildHandlers()
      handlers.onSend.mockRejectedValueOnce(new Error('boom'))

      render(<DraftWakeToast drafts={[draft]} {...handlers} />)
      fireEvent.click(screen.getByTestId('draft-wake-toast-send'))
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000)
      })

      expect(screen.getByRole('alert')).toHaveTextContent(/try again from drafts/i)
      expect(handlers.onDismissOne).not.toHaveBeenCalled()
      // Button comes back out of the busy state so the user can retry.
      const btn = screen.getByTestId('draft-wake-toast-send') as HTMLButtonElement
      expect(btn.disabled).toBe(false)
    })

    it('shows the Sending state while the send is in flight (post-window)', async () => {
      vi.useFakeTimers()
      const draft = buildDraft()
      const handlers = buildHandlers()
      // Never resolve to keep the busy state pinned after the window elapses.
      handlers.onSend.mockReturnValue(new Promise<void>(() => {}))
      render(<DraftWakeToast drafts={[draft]} {...handlers} />)

      fireEvent.click(screen.getByTestId('draft-wake-toast-send'))
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000)
      })
      const btn = screen.getByTestId('draft-wake-toast-send') as HTMLButtonElement
      expect(btn.disabled).toBe(true)
      // Sending state — matches the `sending` key in drafts.json (en: "Sending...")
      expect(btn.textContent?.toLowerCase()).toContain('sending')
    })

    it('Open → fires onOpen then onDismissOne', () => {
      const draft = buildDraft({ id: 'open-id' })
      const handlers = buildHandlers()
      render(<DraftWakeToast drafts={[draft]} {...handlers} />)

      fireEvent.click(screen.getByTestId('draft-wake-toast-open'))
      expect(handlers.onOpen).toHaveBeenCalledWith(draft)
      expect(handlers.onDismissOne).toHaveBeenCalledWith('open-id')
    })

    it('Snooze ▾ trigger opens the menu and does NOT snooze on its own', () => {
      const draft = buildDraft({ id: 'snz-id' })
      const handlers = buildHandlers()
      render(<DraftWakeToast drafts={[draft]} {...handlers} />)

      fireEvent.click(screen.getByTestId('draft-wake-toast-snooze'))
      expect(screen.getByTestId('draft-wake-toast-snooze-menu')).toBeInTheDocument()
      expect(handlers.onSnoozeOne).not.toHaveBeenCalled()
    })

    it('picking a snooze duration calls onSnoozeOne with the matching ms', () => {
      const DAY = 24 * 60 * 60 * 1000
      const draft = buildDraft({ id: 'snz-id' })
      const handlers = buildHandlers()
      render(<DraftWakeToast drafts={[draft]} {...handlers} />)

      fireEvent.click(screen.getByTestId('draft-wake-toast-snooze'))
      fireEvent.click(screen.getByTestId('draft-wake-toast-snooze-1d'))
      expect(handlers.onSnoozeOne).toHaveBeenCalledWith('snz-id', DAY)
      // Selecting closes the menu and does not dismiss the draft.
      expect(screen.queryByTestId('draft-wake-toast-snooze-menu')).toBeNull()
      expect(handlers.onDismissOne).not.toHaveBeenCalled()

      fireEvent.click(screen.getByTestId('draft-wake-toast-snooze'))
      fireEvent.click(screen.getByTestId('draft-wake-toast-snooze-3d'))
      expect(handlers.onSnoozeOne).toHaveBeenCalledWith('snz-id', 3 * DAY)

      fireEvent.click(screen.getByTestId('draft-wake-toast-snooze'))
      fireEvent.click(screen.getByTestId('draft-wake-toast-snooze-1w'))
      expect(handlers.onSnoozeOne).toHaveBeenCalledWith('snz-id', 7 * DAY)
    })

    it('shows a "no reply for N days" signal derived from created_at', () => {
      const draft = buildDraft({
        created_at: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(),
      })
      const handlers = buildHandlers()
      render(<DraftWakeToast drafts={[draft]} {...handlers} />)
      expect(screen.getByTestId('draft-wake-toast')).toHaveTextContent(/no reply for 7d/i)
    })

    it('omits the no-reply signal when the draft is < 1 day old', () => {
      const draft = buildDraft({
        created_at: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
      })
      const handlers = buildHandlers()
      render(<DraftWakeToast drafts={[draft]} {...handlers} />)
      expect(screen.getByTestId('draft-wake-toast')).not.toHaveTextContent(/no reply for/i)
    })

    it('Dismiss (×) → calls onDismissOne with the draft id', () => {
      const draft = buildDraft({ id: 'x-id' })
      const handlers = buildHandlers()
      render(<DraftWakeToast drafts={[draft]} {...handlers} />)

      fireEvent.click(screen.getByTestId('draft-wake-toast-dismiss'))
      expect(handlers.onDismissOne).toHaveBeenCalledWith('x-id')
    })

    it('resets the inline error when the underlying draft id changes', async () => {
      vi.useFakeTimers()
      const handlers = buildHandlers()
      handlers.onSend.mockRejectedValueOnce(new Error('boom'))

      const { rerender } = render(
        <DraftWakeToast drafts={[buildDraft({ id: 'a' })]} {...handlers} />,
      )
      fireEvent.click(screen.getByTestId('draft-wake-toast-send'))
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000)
      })
      // The toast root is also role=status with aria-live, so query
      // specifically for the inline error alert by its body.
      expect(screen.getByText(/try again from drafts/i)).toBeInTheDocument()

      rerender(
        <DraftWakeToast drafts={[buildDraft({ id: 'b' })]} {...handlers} />,
      )
      expect(screen.queryByText(/try again from drafts/i)).toBeNull()
    })
  })

  describe('batched layout', () => {
    it('renders the batched count and three actions when there are ≥ 2 drafts', () => {
      const handlers = buildHandlers()
      render(
        <DraftWakeToast
          drafts={[buildDraft({ id: 'a' }), buildDraft({ id: 'b' }), buildDraft({ id: 'c' })]}
          {...handlers}
        />,
      )
      expect(screen.getByTestId('draft-wake-toast-batched')).toBeInTheDocument()
      expect(screen.getByTestId('draft-wake-toast-batched')).toHaveTextContent(/3/)
      expect(screen.getByTestId('draft-wake-toast-review-all')).toBeInTheDocument()
      expect(screen.getByTestId('draft-wake-toast-snooze-all')).toBeInTheDocument()
      expect(screen.getByTestId('draft-wake-toast-dismiss-all')).toBeInTheDocument()
    })

    it('Review → fires onReviewAll then onDismissAll', () => {
      const handlers = buildHandlers()
      render(
        <DraftWakeToast
          drafts={[buildDraft({ id: 'a' }), buildDraft({ id: 'b' })]}
          {...handlers}
        />,
      )
      fireEvent.click(screen.getByTestId('draft-wake-toast-review-all'))
      expect(handlers.onReviewAll).toHaveBeenCalled()
      expect(handlers.onDismissAll).toHaveBeenCalled()
    })

    it('Snooze all → fires onSnoozeAll', () => {
      const handlers = buildHandlers()
      render(
        <DraftWakeToast
          drafts={[buildDraft({ id: 'a' }), buildDraft({ id: 'b' })]}
          {...handlers}
        />,
      )
      fireEvent.click(screen.getByTestId('draft-wake-toast-snooze-all'))
      expect(handlers.onSnoozeAll).toHaveBeenCalled()
      expect(handlers.onDismissAll).not.toHaveBeenCalled()
    })

    it('Dismiss-all (×) → fires onDismissAll', () => {
      const handlers = buildHandlers()
      render(
        <DraftWakeToast
          drafts={[buildDraft({ id: 'a' }), buildDraft({ id: 'b' })]}
          {...handlers}
        />,
      )
      fireEvent.click(screen.getByTestId('draft-wake-toast-dismiss-all'))
      expect(handlers.onDismissAll).toHaveBeenCalled()
    })
  })

  describe('auto-dismiss', () => {
    it('does NOT auto-dismiss when autoDismissMs is 0 (the default)', () => {
      vi.useFakeTimers()
      const handlers = buildHandlers()
      render(<DraftWakeToast drafts={[buildDraft()]} {...handlers} />)

      act(() => {
        vi.advanceTimersByTime(120_000)
      })
      expect(handlers.onDismissAll).not.toHaveBeenCalled()
    })

    it('fires onDismissAll after autoDismissMs', () => {
      vi.useFakeTimers()
      const handlers = buildHandlers()
      render(
        <DraftWakeToast
          drafts={[buildDraft()]}
          {...handlers}
          autoDismissMs={5000}
        />,
      )

      act(() => {
        vi.advanceTimersByTime(4999)
      })
      expect(handlers.onDismissAll).not.toHaveBeenCalled()

      act(() => {
        vi.advanceTimersByTime(2)
      })
      expect(handlers.onDismissAll).toHaveBeenCalled()
    })

    it('clears the auto-dismiss timer when the drafts list changes', () => {
      vi.useFakeTimers()
      const handlers = buildHandlers()
      const { rerender } = render(
        <DraftWakeToast
          drafts={[buildDraft({ id: 'a' })]}
          {...handlers}
          autoDismissMs={5000}
        />,
      )

      act(() => {
        vi.advanceTimersByTime(3000)
      })

      // Different draft id resets the timer.
      rerender(
        <DraftWakeToast
          drafts={[buildDraft({ id: 'b' })]}
          {...handlers}
          autoDismissMs={5000}
        />,
      )

      act(() => {
        vi.advanceTimersByTime(3000)
      })
      // 6s total from start, but only 3s since the rerender — timer hasn't fired yet.
      expect(handlers.onDismissAll).not.toHaveBeenCalled()

      act(() => {
        vi.advanceTimersByTime(2500)
      })
      expect(handlers.onDismissAll).toHaveBeenCalled()
    })
  })
})
