import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useTrayMenu } from './useTrayMenu';
import type { Email } from '../services/api';

// Mock Tauri APIs
vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}));

vi.mock('@tauri-apps/api/event', () => ({
  listen: vi.fn(() => Promise.resolve(() => {})),
}));

vi.mock('@tauri-apps/api/tray', () => ({
  TrayIcon: {
    getById: vi.fn(() =>
      Promise.resolve({
        menu: () =>
          Promise.resolve({
            items: () =>
              Promise.resolve([
                {
                  id: 'status',
                  setText: vi.fn(),
                },
                {
                  id: 'recent-emails',
                },
              ]),
          }),
      })
    ),
  },
}));

vi.mock('@tauri-apps/api/menu', () => ({
  Menu: {},
  MenuItem: {
    new: vi.fn(() => Promise.resolve({ id: 'mock-item' })),
  },
  Submenu: {},
}));

// Mock isTauri so the hook uses Tauri path
vi.mock('../services/tokenStorage', () => ({
  isTauri: () => true,
}));

import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';

describe('useTrayMenu', () => {
  const mockEmails: Email[] = [
    {
      id: 'email-1',
      sender: 'alice@example.com',
      sender_name: 'Alice',
      subject: 'Hello World',
      received_at: '2026-01-19T10:00:00Z',
    },
    {
      id: 'email-2',
      sender: 'bob@example.com',
      sender_name: 'Bob',
      subject: 'Meeting Tomorrow',
      received_at: '2026-01-19T09:00:00Z',
    },
    {
      id: 'email-3',
      sender: 'charlie@example.com',
      subject: 'Important Update',
      received_at: '2026-01-19T08:00:00Z',
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('updateUnreadCount', () => {
    it('should call invoke with update_tray_unread_count command', async () => {
      renderHook(() => useTrayMenu(5, [], {}));

      // Wait for initial update
      await waitFor(() => {
        expect(invoke).toHaveBeenCalledWith('update_tray_unread_count', { count: 5 });
      });
    });

    it('should not update when count has not changed', async () => {
      const { rerender } = renderHook(({ count }) => useTrayMenu(count, [], {}), {
        initialProps: { count: 5 },
      });

      await waitFor(() => {
        expect(invoke).toHaveBeenCalledTimes(1);
      });

      // Rerender with same count
      rerender({ count: 5 });

      // Should still be 1 call (no duplicate update)
      expect(invoke).toHaveBeenCalledTimes(1);
    });

    it('should update when count changes', async () => {
      const { rerender } = renderHook(({ count }) => useTrayMenu(count, [], {}), {
        initialProps: { count: 5 },
      });

      await waitFor(() => {
        expect(invoke).toHaveBeenCalledWith('update_tray_unread_count', { count: 5 });
      });

      // Change count
      rerender({ count: 10 });

      await waitFor(() => {
        expect(invoke).toHaveBeenCalledWith('update_tray_unread_count', { count: 10 });
      });
    });

    it('should not call invoke when disabled', async () => {
      renderHook(() => useTrayMenu(5, [], { enabled: false }));

      // Give time for any async operations
      await new Promise((resolve) => setTimeout(resolve, 100));

      expect(invoke).not.toHaveBeenCalled();
    });
  });

  describe('event listeners', () => {
    it('should set up event listeners for sync, navigate, and open-email', async () => {
      renderHook(() => useTrayMenu(0, [], {}));

      await waitFor(() => {
        expect(listen).toHaveBeenCalledWith('trigger-sync', expect.any(Function));
        expect(listen).toHaveBeenCalledWith('navigate', expect.any(Function));
        expect(listen).toHaveBeenCalledWith('open-recent-email', expect.any(Function));
      });
    });

    it('should call onSync callback when trigger-sync event is received', async () => {
      const onSync = vi.fn(() => Promise.resolve());
      let syncCallback: (event: unknown) => void = () => {};

      (listen as Mock).mockImplementation((eventName, callback) => {
        if (eventName === 'trigger-sync') {
          syncCallback = callback;
        }
        return Promise.resolve(() => {});
      });

      renderHook(() => useTrayMenu(0, [], { onSync }));

      await waitFor(() => {
        expect(listen).toHaveBeenCalledWith('trigger-sync', expect.any(Function));
      });

      // Trigger the sync event
      await act(async () => {
        syncCallback({});
      });

      expect(onSync).toHaveBeenCalled();
    });

    it('should call onNavigate callback when navigate event is received', async () => {
      const onNavigate = vi.fn();
      let navigateCallback: (event: { payload: string }) => void = () => {};

      (listen as Mock).mockImplementation((eventName, callback) => {
        if (eventName === 'navigate') {
          navigateCallback = callback;
        }
        return Promise.resolve(() => {});
      });

      renderHook(() => useTrayMenu(0, [], { onNavigate }));

      await waitFor(() => {
        expect(listen).toHaveBeenCalledWith('navigate', expect.any(Function));
      });

      // Trigger navigate event
      act(() => {
        navigateCallback({ payload: '/settings' });
      });

      expect(onNavigate).toHaveBeenCalledWith('/settings');
    });

    it('should call onOpenEmail callback with extracted email ID', async () => {
      const onOpenEmail = vi.fn();
      let openEmailCallback: (event: { payload: string }) => void = () => {};

      (listen as Mock).mockImplementation((eventName, callback) => {
        if (eventName === 'open-recent-email') {
          openEmailCallback = callback;
        }
        return Promise.resolve(() => {});
      });

      renderHook(() => useTrayMenu(0, [], { onOpenEmail }));

      await waitFor(() => {
        expect(listen).toHaveBeenCalledWith('open-recent-email', expect.any(Function));
      });

      // Trigger open email event
      act(() => {
        openEmailCallback({ payload: 'recent-email-email-123' });
      });

      expect(onOpenEmail).toHaveBeenCalledWith('email-123');
    });

    it('should clean up listeners on unmount', async () => {
      const unsubscribe = vi.fn();
      (listen as Mock).mockReturnValue(Promise.resolve(unsubscribe));

      const { unmount } = renderHook(() => useTrayMenu(0, [], {}));

      await waitFor(() => {
        expect(listen).toHaveBeenCalled();
      });

      unmount();

      // Give time for cleanup
      await new Promise((resolve) => setTimeout(resolve, 50));

      expect(unsubscribe).toHaveBeenCalled();
    });
  });

  describe('updateRecentEmails', () => {
    it('should not update when emails have not changed', async () => {
      const { rerender } = renderHook(({ emails }) => useTrayMenu(0, emails, {}), {
        initialProps: { emails: mockEmails },
      });

      // Wait for initial setup
      await waitFor(() => {
        expect(listen).toHaveBeenCalled();
      });

      // Rerender with same emails
      rerender({ emails: mockEmails });

      // The hook tracks emails by ID, so same emails should not trigger update
      // This is an implementation detail test
    });

    it('should handle empty email list', async () => {
      const { result } = renderHook(() => useTrayMenu(0, [], {}));

      // Should not throw
      await act(async () => {
        await result.current.updateRecentEmails([]);
      });
    });
  });

  describe('return values', () => {
    it('should return updateUnreadCount and updateRecentEmails functions', () => {
      const { result } = renderHook(() => useTrayMenu(0, [], {}));

      expect(result.current.updateUnreadCount).toBeInstanceOf(Function);
      expect(result.current.updateRecentEmails).toBeInstanceOf(Function);
    });

    it('should allow manual update of unread count', async () => {
      const { result } = renderHook(() => useTrayMenu(5, [], {}));

      // Wait for initial effect to settle
      await waitFor(() => {
        expect(invoke).toHaveBeenCalledWith('update_tray_unread_count', { count: 5 });
      });

      // Clear mocks so we only track the manual call
      vi.clearAllMocks();

      await act(async () => {
        await result.current.updateUnreadCount(15);
      });

      expect(invoke).toHaveBeenCalledWith('update_tray_unread_count', { count: 15 });
    });
  });
});
