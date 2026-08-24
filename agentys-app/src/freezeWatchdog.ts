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

// QA 2026-06-10 — freeze watchdog (dev only).
//
// The renderer intermittently hard-hangs for 30s-4min (observed on the Noise
// tab switch, on reply-draft delete, and once on an idle /archive page; the
// backend logs show zero HTTP requests during the window, so it's a pure
// client-side stall — possibly one of the many injected crypto-wallet
// extension scripts seen on localhost:1420, possibly app code).
//
// A heartbeat interval can't fire while the main thread is blocked, so any
// gap between ticks ≈ the blocked duration. On recovery we log the gap plus
// the most recent PerformanceObserver long-tasks and persist the last 20
// incidents to localStorage('agentys.freeze-log') for post-mortem.
//
// Remove once the hang is root-caused.

if (import.meta.env.DEV && typeof window !== 'undefined') {
  const longTasks: Array<{ start: number; dur: number }> = []
  try {
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        longTasks.push({ start: Math.round(e.startTime), dur: Math.round(e.duration) })
        if (longTasks.length > 50) longTasks.shift()
      }
    }).observe({ entryTypes: ['longtask'] })
  } catch {
    /* longtask unsupported — heartbeat still works */
  }

  let last = performance.now()
  window.setInterval(() => {
    const now = performance.now()
    const gap = now - last
    last = now
    if (gap > 5000) {
      const incident = {
        at: new Date().toISOString(),
        blockedMs: Math.round(gap),
        url: location.pathname,
        recentLongTasks: longTasks.slice(-5),
      }
      console.error('[freeze-watchdog] main thread was blocked', incident)
      try {
        const key = 'agentys.freeze-log'
        const log = JSON.parse(localStorage.getItem(key) || '[]')
        log.push(incident)
        localStorage.setItem(key, JSON.stringify(log.slice(-20)))
      } catch {
        /* quota — console log already emitted */
      }
    }
  }, 1000)
}

export {}
