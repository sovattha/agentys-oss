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

import { useState, useCallback, useEffect, useRef } from 'react'
import { apiClient } from '../services/api'
import { getActiveAccountId } from '../api/emails'

export interface ContactGroupMember {
  name: string
  email: string
}

export interface ContactGroup {
  id: string
  name: string
  emoji?: string | null
  description?: string | null
  label_name?: string | null
  members: ContactGroupMember[]
  created_at: string
  updated_at: string
  use_count: number
  virtual_meeting?: boolean
}

function getCacheKey(): string {
  return `agentys_contact_groups_${getActiveAccountId()}`
}

function loadCache(): ContactGroup[] {
  try {
    const stored = localStorage.getItem(getCacheKey())
    return stored ? JSON.parse(stored) : []
  } catch {
    return []
  }
}

// Migration one-shot : supprime l'ancienne clé non-scopée au premier chargement
const _OLD_CACHE_KEY = 'agentys_contact_groups'
if (typeof localStorage !== 'undefined' && localStorage.getItem(_OLD_CACHE_KEY) !== null) {
  localStorage.removeItem(_OLD_CACHE_KEY)
}

// BUG-Y001 mitigation: multiple components (QuickEventPopover, NewMessageModal,
// ContactAutocomplete) mount roughly at the same time on initial inbox load
// and each triggers loadGroups() — that's 3+ identical GET /api/contact-groups
// firing in parallel, which is exactly the burst pattern that produced 12 ×
// 502 in the QA report (proxy/backend gets stampeded). Deduplicate concurrent
// loads with a module-level in-flight promise, and skip the network entirely
// if the local cache was refreshed within _CACHE_FRESH_MS.
const _CACHE_FRESH_MS = 5_000
type _PendingLoad = Promise<{ groups: ContactGroup[]; total: number }>
const _inflight = new Map<string, _PendingLoad>()
const _lastLoadAt = new Map<string, number>()

export function useContactGroups() {
  const [groups, setGroups] = useState<ContactGroup[]>(loadCache)
  const [loading, setLoading] = useState(false)
  // F-10 (audit 2026-06-11) : un échec de listContactGroups était masqué par le
  // cache localStorage (liste périmée ou vide affichée sans signal). Le cache
  // reste affiché, mais les consommateurs peuvent montrer une bannière d'erreur.
  const [error, setError] = useState(false)
  const activeAccountRef = useRef(getActiveAccountId())

  const loadGroups = useCallback(async () => {
    const cacheKey = getCacheKey()
    const lastAt = _lastLoadAt.get(cacheKey) || 0
    // Skip network if cache was refreshed within _CACHE_FRESH_MS — avoids
    // the simultaneous burst across 3+ components on initial mount.
    if (Date.now() - lastAt < _CACHE_FRESH_MS) return
    // Share an in-flight promise so concurrent callers wait for the same
    // network round-trip instead of each firing their own.
    let pending = _inflight.get(cacheKey)
    if (!pending) {
      pending = apiClient.listContactGroups().finally(() => {
        _inflight.delete(cacheKey)
        _lastLoadAt.set(cacheKey, Date.now())
      })
      _inflight.set(cacheKey, pending)
    }
    setLoading(true)
    try {
      const resp = await pending
      setGroups(resp.groups)
      localStorage.setItem(cacheKey, JSON.stringify(resp.groups))
      setError(false)
    } catch (err) {
      console.error('Failed to load contact groups:', err)
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  // Recharger si le compte actif change. setActiveAccountId (api/emails.ts)
  // dispatche `agentys:account-changed` après chaque transition réelle —
  // pattern partagé avec useLabels et EmailList. Évite un setInterval 500 ms.
  useEffect(() => {
    const handleAccountChange = () => {
      const current = getActiveAccountId()
      if (current !== activeAccountRef.current) {
        activeAccountRef.current = current
        setGroups(loadCache())
        void loadGroups()
      }
    }
    window.addEventListener('agentys:account-changed', handleAccountChange)
    return () => window.removeEventListener('agentys:account-changed', handleAccountChange)
  }, [loadGroups])

  useEffect(() => {
    loadGroups()
  }, [loadGroups])

  const createGroup = useCallback(async (data: {
    name: string
    emoji?: string
    description?: string
    label_name?: string | null
    members: ContactGroupMember[]
    virtual_meeting?: boolean
  }) => {
    const resp = await apiClient.createContactGroup(data)
    setGroups(prev => {
      const next = [resp.group, ...prev]
      localStorage.setItem(getCacheKey(), JSON.stringify(next))
      return next
    })
    return resp.group
  }, [])

  const updateGroup = useCallback(async (id: string, data: Partial<{
    name: string
    emoji: string
    description: string
    label_name: string | null
    members: ContactGroupMember[]
    virtual_meeting: boolean
  }>) => {
    const resp = await apiClient.updateContactGroup(id, data)
    setGroups(prev => {
      const next = prev.map(g => g.id === id ? resp.group : g)
      localStorage.setItem(getCacheKey(), JSON.stringify(next))
      return next
    })
    return resp.group
  }, [])

  const deleteGroup = useCallback(async (id: string) => {
    await apiClient.deleteContactGroup(id)
    setGroups(prev => {
      const next = prev.filter(g => g.id !== id)
      localStorage.setItem(getCacheKey(), JSON.stringify(next))
      return next
    })
  }, [])

  const recordUsage = useCallback(async (id: string) => {
    try {
      await apiClient.recordContactGroupUsage(id)
    } catch {
      // Non-blocking
    }
  }, [])

  return { groups, loading, error, loadGroups, createGroup, updateGroup, deleteGroup, recordUsage }
}
