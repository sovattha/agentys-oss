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

import { describe, it, expect } from 'vitest';
import {
  DEFAULT_SHORTCUTS,
  normalizeShortcut,
  checkShortcutConflict,
  formatShortcutForDisplay,
  KNOWN_SYSTEM_SHORTCUTS,
} from './shortcuts';

describe('shortcuts utilities', () => {
  describe('normalizeShortcut', () => {
    it('normalizes Ctrl to CmdOrCtrl', () => {
      expect(normalizeShortcut('Ctrl+A')).toBe('CmdOrCtrl+A');
    });

    it('normalizes Cmd to CmdOrCtrl', () => {
      expect(normalizeShortcut('Cmd+A')).toBe('CmdOrCtrl+A');
    });

    it('normalizes Command to CmdOrCtrl', () => {
      expect(normalizeShortcut('Command+A')).toBe('CmdOrCtrl+A');
    });

    it('normalizes Control to CmdOrCtrl', () => {
      expect(normalizeShortcut('Control+A')).toBe('CmdOrCtrl+A');
    });

    it('normalizes Meta to CmdOrCtrl', () => {
      expect(normalizeShortcut('Meta+A')).toBe('CmdOrCtrl+A');
    });

    it('normalizes Option to Alt', () => {
      expect(normalizeShortcut('Option+A')).toBe('Alt+A');
    });

    it('sorts modifiers in correct order', () => {
      expect(normalizeShortcut('Shift+Ctrl+A')).toBe('CmdOrCtrl+Shift+A');
      expect(normalizeShortcut('A+Shift+Ctrl')).toBe('CmdOrCtrl+Shift+A');
    });

    it('handles complex shortcuts', () => {
      expect(normalizeShortcut('Ctrl+Shift+Alt+A')).toBe('CmdOrCtrl+Shift+Alt+A');
    });

    it('handles lowercase keys', () => {
      expect(normalizeShortcut('ctrl+shift+a')).toBe('CmdOrCtrl+Shift+A');
    });
  });

  describe('checkShortcutConflict', () => {
    describe('app shortcut conflicts', () => {
      it('detects conflict with existing app shortcut', () => {
        const conflict = checkShortcutConflict(
          'CmdOrCtrl+Shift+A',
          DEFAULT_SHORTCUTS,
          'new_message' // excluding new_message
        );

        expect(conflict).not.toBeNull();
        expect(conflict?.type).toBe('app');
        expect(conflict?.conflictingWith).toBe('shortcut_toggle_window');
      });

      it('does not conflict with its own binding', () => {
        const conflict = checkShortcutConflict(
          'CmdOrCtrl+Shift+A',
          DEFAULT_SHORTCUTS,
          'toggle_window' // excluding itself
        );

        expect(conflict).toBeNull();
      });

      it('detects conflict with different casing', () => {
        const conflict = checkShortcutConflict(
          'cmdorctrl+shift+a',
          DEFAULT_SHORTCUTS,
          'new_message'
        );

        expect(conflict).not.toBeNull();
        expect(conflict?.type).toBe('app');
      });
    });

    describe('system shortcut conflicts', () => {
      it('detects conflict with system shortcut Cmd+C', () => {
        const conflict = checkShortcutConflict(
          'CmdOrCtrl+C',
          DEFAULT_SHORTCUTS
        );

        expect(conflict).not.toBeNull();
        expect(conflict?.type).toBe('system');
        expect(conflict?.conflictingWith).toBe('shortcut_system_conflict');
      });

      it('detects conflict with system shortcut Cmd+V', () => {
        const conflict = checkShortcutConflict(
          'CmdOrCtrl+V',
          DEFAULT_SHORTCUTS
        );

        expect(conflict).not.toBeNull();
        expect(conflict?.type).toBe('system');
      });

      it('detects conflict with system shortcut Cmd+X', () => {
        const conflict = checkShortcutConflict(
          'CmdOrCtrl+X',
          DEFAULT_SHORTCUTS
        );

        expect(conflict).not.toBeNull();
        expect(conflict?.type).toBe('system');
      });

      it('detects conflict with system shortcut Cmd+Z', () => {
        const conflict = checkShortcutConflict(
          'CmdOrCtrl+Z',
          DEFAULT_SHORTCUTS
        );

        expect(conflict).not.toBeNull();
        expect(conflict?.type).toBe('system');
      });

      it('detects conflict with system shortcut Cmd+Q', () => {
        const conflict = checkShortcutConflict(
          'CmdOrCtrl+Q',
          DEFAULT_SHORTCUTS
        );

        expect(conflict).not.toBeNull();
        expect(conflict?.type).toBe('system');
      });
    });

    describe('no conflicts', () => {
      it('returns null for unique shortcut', () => {
        const conflict = checkShortcutConflict(
          'CmdOrCtrl+Shift+B',
          DEFAULT_SHORTCUTS
        );

        expect(conflict).toBeNull();
      });

      it('returns null for shortcut not in system list', () => {
        const conflict = checkShortcutConflict(
          'CmdOrCtrl+Shift+X',
          DEFAULT_SHORTCUTS
        );

        expect(conflict).toBeNull();
      });
    });
  });

  describe('formatShortcutForDisplay', () => {
    it('formats CmdOrCtrl for display', () => {
      const formatted = formatShortcutForDisplay('CmdOrCtrl+Shift+A');
      // Will be either ⌘⇧A (Mac) or Ctrl+Shift+A (Windows/Linux)
      expect(formatted).toMatch(/^(⌘⇧A|Ctrl\+Shift\+A)$/);
    });

    it('handles single modifier', () => {
      const formatted = formatShortcutForDisplay('CmdOrCtrl+A');
      expect(formatted).toMatch(/^(⌘A|Ctrl\+A)$/);
    });

    it('handles Alt modifier', () => {
      const formatted = formatShortcutForDisplay('Alt+A');
      expect(formatted).toMatch(/^(⌥A|Alt\+A)$/);
    });
  });

  describe('DEFAULT_SHORTCUTS', () => {
    it('has correct number of default shortcuts', () => {
      expect(DEFAULT_SHORTCUTS.length).toBe(13);
    });

    it('all shortcuts have required properties', () => {
      DEFAULT_SHORTCUTS.forEach(shortcut => {
        expect(shortcut.id).toBeDefined();
        expect(shortcut.label).toBeDefined();
        expect(shortcut.defaultBinding).toBeDefined();
        expect(shortcut.currentBinding).toBeDefined();
        expect(typeof shortcut.isGlobal).toBe('boolean');
      });
    });

    it('has expected global shortcuts', () => {
      const globalShortcuts = DEFAULT_SHORTCUTS.filter(s => s.isGlobal);
      expect(globalShortcuts.length).toBe(1);

      const globalIds = globalShortcuts.map(s => s.id);
      expect(globalIds).toContain('toggle_window');
    });

    it('has expected local shortcuts', () => {
      const localShortcuts = DEFAULT_SHORTCUTS.filter(s => !s.isGlobal);
      expect(localShortcuts.length).toBe(12);

      const localIds = localShortcuts.map(s => s.id);
      expect(localIds).toContain('settings');
      expect(localIds).toContain('refresh');
      expect(localIds).toContain('help');
    });
  });

  describe('KNOWN_SYSTEM_SHORTCUTS', () => {
    it('contains common system shortcuts', () => {
      expect(KNOWN_SYSTEM_SHORTCUTS).toContain('CmdOrCtrl+C');
      expect(KNOWN_SYSTEM_SHORTCUTS).toContain('CmdOrCtrl+V');
      expect(KNOWN_SYSTEM_SHORTCUTS).toContain('CmdOrCtrl+X');
      expect(KNOWN_SYSTEM_SHORTCUTS).toContain('CmdOrCtrl+Z');
      expect(KNOWN_SYSTEM_SHORTCUTS).toContain('CmdOrCtrl+A');
      expect(KNOWN_SYSTEM_SHORTCUTS).toContain('CmdOrCtrl+S');
      expect(KNOWN_SYSTEM_SHORTCUTS).toContain('CmdOrCtrl+Q');
    });
  });
});
