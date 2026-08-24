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
import { apiClient, type PendingDraft } from '../services/api'
import { getWebSocketClient } from '../services/websocket'

/**
 * Returns the total count of AI-generated pending drafts awaiting user review.
 * Drives the badge on the sidebar Drafts icon. Tracks separately from
 * `draftCount` because that one only updates when the Drafts tab is mounted —
 * this hook fetches globally and listens to WebSocket events so the count is
 * accurate from any tab.
 *
 * `enabled` gates the /api/pending-drafts fetch on app-level auth — without it
 * the hook fired a 401 on the login page (QA 2026-05-19). Defaults to true so
 * existing callers/tests keep their behaviour.
 */
export function useUnviewedDraftCount(enabled: boolean = true): number {
  const [drafts, setDrafts] = useState<PendingDraft[]>([])

  const fetchDrafts = useCallback(async () => {
    try {
      const response = await apiClient.listPendingDrafts(100)
      setDrafts(Array.isArray(response?.drafts) ? response.drafts : [])
    } catch {
      // Silent — sidebar dot is non-critical
    }
  }, [])

  useEffect(() => {
    if (!enabled) return
    fetchDrafts()
    const ws = getWebSocketClient()
    return ws.subscribe((event) => {
      if (event.type === 'draft_ready' || event.type === 'draft_complete') {
        fetchDrafts()
      }
    })
  }, [fetchDrafts, enabled])

  // Show total pending drafts (not filtered by viewed) so the sidebar badge
  // matches what the user sees as actionable items in the Drafts tab (BUG-Q005).
  return drafts.length
}
