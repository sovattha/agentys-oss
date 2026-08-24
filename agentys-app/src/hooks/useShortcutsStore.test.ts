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

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useShortcutsStore } from './useShortcutsStore';
import { DEFAULT_SHORTCUTS } from '../types/shortcuts';

// Mock Tauri APIs
const mockInvoke = vi.fn();
const mockEmit = vi.fn();
const mockListen = vi.fn(() => Promise.resolve(() => {}));

vi.mock('@tauri-apps/api/core', () => ({
  invoke: (cmd: string, args?: unknown) => mockInvoke(cmd, args),
}));

vi.mock('@tauri-apps/api/event', () => ({
  emit: (event: string, payload?: unknown) => mockEmit(event, payload),

  listen: (event: string, handler: () => void) => (mockListen as any)(event, handler),
}));

// Mock isTauri so the hook uses Tauri path
vi.mock('../services/tokenStorage', () => ({
  isTauri: () => true,
}));

// localStorage mock
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
    get length() { return Object.keys(store).length; },
    key: (index: number) => Object.keys(store)[index] ?? null,
  };
})();

Object.defineProperty(globalThis, 'localStorage', {
  value: localStorageMock,
  writable: true,
});

describe('useShortcutsStore', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.clear();
    mockInvoke.mockRejectedValue(new Error('Tauri not available'));
  });

  afterEach(() => {
    localStorageMock.clear();
  });

  describe('Initial load (AC4)', () => {
    it('loads default shortcuts when no stored data', async () => {
      const { result } = renderHook(() => useShortcutsStore());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.shortcuts).toEqual(DEFAULT_SHORTCUTS);
      expect(result.current.error).toBeNull();
    });

    it('loads custom shortcuts from localStorage', async () => {
      const customShortcuts = { toggle_window: 'CmdOrCtrl+Shift+X' };
      localStorage.setItem('agentys_custom_shortcuts', JSON.stringify(customShortcuts));

      const { result } = renderHook(() => useShortcutsStore());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      const toggleShortcut = result.current.shortcuts.find(s => s.id === 'toggle_window');
      expect(toggleShortcut?.currentBinding).toBe('CmdOrCtrl+Shift+X');
    });

    it('loads from Tauri store when available', async () => {
      const customShortcuts = { new_message: 'CmdOrCtrl+Shift+N' };
      mockInvoke.mockImplementation((cmd: string) => {
        if (cmd === 'get_shortcuts_config') {
          return Promise.resolve(JSON.stringify(customShortcuts));
        }
        return Promise.reject(new Error('Unknown command'));
      });

      const { result } = renderHook(() => useShortcutsStore());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      const newMessageShortcut = result.current.shortcuts.find(s => s.id === 'new_message');
      expect(newMessageShortcut?.currentBinding).toBe('CmdOrCtrl+Shift+N');
    });
  });

  describe('updateShortcuts (AC4)', () => {
    it('saves shortcuts to storage', async () => {
      mockInvoke.mockImplementation((cmd: string) => {
        if (cmd === 'get_shortcuts_config') {
          return Promise.reject(new Error('Not found'));
        }
        if (cmd === 'set_shortcuts_config') {
          return Promise.resolve();
        }
        return Promise.reject(new Error('Unknown command'));
      });
      mockEmit.mockResolvedValue(undefined);

      const { result } = renderHook(() => useShortcutsStore());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      const updatedShortcuts = DEFAULT_SHORTCUTS.map(s =>
        s.id === 'toggle_window' ? { ...s, currentBinding: 'CmdOrCtrl+Shift+Z' } : s
      );

      await act(async () => {
        await result.current.updateShortcuts(updatedShortcuts);
      });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      const toggleShortcut = result.current.shortcuts.find(s => s.id === 'toggle_window');
      expect(toggleShortcut?.currentBinding).toBe('CmdOrCtrl+Shift+Z');
    });

    it('emits shortcuts-changed event after save', async () => {
      mockInvoke.mockRejectedValue(new Error('Not available'));
      mockEmit.mockResolvedValue(undefined);

      const { result } = renderHook(() => useShortcutsStore());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      const updatedShortcuts = DEFAULT_SHORTCUTS.map(s =>
        s.id === 'toggle_window' ? { ...s, currentBinding: 'CmdOrCtrl+Shift+Z' } : s
      );

      await act(async () => {
        await result.current.updateShortcuts(updatedShortcuts);
      });

      expect(mockEmit).toHaveBeenCalledWith('shortcuts-changed', expect.any(Object));
    });
  });

  describe('resetToDefaults (AC3)', () => {
    it('resets all shortcuts to default values', async () => {
      localStorage.setItem('agentys_custom_shortcuts', JSON.stringify({
        toggle_window: 'CmdOrCtrl+Shift+X',
        new_message: 'CmdOrCtrl+Shift+Y',
      }));

      const { result } = renderHook(() => useShortcutsStore());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      // Verify custom shortcuts are loaded
      const toggleShortcut = result.current.shortcuts.find(s => s.id === 'toggle_window');
      expect(toggleShortcut?.currentBinding).toBe('CmdOrCtrl+Shift+X');

      await act(async () => {
        await result.current.resetToDefaults();
      });

      // Verify defaults are restored
      expect(result.current.shortcuts).toEqual(DEFAULT_SHORTCUTS);
    });

    it('clears storage on reset', async () => {
      localStorage.setItem('agentys_custom_shortcuts', JSON.stringify({
        toggle_window: 'CmdOrCtrl+Shift+X',
      }));

      const { result } = renderHook(() => useShortcutsStore());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      await act(async () => {
        await result.current.resetToDefaults();
      });

      expect(localStorage.getItem('agentys_custom_shortcuts')).toBeNull();
    });

    it('emits shortcuts-changed event after reset', async () => {
      mockEmit.mockResolvedValue(undefined);

      const { result } = renderHook(() => useShortcutsStore());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      await act(async () => {
        await result.current.resetToDefaults();
      });

      expect(mockEmit).toHaveBeenCalledWith('shortcuts-changed', {
        shortcuts: DEFAULT_SHORTCUTS,
      });
    });
  });

  describe('Error handling', () => {
    it('handles storage errors gracefully', async () => {
      // Simulate localStorage error
      const originalGetItem = localStorage.getItem;
      localStorage.getItem = () => {
        throw new Error('Storage error');
      };

      const { result } = renderHook(() => useShortcutsStore());

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      // Should fall back to defaults
      expect(result.current.shortcuts).toEqual(DEFAULT_SHORTCUTS);

      // Restore
      localStorage.getItem = originalGetItem;
    });
  });
});
