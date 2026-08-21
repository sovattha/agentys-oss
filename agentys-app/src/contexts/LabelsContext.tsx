/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useMemo, type ReactNode } from 'react'
import { useLabels, type UseLabelReturn } from '../hooks/useLabels'
import type { Label } from '../types/labels'

// Split context: components that only need labels data don't re-render on count changes
interface LabelsDataValue {
  labels: Label[]
  favoriteLabels: Label[]
  projectLabels: Label[]
  loading: boolean
  error: string | null
  refreshLabels: () => Promise<void>
  toggleFavorite: (name: string) => Promise<void>
  reorderFavorites: (newOrder: string[]) => void
  getLabelByName: (name: string) => Label | undefined
}

interface LabelCountsValue {
  labelCounts: Record<string, number>
  refreshCounts: () => Promise<void>
}

const LabelsDataContext = createContext<LabelsDataValue | null>(null)
const LabelCountsContext = createContext<LabelCountsValue | null>(null)

// Legacy unified context for backwards compatibility
const LabelsContext = createContext<UseLabelReturn | null>(null)

export function LabelsProvider({ children }: { children: ReactNode }) {
  const all = useLabels()

  const dataValue = useMemo<LabelsDataValue>(() => ({
    labels: all.labels,
    favoriteLabels: all.favoriteLabels,
    projectLabels: all.projectLabels,
    loading: all.loading,
    error: all.error,
    refreshLabels: all.refreshLabels,
    toggleFavorite: all.toggleFavorite,
    reorderFavorites: all.reorderFavorites,
    getLabelByName: all.getLabelByName,
  }), [all.labels, all.favoriteLabels, all.projectLabels, all.loading, all.error, all.refreshLabels, all.toggleFavorite, all.reorderFavorites, all.getLabelByName])

  const countsValue = useMemo<LabelCountsValue>(() => ({
    labelCounts: all.labelCounts,
    refreshCounts: all.refreshCounts,
  }), [all.labelCounts, all.refreshCounts])

  return (
    <LabelsContext.Provider value={all}>
      <LabelsDataContext.Provider value={dataValue}>
        <LabelCountsContext.Provider value={countsValue}>
          {children}
        </LabelCountsContext.Provider>
      </LabelsDataContext.Provider>
    </LabelsContext.Provider>
  )
}

/**
 * Use shared labels from the nearest LabelsProvider.
 * Falls back to a fresh useLabels() instance if no provider is found.
 */
export function useSharedLabels(): UseLabelReturn {
  const ctx = useContext(LabelsContext)
  if (ctx) return ctx
  // eslint-disable-next-line react-hooks/rules-of-hooks
  return useLabels()
}

/** Use only label data (no counts) — won't re-render on count changes. */
export function useSharedLabelsData(): LabelsDataValue {
  const ctx = useContext(LabelsDataContext)
  if (ctx) return ctx
  // eslint-disable-next-line react-hooks/rules-of-hooks
  return useLabels()
}

/** Use only label counts — won't re-render on label data changes. */
export function useSharedLabelCounts(): LabelCountsValue {
  const ctx = useContext(LabelCountsContext)
  if (ctx) return ctx
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const all = useLabels()
  return { labelCounts: all.labelCounts, refreshCounts: all.refreshCounts }
}
