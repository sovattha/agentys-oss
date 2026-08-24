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

export interface ShortcutConfig {
  id: string;
  /** i18n key — resolve display text via t('settings:' + label) */
  label: string;
  defaultBinding: string;
  currentBinding: string;
  isGlobal: boolean;
  category: 'navigation' | 'composition' | 'application';
}

export const DEFAULT_SHORTCUTS: ShortcutConfig[] = [
  // Navigation — labels are i18n keys resolved via t('settings:' + label)
  { id: 'prev_email', label: 'shortcut_prev_email', defaultBinding: 'K', currentBinding: 'K', isGlobal: false, category: 'navigation' },
  { id: 'next_email', label: 'shortcut_next_email', defaultBinding: 'J', currentBinding: 'J', isGlobal: false, category: 'navigation' },
  { id: 'archive_email', label: 'shortcut_archive', defaultBinding: 'E', currentBinding: 'E', isGlobal: false, category: 'navigation' },
  { id: 'delete_email', label: 'shortcut_delete', defaultBinding: 'Delete', currentBinding: 'Delete', isGlobal: false, category: 'navigation' },
  { id: 'open_email', label: 'shortcut_open_email', defaultBinding: 'Enter', currentBinding: 'Enter', isGlobal: false, category: 'navigation' },
  { id: 'close', label: 'shortcut_close', defaultBinding: 'Escape', currentBinding: 'Escape', isGlobal: false, category: 'navigation' },
  // Composition
  { id: 'new_message', label: 'shortcut_new_message', defaultBinding: 'CmdOrCtrl+N', currentBinding: 'CmdOrCtrl+N', isGlobal: false, category: 'composition' },
  { id: 'send', label: 'shortcut_send', defaultBinding: 'CmdOrCtrl+Enter', currentBinding: 'CmdOrCtrl+Enter', isGlobal: false, category: 'composition' },
  { id: 'slash_command', label: 'shortcut_slash_commands', defaultBinding: '/', currentBinding: '/', isGlobal: false, category: 'composition' },
  // Application
  { id: 'toggle_window', label: 'shortcut_toggle_window', defaultBinding: 'CmdOrCtrl+Shift+A', currentBinding: 'CmdOrCtrl+Shift+A', isGlobal: true, category: 'application' },
  { id: 'settings', label: 'shortcut_settings', defaultBinding: 'CmdOrCtrl+,', currentBinding: 'CmdOrCtrl+,', isGlobal: false, category: 'application' },
  { id: 'refresh', label: 'shortcut_refresh', defaultBinding: 'CmdOrCtrl+R', currentBinding: 'CmdOrCtrl+R', isGlobal: false, category: 'application' },
  { id: 'help', label: 'shortcut_help', defaultBinding: 'CmdOrCtrl+/', currentBinding: 'CmdOrCtrl+/', isGlobal: false, category: 'application' },
];

export const KNOWN_SYSTEM_SHORTCUTS: string[] = [
  'CmdOrCtrl+C',
  'CmdOrCtrl+V',
  'CmdOrCtrl+X',
  'CmdOrCtrl+A',
  'CmdOrCtrl+Z',
  'CmdOrCtrl+Y',
  'CmdOrCtrl+S',
  'CmdOrCtrl+O',
  'CmdOrCtrl+P',
  'CmdOrCtrl+F',
  'CmdOrCtrl+Q',
  'CmdOrCtrl+W',
  'CmdOrCtrl+Tab',
  'CmdOrCtrl+Shift+Tab',
  'Alt+Tab',
  'Alt+F4',
];

export type ShortcutConflict = {
  type: 'app' | 'system';
  conflictingWith: string;
};

export function normalizeShortcut(shortcut: string): string {
  return shortcut
    .split('+')
    .map(key => key.trim())
    .map(key => {
      const lower = key.toLowerCase();
      if (lower === 'cmd' || lower === 'command' || lower === 'meta') return 'CmdOrCtrl';
      if (lower === 'ctrl' || lower === 'control') return 'CmdOrCtrl';
      if (lower === 'cmdorctrl') return 'CmdOrCtrl';
      if (lower === 'shift') return 'Shift';
      if (lower === 'alt' || lower === 'option') return 'Alt';
      return key.charAt(0).toUpperCase() + key.slice(1).toLowerCase();
    })
    .sort((a, b) => {
      const order = ['CmdOrCtrl', 'Shift', 'Alt'];
      const aIndex = order.indexOf(a);
      const bIndex = order.indexOf(b);
      if (aIndex === -1 && bIndex === -1) return 0;
      if (aIndex === -1) return 1;
      if (bIndex === -1) return -1;
      return aIndex - bIndex;
    })
    .join('+');
}

export function checkShortcutConflict(
  shortcut: string,
  currentShortcuts: ShortcutConfig[],
  excludeId?: string
): ShortcutConflict | null {
  const normalized = normalizeShortcut(shortcut);

  // Check against other app shortcuts
  const conflictingShortcut = currentShortcuts.find(
    s => s.id !== excludeId && normalizeShortcut(s.currentBinding) === normalized
  );

  if (conflictingShortcut) {
    return {
      type: 'app',
      conflictingWith: conflictingShortcut.label,
    };
  }

  // Check against system shortcuts
  const isSystemShortcut = KNOWN_SYSTEM_SHORTCUTS.some(
    sys => normalizeShortcut(sys) === normalized
  );

  if (isSystemShortcut) {
    return {
      type: 'system',
      conflictingWith: 'shortcut_system_conflict',
    };
  }

  return null;
}

export function formatShortcutForDisplay(shortcut: string): string {
  const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;

  return shortcut
    .replace(/CmdOrCtrl/g, isMac ? '⌘' : 'Ctrl')
    .replace(/Shift/g, isMac ? '⇧' : 'Shift')
    .replace(/Alt/g, isMac ? '⌥' : 'Alt')
    .replace(/\+/g, isMac ? '' : '+');
}
