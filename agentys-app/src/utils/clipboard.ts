/**
 * Cross-browser clipboard write.
 *
 * `navigator.clipboard.writeText` is async + permission-gated and unsupported
 * on:
 *   - Safari <13.4 (no async clipboard)
 *   - Firefox <53 (no async clipboard)
 *   - HTTP contexts (modern Firefox/Chrome refuse to expose the async API)
 *   - Brave with strict shields (treats clipboard as fingerprinting surface)
 *
 * Calling it without a guard throws TypeError on those targets, which the
 * surrounding `await` rethrows uncaught and crashes the click handler.
 *
 * This helper:
 *   1. Tries `navigator.clipboard.writeText(text)` (preferred — async, secure
 *      context only).
 *   2. Falls back to a hidden-textarea + `document.execCommand('copy')` —
 *      synchronous, deprecated but universally supported including HTTP and
 *      old Safari/Firefox.
 *   3. Returns a boolean (true = copied) so callers can show a "couldn't copy
 *      — please copy manually" toast instead of an unhandled exception.
 *
 * Never throws.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Fall through to execCommand fallback. Common reasons:
      //   - permissions-policy denial
      //   - non-secure context (HTTP)
      //   - user gesture not preserved across an awaited promise
    }
  }

  if (typeof document === 'undefined') return false

  try {
    const textarea = document.createElement('textarea')
    textarea.value = text
    // Off-screen but still in the layout tree (display:none breaks selection).
    textarea.setAttribute('readonly', '')
    textarea.style.position = 'fixed'
    textarea.style.top = '0'
    textarea.style.left = '0'
    textarea.style.width = '1px'
    textarea.style.height = '1px'
    textarea.style.padding = '0'
    textarea.style.border = 'none'
    textarea.style.outline = 'none'
    textarea.style.boxShadow = 'none'
    textarea.style.background = 'transparent'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)

    // Preserve the existing selection so we don't disrupt the user's text
    // selection just because they clicked a Copy button.
    const selection = document.getSelection()
    const previousRange = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null

    textarea.select()
    textarea.setSelectionRange(0, text.length)

    let ok = false
    try {
      ok = document.execCommand('copy')
    } catch {
      ok = false
    }

    document.body.removeChild(textarea)

    if (previousRange && selection) {
      selection.removeAllRanges()
      selection.addRange(previousRange)
    }

    return ok
  } catch {
    return false
  }
}
