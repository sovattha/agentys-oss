import { useState, useEffect, useCallback } from 'react'
import type {
  Snippet,
  SharedSnippet,
  CreateSnippetPayload,
  UpdateSnippetPayload,
} from '../types/snippets'
import {
  fetchSnippets,
  fetchSharedSnippets as apiFetchSharedSnippets,
  createSnippet as apiCreateSnippet,
  updateSnippet as apiUpdateSnippet,
  deleteSnippet as apiDeleteSnippet,
  recordSnippetUsage,
  shareSnippet as apiShareSnippet,
  unshareSnippet as apiUnshareSnippet,
  duplicateSnippet as apiDuplicateSnippet,
  getLocalSnippets,
  saveLocalSnippets,
} from '../api/snippets'

export interface UseSnippetsReturn {
  snippets: Snippet[]
  loading: boolean
  error: string | null
  createSnippet: (payload: CreateSnippetPayload) => Promise<Snippet>
  updateSnippet: (id: string, payload: UpdateSnippetPayload) => Promise<Snippet>
  deleteSnippet: (id: string) => Promise<void>
  trackSnippetUsage: (snippet: Snippet) => void
  refreshSnippets: () => Promise<void>
  getSnippetById: (id: string) => Snippet | undefined
  // Sharing
  sharedSnippets: SharedSnippet[]
  sharedLoading: boolean
  shareSnippet: (id: string, email: string) => Promise<void>
  unshareSnippet: (id: string, email: string) => Promise<void>
  duplicateSnippet: (id: string) => Promise<Snippet>
  refreshSharedSnippets: () => Promise<void>
}

export function useSnippets(accountId?: number): UseSnippetsReturn {
  const [snippets, setSnippets] = useState<Snippet[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [useLocalStorage, setUseLocalStorage] = useState(false)

  const [sharedSnippets, setSharedSnippets] = useState<SharedSnippet[]>([])
  const [sharedLoading, setSharedLoading] = useState(false)

  const loadSnippets = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)

      // Try API first
      const response = await fetchSnippets(accountId)
      setSnippets(response.snippets)
      setUseLocalStorage(false)
    } catch (err) {
      console.warn('Backend snippets not available, using localStorage:', err)
      // Fallback to localStorage
      const localSnippets = getLocalSnippets()
      setSnippets(localSnippets)
      setUseLocalStorage(true)
    } finally {
      setLoading(false)
    }
  }, [accountId])

  const loadSharedSnippets = useCallback(async () => {
    if (useLocalStorage) return
    try {
      setSharedLoading(true)
      const response = await apiFetchSharedSnippets()
      setSharedSnippets(response.snippets)
    } catch (err) {
      console.warn('Failed to load shared snippets:', err)
    } finally {
      setSharedLoading(false)
    }
  }, [useLocalStorage])

  useEffect(() => {
    loadSnippets()
  }, [loadSnippets])

  // Load shared snippets after own snippets (once we know if backend is available)
  useEffect(() => {
    if (!loading && !useLocalStorage) {
      loadSharedSnippets()
    }
  }, [loading, useLocalStorage, loadSharedSnippets])

  const createSnippet = useCallback(
    async (payload: CreateSnippetPayload): Promise<Snippet> => {
      if (useLocalStorage) {
        // Create locally
        const newSnippet: Snippet = {
          id: `snippet_${Date.now()}`,
          name: payload.name,
          content: payload.content,
          subject: payload.subject,
          to: payload.to,
          cc: payload.cc,
          bcc: payload.bcc,
          category: payload.category,
          is_private: payload.is_private ?? true,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          use_count: 0,
        }

        const updatedSnippets = [...snippets, newSnippet]
        setSnippets(updatedSnippets)
        saveLocalSnippets(updatedSnippets)
        return newSnippet
      }

      // Use API
      const response = await apiCreateSnippet(payload, accountId)
      setSnippets((prev) => [...prev, response.snippet])
      return response.snippet
    },
    [snippets, useLocalStorage, accountId]
  )

  const updateSnippet = useCallback(
    async (id: string, payload: UpdateSnippetPayload): Promise<Snippet> => {
      if (useLocalStorage) {
        // Update locally
        const updatedSnippets = snippets.map((s) => {
          if (s.id === id) {
            return {
              ...s,
              ...payload,
              updated_at: new Date().toISOString(),
            }
          }
          return s
        })

        setSnippets(updatedSnippets)
        saveLocalSnippets(updatedSnippets)

        const updated = updatedSnippets.find((s) => s.id === id)
        if (!updated) throw new Error('Snippet not found')
        return updated
      }

      // Use API
      const response = await apiUpdateSnippet(id, payload)
      setSnippets((prev) =>
        prev.map((s) => (s.id === id ? response.snippet : s))
      )
      return response.snippet
    },
    [snippets, useLocalStorage]
  )

  const deleteSnippet = useCallback(
    async (id: string): Promise<void> => {
      if (useLocalStorage) {
        // Delete locally
        const updatedSnippets = snippets.filter((s) => s.id !== id)
        setSnippets(updatedSnippets)
        saveLocalSnippets(updatedSnippets)
        return
      }

      // Use API
      await apiDeleteSnippet(id)
      setSnippets((prev) => prev.filter((s) => s.id !== id))
    },
    [snippets, useLocalStorage]
  )

  const trackSnippetUsage = useCallback(
    (snippet: Snippet) => {
      // Record usage
      if (useLocalStorage) {
        const updatedSnippets = snippets.map((s) => {
          if (s.id === snippet.id) {
            return { ...s, use_count: s.use_count + 1 }
          }
          return s
        })
        setSnippets(updatedSnippets)
        saveLocalSnippets(updatedSnippets)
      } else {
        recordSnippetUsage(snippet.id).catch(console.warn)
        setSnippets((prev) =>
          prev.map((s) =>
            s.id === snippet.id ? { ...s, use_count: s.use_count + 1 } : s
          )
        )
      }
    },
    [snippets, useLocalStorage]
  )

  const getSnippetById = useCallback(
    (id: string): Snippet | undefined => {
      return snippets.find((s) => s.id === id)
    },
    [snippets]
  )

  const shareSnippet = useCallback(
    async (id: string, email: string): Promise<void> => {
      await apiShareSnippet(id, { email })
    },
    []
  )

  const unshareSnippet = useCallback(
    async (id: string, email: string): Promise<void> => {
      await apiUnshareSnippet(id, email)
    },
    []
  )

  const duplicateSnippet = useCallback(
    async (id: string): Promise<Snippet> => {
      const response = await apiDuplicateSnippet(id)
      setSnippets((prev) => [...prev, response.snippet])
      return response.snippet
    },
    []
  )

  return {
    snippets,
    loading,
    error,
    createSnippet,
    updateSnippet,
    deleteSnippet,
    trackSnippetUsage,
    refreshSnippets: loadSnippets,
    getSnippetById,
    // Sharing
    sharedSnippets,
    sharedLoading,
    shareSnippet,
    unshareSnippet,
    duplicateSnippet,
    refreshSharedSnippets: loadSharedSnippets,
  }
}
