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

// P3-21 (2026-05-17): suppress the i18next "Locize" promo banner in
// production. Runs BEFORE i18n import so the wrapper is in place by the
// time any module emits its first log line. We only filter literal
// 'Locize' mentions (and the "i18next: hasLoadedNamespace" warning, which
// fires under the same code path) so legitimate app logs are unaffected.
// Dev keeps the original logger so library debug output still flows.
if (typeof console !== 'undefined' && !import.meta.env.DEV) {
  const SUPPRESS = /Locize|i18next is made possible/i
  const originalLog = console.log.bind(console)
  console.log = ((...args: unknown[]) => {
    const first = args[0]
    if (typeof first === 'string' && SUPPRESS.test(first)) return
    originalLog(...(args as []))
  }) as typeof console.log
}
import './instrument'
import { i18nReady } from './i18n'
import { StrictMode } from 'react'
import './freezeWatchdog'
import { createRoot } from 'react-dom/client'
import { ErrorBoundary } from './components/ErrorBoundary'
import * as Sentry from '@sentry/react'
import './animations.css'
import './index.css'

// P0-2 (2026-05-17): stale-chunk recovery after a deploy. The browser caches
// the previous build's HTML and points at lazy chunks whose hashes no longer
// exist on the CDN — the requests come back as text/html (the SPA shell) and
// the browser refuses to import them. We recover by reloading exactly once
// per session (gated via sessionStorage so a hard server outage can't trip
// an infinite reload loop). Covers three event surfaces:
//   1. Vite's first-class `vite:preloadError` (lazy import + CSS preload).
//   2. Generic window `error` for "Failed to fetch dynamically imported module"
//      / "Loading chunk N failed" / MIME-type complaints.
//   3. `unhandledrejection` (the import promise rejects without an error
//      event when the module fetch itself succeeds but the script can't be
//      parsed because the server returned HTML).
const CHUNK_RELOAD_SESSION_KEY = 'agentys.reloaded-for-chunk'
const STALE_CHUNK_PATTERN = /Failed to fetch dynamically imported module|Loading chunk \d+ failed|'text\/html' is not a valid JavaScript MIME type|Unable to preload CSS/i

function reloadOnceForStaleChunk(reason: string, detail?: unknown) {
  try {
    if (sessionStorage.getItem(CHUNK_RELOAD_SESSION_KEY) === 'true') {
      // Already reloaded this session — don't loop. Surface to Sentry so we
      // notice if the bad chunk is actually missing from the CDN.
      Sentry.addBreadcrumb({
        category: 'app.chunk-recovery',
        level: 'error',
        message: `stale-chunk reload already used this session (${reason})`,
        data: { detail: String(detail).slice(0, 300) },
      })
      return
    }
    sessionStorage.setItem(CHUNK_RELOAD_SESSION_KEY, 'true')
  } catch {
    // sessionStorage may be unavailable (privacy mode). Fall through and
    // reload anyway — the worst case is a one-extra-reload after deploy.
  }
  Sentry.addBreadcrumb({
    category: 'app.chunk-recovery',
    level: 'warning',
    message: `reloading once for stale chunk (${reason})`,
    data: { detail: String(detail).slice(0, 300) },
  })
  // Use replace() so the failed-load entry isn't in history; immediate reload.
  window.location.reload()
}

if (typeof window !== 'undefined') {
  window.addEventListener('vite:preloadError', (event) => {
    event.preventDefault?.()
    reloadOnceForStaleChunk('vite:preloadError', (event as Event & { payload?: unknown }).payload)
  })
  window.addEventListener('error', (event) => {
    const msg = event?.message || ''
    if (STALE_CHUNK_PATTERN.test(msg)) {
      reloadOnceForStaleChunk('window.error', msg)
    }
  })
  window.addEventListener('unhandledrejection', (event) => {
    const reason = event?.reason
    const msg = typeof reason === 'string'
      ? reason
      : (reason && typeof reason === 'object' && 'message' in reason
          ? String((reason as { message?: unknown }).message ?? '')
          : '')
    if (STALE_CHUNK_PATTERN.test(msg)) {
      reloadOnceForStaleChunk('unhandledrejection', msg)
    }
  })
  // Clear the gate once the new build successfully boots — landing here means
  // i18n + React mounted, so chunk loads are working for the current bundle.
  window.addEventListener('load', () => {
    try { sessionStorage.removeItem(CHUNK_RELOAD_SESSION_KEY) } catch { /* noop */ }
  })
}

// Promote the preloaded theme-fonts <link> to a real stylesheet after first
// paint. Replaces an inline `onload="this.media='all'"` that CSP `script-src
// 'self'` blocks (cf. audit 2026-05-01 P1 finding #4).
const themeFonts = document.getElementById('theme-fonts') as HTMLLinkElement | null
if (themeFonts && themeFonts.rel === 'preload') {
  themeFonts.rel = 'stylesheet'
}
// Clarity (default) est le seul thème. On pose data-theme="default" en synchrone
// avant le 1er render pour que le fallback `prefers-color-scheme: dark` de
// index.css (gated sur `:root:not([data-theme])`) ne s'applique jamais quand l'OS
// est en mode sombre.
document.documentElement.setAttribute('data-theme', 'default')
// In-app zoom: applique la valeur sauvegardée avant le 1er render pour éviter un reflow visible.
import { preloadSavedZoom } from './hooks/useZoom'
preloadSavedZoom()
import App from './App.tsx'
import { TooltipSettingsProvider } from './hooks/useTooltipSettings.js'
import { QueryClientProvider } from '@tanstack/react-query'
import { getQueryClient } from './lib/queryClient'
import { getWebSocketInvalidator } from './lib/webSocketInvalidator'
import { resetWebSocketClient } from './services/websocket'
import { resetNotificationService } from './services/notifications'
import { resetDraftReminderService } from './services/draftReminder'
import { resetApiClient } from './services/api'
import { resetCrossChannelRulesService } from './services/crossChannelRules'

// Cleanup singletons on Vite HMR to prevent memory leaks in dev mode
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    resetWebSocketClient()
    resetNotificationService()
    resetDraftReminderService()
    resetApiClient()
    resetCrossChannelRulesService()
  })
}

// Tauri v2 exposes `__TAURI_INTERNALS__` (NOT `__TAURI__`, which was the v1
// global) — check both for safety, plus the UA sniff as a last resort in
// case neither global is set when this module runs at boot.
const isTauriContext =
  window.__TAURI_INTERNALS__ !== undefined ||
  window.__TAURI__ !== undefined ||
  navigator.userAgent.includes('Tauri')

// Neutralize window.resizeTo / resizeBy: calling these in Tauri's WebView
// triggers a native resize event that crashes the webview tab entirely.
// Override them as no-ops so automation scripts and devtools don't cause crashes.
if (isTauriContext) {
  window.resizeTo = () => { /* no-op in Tauri */ }
  window.resizeBy = () => { /* no-op in Tauri */ }
}

// Prevent native WebView2 context menu in Tauri only.
// Custom React menus (SwipeableEmailItem, CalendarView, LabelBadge, etc.) call
// e.preventDefault() on their own onContextMenu, so they still win over the
// native menu. On the web build, keep the browser's native menu available
// (Inspect, Copy link, Reload…).
if (isTauriContext) {
  document.addEventListener('contextmenu', (e) => {
    const tag = (e.target as HTMLElement)?.tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA' || (e.target as HTMLElement)?.isContentEditable) return
    e.preventDefault()
  })
}

// TanStack Query — single source of truth for server state.
// Phase 0 wiring: the WebSocket invalidator is attached but does not yet
// route any events (that's Phase 5). Attaching here keeps the lifecycle
// ownership obvious — root creates, root tears down via HMR dispose.
const queryClient = getQueryClient()
getWebSocketInvalidator().attach(queryClient)

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    getWebSocketInvalidator().detach()
  })
}

// Gate React mount on the active language being fully loaded. With lazy
// i18n chunking the active language's strings live in `locale-<lng>.js`
// (built per-language by vite manualChunks), and awaiting `i18nReady`
// guarantees the first paint never shows raw t() keys. If the chunk fails
// to load (build/file-missing), log and render anyway — the app degrades
// gracefully to keys + fallbackLng rather than hanging on a blank screen.
i18nReady
  .catch(err => {
    console.error('[i18n] preload failed, rendering with partial resources', err)
  })
  .finally(() => {
    createRoot(document.getElementById('root')!).render(
      <StrictMode>
        <ErrorBoundary>
          <QueryClientProvider client={queryClient}>
            <TooltipSettingsProvider>
              <App />
            </TooltipSettingsProvider>
          </QueryClientProvider>
        </ErrorBoundary>
      </StrictMode>,
    )
  })
