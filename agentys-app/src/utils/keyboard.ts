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

// Shared keyboard-chord predicates.
//
// THE BUG (delete-draft shortcut, fixed 2026-06-02): the "delete draft" chord is
// advertised across the UI (the App.tsx shortcuts ribbon and the shortcuts help
// panel) as  Ctrl/⌘ + Shift + ,  yet it did nothing on every surface that
// offered it — the compose modal, the reply-inside-an-email composer, AND the
// Drafts page. (The reply composer was doubly broken: it listened for Ctrl+Shift+D.)
//
// Root cause: the handlers tested `e.shiftKey && e.key === ','`. With Shift held,
// `KeyboardEvent.key` is the comma key's SHIFTED glyph and is NEVER ',':
//   • US / UK QWERTY ............... '<'
//   • Canadian Multilingual Std .... a dead key / apostrophe
//   • French AZERTY ................ '?'
// so `shiftKey && key === ','` is a contradiction that cannot fire on a real
// keyboard. (The codebase already half-knew this: useAppShortcuts treats
// Shift+'/' as the glyph '?', not '/'.)
//
// THE FIX: match on `KeyboardEvent.code`, which reports the PHYSICAL key
// independent of Shift and layout ('Comma' for the comma key on QWERTY-family
// boards). The `e.key` glyph fallbacks keep boards that don't populate `code`
// working. All three surfaces call this so they stay in lockstep with the hint.

/**
 * True for the "delete draft" chord — Ctrl (Windows/Linux) or ⌘ (Mac) + Shift + ,
 *
 * Detection is `code`-first on purpose: with Shift held `e.key` is the shifted
 * glyph of the comma key (`<`, `?`, a dead key…), never ',', so a
 * `shiftKey && key === ','` test can never match. See the file header.
 */
export function isDeleteDraftShortcut(e: KeyboardEvent): boolean {
  if (!(e.ctrlKey || e.metaKey) || !e.shiftKey) return false;
  return e.code === 'Comma' || e.key === ',' || e.key === '<';
}
