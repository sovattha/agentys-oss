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
import { isDeleteDraftShortcut } from './keyboard';

// Regression coverage for the 2026-06-02 delete-draft shortcut bug. The chord is
// advertised as Ctrl/⌘+Shift+, but the old handlers tested `shiftKey && key === ','`,
// which can never be true: holding Shift turns the comma key's `e.key` into its
// shifted glyph ('<' on US/UK QWERTY, '?' on AZERTY, a dead key on Canadian
// Multilingual Standard). Detection must therefore key off `e.code === 'Comma'`.
const ev = (init: KeyboardEventInit): KeyboardEvent => new KeyboardEvent('keydown', init);

describe('isDeleteDraftShortcut', () => {
  it('matches Ctrl+Shift+Comma even though Shift makes e.key "<" (US/UK QWERTY)', () => {
    // This is the exact event the old `key === ','` check silently dropped.
    expect(isDeleteDraftShortcut(ev({ code: 'Comma', key: '<', ctrlKey: true, shiftKey: true }))).toBe(true);
  });

  it('matches ⌘+Shift+Comma on macOS', () => {
    expect(isDeleteDraftShortcut(ev({ code: 'Comma', key: '<', metaKey: true, shiftKey: true }))).toBe(true);
  });

  it('matches regardless of the shifted glyph (e.g. AZERTY "?") because code wins', () => {
    expect(isDeleteDraftShortcut(ev({ code: 'Comma', key: '?', ctrlKey: true, shiftKey: true }))).toBe(true);
  });

  it('falls back to e.key === "," when code is absent', () => {
    expect(isDeleteDraftShortcut(ev({ key: ',', ctrlKey: true, shiftKey: true }))).toBe(true);
  });

  it('does NOT match Ctrl+Comma without Shift (that is the Settings shortcut)', () => {
    expect(isDeleteDraftShortcut(ev({ code: 'Comma', key: ',', ctrlKey: true, shiftKey: false }))).toBe(false);
  });

  it('does NOT match the old, mistaken Ctrl+Shift+D binding', () => {
    expect(isDeleteDraftShortcut(ev({ code: 'KeyD', key: 'D', ctrlKey: true, shiftKey: true }))).toBe(false);
  });

  it('does NOT match Shift+Comma with no Ctrl/Cmd', () => {
    expect(isDeleteDraftShortcut(ev({ code: 'Comma', key: '<', shiftKey: true }))).toBe(false);
  });

  it('does NOT match a bare comma keypress', () => {
    expect(isDeleteDraftShortcut(ev({ code: 'Comma', key: ',' }))).toBe(false);
  });
});
