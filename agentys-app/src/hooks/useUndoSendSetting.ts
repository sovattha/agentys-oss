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
