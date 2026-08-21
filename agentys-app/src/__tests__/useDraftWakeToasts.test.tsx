import { renderHook, waitFor, act } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  listPendingDrafts: vi.fn(),
  subscribe: vi.fn(),
}))

vi.mock('../services/api', () => ({
  apiClient: {
    listPendingDrafts: mocks.listPendingDrafts,
  },
}))

vi.mock('../services/websocket', () => ({
  getWebSocketClient: () => ({
    subscribe: mocks.subscribe,
  }),
}))

import { useDraftWakeToasts } from '../hooks/useDraftWakeToasts'
import { _resetFiredStore, markFired } from '../services/draftWakeStore'

type DraftStub = {
  id: string
  routing_tier?: string
  snoozed_until?: string
  status?: string
}

function buildResponse(stubs: DraftStub[]) {
  const drafts = stubs.map((s) => ({
    id: s.id,
    email_id: `email-${s.id}`,
    email_sender: 'alex.doe@acme.com',
    email_sender_name: 'Alex Doe',
    email_subject: 'Subject',
    email_body: 'Body',
    draft_subject: 'Re: Subject',
    draft_body: 'Hi Alex',
    draft_v1: '',
    critique: '',
    classification: '',
    priority: 50,
    confidence: 0.85,
    routing_tier: s.routing_tier ?? 'followup',
    snoozed_until: s.snoozed_until,
    status: s.status ?? 'pending',
    created_at: '2026-05-19T09:00:00Z',
  }))
  return { count: drafts.length, pending_count: drafts.length, drafts }
}

describe('useDraftWakeToasts', () => {
  beforeEach(() => {
    _resetFiredStore()
    mocks.listPendingDrafts.mockReset()
    mocks.subscribe.mockReset()
    mocks.subscribe.mockReturnValue(() => {})
    vi.useRealTimers()
  })

  it('surfaces a woken follow-up draft', async () => {
    mocks.listPendingDrafts.mockResolvedValue(buildResponse([{ id: 'd1' }]))

    const { result } = renderHook(() => useDraftWakeToasts())

    await waitFor(() => expect(result.current.visibleDrafts).toHaveLength(1))
    expect(result.current.visibleDrafts[0].id).toBe('d1')
  })

  it('filters out drafts that still have a snoozed_until set', async () => {
    mocks.listPendingDrafts.mockResolvedValue(
      buildResponse([
        { id: 'still-sleeping', snoozed_until: '2026-05-20T09:00:00Z' },
        { id: 'just-woke' },
      ]),
    )

    const { result } = renderHook(() => useDraftWakeToasts())

    await waitFor(() => expect(result.current.visibleDrafts).toHaveLength(1))
    expect(result.current.visibleDrafts[0].id).toBe('just-woke')
  })

  it('filters out non-followup routing tiers', async () => {
    mocks.listPendingDrafts.mockResolvedValue(
      buildResponse([
        { id: 'standard', routing_tier: 'standard' },
        { id: 'simple', routing_tier: 'simple' },
        { id: 'followup', routing_tier: 'followup' },
      ]),
    )

    const { result } = renderHook(() => useDraftWakeToasts())

    await waitFor(() => expect(result.current.visibleDrafts).toHaveLength(1))
    expect(result.current.visibleDrafts[0].id).toBe('followup')
  })

  it('filters out non-pending statuses defensively', async () => {
    mocks.listPendingDrafts.mockResolvedValue(
      buildResponse([
        { id: 'sent-draft', status: 'sent' },
        { id: 'rejected-draft', status: 'rejected' },
        { id: 'pending-draft', status: 'pending' },
      ]),
    )

    const { result } = renderHook(() => useDraftWakeToasts())

    await waitFor(() => expect(result.current.visibleDrafts).toHaveLength(1))
    expect(result.current.visibleDrafts[0].id).toBe('pending-draft')
  })

  it('dedups drafts already marked fired', async () => {
    markFired('already-seen')
    mocks.listPendingDrafts.mockResolvedValue(
      buildResponse([{ id: 'already-seen' }, { id: 'new-one' }]),
    )

    const { result } = renderHook(() => useDraftWakeToasts())

    await waitFor(() => expect(result.current.visibleDrafts).toHaveLength(1))
    expect(result.current.visibleDrafts[0].id).toBe('new-one')
  })

  it('dismissOne marks the draft fired and removes it from visibleDrafts', async () => {
    mocks.listPendingDrafts.mockResolvedValue(
      buildResponse([{ id: 'd1' }, { id: 'd2' }]),
    )

    const { result } = renderHook(() => useDraftWakeToasts())

    await waitFor(() => expect(result.current.visibleDrafts).toHaveLength(2))

    act(() => {
      result.current.dismissOne('d1')
    })

    expect(result.current.visibleDrafts.map((d) => d.id)).toEqual(['d2'])
  })

  it('dismissAll marks every visible draft fired', async () => {
    mocks.listPendingDrafts.mockResolvedValue(
      buildResponse([{ id: 'd1' }, { id: 'd2' }, { id: 'd3' }]),
    )

    const { result } = renderHook(() => useDraftWakeToasts())

    await waitFor(() => expect(result.current.visibleDrafts).toHaveLength(3))

    act(() => {
      result.current.dismissAll()
    })

    expect(result.current.visibleDrafts).toHaveLength(0)
  })

  it('snoozeOne removes the draft from visibleDrafts immediately', async () => {
    mocks.listPendingDrafts.mockResolvedValue(
      buildResponse([{ id: 'd-snooze' }, { id: 'd-other' }]),
    )

    const { result } = renderHook(() => useDraftWakeToasts())
    await waitFor(() => expect(result.current.visibleDrafts).toHaveLength(2))

    act(() => {
      result.current.snoozeOne('d-snooze')
    })

    expect(result.current.visibleDrafts.map((d) => d.id)).toEqual(['d-other'])
    // TTL re-fire behavior is covered by draftWakeStore.test — here we only
    // assert the hook's filtering surface.
  })

  it('snoozeAll removes every visible draft', async () => {
    mocks.listPendingDrafts.mockResolvedValue(
      buildResponse([{ id: 'a' }, { id: 'b' }]),
    )

    const { result } = renderHook(() => useDraftWakeToasts())
    await waitFor(() => expect(result.current.visibleDrafts).toHaveLength(2))

    act(() => {
      result.current.snoozeAll(60_000)
    })

    expect(result.current.visibleDrafts).toHaveLength(0)
  })

  it('re-fetches when a draft_ready WebSocket event fires', async () => {
    let wsHandler: ((event: { type: string }) => void) | null = null
    mocks.subscribe.mockImplementation((cb: (event: { type: string }) => void) => {
      wsHandler = cb
      return () => {}
    })
    mocks.listPendingDrafts.mockResolvedValue(buildResponse([{ id: 'first' }]))

    const { result } = renderHook(() => useDraftWakeToasts())
    await waitFor(() => expect(result.current.visibleDrafts).toHaveLength(1))

    mocks.listPendingDrafts.mockResolvedValueOnce(
      buildResponse([{ id: 'first' }, { id: 'second' }]),
    )

    await act(async () => {
      wsHandler?.({ type: 'draft_ready' })
    })

    await waitFor(() => expect(result.current.visibleDrafts).toHaveLength(2))
  })

  it('survives a listPendingDrafts rejection without throwing', async () => {
    mocks.listPendingDrafts.mockRejectedValue(new Error('network'))

    const { result } = renderHook(() => useDraftWakeToasts())
    await waitFor(() => expect(mocks.listPendingDrafts).toHaveBeenCalled())
    expect(result.current.visibleDrafts).toHaveLength(0)
  })

  it('treats malformed responses as empty rather than throwing', async () => {
    mocks.listPendingDrafts.mockResolvedValue({})

    const { result } = renderHook(() => useDraftWakeToasts())
    await waitFor(() => expect(mocks.listPendingDrafts).toHaveBeenCalled())
    expect(result.current.visibleDrafts).toHaveLength(0)
  })

  it('does not setState after unmount when fetch resolves late', async () => {
    let resolveFetch: (value: unknown) => void = () => {}
    mocks.listPendingDrafts.mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve
      }),
    )

    const { unmount } = renderHook(() => useDraftWakeToasts())
    unmount()
    // Resolving after unmount should not throw or warn.
    resolveFetch(buildResponse([{ id: 'late' }]))
    // Wait a microtask tick for the promise chain to flush.
    await Promise.resolve()
  })
})
