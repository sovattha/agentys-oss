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

import { useCallback, useMemo, useState, useEffect } from 'react'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import {
  fetchLabels,
  fetchLabelCounts,
  toggleLabelFavorite,
  saveFavoriteLabelOrder,
  getFavoriteLabelOrder,
} from '../api/labels'
import { qk } from '../lib/queryKeys'
import { useActiveAccountId } from './useActiveAccountId'
import i18n from '../i18n'
import type { Label } from '../types/labels'
import { DEFAULT_LABELS } from '../types/labels'

/**
 * Phase 2 migration: useLabels now uses TanStack Query for both the label
 * list and the unread-only counts.
 *
 * What this replaces:
 *  - Manual `loadLabels` / `loadCounts` callbacks running through
 *    useState+useEffect (~25 LOC each)
 *  - `countsFetchingRef` + `countsDebounceRef` manual dedup/debounce — the
 *    queryClient's in-flight dedup + `staleTime` cover the same surface
 *  - `useEffect` listener on `agentys:account-changed` — replaced by the
 *    query key flipping when `useActiveAccountId()` changes (the new key
 *    naturally triggers a refetch for the new account)
 *
 * Public signature `UseLabelReturn` is unchanged so every consumer
 * (`useSharedLabels`, `useSharedLabelsData`, `useSharedLabelCounts`,
 * `LabelsProvider`, …) keeps working without a diff.
 */

function hasActiveAccount(accountId: string): boolean {
  return !!accountId && accountId !== 'default'
}

export interface UseLabelReturn {
  labels: Label[]
  favoriteLabels: Label[]
  projectLabels: Label[]
  labelCounts: Record<string, number>
  loading: boolean
  error: string | null
  refreshLabels: () => Promise<void>
  refreshCounts: () => Promise<void>
  toggleFavorite: (name: string) => Promise<void>
  reorderFavorites: (newOrder: string[]) => void
  getLabelByName: (name: string) => Label | undefined
}

// `unread_only=true` for the header tabs (Inbox/Action/FYI/Noise/…) — same
// rationale as pre-migration: the header shows Gmail-style unread badges
// and a fresh inbox displays manageable numbers, not 504 total.
const COUNTS_UNREAD_ONLY = true

export function useLabels(): UseLabelReturn {
  const queryClient = useQueryClient()
  const accountId = useActiveAccountId()
  const active = hasActiveAccount(accountId)

  // ---------- queries ----------

  const labelsQuery = useQuery({
    queryKey: qk.labels(accountId),
    queryFn: async () => {
      const res = await fetchLabels()
      return res.labels
    },
    // Don't fire requests before the user has bound an account — pre-OAuth
    // the backend returns 401 ("No active account") and pollutes logs.
    enabled: active,
  })

  const countsQuery = useQuery({
    queryKey: qk.labelCounts(accountId, COUNTS_UNREAD_ONLY),
    queryFn: async () => {
      const res = await fetchLabelCounts(COUNTS_UNREAD_ONLY)
      return { ...res.counts, __total__: res.total } as Record<string, number>
    },
    enabled: active,
  })

  // ---------- favorite order (local, per-device) ----------

  const [favoriteOrder, setFavoriteOrder] = useState<string[]>(() => getFavoriteLabelOrder())

  useEffect(() => {
    setFavoriteOrder(getFavoriteLabelOrder())
  }, [accountId])

  // ---------- mutation: toggle favorite ----------

  const toggleFavoriteMutation = useMutation({
    mutationFn: async ({ name, next }: { name: string; next: boolean }) => {
      return toggleLabelFavorite(name, next)
    },
    onSuccess: (result, { name }) => {
      // Swap the single label in the cached list — avoids a full refetch.
      queryClient.setQueryData<Label[]>(qk.labels(accountId), (prev) =>
        prev ? prev.map((l) => (l.name === name ? result.label : l)) : prev,
      )
      // Mirror the favoriteOrder update from the pre-migration logic.
      if (result.label.is_favorite) {
        setFavoriteOrder((prev) => {
          if (prev.includes(name)) return prev
          const newOrder = [...prev, name]
          saveFavoriteLabelOrder(newOrder)
          return newOrder
        })
      } else {
        setFavoriteOrder((prev) => {
          if (!prev.includes(name)) return prev
          const newOrder = prev.filter((n) => n !== name)
          saveFavoriteLabelOrder(newOrder)
          return newOrder
        })
      }
    },
    onError: (err) => {
      // F-08 (audit 2026-06-11) : en échec l'étoile ne bouge pas (pas
      // d'optimistic) et rien n'expliquait pourquoi — le clic semblait mort.
      console.error('Failed to toggle favorite:', err)
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: { message: i18n.t('common:toasts.label_favorite_failed'), type: 'error' },
        }))
      }
    },
  })

  // ---------- imperative refresh helpers (signature preserved) ----------

  const refreshLabels = useCallback(async (): Promise<void> => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: qk.labels(accountId) }),
      queryClient.invalidateQueries({ queryKey: qk.labelCounts(accountId, COUNTS_UNREAD_ONLY) }),
    ])
  }, [accountId, queryClient])

  const refreshCounts = useCallback(async (): Promise<void> => {
    await queryClient.invalidateQueries({ queryKey: qk.labelCounts(accountId, COUNTS_UNREAD_ONLY) })
  }, [accountId, queryClient])

  const toggleFavorite = useCallback(
    async (name: string): Promise<void> => {
      const labels = labelsQuery.data ?? []
      const label = labels.find((l) => l.name === name)
      if (!label) return
      try {
        await toggleFavoriteMutation.mutateAsync({ name, next: !label.is_favorite })
      } catch {
        /* swallowed in onError */
      }
    },
    [labelsQuery.data, toggleFavoriteMutation],
  )

  const reorderFavorites = useCallback((newOrder: string[]) => {
    setFavoriteOrder(newOrder)
    saveFavoriteLabelOrder(newOrder)
  }, [])

  const getLabelByName = useCallback(
    (name: string): Label | undefined => {
      return (labelsQuery.data ?? []).find((l) => l.name === name)
    },
    [labelsQuery.data],
  )

  // ---------- derived: favorites + projects ----------

  const labels: Label[] = labelsQuery.data ?? []
  const labelCounts: Record<string, number> = countsQuery.data ?? {}

  // Core labels always shown first in this exact order
  const CORE_LABEL_ORDER = ['Action', 'FYI', 'Noise']

  const projectLabels = useMemo(() => {
    return labels.filter((l) => l.is_project).sort((a, b) => a.name.localeCompare(b.name))
  }, [labels])

  const favoriteLabels = useMemo(() => {
    // Pre-load DEFAULT_LABELS until the real list arrives so tabs render
    // immediately (otherwise the header would flicker on first paint).
    const source: Label[] = labels.length > 0
      ? labels
      : DEFAULT_LABELS.map((d) => ({ ...d, created_at: '', rules: [] } as Label))
    const favorites = source.filter((l) => l.is_favorite)

    const coreLabels = CORE_LABEL_ORDER
      .map((name) => favorites.find((l) => l.name === name) || source.find((l) => l.name === name))
      .filter((l): l is Label => !!l)

    const coreNames = new Set(CORE_LABEL_ORDER)
    const rest = favorites.filter((l) => !coreNames.has(l.name))

    const order = favoriteOrder.length > 0 ? favoriteOrder : []
    rest.sort((a, b) => {
      const aIndex = order.indexOf(a.name)
      const bIndex = order.indexOf(b.name)
      if (aIndex === -1 && bIndex === -1) return a.name.localeCompare(b.name)
      if (aIndex === -1) return 1
      if (bIndex === -1) return -1
      return aIndex - bIndex
    })

    return [...coreLabels, ...rest]
  }, [labels, favoriteOrder])

  return {
    labels,
    favoriteLabels,
    projectLabels,
    labelCounts,
    loading: active ? labelsQuery.isLoading : false,
    error: labelsQuery.error ? 'Impossible de charger les labels' : null,
    refreshLabels,
    refreshCounts,
    toggleFavorite,
    reorderFavorites,
    getLabelByName,
  }
}
