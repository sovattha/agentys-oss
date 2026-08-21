import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  clearDraftStreamState,
  getDraftStreamState,
  subscribeDraftStream,
  useWebSocketSync,
} from './useWebSocketSync'
import type { WebSocketEvent } from '../services/websocket'
import { __resetQueryClientForTests, getQueryClient } from '../lib/queryClient'

const mockSubscribe = vi.fn()
const mockConnect = vi.fn()
const mockNotifyNewEmail = vi.fn()
const mockOnRefresh = vi.fn()
let eventHandler: ((event: WebSocketEvent) => void) | undefined

vi.mock('../services/websocket', () => ({
  getWebSocketClient: vi.fn(() => ({
    subscribe: mockSubscribe,
    connect: mockConnect,
  })),
}))

vi.mock('../services/notifications', () => ({
  getNotificationService: vi.fn(() => ({
    notifyNewEmail: mockNotifyNewEmail,
  })),
}))

vi.mock('../services/uiSounds', () => ({
  playUISound: vi.fn(),
}))

vi.mock('../api/emails', () => ({
  invalidateEmailCache: vi.fn(),
  getActiveAccountId: vi.fn(() => '7'),
}))

describe('useWebSocketSync', () => {
  beforeEach(() => {
    __resetQueryClientForTests()
    vi.clearAllMocks()
    eventHandler = undefined
    mockSubscribe.mockImplementation((handler: (event: WebSocketEvent) => void) => {
      eventHandler = handler
      return () => {}
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    __resetQueryClientForTests()
  })

  it('ne connecte pas le socket tant que isAuthenticated est false (login page)', () => {
    renderHook(() => useWebSocketSync({
      backendStatus: 'connected',
      onRefresh: mockOnRefresh,
      isAuthenticated: false,
    }))

    // No handshake on the login screen — this is what prevents the
    // `wss://…/socket.io/ Invalid frame header` failure + reconnect storm.
    expect(mockConnect).not.toHaveBeenCalled()
    expect(mockSubscribe).not.toHaveBeenCalled()
  })

  it('connecte le socket une fois isAuthenticated true', () => {
    const { rerender } = renderHook(
      ({ authed }: { authed: boolean }) => useWebSocketSync({
        backendStatus: 'connected',
        onRefresh: mockOnRefresh,
        isAuthenticated: authed,
      }),
      { initialProps: { authed: false } },
    )

    expect(mockConnect).not.toHaveBeenCalled()

    rerender({ authed: true })

    expect(mockConnect).toHaveBeenCalledOnce()
    expect(mockSubscribe).toHaveBeenCalledOnce()
  })

  it('applique new_email via WebSocket sans refresh HTTP quand la liste le prend en charge', () => {
    const handled = vi.fn((event: Event) => event.preventDefault())
    window.addEventListener('agentys:email-upsert', handled)

    try {
      renderHook(() => useWebSocketSync({
        backendStatus: 'connected',
        onRefresh: mockOnRefresh,
        isAuthenticated: true,
      }))

      act(() => {
        eventHandler?.({
          type: 'new_email',
          data: {
            email_id: 'email-1',
            account_id: 7,
            sender: 'alice@example.com',
            sender_name: 'Alice',
            subject: 'Bonjour',
            received_at: '2026-05-13T10:00:00Z',
            is_read: false,
            has_attachments: false,
            conversation_id: 'thread-1',
            body_preview: 'Aperçu',
          },
        })
      })

      expect(handled).toHaveBeenCalledOnce()
      expect(mockOnRefresh).not.toHaveBeenCalled()
    } finally {
      window.removeEventListener('agentys:email-upsert', handled)
    }
  })

  it('garde le refresh HTTP comme fallback si aucun composant ne consomme le new_email', () => {
    renderHook(() => useWebSocketSync({
      backendStatus: 'connected',
      onRefresh: mockOnRefresh,
      isAuthenticated: true,
    }))

    act(() => {
      eventHandler?.({
        type: 'new_email',
        data: {
          email_id: 'email-1',
          account_id: 7,
          sender: 'alice@example.com',
          subject: 'Bonjour',
        },
      })
    })

    expect(mockOnRefresh).toHaveBeenCalledOnce()
  })

  it('rafraîchit les compteurs de labels quand un email passe lu/non lu', () => {
    const queryClient = getQueryClient()
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    renderHook(() => useWebSocketSync({
      backendStatus: 'connected',
      onRefresh: mockOnRefresh,
      isAuthenticated: true,
    }))

    act(() => {
      eventHandler?.({
        type: 'email_updated',
        data: {
          email_id: 'email-action-1',
          updates: { is_read: true },
        },
      })
    })

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['labelCounts'] })
  })

  it('attend la V2 au lieu de finaliser sur un draft_complete V1 rejeté', () => {
    const emailId = 'email-revised'
    const v1 = 'Hi Nathan,\n\nBest regards,'
    const v2 = 'Hi Nathan,\n\nbackend-tests failed. I will check the annotation.\n\nBest regards,'
    const streamedStates: string[] = []
    const unsubscribe = subscribeDraftStream((state) => {
      if (state.emailId === emailId) streamedStates.push(state.accumulatedText)
    })

    try {
      clearDraftStreamState(emailId)
      renderHook(() => useWebSocketSync({
        backendStatus: 'connected',
        onRefresh: mockOnRefresh,
        isAuthenticated: true,
      }))

      act(() => {
        eventHandler?.({
          type: 'critique_complete',
          data: {
            email_id: emailId,
            decision: 'reject',
            overall_score: 52,
            suggestions: ['Draft is incomplete'],
          },
        })
      })

      act(() => {
        eventHandler?.({
          type: 'draft_complete',
          data: {
            email_id: emailId,
            draft: v1,
            confidence: 0.8,
            generation_time_ms: 1431,
            tokens_used: 5,
          },
        })
      })

      expect(getDraftStreamState(emailId)?.isComplete).toBe(false)
      expect(getDraftStreamState(emailId)?.expectsNewVersion).toBe(true)
      expect(mockOnRefresh).not.toHaveBeenCalled()

      act(() => {
        eventHandler?.({
          type: 'draft_revised',
          data: {
            email_id: emailId,
            v1,
            v2,
            critique_summary: 'Draft is incomplete',
          },
        })
      })

      expect(getDraftStreamState(emailId)?.isComplete).toBe(true)
      expect(getDraftStreamState(emailId)?.accumulatedText).toBe(v2)
      expect(streamedStates[streamedStates.length - 1]).toBe(v2)
    } finally {
      unsubscribe()
      clearDraftStreamState(emailId)
    }
  })
})
