import { renderHook, waitFor } from '@testing-library/react'
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

import { useUnviewedDraftCount } from '../hooks/useUnviewedDraftCount'

describe('useUnviewedDraftCount', () => {
  beforeEach(() => {
    localStorage.clear()
    mocks.listPendingDrafts.mockReset()
    mocks.subscribe.mockReset()
    mocks.subscribe.mockReturnValue(() => {})
  })

  it('treats malformed draft responses as an empty list', async () => {
    mocks.listPendingDrafts.mockResolvedValue({})

    const { result } = renderHook(() => useUnviewedDraftCount())

    await waitFor(() => expect(mocks.listPendingDrafts).toHaveBeenCalled())
    expect(result.current).toBe(0)
  })

  it('counts drafts already viewed in this browser', async () => {
    localStorage.setItem('agentys:viewed-drafts', JSON.stringify(['draft-1']))
    mocks.listPendingDrafts.mockResolvedValue({
      drafts: [
        { id: 'draft-1' },
        { id: 'draft-2' },
      ],
    })

    const { result } = renderHook(() => useUnviewedDraftCount())

    await waitFor(() => expect(result.current).toBe(2))
  })
})
