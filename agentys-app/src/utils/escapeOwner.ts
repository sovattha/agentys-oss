// Shared "an inner popover currently owns Escape" signal.
//
// THE BUG (LocalePickers regression class, audited 2026-05-30): a host modal
// closes on a document/window-level Escape (e.g. TrainingPage, EmailDetailModal,
// NewMessageModal, or App via useAppShortcuts). An inner dropdown/popover nested
// inside that host dismisses itself on Escape too. Pressing Escape to dismiss the
// popover ALSO reaches the host's listener and closes the whole host.
//
// Why a popup-side `stopPropagation` is NOT enough: several hosts listen in the
// CAPTURE phase on `window`, registered at app mount (useAppShortcuts.ts), or
// natively at the document level. A popover that opens later cannot register a
// listener that beats them by phase or order — capture + same-target ordering is
// decided by registration time, and the host registered first. So the only
// race-proof fix is STRUCTURAL, not ordering-based.
//
// THE CONTRACT:
//   - An inner popover tags the root element it renders WHILE OPEN with the
//     `data-escape-owner` attribute (see ESCAPE_OWNER_ATTR). Conditional render
//     means the tagged node only exists while the popover is open; React removes
//     it (and the attribute with it) on close, so there is nothing to leak — no
//     refcount needed (unlike modalOpenFlag, which shares one body attribute).
//   - Every host's Escape close-path calls `hasEscapeOwner()` first and bails if
//     true. At the moment any keydown listener runs, the popover's DOM node is
//     still present (it opened on a prior event; React has not re-rendered yet),
//     so the host sees the tag and defers. The popover then closes itself; a
//     SECOND Escape (popover now gone) closes the host. That two-press behaviour
//     is exactly what users expect.
//   - The popover MUST still have its own Escape→close handler (the host only
//     stops closing ITSELF; it does not close the popover for it).

export const ESCAPE_OWNER_ATTR = 'data-escape-owner';

/** True when an inner popover currently owns Escape (host close-paths must defer). */
export function hasEscapeOwner(): boolean {
  return (
    typeof document !== 'undefined' &&
    document.querySelector(`[${ESCAPE_OWNER_ATTR}]`) !== null
  );
}
