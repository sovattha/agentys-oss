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

/**
 * Undo Send — always 15s delay, no user setting.
 * Kept as a module for backward compatibility with imports.
 */

// 2026-05-13: user requested immediate send (no undo window). Kept as 0 instead
// of removing the helper so all callsites that import it continue to compile —
// `registerPendingSend(..., 0)` still goes through localStorage persistence,
// which is what protects against a window-close mid-send.
const UNDO_SEND_DELAY = 0;

/** Standalone getter for use outside React (e.g. in PendingDraftDetail) */
export function getUndoSendDelay(): number {
  return UNDO_SEND_DELAY;
}

/**
 * @deprecated — delay is now hardcoded to 15s. Hook kept for Settings import compat.
 */
export function useUndoSendSetting() {
  return {
    undoSendDelay: UNDO_SEND_DELAY,
    setUndoSendDelay: (_v: number) => { /* no-op */ },
  };
}
