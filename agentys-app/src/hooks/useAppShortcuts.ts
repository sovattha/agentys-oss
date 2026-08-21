import { useEffect, useRef } from 'react'
import { isTauri } from '../services/tokenStorage'
import { setKeyboardNavMode, triggerKeyboardPulse } from '../components/SwipeableEmailItem'
import { API_URL } from '../config'
import { getAuthHeaders, getStoredToken } from '../services/authToken'
import { hasEscapeOwner } from '../utils/escapeOwner'

/** Fire-and-forget shortcut tracking (batched: flushes every 4s or at 10 actions) */
let _shortcutBuffer = 0
let _shortcutTimer: ReturnType<typeof setTimeout> | null = null
function _flushShortcuts() {
  if (_shortcutBuffer <= 0) return
  const count = _shortcutBuffer
  _shortcutBuffer = 0
  _shortcutTimer = null
  // Audit 2026-05-18: this telemetry endpoint sits behind the api_bp auth
  // gate, so the bare-fetch (no Authorization header) version produced a
  // steady stream of 401s on cloud. Skip the call entirely when no JWT is
  // stored (logged-out / Tauri-loopback paths) and otherwise pass auth.
  if (!getStoredToken()) return
  fetch(`${API_URL}/api/stats/feature`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ feature: 'shortcut', count }),
  }).catch(() => { /* fire-and-forget */ })
}
function trackShortcut() {
  _shortcutBuffer++
  if (_shortcutBuffer >= 10) { if (_shortcutTimer) clearTimeout(_shortcutTimer); _flushShortcuts(); return }
  if (!_shortcutTimer) _shortcutTimer = setTimeout(_flushShortcuts, 4000)
}

type UnlistenFn = () => void

// Dynamic Tauri import
async function getTauriEvent() {
  if (!isTauri()) return null
  try {
    return await import('@tauri-apps/api/event')
  } catch {
    return null
  }
}

export interface AppShortcutsConfig {
  onShowShortcutsHelp?: () => void
  onOpenSettings?: () => void
  onRefreshEmails?: () => void
  onCloseModal?: () => void
  onNavigateUp?: () => void
  onNavigateDown?: () => void
  onOpenSelected?: () => void
  onNewMessage?: () => void
  onCommandPalette?: () => void
  onReply?: () => void
  onReplyAll?: () => void
  onForward?: () => void
  onArchive?: () => void
  onDelete?: () => void
  onToggleRead?: () => void
  onSearch?: () => void
  onSelectAll?: () => void
  onSelectAllFromHere?: () => void
  onZoomIn?: () => void
  onZoomOut?: () => void
  onZoomReset?: () => void
  enabled?: boolean
  /** When true, ArrowLeft/ArrowRight are handled by the detail panel — skip them here */
  detailPanelVisible?: boolean
}

export function useAppShortcuts(config: AppShortcutsConfig): void {
  // Always-fresh ref — no stale closures, no listener re-registration
  const configRef = useRef(config)
  configRef.current = config

  // Listen for global shortcut events from Tauri backend
  useEffect(() => {
    let unlistenShowShortcuts: UnlistenFn | undefined

    const setupListeners = async () => {
      const eventModule = await getTauriEvent()
      if (!eventModule) return

      unlistenShowShortcuts = await eventModule.listen('show-shortcuts-help', () => {
        configRef.current.onShowShortcutsHelp?.()
      })
    }

    setupListeners()

    return () => {
      unlistenShowShortcuts?.()
    }
  }, [])

  // Register keyboard listener ONCE — reads latest config via ref
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const c = configRef.current
      const isMeta = event.metaKey || event.ctrlKey
      const key = event.key.toLowerCase()

      if (c.enabled === false) return

      // Cmd/Ctrl+, opens settings
      if (isMeta && key === ',') {
        event.preventDefault()
        c.onOpenSettings?.()
        return
      }

      // Cmd/Ctrl+R refreshes email list
      if (isMeta && key === 'r') {
        event.preventDefault()
        trackShortcut()
        c.onRefreshEmails?.()
        return
      }

      // Cmd/Ctrl+= ou Cmd/Ctrl++ : zoom in (sur AZERTY / QWERTY / pavé numérique)
      if (isMeta && (key === '=' || key === '+' || event.code === 'NumpadAdd')) {
        event.preventDefault()
        trackShortcut()
        c.onZoomIn?.()
        return
      }

      // Cmd/Ctrl+- : zoom out (pavé numérique inclus)
      if (isMeta && (key === '-' || event.code === 'NumpadSubtract')) {
        event.preventDefault()
        trackShortcut()
        c.onZoomOut?.()
        return
      }

      // Cmd/Ctrl+0 : reset zoom
      if (isMeta && (key === '0' || event.code === 'Numpad0' || event.code === 'Digit0')) {
        event.preventDefault()
        trackShortcut()
        c.onZoomReset?.()
        return
      }

      // Cmd/Ctrl+/ shows shortcuts help
      if (isMeta && key === '/') {
        event.preventDefault()
        c.onShowShortcutsHelp?.()
        return
      }

      // Cmd/Ctrl+K opens command palette
      if (isMeta && key === 'k') {
        event.preventDefault()
        trackShortcut()
        c.onCommandPalette?.()
        return
      }

      // Ctrl+Shift+O/S/C/B — composer field shortcuts (To/Subject/Cc/Bcc)
      // Also handle dead-key variants (some keyboards send ç/ø instead of c/o with Ctrl+Shift)
      const normalizedKey = key === 'ç' ? 'c' : key === 'ø' ? 'o' : key
      if (isMeta && event.shiftKey && (normalizedKey === 'o' || normalizedKey === 's' || normalizedKey === 'c' || normalizedKey === 'b')) {
        event.preventDefault()
        window.dispatchEvent(new CustomEvent('agentys:composer-field', { detail: { key: normalizedKey } }))
        return
      }

      // Ctrl+Shift+A — select all emails
      // QA 2026-05-18: on the web build this synchronous select-all on a 400+
      // email inbox locks the renderer for tens of seconds (the tab becomes
      // unresponsive to screenshots / waits). The shortcut is also taken by
      // Chrome itself (tab search) on the web. The in-app help labels this
      // hotkey "Open / Close Agentys", which only makes sense in the Tauri
      // desktop build. So: skip entirely on web, and on Tauri defer the heavy
      // walk to a microtask so the keydown unwinds first.
      if (isMeta && event.shiftKey && key === 'a') {
        if (!isTauri()) {
          // Web: let the browser handle Ctrl+Shift+A (or do nothing). Do NOT
          // preventDefault — that would silently swallow the user's keystroke.
          return
        }
        const _target = event.target as HTMLElement
        const _active = document.activeElement as HTMLElement | null
        const _inField = (_target.tagName === 'INPUT' || _target.tagName === 'TEXTAREA' || _target.isContentEditable) ||
          (_active && _active !== document.body && _active !== document.documentElement &&
            (_active.tagName === 'INPUT' || _active.tagName === 'TEXTAREA' || _active.isContentEditable))
        if (!_inField) {
          event.preventDefault()
          event.stopPropagation()
          trackShortcut()
          // Defer to a microtask so the keydown event finishes propagating
          // (and any focus/scroll work yields) before the potentially heavy
          // select-all walks the email list.
          queueMicrotask(() => c.onSelectAll?.())
          return
        }
      }

      // Ctrl+A — select all from here
      if (isMeta && !event.shiftKey && key === 'a') {
        const _target = event.target as HTMLElement
        const _active = document.activeElement as HTMLElement | null
        const _inField = (_target.tagName === 'INPUT' || _target.tagName === 'TEXTAREA' || _target.isContentEditable) ||
          (_active && _active !== document.body && _active !== document.documentElement &&
            (_active.tagName === 'INPUT' || _active.tagName === 'TEXTAREA' || _active.isContentEditable))
        if (!_inField) {
          event.preventDefault()
          event.stopPropagation()
          trackShortcut()
          c.onSelectAllFromHere?.()
          return
        }
      }

      // Escape closes modals/panels — UNLESS an inner popover currently owns
      // Escape (a dropdown/date-picker/command-menu nested in the open modal).
      // This handler runs in the capture phase on `window`, registered at app
      // mount, so it fires before any popover's own listener; without this
      // structural check, dismissing such a popover with Escape would also fire
      // handleCloseModal and tear down the whole host (the LocalePickers bug
      // class). The popover still closes itself; a second Escape closes the host.
      if (key === 'escape') {
        if (hasEscapeOwner()) return
        event.preventDefault()
        c.onCloseModal?.()
        return
      }

      // Any non-Cmd shortcut below this point is suppressed while
      // ``body.dataset.modalOpen`` is set. App.tsx mirrors its `isModalOpen`
      // state into this flag, AND any popover/picker that semantically owns
      // the keyboard (e.g. Calendar QuickEventPopover) can set it directly
      // when mounted — so we don't have to thread per-popover state into
      // every handler binding. Cmd-modified shortcuts (Cmd+R, Cmd+K, etc.)
      // are still allowed because they're explicit user intent.
      if (!isMeta && document.body.dataset.modalOpen === 'true') return

      // Arrow keys — navigate prev/next email; detail panel handles ArrowLeft/ArrowRight
      if ((key === 'arrowleft' || key === 'arrowup') && !isMeta) {
        if (c.detailPanelVisible && key === 'arrowleft') return
        const target = event.target as HTMLElement
        if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) return
        event.preventDefault()
        trackShortcut()
        setKeyboardNavMode(true)
        c.onNavigateUp?.()
        triggerKeyboardPulse()
        return
      }

      if ((key === 'arrowright' || key === 'arrowdown') && !isMeta) {
        if (c.detailPanelVisible && key === 'arrowright') return
        const target = event.target as HTMLElement
        if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) return
        event.preventDefault()
        trackShortcut()
        setKeyboardNavMode(true)
        c.onNavigateDown?.()
        triggerKeyboardPulse()
        return
      }

      // Enter opens selected email
      if (key === 'enter' && !isMeta) {
        const target = event.target as HTMLElement
        if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
          return
        }
        event.preventDefault()
        c.onOpenSelected?.()
        return
      }

      // Skip single-key shortcuts when inside form fields.
      // On vérifie document.activeElement (plus fiable que event.target en phase capture)
      // pour détecter si l'utilisateur est en train de taper dans un champ.
      const target = event.target as HTMLElement
      const activeEl = document.activeElement as HTMLElement | null
      const isCheckbox = target.tagName === 'INPUT' && (target as HTMLInputElement).type === 'checkbox'
      const inInputTarget = (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) && !isCheckbox
      const inInputActive = activeEl !== null && activeEl !== document.body && activeEl !== document.documentElement &&
        (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA' || activeEl.isContentEditable) &&
        !((activeEl as HTMLInputElement).type === 'checkbox')
      const inInput = inInputTarget || inInputActive
      if (inInput) return

      // N opens new message compose
      // BUG-J001 fix: call onNewMessage() after the current keydown event has
      // finished propagating. Without the delay, some browsers deliver the 'n'
      // character to the newly-focused "To" input because focus transfers
      // synchronously inside onNewMessage() while the keydown is still being
      // dispatched — event.preventDefault() only guards the element that was
      // focused at the time the event fired, not elements focused during the handler.
      //
      // QA 2026-06-12: the deferral used requestAnimationFrame, but rAF does
      // NOT fire while Chrome throttles frame production (occluded/background
      // window, busy compositor) — the callback was parked indefinitely, so the
      // first N press looked dead. The user pressed N again; by then the modal
      // from the parked callback had mounted with the To field focused, and the
      // retry keystroke typed a literal "n" into it. queueMicrotask gives the
      // same guarantee BUG-J001 needs (runs after the keydown task, including
      // default-action processing, has fully unwound) but is never throttled.
      if (key === 'n' && !isMeta) {
        event.preventDefault()
        trackShortcut()
        queueMicrotask(() => c.onNewMessage?.())
        return
      }

      // R — reply to selected email (microtask, not rAF — see N above)
      if (key === 'r' && !isMeta) {
        event.preventDefault()
        trackShortcut()
        queueMicrotask(() => c.onReply?.())
        return
      }

      // A — reply all to selected email (microtask, not rAF — see N above)
      if (key === 'a' && !isMeta) {
        event.preventDefault()
        trackShortcut()
        queueMicrotask(() => c.onReplyAll?.())
        return
      }

      // F — forward selected email (microtask, not rAF — see N above)
      if (key === 'f' && !isMeta) {
        event.preventDefault()
        trackShortcut()
        queueMicrotask(() => c.onForward?.())
        return
      }

      // E — archive selected email
      if (key === 'e' && !isMeta) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        if ((event as any)._handledByItem) return
        event.preventDefault()
        trackShortcut()
        c.onArchive?.()
        return
      }

      // Delete/Backspace — delete hovered or selected email (global handler always runs)
      if ((key === 'delete' || key === 'backspace') && !isMeta) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        if ((event as any)._handledByItem) return
        event.preventDefault()
        trackShortcut()
        c.onDelete?.()
        return
      }

      // U — toggle read/unread on selected email
      if (key === 'u' && !isMeta) {
        event.preventDefault()
        trackShortcut()
        c.onToggleRead?.()
        return
      }

      // / — focus search bar (guard inInput déjà appliqué plus haut)
      // BUG-#15 (2026-05-17): Shift+/ (i.e. `?`) opens the keyboard
      // shortcuts cheatsheet. Same focus guard as the rest of the
      // single-key shortcuts. Detected via key === '?' (Shift modifier
      // produces this char on most keyboard layouts) and falls back to
      // (key === '/' && shiftKey) for layouts where the modifier doesn't
      // resolve `?` automatically.
      if (!isMeta && (key === '?' || (key === '/' && event.shiftKey))) {
        event.preventDefault()
        trackShortcut()
        c.onShowShortcutsHelp?.()
        return
      }

      if (key === '/' && !isMeta) {
        event.preventDefault()
        trackShortcut()
        c.onSearch?.()
        return
      }

    }

    window.addEventListener('keydown', handleKeyDown, true)
    return () => {
      window.removeEventListener('keydown', handleKeyDown, true)
    }
  }, [])
}
