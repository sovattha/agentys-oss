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

import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import type { Label } from '../../types/labels'
import type { Contact } from '../compose/ContactAutocomplete'
import { apiClient } from '../../services/api'
import { SearchChip, CHIP_COLORS } from './SearchChip'
import {
  SearchSuggestionsDropdown,
  buildSavedSearchItems,
  buildRecentItems,
  buildContactItems,
  buildLabelItems,
  buildOperatorItems,
  buildApiSenderItems,
  buildApiSubjectItems,
  buildDateItems,
  type SuggestionItem,
  type InlineFilterState,
} from './SearchSuggestionsDropdown'
import { useSavedSearches } from '../../hooks/useSavedSearches'
import { SaveSearchModal } from './SaveSearchModal'
import { SearchIcon, PlusIcon, CloseIcon } from '../icons/ActionIcons'
import './SmartSearchBar.css'

export interface SearchFilter {
  type: 'from' | 'to' | 'cc' | 'subject' | 'label' | 'body' | 'has' | 'after' | 'before' | 'text' | 'exclude' | 'in'
  value: string
  displayValue: string
  color?: string
}

interface SmartSearchBarProps {
  onSearch: (query: string) => void
  initialValue?: string
  isLoading?: boolean
  labels?: Label[]
  accountId?: string
  /** Called when the user presses Escape with nothing left to clear — closes the bar */
  onClose?: () => void
}

const RECENT_SEARCHES_KEY = 'agentys_recent_searches'
const MAX_RECENT = 8

function loadRecentSearches(): string[] {
  try {
    const stored = localStorage.getItem(RECENT_SEARCHES_KEY)
    return stored ? JSON.parse(stored) : []
  } catch {
    return []
  }
}

function saveRecentSearch(query: string) {
  const recents = loadRecentSearches()
  const filtered = recents.filter(r => r !== query)
  filtered.unshift(query)
  localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(filtered.slice(0, MAX_RECENT)))
}

/** Detect if text starts with a filter prefix like from:, de:, to:, etc. */
function detectPrefix(text: string): { prefix: string; remainder: string } | null {
  const prefixes: Record<string, string> = {
    'from:': 'from',
    'de:': 'from',
    'to:': 'to',
    'a:': 'to',
    'cc:': 'cc',
    'is:': 'has',
    'subject:': 'subject',
    'objet:': 'subject',
    'label:': 'label',
    'contenu:': 'body',
    'body:': 'body',
    'has:': 'has',
    'after:': 'after',
    'before:': 'before',
    'in:': 'in',
    'folder:': 'in',
    'dossier:': 'in',
    '-': 'exclude',
  }

  const lower = text.toLowerCase()
  for (const [p, type] of Object.entries(prefixes)) {
    if (lower.startsWith(p)) {
      return { prefix: type, remainder: text.slice(p.length) }
    }
  }
  return null
}

/** Build a query string from filters + free text. */
function buildQueryFromFilters(filters: SearchFilter[], textQuery: string): string {
  const parts: string[] = []

  for (const f of filters) {
    switch (f.type) {
      case 'from':
        parts.push(`from:${f.value}`)
        break
      case 'to':
        parts.push(`to:${f.value}`)
        break
      case 'cc':
        parts.push(`cc:${f.value}`)
        break
      case 'subject':
        parts.push(`subject:${f.value}`)
        break
      case 'label':
        parts.push(`label:${f.value}`)
        break
      case 'body':
        parts.push(`body:${f.value}`)
        break
      case 'has':
        parts.push(`has:${f.value}`)
        break
      case 'after':
        parts.push(`after:${f.value}`)
        break
      case 'before':
        parts.push(`before:${f.value}`)
        break
      case 'in':
        parts.push(`in:${f.value}`)
        break
      case 'exclude':
        parts.push(`-${f.value}`)
        break
      case 'text':
        parts.push(f.value)
        break
    }
  }

  if (textQuery.trim()) {
    parts.push(textQuery.trim())
  }

  return parts.join(' ')
}

export function SmartSearchBar({
  onSearch,
  initialValue = '',
  isLoading = false,
  labels = [],
  accountId,
  onClose,
}: SmartSearchBarProps) {
  const [filters, setFilters] = useState<SearchFilter[]>([])
  const [textQuery, setTextQuery] = useState(initialValue)
  const [isDropdownOpen, setIsDropdownOpen] = useState(false)
  const { t } = useTranslation('search')
  const [highlightedIndex, setHighlightedIndex] = useState(-1)
  const [recentSearches] = useState<string[]>(loadRecentSearches)
  const [contactResults, setContactResults] = useState<Contact[]>([])
  const [apiSuggestions, setApiSuggestions] = useState<{
    senders: { email: string; name: string }[]
    subjects: string[]
    labels: { name: string; color: string }[]
  }>({ senders: [], subjects: [], labels: [] })
  const [showSaveModal, setShowSaveModal] = useState(false)
  const { searches: savedSearches, saveSearch, deleteSearch } = useSavedSearches()

  const [editingChipIndex, setEditingChipIndex] = useState<number | null>(null)
  const [editingChipValue, setEditingChipValue] = useState('')
  const chipEditRef = useRef<HTMLInputElement>(null)

  // Inline filter panel state
  const [inlineFilter, setInlineFilter] = useState<InlineFilterState | null>(null)
  const inlineActiveRef = useRef(false)
  const inlineInputRef = useRef<HTMLInputElement>(null)
  const [inlineContacts, setInlineContacts] = useState<Contact[]>([])
  const [inlineHighlightedIndex, setInlineHighlightedIndex] = useState(-1)

  const inputRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const blurCloseRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isFocusedRef = useRef(false)
  const suppressNextFocusRef = useRef(false)
  // Version counter to discard stale async results (race condition fix)
  const searchVersionRef = useRef(0)

  // Build suggestion items based on current state
  const suggestions = useMemo((): SuggestionItem[] => {
    const items: SuggestionItem[] = []
    const query = textQuery.trim()
    const prefixInfo = detectPrefix(query)

    // Always show saved searches first (if any)
    const savedItems = buildSavedSearchItems(savedSearches, query)
    if (savedItems.length > 0) items.push(...savedItems)

    if (!query) {
      // Empty focus: show recents + operators + quick filters
      items.push(...buildRecentItems(recentSearches, ''))
      items.push(...buildOperatorItems(t))
    } else if (prefixInfo && (prefixInfo.prefix === 'from' || prefixInfo.prefix === 'to') && prefixInfo.remainder.length >= 1) {
      // Contact autocomplete mode (from: or to:)
      items.push(...buildContactItems(contactResults, prefixInfo.prefix as 'from' | 'to'))
    } else if (prefixInfo && prefixInfo.prefix === 'label') {
      // Label autocomplete mode (label:)
      const labelItems = buildLabelItems(labels, prefixInfo.remainder || '')
      if (labelItems.length > 0) {
        items.push(...labelItems)
      } else if (!prefixInfo.remainder) {
        // No remainder yet — show all labels
        items.push(...buildLabelItems(labels, ''))
      }
    } else if (prefixInfo && (prefixInfo.prefix === 'after' || prefixInfo.prefix === 'before')) {
      // Date picker mode — show predefined period suggestions
      items.push(...buildDateItems(prefixInfo.prefix, t))
    } else {
      // General query: show matching recents, contacts, labels
      const recentItems = buildRecentItems(recentSearches, query)
      if (recentItems.length > 0) items.push(...recentItems)

      if (query.length >= 2) {
        // Local contacts (from cache)
        const localContactEmails = new Set(contactResults.map(c => c.email))
        const contactItems = buildContactItems(contactResults)
        if (contactItems.length > 0) items.push(...contactItems)

        // API senders (deduplicated vs local contacts)
        const apiSenderItems = buildApiSenderItems(apiSuggestions.senders, localContactEmails)
        if (apiSenderItems.length > 0) items.push(...apiSenderItems)

        const labelItems = buildLabelItems(labels, query)
        if (labelItems.length > 0) items.push(...labelItems)

        // API subjects
        const apiSubjectItems = buildApiSubjectItems(apiSuggestions.subjects)
        if (apiSubjectItems.length > 0) items.push(...apiSubjectItems)
      }
    }

    return items
  }, [textQuery, recentSearches, contactResults, apiSuggestions, labels, savedSearches, t])

  // Search contacts API (debounced)
  const searchContacts = useCallback(async (query: string, version: number) => {
    if (query.length < 1) {
      setContactResults([])
      return
    }
    try {
      const results = await apiClient.searchContacts(query, accountId)
      if (isFocusedRef.current && version === searchVersionRef.current) {
        setContactResults(results)
      }
    } catch {
      setContactResults([])
    }
  }, [accountId])

  // Handle text input change
  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value
    setTextQuery(val)
    setIsDropdownOpen(true)
    setHighlightedIndex(-1)

    // Debounced contact search (only for contact-relevant prefixes or general query)
    if (debounceRef.current) clearTimeout(debounceRef.current)

    const trimmed = val.trim()
    const prefixInfo = detectPrefix(trimmed)
    const isContactPrefix = prefixInfo && (prefixInfo.prefix === 'from' || prefixInfo.prefix === 'to')
    const searchTerm = prefixInfo ? prefixInfo.remainder : trimmed

    // Label/date prefix → no API call needed
    if (prefixInfo && (prefixInfo.prefix === 'label' || prefixInfo.prefix === 'after' || prefixInfo.prefix === 'before')) {
      setContactResults([])
      return
    }

    if (isContactPrefix && searchTerm.length >= 1) {
      debounceRef.current = setTimeout(() => {
        const version = ++searchVersionRef.current
        searchContacts(searchTerm, version)
      }, 300)
    } else if (!prefixInfo && searchTerm.length >= 2) {
      debounceRef.current = setTimeout(async () => {
        const version = ++searchVersionRef.current
        await Promise.all([
          searchContacts(searchTerm, version),
          apiClient.getSearchSuggestions(searchTerm, accountId)
            .then(data => {
              if (!isFocusedRef.current || version !== searchVersionRef.current) return
              // BUG-T001 (2026-05-16): always returning a new object reference
              // from the API made the `suggestions` memo recompute on every
              // response — even when the suggestions list was identical to
              // the previous one. Combined with the downstream
              // onDisplayedEmailsChange loop, this could push React past its
              // update-depth limit. Skip the setState if the shape didn't
              // change.
              setApiSuggestions(prev => {
                if (
                  prev.senders.length === data.senders.length &&
                  prev.subjects.length === data.subjects.length &&
                  prev.labels.length === data.labels.length &&
                  prev.senders.every((s, i) => s.email === data.senders[i]?.email) &&
                  prev.subjects.every((s, i) => s === data.subjects[i]) &&
                  prev.labels.every((l, i) => l.name === data.labels[i]?.name)
                ) {
                  return prev
                }
                return data
              })
            })
            .catch(() => {}),
        ])
      }, 300)
    } else {
      setContactResults(prev => prev.length === 0 ? prev : [])
      setApiSuggestions(prev =>
        prev.senders.length === 0 && prev.subjects.length === 0 && prev.labels.length === 0
          ? prev
          : { senders: [], subjects: [], labels: [] }
      )
    }

    // Search as-you-type : déclenche onSearch après 500ms si ≥3 chars, pas de prefix incomplet
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current)
    const hasIncompletePrefix = trimmed.endsWith(':') || (prefixInfo !== null && prefixInfo.remainder.trim() === '')
    if (trimmed.length >= 3 && !hasIncompletePrefix) {
      searchDebounceRef.current = setTimeout(() => {
        onSearch(buildQueryFromFilters(filters, trimmed))
      }, 500)
    }
  }

  // Handle suggestion selection
  const handleSelectSuggestion = useCallback((item: SuggestionItem) => {
    if ((item.type === 'recent' || item.type === 'saved') && item.rawQuery) {
      // For recent/saved searches, execute the raw query directly
      setTextQuery(item.rawQuery)
      setIsDropdownOpen(false)
      onSearch(item.rawQuery)
      return
    }

    if (item.type === 'operator' && item.prefixInsert) {
      // Open inline filter panel instead of inserting prefix into main input
      inlineActiveRef.current = true
      setInlineFilter({ item, inputValue: '' })
      setInlineHighlightedIndex(-1)
      setIsDropdownOpen(true)
      // Prefetch contacts on open for from/to/cc operators so the user sees
      // suggestions immediately (matches ContactAutocomplete which fires its
      // API on focus). Without this the panel opens empty and users had to
      // type to discover that the autocomplete exists at all.
      const prefixInfo = detectPrefix(item.prefixInsert)
      const filterTypeOnOpen = prefixInfo?.prefix || ''
      if (['from', 'to', 'cc'].includes(filterTypeOnOpen)) {
        const version = ++searchVersionRef.current
        ;(async () => {
          try {
            const results = await apiClient.searchContacts('', accountId, { includeSelf: true })
            if (version === searchVersionRef.current) setInlineContacts(results)
          } catch {
            // Silent — empty list just means no suggestions until the user
            // types, same effect as the legacy fall-through.
          }
        })()
      }
      // Double-rAF to ensure dropdown is rendered before focusing
      requestAnimationFrame(() => requestAnimationFrame(() => {
        inlineInputRef.current?.focus()
      }))
      return
    }

    if (item.filterType && item.filterValue) {
      const newFilter: SearchFilter = {
        type: item.filterType,
        value: item.filterValue,
        displayValue: item.filterDisplayValue || item.filterValue,
        color: item.filterColor,
      }
      setFilters(prev => [...prev, newFilter])
      setTextQuery('')
      setContactResults([])
      setIsDropdownOpen(false)

      // Auto-execute search with new filter
      const query = buildQueryFromFilters([...filters, newFilter], '')
      if (query) {
        onSearch(query)
        saveRecentSearch(query)
      }

      // Re-focus input so user can immediately add another filter
      suppressNextFocusRef.current = true
      requestAnimationFrame(() => {
        inputRef.current?.focus()
      })
    }
  }, [filters, onSearch, accountId])

  // Remove a filter chip
  const handleRemoveFilter = useCallback((index: number) => {
    setFilters(prev => {
      const next = [...prev]
      next.splice(index, 1)
      const query = buildQueryFromFilters(next, textQuery)
      onSearch(query || '')
      return next
    })
    inputRef.current?.focus()
  }, [textQuery, onSearch])

  // Chip inline editing
  const startEditChip = useCallback((index: number) => {
    setEditingChipIndex(index)
    setEditingChipValue(filters[index].displayValue)
    setIsDropdownOpen(false)
  }, [filters])

  const commitChipEdit = useCallback(() => {
    if (editingChipIndex === null) return
    const trimmed = editingChipValue.trim()
    if (trimmed) {
      setFilters(prev => {
        const next = [...prev]
        next[editingChipIndex] = { ...next[editingChipIndex], value: trimmed, displayValue: trimmed }
        const query = buildQueryFromFilters(next, textQuery)
        if (query) onSearch(query)
        return next
      })
    }
    setEditingChipIndex(null)
    suppressNextFocusRef.current = true
    requestAnimationFrame(() => inputRef.current?.focus())
  }, [editingChipIndex, editingChipValue, textQuery, onSearch])

  const cancelChipEdit = useCallback(() => {
    setEditingChipIndex(null)
    suppressNextFocusRef.current = true
    requestAnimationFrame(() => inputRef.current?.focus())
  }, [])

  // ── Inline filter handlers ────────────────────────────────────────────────

  const handleInlineChange = useCallback((val: string) => {
    setInlineHighlightedIndex(-1)
    setInlineFilter(prev => {
      if (!prev) return null
      const prefix = prev.item.prefixInsert || ''
      const prefixInfo = detectPrefix(prefix)
      const type = prefixInfo?.prefix || ''
      // For contact filters, fire the API on every change INCLUDING an
      // empty value so the dropdown keeps showing top contacts after the
      // user backspaces. Matches ContactAutocomplete's focus-fires-API UX.
      if (['from', 'to', 'cc'].includes(type)) {
        if (debounceRef.current) clearTimeout(debounceRef.current)
        debounceRef.current = setTimeout(async () => {
          const version = ++searchVersionRef.current
          try {
            // includeSelf: the inbox search bar must surface the user's own
            // multi-account emails too (e.g. finding emails from your other
            // address). Without this the backend strips them, leaving the
            // dropdown empty when the user types their own name.
            const results = await apiClient.searchContacts(val, accountId, { includeSelf: true })
            if (version === searchVersionRef.current) setInlineContacts(results)
          } catch {
            // Keep previous suggestions on error rather than clearing —
            // avoids a flashing dropdown on transient network blips.
          }
        }, 300)
      } else if (type !== 'label') {
        setInlineContacts([])
      }
      return { ...prev, inputValue: val }
    })
  }, [accountId])

  const handleInlineSubmit = useCallback((displayValue: string, value: string) => {
    if (!inlineActiveRef.current) return
    const current = inlineFilter
    if (!current) return
    inlineActiveRef.current = false
    const prefixInfo = detectPrefix(current.item.prefixInsert || '')
    if (!prefixInfo) return

    const newFilter: SearchFilter = {
      type: prefixInfo.prefix as SearchFilter['type'],
      value,
      displayValue,
      color: current.item.filterColor,
    }

    setFilters(existing => {
      const toAdd: SearchFilter[] = [newFilter]
      // "Sent to:" — also add in:sent automatically
      if (current.item.addSentFilter && !existing.some(f => f.type === 'in' && f.value === 'sent')) {
        toAdd.push({ type: 'in', value: 'sent', displayValue: t('op_in_sent_display'), color: '#10b981' })
      }
      const next = [...existing, ...toAdd]
      const query = buildQueryFromFilters(next, textQuery)
      if (query) {
        onSearch(query)
        saveRecentSearch(query)
      }
      return next
    })

    setInlineFilter(null)
    setInlineContacts([])
    setInlineHighlightedIndex(-1)
    suppressNextFocusRef.current = true
    requestAnimationFrame(() => inputRef.current?.focus())
  }, [inlineFilter, textQuery, onSearch, t])

  const handleInlineCancel = useCallback(() => {
    inlineActiveRef.current = false
    setInlineFilter(null)
    setInlineContacts([])
    setInlineHighlightedIndex(-1)
    suppressNextFocusRef.current = true
    requestAnimationFrame(() => inputRef.current?.focus())
  }, [])

  // Auto-select text in chip edit input when entering edit mode
  useEffect(() => {
    if (editingChipIndex !== null) {
      requestAnimationFrame(() => chipEditRef.current?.select())
    }
  }, [editingChipIndex])

  // Handle keyboard navigation
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (!isDropdownOpen) {
        setIsDropdownOpen(true)
      }
      setHighlightedIndex(prev =>
        prev < suggestions.length - 1 ? prev + 1 : prev
      )
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlightedIndex(prev => (prev > 0 ? prev - 1 : -1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      // Annuler le debounce as-you-type — Enter déclenche immédiatement
      if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current)
      // Si du texte est présent dans l'input, Enter crée le chip et lance la recherche directement
      // (la suggestion surlignée est ignorée pour éviter le double-Enter)
      if (highlightedIndex >= 0 && highlightedIndex < suggestions.length && !textQuery.trim()) {
        handleSelectSuggestion(suggestions[highlightedIndex])
      } else {
        // Execute current query
        const prefixInfo = detectPrefix(textQuery.trim())
        if (prefixInfo && prefixInfo.remainder.trim()) {
          // Convert prefix + remainder into a filter
          const newFilter: SearchFilter = {
            type: prefixInfo.prefix as SearchFilter['type'],
            value: prefixInfo.remainder.trim(),
            displayValue: prefixInfo.remainder.trim(),
          }
          setFilters(prev => [...prev, newFilter])
          setTextQuery('')
          const query = buildQueryFromFilters([...filters, newFilter], '')
          if (query) {
            onSearch(query)
            saveRecentSearch(query)
          }
        } else if (textQuery.trim()) {
          // Convert plain text into a "text" filter chip
          const newFilter: SearchFilter = {
            type: 'text',
            value: textQuery.trim(),
            displayValue: textQuery.trim(),
          }
          setFilters(prev => [...prev, newFilter])
          setTextQuery('')
          const query = buildQueryFromFilters([...filters, newFilter], '')
          if (query) {
            onSearch(query)
            saveRecentSearch(query)
          }
        } else if (filters.length > 0) {
          // Enter with empty input but existing filters → re-trigger search
          const query = buildQueryFromFilters(filters, '')
          if (query) {
            onSearch(query)
          }
        }
        setIsDropdownOpen(false)
      }
    } else if (e.key === 'Escape') {
      // BUG-#14 (2026-05-17): a single Escape now fully closes the bar.
      // Previously Esc collapsed the dropdown but left the search input
      // pinned + focused, so the next letter (e.g. `n`) typed into the
      // search instead of triggering a global shortcut. Footer hint promises
      // "Esc Close", so honour that on the first press.
      e.preventDefault()
      if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current)
      if (inlineFilter) handleInlineCancel()
      const hadContent = textQuery || filters.length > 0
      setTextQuery('')
      setFilters([])
      setIsDropdownOpen(false)
      if (hadContent) onSearch('')
      inputRef.current?.blur()
      // Hand focus back to the list so subsequent shortcut keys (N, /, ?…)
      // are received by the global window listener instead of leaking into
      // a stale input.
      if (typeof document !== 'undefined' && document.body) {
        try { (document.body as HTMLElement).focus?.() } catch { /* no-op */ }
      }
      onClose?.()
      return
    } else if (e.key === 'Backspace' && textQuery === '' && filters.length > 0) {
      // Remove last chip on backspace at position 0
      handleRemoveFilter(filters.length - 1)
    }
  }

  // Focus/blur handlers
  const handleFocus = () => {
    if (suppressNextFocusRef.current) {
      suppressNextFocusRef.current = false
      return
    }
    isFocusedRef.current = true
    setIsDropdownOpen(true)
  }

  const handleBlur = () => {
    isFocusedRef.current = false
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (blurCloseRef.current) clearTimeout(blurCloseRef.current)
    // Delay closing to allow click on suggestions
    blurCloseRef.current = setTimeout(() => {
      if (!isFocusedRef.current) {
        // Don't close dropdown while inline filter is active — user is typing in it
        if (inlineActiveRef.current) return
        setIsDropdownOpen(false)
      }
      blurCloseRef.current = null
    }, 200)
  }

  // Close dropdown on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Cleanup debounces on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current)
      if (blurCloseRef.current) clearTimeout(blurCloseRef.current)
    }
  }, [])

  // BUG-I002 (2026-04-26): autofocus on mount caused the search dropdown
  // to open whenever EmailList unmounted/remounted the bar — which happens
  // on every label tab click because EmailList early-returns a loading
  // skeleton (without the SmartSearchBar) while the new label's emails
  // fetch. The remount fired this effect and stole focus from the page,
  // hijacking the user's next keystroke into the search input.
  //
  // Focus is now driven explicitly by the parent's toggle handlers
  // (toggleSearchFromShortcut for `/`, toggleSearchBar for the header icon
  // click — both call `inputRef.focus()` after `setShowSearchBar(true)`).
  // We still focus when *content* changes via filter inserts (handled in
  // the per-action focus calls scattered through this file).

  const handleClear = () => {
    setTextQuery('')
    setFilters([])
    setContactResults([])
    setInlineFilter(null)
    setInlineContacts([])
    onSearch('')
    inputRef.current?.focus()
  }

  const hasContent = textQuery.trim() !== '' || filters.length > 0

  return (
    <div className="smart-search-bar" ref={containerRef} data-testid="smart-search-bar">
      <div className="smart-search-input-row">
        <span className="smart-search-icon" aria-hidden="true">
          <SearchIcon />
        </span>

        {filters.map((filter, i) => (
          editingChipIndex === i
            ? <input
                key={`edit-chip-${i}`}
                ref={chipEditRef}
                className="search-chip-edit-input"
                style={{ '--chip-color': filter.color || CHIP_COLORS[filter.type] || 'var(--accent-primary)' } as React.CSSProperties}
                value={editingChipValue}
                onChange={(e) => setEditingChipValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') { e.preventDefault(); commitChipEdit() }
                  if (e.key === 'Escape') { e.preventDefault(); cancelChipEdit() }
                }}
                onBlur={commitChipEdit}
                aria-label={`Modifier le filtre ${filter.type}`}
              />
            : <SearchChip
                key={`${filter.type}-${filter.value}-${i}`}
                filter={filter}
                onRemove={() => handleRemoveFilter(i)}
                onEdit={() => startEditChip(i)}
              />
        ))}

        {filters.length > 0 && !textQuery && (
          <button
            type="button"
            className="smart-search-add-filter"
            onClick={() => {
              inputRef.current?.focus()
              setIsDropdownOpen(true)
            }}
          >
            <PlusIcon size={16} />
            {t('add_filter')}
          </button>
        )}

        <input
          ref={inputRef}
          type="text"
          className="smart-search-input"
          data-testid="smart-search-input"
          placeholder={filters.length > 0 ? '' : t('search_placeholder')}
          value={textQuery}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          onFocus={handleFocus}
          onBlur={handleBlur}
          aria-label={t('search_emails_aria')}
          aria-expanded={isDropdownOpen}
          aria-autocomplete="list"
          autoComplete="off"
          spellCheck={false}
        />

        {isLoading ? (
          <span className="smart-search-loading" aria-label="Recherche en cours">
            <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="spinner">
              <circle cx="12" cy="12" r="10" strokeOpacity="0.25" />
              <path d="M12 2a10 10 0 0 1 10 10" />
            </svg>
          </span>
        ) : hasContent ? (
          <>
            <button
              type="button"
              className={`smart-search-save${filters.length > 0 ? ' has-content' : ''}`}
              onClick={() => setShowSaveModal(true)}
              aria-label={t('save_search_title')}
              title={t('save_search_btn')}
            >
              <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
              </svg>
            </button>
            <button
              type="button"
              className="smart-search-clear"
              onClick={handleClear}
              aria-label={t('clear_search')}
            >
              <CloseIcon size={16} />
            </button>
          </>
        ) : null}
      </div>

      <SearchSuggestionsDropdown
        items={suggestions}
        highlightedIndex={highlightedIndex}
        onSelect={handleSelectSuggestion}
        onHighlight={setHighlightedIndex}
        visible={isDropdownOpen}
        onDeleteSaved={deleteSearch}
        activeFilters={filters}
        inlineFilter={inlineFilter}
        inlineInputRef={inlineInputRef}
        inlineContacts={inlineContacts}
        inlineHighlightedIndex={inlineHighlightedIndex}
        onInlineChange={handleInlineChange}
        onInlineSubmit={handleInlineSubmit}
        onInlineCancel={handleInlineCancel}
        onInlineHighlight={setInlineHighlightedIndex}
        labels={labels}
      />

      {showSaveModal && (
        <SaveSearchModal
          query={buildQueryFromFilters(filters, textQuery)}
          onSave={saveSearch}
          onClose={() => setShowSaveModal(false)}
        />
      )}
    </div>
  )
}
