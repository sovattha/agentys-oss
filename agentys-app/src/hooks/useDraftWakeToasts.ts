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
 * Wake-time toast scheduler for snoozed follow-up drafts.
 *
 * Watches the pending-drafts list and surfaces a floating toast whenever a
 * `create_snoozed_followup_draft` draft transitions from "in Later" to
 * "ready for review" — i.e. its `draft_followup` reminder has been promoted
 * server-side by `sweep_woken_draft_followups`.
 *
 * Detection contract (mirrors `routes_pending.list_pending_drafts`):
 *   - `routing_tier === "followup"`  — only the Quick-Step-armed follow-ups
 *     surface this way (the AI reply pipeline emits other tiers).
 *   - `!snoozed_until`               — the reminder's `notified` flag was
 *     flipped (un-promoted entries would still carry the wake date).
 *   - `status === "pending"`         — defensive; the backend already filters
 *     rejected/sent, but a stale cache would otherwise re-toast them.
 *
 * Dedup lives in `draftWakeStore` (per-draft, permanent or until-timestamp).
 * A draft only toasts once — even across page reloads — until the user
 * explicitly clears localStorage or `markFiredUntil` expires.
 *
 * Cost: piggybacks on the existing `/api/pending-drafts` polling cadence
 * (60s + WebSocket `draft_ready` / `draft_complete`). No new endpoint.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { apiClient, type PendingDraft } from '../services/api'
import { getWebSocketClient } from '../services/websocket'
import { hasFired, markFired, markFiredUntil } from '../services/draftWakeStore'

const POLL_INTERVAL_MS = 60_000
const SNOOZE_ONE_DAY_MS = 24 * 60 * 60 * 1000
/** Cap how many drafts the singular layout would unfold into stacked toasts. */
const MAX_WAKEN_PER_BATCH = 50

export interface DraftWakeToastsResult {
  /** Drafts the toast should render right now (post-dedup). Empty = no toast. */
  visibleDrafts: PendingDraft[]
  /** Permanent dismiss for a single draft. */
  dismissOne: (draftId: string) => void
  /** Permanent dismiss for every currently-visible draft. */
  dismissAll: () => void
  /** Re-fire this draft's toast after the given delay (default 24h). */
  snoozeOne: (draftId: string, ms?: number) => void
  /** Re-fire every visible draft's toast after the given delay. */
  snoozeAll: (ms?: number) => void
  /** Force an immediate poll. Returned for tests + post-send refresh. */
  refresh: () => Promise<void>
}

function isWokenFollowup(d: PendingDraft): boolean {
  if (!d || typeof d.id !== 'string' || !d.id) return false
  if ((d.routing_tier || '') !== 'followup') return false
  if (d.snoozed_until) return false
  // Backend already filters non-pending out of /api/pending-drafts but a
  // stale in-memory cache could still surface them — be defensive.
  if (d.status && d.status !== 'pending') return false
  return true
}

export function useDraftWakeToasts(enabled: boolean = true): DraftWakeToastsResult {
  const [drafts, setDrafts] = useState<PendingDraft[]>([])
  /** Bumped every time the dedup store mutates so visibleDrafts recomputes. */
  const [firedTick, setFiredTick] = useState(0)
  const mountedRef = useRef(true)

  const fetchDrafts = useCallback(async () => {
    try {
      const response = await apiClient.listPendingDrafts(100)
      if (!mountedRef.current) return
      const list = Array.isArray(response?.drafts) ? response.drafts : []
      const woken = list.filter(isWokenFollowup).slice(0, MAX_WAKEN_PER_BATCH)
      setDrafts(woken)
    } catch {
      // Silent — toast is non-critical; sidebar count + Drafts list catch the miss.
    }
  }, [])

  // Mount: initial fetch + WS subscription + 60s polling fallback.
  // Gated on `enabled` (app-level auth) so /api/pending-drafts doesn't 401 on
  // the login page (QA 2026-05-19).
  useEffect(() => {
    if (!enabled) return
    mountedRef.current = true
    void fetchDrafts()

    const ws = getWebSocketClient()
    const unsubscribe = ws.subscribe((event) => {
      // Wake transitions don't have a dedicated event today — they ride on
      // the same `draft_ready` / `draft_complete` channel that
      // `useUnviewedDraftCount` listens to. Re-fetch is cheap (HTTP only,
      // server returns the filtered set already).
      if (event.type === 'draft_ready' || event.type === 'draft_complete') {
        void fetchDrafts()
      }
    })

    const intervalId = window.setInterval(() => {
      void fetchDrafts()
    }, POLL_INTERVAL_MS)

    return () => {
      mountedRef.current = false
      window.clearInterval(intervalId)
      try {
        unsubscribe?.()
      } catch {
        // ignore
      }
    }
  }, [fetchDrafts, enabled])

  // `firedTick` is read so this memo re-runs when dedup state mutates.
  // (Direct read in JSX would suffice but the tick keeps the recompute
  // synchronous with the markFired/markFiredUntil calls below.)
  const _firedTick = firedTick
  const visibleDrafts = drafts.filter((d) => !hasFired(d.id))
  void _firedTick

  const dismissOne = useCallback((draftId: string) => {
    markFired(draftId)
    setFiredTick((t) => t + 1)
  }, [])

  const dismissAll = useCallback(() => {
    // Snapshot to avoid mutating the array we're iterating.
    for (const d of drafts) {
      if (!hasFired(d.id)) markFired(d.id)
    }
    setFiredTick((t) => t + 1)
  }, [drafts])

  const snoozeOne = useCallback((draftId: string, ms: number = SNOOZE_ONE_DAY_MS) => {
    markFiredUntil(draftId, Date.now() + ms)
    setFiredTick((t) => t + 1)
  }, [])

  const snoozeAll = useCallback((ms: number = SNOOZE_ONE_DAY_MS) => {
    const expiresAt = Date.now() + ms
    for (const d of drafts) {
      if (!hasFired(d.id)) markFiredUntil(d.id, expiresAt)
    }
    setFiredTick((t) => t + 1)
  }, [drafts])

  const refresh = useCallback(async () => {
    await fetchDrafts()
  }, [fetchDrafts])

  return {
    visibleDrafts,
    dismissOne,
    dismissAll,
    snoozeOne,
    snoozeAll,
    refresh,
  }
}
