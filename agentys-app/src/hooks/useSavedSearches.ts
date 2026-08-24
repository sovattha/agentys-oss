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

import { useState, useCallback } from 'react'

const SAVED_SEARCHES_KEY = 'agentys_saved_searches'
const MAX_SAVED = 20

export interface SavedSearch {
  id: string
  name: string
  query: string
  createdAt: string
}

function loadSavedSearches(): SavedSearch[] {
  try {
    const stored = localStorage.getItem(SAVED_SEARCHES_KEY)
    return stored ? JSON.parse(stored) : []
  } catch {
    return []
  }
}

function persistSavedSearches(searches: SavedSearch[]) {
  localStorage.setItem(SAVED_SEARCHES_KEY, JSON.stringify(searches.slice(0, MAX_SAVED)))
}

export function useSavedSearches() {
  const [searches, setSearches] = useState<SavedSearch[]>(loadSavedSearches)

  const saveSearch = useCallback((name: string, query: string) => {
    const trimmedName = name.trim()
    const trimmedQuery = query.trim()
    if (!trimmedName || !trimmedQuery) return

    setSearches(prev => {
      // Avoid duplicate names
      if (prev.some(s => s.name.toLowerCase() === trimmedName.toLowerCase())) return prev

      const newSearch: SavedSearch = {
        id: `saved_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        name: trimmedName,
        query: trimmedQuery,
        createdAt: new Date().toISOString(),
      }
      const next = [newSearch, ...prev].slice(0, MAX_SAVED)
      persistSavedSearches(next)
      return next
    })
  }, [])

  const deleteSearch = useCallback((id: string) => {
    setSearches(prev => {
      const next = prev.filter(s => s.id !== id)
      persistSavedSearches(next)
      return next
    })
  }, [])

  return { searches, saveSearch, deleteSearch }
}
