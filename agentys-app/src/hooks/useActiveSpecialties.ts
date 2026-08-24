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
 * Returns the list of currently active specialty IDs from settings.
 *
 * Used by App.tsx to conditionally display the Ctrl+Shift+G shortcut hint in
 * the compose/reply shortcut bar — no point advertising the expert mode if
 * the user hasn't activated any specialty.
 *
 * Settings shape (from `/api/settings`): `{ active_specialties: string[] }`.
 * Empty array when no specialty is active or the field is absent.
 */
import { useEffect, useState } from 'react'
import { fetchSettingsCached } from './useSettingsCache'
import { getStoredToken } from '../services/authToken'

export function useActiveSpecialties(accountId?: number): string[] {
  const [list, setList] = useState<string[]>([])

  useEffect(() => {
    // Skip the fetch entirely when no JWT is stored — the user is on the
    // login page or signed out, so /api/settings would 401 and pollute the
    // console. The post-OAuth `auth:login_success` event remounts consumers
    // of this hook, which re-triggers the effect with a token in hand.
    if (!getStoredToken()) {
      setList([])
      return
    }
    let cancelled = false
    fetchSettingsCached(accountId)
      .then((data) => {
        if (cancelled) return
        const raw = (data as Record<string, unknown>)['active_specialties']
        if (Array.isArray(raw)) {
          const filtered = raw.filter((v): v is string => typeof v === 'string')
          setList(filtered)
        } else {
          setList([])
        }
      })
      .catch((err) => {
        // 401 is expected when the JWT got cleared mid-flight (logout, expiry);
        // useAuth's auth:unauthorized handler already kicks the user back to
        // login. No need to surface as an error to the console.
        const msg = err instanceof Error ? err.message : String(err)
        if (!/\b401\b/.test(msg)) {
          console.warn('[useActiveSpecialties] load settings failed:', err)
        }
        if (!cancelled) setList([])
      })
    return () => { cancelled = true }
  }, [accountId])

  return list
}
