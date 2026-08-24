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

import { useEffect, useState, useCallback } from 'react'
import { apiClient } from '../services/api'

interface FollowupDraft {
  email_sender?: string
  email_subject?: string
  routing_tier?: string
  /** Wake date while the follow-up is still snoozed ("in Later"); absent
   *  once the wake-sweep promoted it (delay elapsed, no reply). */
  snoozed_until?: string
}

export interface FollowupNudgeState {
  count: number
  /** "recipient::subject" keys — fast lookup for the per-row `🔁 Suivi` chip. */
  pendingKeys: Set<string>
}

const POLL_INTERVAL = 5 * 60 * 1000 // 5 min

/**
 * Drives the inbox/sent `🔁 Suivi` chip — sourced from the
 * `create_snoozed_followup_draft` Quick Step, NOT the legacy auto-followup
 * tracker (`/api/followups/pending`). This is what makes the chip honour the
 * Quick Action's own `delay_days`: a follow-up is "due" (chip shows) only once
 * its snooze has elapsed with no reply — i.e. at day N, where N is the rule's
 * delay. While the draft is still snoozed ("in Later"), no chip.
 *
 * The key shape (`recipient::subject`) is unchanged from the legacy source, so
 * the matching in EmailList / SwipeableEmailItem needs no change: a follow-up
 * draft's `email_sender` IS the original recipient and `email_subject` IS the
 * sent subject.
 */
export function useFollowupNudgeCount(): FollowupNudgeState {
  const [state, setState] = useState<FollowupNudgeState>({ count: 0, pendingKeys: new Set() })

  const refresh = useCallback(async () => {
    try {
      const data = await apiClient.listPendingDrafts(100)
      const now = Date.now()
      const keys = new Set<string>()
      for (const d of (data.drafts ?? []) as FollowupDraft[]) {
        // /api/pending-drafts already filters to routing_tier=followup; guard anyway.
        if ((d.routing_tier ?? '') !== 'followup') continue
        // Due = snooze gone (promoted) or its wake date already passed.
        const su = d.snoozed_until
        const due = !su || new Date(su).getTime() <= now
        if (!due) continue
        if (d.email_sender && d.email_subject) {
          // Case-insensitive: the sent row's To address and the draft's
          // stored sender can differ in casing (e.g. "Alexandre.Simon"
          // vs "alexandre.simon"). Lowercase both sides so no thread is
          // silently dropped. The EmailList lookup lowercases identically.
          keys.add(`${d.email_sender}::${d.email_subject}`.toLowerCase())
        }
      }
      setState({ count: keys.size, pendingKeys: keys })
    } catch {
      // sidebar dot is non-critical
    }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, POLL_INTERVAL)
    return () => clearInterval(id)
  }, [refresh])

  return state
}
