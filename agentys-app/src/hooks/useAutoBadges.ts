// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2024-2026 Agentys contributors
/**
 * useAutoBadges — fetch + cache the ⚡ Auto badge map for the current
 * inbox slice. Pairs with the per-rule `showAutoBadge` toggle and the
 * `<AutoBadgeChip>` rendered next to label badges on each row.
 *
 * Why a dedicated hook (not folded into the email-list endpoint) :
 *   - Keeps the hot inbox-list query free of an extra JOIN on the audit
 *     log table — that scales linearly with auto-rule firing volume.
 *   - The badge map can refresh independently of the email list (when
 *     the user toggles a rule's badge off, we want existing rows to lose
 *     their chip without a full list refetch).
 *
 * Behavior :
 *   - Debounces inputs by 200ms so rapid list updates (e.g. WebSocket
 *     email arrivals) collapse into a single request.
 *   - Chunks long id lists into parallel calls of `MAX_IDS_PER_CALL` each
 *     so paginated inboxes (loadMore past 200 rows) still badge rows
 *     beyond the first page (F-02 fix from audit-2026-05-12_2129).
 *   - Subscribes to `agentys:quicksteps-changed` so toggling a rule's
 *     `showAutoBadge` off makes existing chips disappear without
 *     waiting for the next list refetch (F-03 fix from same audit).
 *   - Best-effort : any fetch failure resolves to an empty map so the
 *     inbox keeps rendering without the chip.
 */
import { useEffect, useRef, useState } from 'react'

import { fetchAutoBadges } from '../services/api'
import type { AutoBadgeMap } from '../types/quickStep'

const DEBOUNCE_MS = 200
const MAX_IDS_PER_CALL = 200 // mirrors `_AUTO_BADGES_MAX_IDS` in app/api/quicksteps.py

function chunk<T>(arr: T[], size: number): T[][] {
  if (size <= 0 || arr.length === 0) return arr.length ? [arr] : []
  const out: T[][] = []
  for (let i = 0; i < arr.length; i += size) {
    out.push(arr.slice(i, i + size))
  }
  return out
}

export function useAutoBadges(emailIds: string[]): AutoBadgeMap {
  const [badges, setBadges] = useState<AutoBadgeMap>({})
  // Track in-flight request so a later list change (or rule-change event)
  // supersedes the result of an earlier slow request (last-write-wins).
  const reqIdRef = useRef(0)
  // Bump this to force a re-run of the effect when an external signal
  // (rule toggled off, rule deleted) needs to invalidate the badge map.
  const [refreshCounter, setRefreshCounter] = useState(0)

  // Stable signature for the deps array : the list of ids by value, not
  // by reference. Without this, every parent render creates a new array
  // reference and the effect re-fires endlessly.
  const idsKey = emailIds.join(',')

  // F-03 (audit-2026-05-12_2129): bump refreshCounter on Quick Step
  // changes so the cached badge map is invalidated and refetched.
  useEffect(() => {
    const handler = () => setRefreshCounter((n) => n + 1)
    window.addEventListener('agentys:quicksteps-changed', handler)
    return () => window.removeEventListener('agentys:quicksteps-changed', handler)
  }, [])

  useEffect(() => {
    if (!idsKey) {
      setBadges({})
      return
    }
    const ids = idsKey.split(',').filter(Boolean)
    if (!ids.length) {
      setBadges({})
      return
    }

    const myReqId = ++reqIdRef.current
    const timer = setTimeout(async () => {
      try {
        // F-02 (audit-2026-05-12_2129): chunk the ids into N parallel
        // requests of MAX_IDS_PER_CALL each so paginated inboxes past
        // 200 rows still badge correctly. Each request still respects
        // the backend cap; merging the resulting maps preserves the
        // last-write-wins semantics per email_id.
        const chunks = chunk(ids, MAX_IDS_PER_CALL)
        const results = await Promise.all(chunks.map((c) => fetchAutoBadges(c)))
        if (myReqId !== reqIdRef.current) return
        const merged: AutoBadgeMap = {}
        for (const resp of results) {
          if (resp?.badges) Object.assign(merged, resp.badges)
        }
        setBadges(merged)
      } catch {
        // Silent failure : the badge is decorative, never block the inbox.
        if (myReqId !== reqIdRef.current) return
        setBadges({})
      }
    }, DEBOUNCE_MS)

    return () => clearTimeout(timer)
  }, [idsKey, refreshCounter])

  return badges
}
