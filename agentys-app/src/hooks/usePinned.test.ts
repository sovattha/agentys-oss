import { renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// usePinned imports these from ../services/api. fetchPinnedEmailIds drives the
// mount reconcile; pin/unpin are only referenced by toggle/addPin (unused here).
vi.mock('../services/api', () => ({
  fetchPinnedEmailIds: vi.fn(),
  pinEmail: vi.fn(() => Promise.resolve()),
  unpinEmail: vi.fn(() => Promise.resolve()),
}));

import { usePinned } from './usePinned';
import { fetchPinnedEmailIds } from '../services/api';

const mockFetch = fetchPinnedEmailIds as unknown as ReturnType<typeof vi.fn>;

describe('usePinned — authoritative backend reconcile', () => {
  beforeEach(() => {
    localStorage.clear();
    mockFetch.mockReset();
  });

  it('drops a local pin the backend no longer reports (server-side unpin)', async () => {
    // Mirrors a follow-up that was auto-unpinned server-side on send/reject:
    // 'a' lingers in localStorage but the backend no longer pins it.
    localStorage.setItem('agentys_pinned', JSON.stringify(['a', 'b']));
    mockFetch.mockResolvedValue({ pinned_ids: ['b'] });

    const { result } = renderHook(() => usePinned());

    await waitFor(() => expect(result.current.pinnedIds.has('a')).toBe(false));
    expect(result.current.pinnedIds.has('b')).toBe(true);
  });

  it('adopts a backend pin absent locally (wake sweep pinned it)', async () => {
    localStorage.setItem('agentys_pinned', JSON.stringify([]));
    mockFetch.mockResolvedValue({ pinned_ids: ['thread-9'] });

    const { result } = renderHook(() => usePinned());

    await waitFor(() => expect(result.current.pinnedIds.has('thread-9')).toBe(true));
  });

  it('leaves local state intact when the backend fetch fails', async () => {
    localStorage.setItem('agentys_pinned', JSON.stringify(['a']));
    mockFetch.mockRejectedValue(new Error('network down'));

    const { result } = renderHook(() => usePinned());

    // Let the rejected promise settle, then assert nothing was dropped.
    await new Promise((r) => setTimeout(r, 0));
    expect(result.current.pinnedIds.has('a')).toBe(true);
  });

  it('leaves local state intact when the backend payload is malformed', async () => {
    localStorage.setItem('agentys_pinned', JSON.stringify(['a']));
    mockFetch.mockResolvedValue({} as { pinned_ids: string[] });

    const { result } = renderHook(() => usePinned());

    await new Promise((r) => setTimeout(r, 0));
    expect(result.current.pinnedIds.has('a')).toBe(true);
  });
});
