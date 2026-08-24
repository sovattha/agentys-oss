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

/* eslint-disable react-refresh/only-export-components */
import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import type { Label } from '../../types/labels'
import { getLabelDisplayName } from '../../types/labels'
import type { Contact } from '../compose/ContactAutocomplete'
import type { SavedSearch } from '../../hooks/useSavedSearches'
import { CHIP_COLORS } from './SearchChip'
import { getInitials as getAvatarInitials } from '../Avatar'
import { CloseIcon, SearchIcon } from '../icons/ActionIcons'

export interface SuggestionItem {
  id: string
  type: 'recent' | 'contact' | 'label' | 'operator' | 'saved' | 'date' | 'quick'
  label: string
  sublabel?: string
  icon?: 'clock' | 'user' | 'user-send' | 'tag' | 'calendar' | 'mail' | 'paperclip' | 'arrow-right' | 'type' | 'filter' | 'file-text' | 'star' | 'send' | 'heading' | 'align-left' | 'layers' | 'inbox'
  /** Value applied when selected */
  filterType?: 'from' | 'to' | 'cc' | 'subject' | 'label' | 'has' | 'after' | 'before' | 'text' | 'exclude' | 'in'
  filterValue?: string
  filterDisplayValue?: string
  filterColor?: string
  /** For recent searches, the raw query string */
  rawQuery?: string
  /** For operators: the prefix to insert (e.g. "from:") */
  prefixInsert?: string
  /** For saved searches: the saved search ID (for deletion) */
  savedSearchId?: string
  /** Operator group for grid layout */
  group?: 'people' | 'content' | 'date' | 'folder'
  /** When true, also adds in:sent alongside the main filter */
  addSentFilter?: boolean
}

/** State shared between SmartSearchBar and SearchSuggestionsDropdown for inline filter mode */
export interface InlineFilterState {
  item: SuggestionItem
  inputValue: string
}

interface SearchSuggestionsDropdownProps {
  items: SuggestionItem[]
  highlightedIndex: number
  onSelect: (item: SuggestionItem) => void
  onHighlight: (index: number) => void
  visible: boolean
  onDeleteSaved?: (id: string) => void
  /** Active filters — used to highlight operator items that are already applied */
  activeFilters?: { type: string }[]
  /** Inline filter mode — when set, renders a dedicated sub-panel instead of the full list */
  inlineFilter?: InlineFilterState | null
  inlineInputRef?: React.RefObject<HTMLInputElement | null>
  inlineContacts?: Contact[]
  inlineHighlightedIndex?: number
  onInlineChange?: (val: string) => void
  onInlineSubmit?: (displayValue: string, value: string) => void
  onInlineCancel?: () => void
  onInlineHighlight?: (index: number) => void
  /** Available labels — used in inline label filter mode */
  labels?: Label[]
}

// Parse a raw query string into colored mini-chips for display
function parseQueryToMiniChips(query: string): { label: string; color: string }[] {
  const chips: { label: string; color: string }[] = []
  const tokens = query.trim().split(/\s+/)
  for (const token of tokens) {
    if (!token) continue
    const colonIdx = token.indexOf(':')
    if (colonIdx > 0) {
      const prefix = token.slice(0, colonIdx).toLowerCase()
      const value = token.slice(colonIdx + 1)
      const color = CHIP_COLORS[prefix] || '#6b7280'
      chips.push({ label: value || prefix, color })
    } else if (token.startsWith('-')) {
      chips.push({ label: token, color: CHIP_COLORS['exclude'] })
    } else {
      chips.push({ label: token, color: '#6b7280' })
    }
  }
  return chips
}

// Consistent color from name hash
function getAvatarColor(name: string): string {
  const palette = ['#3b82f6', '#8b5cf6', '#22c55e', '#0d9488', '#ea580c', '#6366f1', '#eab308', '#ec4899']
  let hash = 0
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash)
  return palette[Math.abs(hash) % palette.length]
}

// Initiales : déléguées au canon Avatar.getInitials (règle unique « toujours
// 2 lettres », 2026-06-09) — gère aussi les labels type local-part à points.
function getInitials(name: string): string {
  return getAvatarInitials(name, '')
}

/** Derive which SearchFilter.type corresponds to an operator's prefixInsert */
function prefixToFilterType(prefixInsert: string): string {
  const map: Record<string, string> = {
    'from:': 'from', 'de:': 'from',
    'to:': 'to', 'a:': 'to',
    'cc:': 'cc',
    'subject:': 'subject', 'objet:': 'subject',
    'contenu:': 'body', 'body:': 'body',
    'label:': 'label',
    'after:': 'after',
    'before:': 'before',
    '-': 'exclude',
  }
  return map[prefixInsert.toLowerCase()] || 'text'
}

/** Returns placeholder text for inline input based on filter type */
function getInlinePlaceholder(filterType: string, t: TFunction): string {
  switch (filterType) {
    case 'from':    return t('inline_ph_from')
    case 'to':      return t('inline_ph_to')
    case 'cc':      return t('inline_ph_cc')
    case 'subject': return t('inline_ph_subject')
    case 'body':    return t('inline_ph_body')
    case 'label':   return t('inline_ph_label')
    case 'exclude': return t('inline_ph_exclude')
    default:        return t('inline_ph_default')
  }
}

export function SearchSuggestionsDropdown({
  items,
  highlightedIndex,
  onSelect,
  onHighlight,
  visible,
  onDeleteSaved,
  activeFilters = [],
  inlineFilter,
  inlineInputRef,
  inlineContacts = [],
  inlineHighlightedIndex = -1,
  onInlineChange,
  onInlineSubmit,
  onInlineCancel,
  onInlineHighlight,
  labels = [],
}: SearchSuggestionsDropdownProps) {
  const { t } = useTranslation('common')
  const { t: ts } = useTranslation('search')
  const listRef = useRef<HTMLDivElement>(null)

  // Scroll highlighted item into view
  useEffect(() => {
    if (highlightedIndex < 0 || !listRef.current) return
    const el = listRef.current.querySelector(`[data-index="${highlightedIndex}"]`)
    if (el) {
      el.scrollIntoView({ block: 'nearest' })
    }
  }, [highlightedIndex])

  if (!visible) return null

  // ── Inline filter panel mode ────────────────────────────────────────────────
  if (inlineFilter && onInlineSubmit && onInlineCancel) {
    const filterType = prefixToFilterType(inlineFilter.item.prefixInsert || '')
    const isDateMode = filterType === 'after' || filterType === 'before'
    const isLabelMode = filterType === 'label'
    const isContactMode = ['from', 'to', 'cc'].includes(filterType)

    // Inline suggestions list
    let inlineSuggestions: SuggestionItem[] = []
    if (isContactMode) {
      inlineSuggestions = buildContactItems(inlineContacts, filterType as 'from' | 'to')
    } else if (isLabelMode) {
      inlineSuggestions = buildLabelItems(labels, inlineFilter.inputValue)
    }

    const handleInlineKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Escape') { e.preventDefault(); onInlineCancel(); return }
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        onInlineHighlight?.(Math.min((inlineHighlightedIndex ?? -1) + 1, inlineSuggestions.length - 1))
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        onInlineHighlight?.(Math.max((inlineHighlightedIndex ?? -1) - 1, -1))
        return
      }
      if (e.key === 'Enter') {
        e.preventDefault()
        if (inlineHighlightedIndex >= 0 && inlineSuggestions[inlineHighlightedIndex]) {
          const s = inlineSuggestions[inlineHighlightedIndex]
          onInlineSubmit(s.filterDisplayValue || s.label, s.filterValue || s.label)
        } else if (inlineFilter.inputValue.trim()) {
          onInlineSubmit(inlineFilter.inputValue.trim(), inlineFilter.inputValue.trim())
        }
      }
    }

    return (
      <div className="search-suggestions-dropdown" ref={listRef} role="dialog" aria-label={ts('inline_filter_aria', { label: inlineFilter.item.label })} onMouseDown={(e) => { if ((e.target as HTMLElement).tagName !== 'INPUT') e.preventDefault() }}>
        <div className="inline-filter-panel">
          {/* Header: badge + input (or just title for date mode) */}
          <div className="inline-filter-header">
            <span className="inline-filter-badge">{inlineFilter.item.label}</span>
            {!isDateMode && (
              <input
                ref={inlineInputRef}
                type="text"
                className="inline-filter-input"
                data-testid="inline-filter-input"
                placeholder={getInlinePlaceholder(filterType, ts)}
                value={inlineFilter.inputValue}
                onChange={(e) => onInlineChange?.(e.target.value)}
                onKeyDown={handleInlineKeyDown}
                autoComplete="off"
                spellCheck={false}
                aria-label={getInlinePlaceholder(filterType, ts)}
              />
            )}
            <button
              type="button"
              className="inline-filter-cancel"
              onClick={onInlineCancel}
              aria-label={ts('inline_cancel_aria')}
            >
              <CloseIcon size={12} />
            </button>
          </div>

          {/* Date mode: text input with yyyy/mm/dd format */}
          {isDateMode && (
            <div className="inline-date-picker-wrap">
              <input
                ref={inlineInputRef}
                type="text"
                inputMode="numeric"
                className="inline-date-picker"
                data-testid="inline-date-picker"
                placeholder="yyyy/mm/dd"
                autoFocus
                autoComplete="off"
                spellCheck={false}
                onChange={(e) => {
                  // Auto-insert slashes: yyyy/ → yyyy/mm/ → yyyy/mm/dd
                  let v = e.target.value.replace(/[^\d/]/g, '')
                  const digits = v.replace(/\//g, '')
                  if (digits.length >= 4 && v.indexOf('/') === -1) v = digits.slice(0, 4) + '/' + digits.slice(4)
                  if (digits.length >= 6 && (v.match(/\//g) || []).length < 2) {
                    const parts = v.split('/')
                    v = parts[0] + '/' + (parts[1] || '').slice(0, 2) + '/' + ((parts[1] || '').slice(2) + (parts[2] || ''))
                  }
                  if (v.length > 10) v = v.slice(0, 10)
                  e.target.value = v
                  onInlineChange?.(v)
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') { e.preventDefault(); onInlineCancel(); return }
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    const v = (e.target as HTMLInputElement).value.trim()
                    // Validate yyyy/mm/dd
                    const match = v.match(/^(\d{4})\/(\d{2})\/(\d{2})$/)
                    if (match) {
                      const isoDate = `${match[1]}-${match[2]}-${match[3]}`
                      const d = new Date(isoDate + 'T00:00:00')
                      if (!isNaN(d.getTime())) {
                        onInlineSubmit(v, isoDate)
                      }
                    }
                  }
                }}
              />
              <span className="inline-date-hint">{ts('inline_date_hint')}</span>
            </div>
          )}

          {/* Contact / label suggestions */}
          {!isDateMode && inlineSuggestions.length > 0 && (
            <div className="inline-filter-suggestions">
              {inlineSuggestions.map((s, idx) => (
                <div
                  key={s.id}
                  className={`search-suggestion-item${idx === inlineHighlightedIndex ? ' highlighted' : ''}`}
                  role="option"
                  aria-selected={idx === inlineHighlightedIndex}
                  data-testid="inline-suggestion-item"
                  onClick={() => onInlineSubmit(s.filterDisplayValue || s.label, s.filterValue || s.label)}
                  onMouseEnter={() => onInlineHighlight?.(idx)}
                >
                  {s.type === 'contact' ? (
                    <span className="search-suggestion-avatar" style={{ background: getAvatarColor(s.label) }} aria-hidden="true">
                      {getInitials(s.label)}
                    </span>
                  ) : (
                    <>
                      {s.filterColor && <span className="search-suggestion-color-dot" style={{ background: s.filterColor }} />}
                      <span className="search-suggestion-icon" aria-hidden="true">{renderIcon(s.icon)}</span>
                    </>
                  )}
                  <span className="search-suggestion-label">{s.label}</span>
                  {s.sublabel && <span className="search-suggestion-sublabel">{s.sublabel}</span>}
                </div>
              ))}
            </div>
          )}
          {/* No hardcoded empty state — the contact API call is debounced
              (300ms) and parents prefetch on panel open, so an empty
              suggestion list typically means "still loading". The user can
              still press Enter on raw text to commit it as the filter
              value; that behaviour is wired in handleInlineKeyDown above. */}
        </div>
      </div>
    )
  }

  if (items.length === 0) return null

  // ── Normal suggestions mode ─────────────────────────────────────────────────

  // Group items by type for section headers
  const sections: { type: string; title: string; items: { item: SuggestionItem; globalIndex: number }[] }[] = []
  let currentSection: typeof sections[0] | null = null

  const sectionTitles: Record<string, string> = {
    saved:    ts('section_saved'),
    recent:   ts('section_recent'),
    operator: ts('section_operator'),
    contact:  ts('section_contact'),
    label:    ts('section_label'),
    date:     ts('section_date'),
    quick:    ts('section_quick'),
  }

  items.forEach((item, globalIndex) => {
    if (!currentSection || currentSection.type !== item.type) {
      currentSection = {
        type: item.type,
        title: sectionTitles[item.type] || item.type,
        items: [],
      }
      sections.push(currentSection)
    }
    currentSection.items.push({ item, globalIndex })
  })

  /** Render a single suggestion item (shared between normal and grouped rendering) */
  const renderSuggestionItem = (item: SuggestionItem, globalIndex: number, extraClass = '') => (
    <div
      key={item.id}
      className={`search-suggestion-item${item.type === 'operator' ? ' operator-item' : ''}${extraClass}${globalIndex === highlightedIndex ? ' highlighted' : ''}${item.type === 'operator' && activeFilters.some(f => f.type === prefixToFilterType(item.prefixInsert || '')) ? ' is-active' : ''}`}
      role="option"
      aria-selected={globalIndex === highlightedIndex}
      data-index={globalIndex}
      data-operator-type={item.prefixInsert}
      onClick={() => onSelect(item)}
      onMouseEnter={() => onHighlight(globalIndex)}
    >
      {/* Icon or avatar */}
      {item.type === 'contact' ? (
        <span className="search-suggestion-avatar" style={{ background: getAvatarColor(item.label) }} aria-hidden="true">
          {getInitials(item.label)}
        </span>
      ) : (
        <span className="search-suggestion-icon" aria-hidden="true">
          {renderIcon(item.icon)}
        </span>
      )}

      {/* Color dot for labels */}
      {item.filterColor && item.type === 'label' && (
        <span className="search-suggestion-color-dot" style={{ background: item.filterColor }} />
      )}

      {/* Main content */}
      {item.type === 'recent' && item.rawQuery ? (
        <span className="recent-query-chips" aria-label={item.rawQuery}>
          {parseQueryToMiniChips(item.rawQuery).map((chip, idx) => (
            <span key={idx} className="recent-query-chip" style={{ '--chip-color': chip.color } as React.CSSProperties}>
              {chip.label}
            </span>
          ))}
        </span>
      ) : item.type === 'operator' || item.type === 'quick' ? (
        <span className="search-suggestion-label">
          {item.label}
          {item.sublabel && !item.group && (
            <span className="search-suggestion-operator-hint">{item.sublabel}</span>
          )}
        </span>
      ) : (
        <span className="search-suggestion-label">{item.label}</span>
      )}

      {/* Sublabel for grouped operator items — shown below label */}
      {item.group && item.sublabel && (
        <span className="search-suggestion-operator-hint operator-item-hint">{item.sublabel}</span>
      )}

      {/* Sublabel (contact email, date string) — not for operators/recent */}
      {item.type !== 'operator' && item.type !== 'quick' && item.type !== 'recent' && !item.group && item.sublabel && (
        <span className="search-suggestion-sublabel">{item.sublabel}</span>
      )}

      {/* Delete button for saved searches */}
      {item.type === 'saved' && item.savedSearchId && onDeleteSaved && (
        <button
          className="search-suggestion-delete"
          onClick={(e) => { e.stopPropagation(); onDeleteSaved(item.savedSearchId!); }}
          aria-label={t('delete')}
        >
          <CloseIcon size={12} />
        </button>
      )}
    </div>
  )

  // Split into operator column (right) and everything else (left)
  const operatorSections = sections.filter(s => s.type === 'operator')
  const otherSections = sections.filter(s => s.type !== 'operator')
  const hasBothColumns = operatorSections.length > 0 && otherSections.length > 0

  if (hasBothColumns) {
    return (
      <div className="search-suggestions-dropdown" ref={listRef} role="listbox">
        <div className="search-suggestions-two-col">
          <div className="search-suggestions-col-left">
            {otherSections.map((section, sIdx) => (
              <div key={section.type + sIdx} className="search-suggestions-section">
                <div className="search-suggestions-section-header">{section.title}</div>
                {section.items.map(({ item, globalIndex }) => renderSuggestionItem(item, globalIndex))}
                {sIdx < otherSections.length - 1 && <div className="search-suggestions-divider" />}
              </div>
            ))}
          </div>
          <div className="search-suggestions-col-sep" aria-hidden="true" />
          <div className="search-suggestions-col-right">
            {operatorSections.map((section, sIdx) => (
              <div key={section.type + sIdx} className="search-suggestions-section">
                <div className="search-suggestions-section-header">{section.title}</div>
                <OperatorGroupedGrid
                  items={section.items}
                  highlightedIndex={highlightedIndex}
                  activeFilters={activeFilters}
                  onSelect={onSelect}
                  onHighlight={onHighlight}
                  renderItem={renderSuggestionItem}
                />
              </div>
            ))}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="search-suggestions-dropdown" ref={listRef} role="listbox">
      {sections.map((section, sIdx) => (
        <div key={section.type + sIdx} className="search-suggestions-section">
          <div className="search-suggestions-section-header">{section.title}</div>

          {/* Operator section: grouped 2-column grid layout */}
          {section.type === 'operator' ? (
            <OperatorGroupedGrid
              items={section.items}
              highlightedIndex={highlightedIndex}
              activeFilters={activeFilters}
              onSelect={onSelect}
              onHighlight={onHighlight}
              renderItem={renderSuggestionItem}
            />
          ) : (
            section.items.map(({ item, globalIndex }) => renderSuggestionItem(item, globalIndex))
          )}

          {sIdx < sections.length - 1 && <div className="search-suggestions-divider" />}
        </div>
      ))}
    </div>
  )
}

// ── Grouped operator grid sub-component ──────────────────────────────────────

type OperatorGroupKey = 'people' | 'content' | 'date' | 'folder'

function getOperatorGroups(t: TFunction): { key: OperatorGroupKey; label: string }[] {
  return [
    { key: 'people',  label: t('group_people') },
    { key: 'content', label: t('group_content') },
    { key: 'date',    label: t('group_date') },
    { key: 'folder',  label: t('group_folder') },
  ]
}

interface OperatorGroupedGridProps {
  items: { item: SuggestionItem; globalIndex: number }[]
  highlightedIndex: number
  activeFilters: { type: string }[]
  onSelect: (item: SuggestionItem) => void
  onHighlight: (index: number) => void
  renderItem: (item: SuggestionItem, globalIndex: number, extraClass?: string) => React.ReactNode
}

function OperatorGroupedGrid({ items, highlightedIndex: _hi, activeFilters: _af, onSelect: _onSelect, onHighlight: _onHighlight, renderItem }: OperatorGroupedGridProps) {
  const { t: ts } = useTranslation('search')
  const groupedItems: Record<string, { item: SuggestionItem; globalIndex: number }[]> = { people: [], content: [], date: [], folder: [], ungrouped: [] }

  for (const entry of items) {
    const g = entry.item.group
    if (g && g in groupedItems) {
      groupedItems[g].push(entry)
    } else {
      groupedItems.ungrouped.push(entry)
    }
  }

  return (
    <div className="search-operators-section">
      {getOperatorGroups(ts).map(({ key, label }) => {
        const groupItems = groupedItems[key]
        if (!groupItems || groupItems.length === 0) return null
        return (
          <div key={key} className="search-operators-group" data-testid={`operator-group-${key}`}>
            <div className="search-operators-group-title">{label}</div>
            <div className="search-operators-grid">
              {groupItems.map(({ item, globalIndex }) => renderItem(item, globalIndex))}
            </div>
          </div>
        )
      })}
      {/* Ungrouped operators (Non lus, Dans:, Exclure) rendered flat below a separator */}
      {groupedItems.ungrouped.length > 0 && (
        <div className="search-operators-ungrouped">
          {groupedItems.ungrouped.map(({ item, globalIndex }) => renderItem(item, globalIndex))}
        </div>
      )}
    </div>
  )
}

function renderIcon(icon?: string) {
  switch (icon) {
    case 'clock':
      return (
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
        </svg>
      )
    case 'user':
      return (
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
        </svg>
      )
    case 'tag':
      return (
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" /><line x1="7" y1="7" x2="7.01" y2="7" />
        </svg>
      )
    case 'calendar':
      return (
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" />
        </svg>
      )
    case 'mail':
      return (
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="4" /><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-3.92 7.94" />
        </svg>
      )
    case 'paperclip':
      return (
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
        </svg>
      )
    case 'arrow-right':
      return (
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 12h14M12 5l7 7-7 7" />
        </svg>
      )
    case 'send':
      return (
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
        </svg>
      )
    case 'user-send':
      return (
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M16 21v-1.5a3.5 3.5 0 0 0-3.5-3.5h-5A3.5 3.5 0 0 0 4 19.5V21" /><circle cx="10" cy="8" r="3.5" /><polygon points="22 3 18 11 15.5 8.5 12 7 22 3" fill="none" />
        </svg>
      )
    case 'heading':
      return (
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 12h12M6 4v16M18 4v16" />
        </svg>
      )
    case 'align-left':
      return (
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <line x1="17" y1="10" x2="3" y2="10" /><line x1="21" y1="6" x2="3" y2="6" /><line x1="21" y1="14" x2="3" y2="14" /><line x1="17" y1="18" x2="3" y2="18" />
        </svg>
      )
    case 'layers':
      return (
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="12 2 2 7 12 12 22 7 12 2" /><polyline points="2 17 12 22 22 17" /><polyline points="2 12 12 17 22 12" />
        </svg>
      )
    case 'inbox':
      return (
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="22 12 16 12 14 15 10 15 8 12 2 12" /><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
        </svg>
      )
    case 'type':
      return (
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="4 7 4 4 20 4 20 7" /><line x1="9" y1="20" x2="15" y2="20" /><line x1="12" y1="4" x2="12" y2="20" />
        </svg>
      )
    case 'filter':
      return (
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
        </svg>
      )
    case 'file-text':
      return (
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><polyline points="10 9 9 9 8 9" />
        </svg>
      )
    case 'star':
      return (
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
        </svg>
      )
    default:
      return <SearchIcon size={14} />
  }
}

// === Helper functions for building suggestion items ===

export function buildSavedSearchItems(savedSearches: SavedSearch[], query: string): SuggestionItem[] {
  const lq = query.toLowerCase()
  const filtered = lq
    ? savedSearches.filter(s => s.name.toLowerCase().includes(lq) || s.query.toLowerCase().includes(lq))
    : savedSearches
  return filtered.slice(0, 5).map((s, i) => ({
    id: `saved-${i}-${s.id}`,
    type: 'saved' as const,
    label: s.name,
    sublabel: s.query,
    icon: 'star' as const,
    rawQuery: s.query,
    savedSearchId: s.id,
  }))
}

export function buildRecentItems(recents: string[], query: string): SuggestionItem[] {
  const lq = query.toLowerCase()
  const filtered = lq
    ? recents.filter(r => r.toLowerCase().includes(lq))
    : recents
  return filtered.slice(0, 3).map((r, i) => ({
    id: `recent-${i}`,
    type: 'recent' as const,
    label: r,
    rawQuery: r,
  }))
}

export function buildContactItems(contacts: Contact[], targetFilter: 'from' | 'to' = 'from'): SuggestionItem[] {
  return contacts.slice(0, 6).map((c, i) => ({
    id: `contact-${i}-${c.email}`,
    type: 'contact' as const,
    label: c.name || c.email.split('@')[0],
    sublabel: c.email,
    icon: 'user' as const,
    filterType: targetFilter,
    filterValue: c.email,
    filterDisplayValue: c.name || c.email.split('@')[0],
    filterColor: targetFilter === 'to' ? '#8b5cf6' : '#3b82f6',
  }))
}

export function buildLabelItems(labels: Label[], query: string): SuggestionItem[] {
  const lq = query.toLowerCase().trim()
  const filtered = lq
    ? labels.filter(l =>
        l.name.toLowerCase().includes(lq) ||
        getLabelDisplayName(l.name).toLowerCase().includes(lq)
      )
    : labels
  return filtered.slice(0, 8).map((l, i) => ({
    id: `label-${i}-${l.name}`,
    type: 'label' as const,
    label: getLabelDisplayName(l.name),
    icon: 'tag' as const,
    filterType: 'label' as const,
    filterValue: l.name,
    filterDisplayValue: getLabelDisplayName(l.name),
    filterColor: l.color,
  }))
}

export function buildApiSenderItems(
  senders: { email: string; name: string }[],
  excludeEmails?: Set<string>,
): SuggestionItem[] {
  return senders
    .filter(s => !excludeEmails?.has(s.email))
    .slice(0, 4)
    .map((s, i) => ({
      id: `api-sender-${i}-${s.email}`,
      type: 'contact' as const,
      label: s.name || s.email.split('@')[0],
      sublabel: s.email,
      icon: 'user' as const,
      filterType: 'from' as const,
      filterValue: s.email,
      filterDisplayValue: s.name || s.email.split('@')[0],
      filterColor: '#3b82f6',
    }))
}

export function buildApiSubjectItems(subjects: string[]): SuggestionItem[] {
  return subjects.slice(0, 4).map((s, i) => ({
    id: `api-subject-${i}`,
    type: 'recent' as const,
    label: s,
    icon: 'type' as const,
    rawQuery: `subject:"${s}"`,
  }))
}

export function buildDateItems(prefix: 'after' | 'before', t: TFunction): SuggestionItem[] {
  const today = new Date()
  const fmt = (d: Date) => d.toISOString().split('T')[0]
  const subtract = (days: number) => {
    const d = new Date(today)
    d.setDate(d.getDate() - days)
    return d
  }

  if (prefix === 'after') {
    return [
      { id: 'date-after-7',   type: 'date', label: t('date_after_7d'),   sublabel: t('date_after_prefix', { date: fmt(subtract(7)) }),   icon: 'calendar', filterType: 'after', filterValue: fmt(subtract(7)),   filterDisplayValue: t('date_after_7d'),   filterColor: '#eab308' },
      { id: 'date-after-30',  type: 'date', label: t('date_after_30d'),  sublabel: t('date_after_prefix', { date: fmt(subtract(30)) }),  icon: 'calendar', filterType: 'after', filterValue: fmt(subtract(30)),  filterDisplayValue: t('date_after_30d'),  filterColor: '#eab308' },
      { id: 'date-after-90',  type: 'date', label: t('date_after_90d'),  sublabel: t('date_after_prefix', { date: fmt(subtract(90)) }),  icon: 'calendar', filterType: 'after', filterValue: fmt(subtract(90)),  filterDisplayValue: t('date_after_90d'),  filterColor: '#eab308' },
      { id: 'date-after-180', type: 'date', label: t('date_after_180d'), sublabel: t('date_after_prefix', { date: fmt(subtract(180)) }), icon: 'calendar', filterType: 'after', filterValue: fmt(subtract(180)), filterDisplayValue: t('date_after_180d'), filterColor: '#eab308' },
      { id: 'date-after-365', type: 'date', label: t('date_after_365d'), sublabel: t('date_after_prefix', { date: fmt(subtract(365)) }), icon: 'calendar', filterType: 'after', filterValue: fmt(subtract(365)), filterDisplayValue: t('date_after_365d'), filterColor: '#eab308' },
      { id: 'date-after-730', type: 'date', label: t('date_after_730d'), sublabel: t('date_after_prefix', { date: fmt(subtract(730)) }), icon: 'calendar', filterType: 'after', filterValue: fmt(subtract(730)), filterDisplayValue: t('date_after_730d'), filterColor: '#eab308' },
    ]
  } else {
    return [
      { id: 'date-before-30',  type: 'date', label: t('date_before_30d'),  sublabel: t('date_before_prefix', { date: fmt(subtract(30)) }),  icon: 'calendar', filterType: 'before', filterValue: fmt(subtract(30)),  filterDisplayValue: t('date_before_30d'),  filterColor: '#eab308' },
      { id: 'date-before-90',  type: 'date', label: t('date_before_90d'),  sublabel: t('date_before_prefix', { date: fmt(subtract(90)) }),  icon: 'calendar', filterType: 'before', filterValue: fmt(subtract(90)),  filterDisplayValue: t('date_before_90d'),  filterColor: '#eab308' },
      { id: 'date-before-180', type: 'date', label: t('date_before_180d'), sublabel: t('date_before_prefix', { date: fmt(subtract(180)) }), icon: 'calendar', filterType: 'before', filterValue: fmt(subtract(180)), filterDisplayValue: t('date_before_180d'), filterColor: '#eab308' },
      { id: 'date-before-365', type: 'date', label: t('date_before_365d'), sublabel: t('date_before_prefix', { date: fmt(subtract(365)) }), icon: 'calendar', filterType: 'before', filterValue: fmt(subtract(365)), filterDisplayValue: t('date_before_365d'), filterColor: '#eab308' },
      { id: 'date-before-730', type: 'date', label: t('date_before_730d'), sublabel: t('date_before_prefix', { date: fmt(subtract(730)) }), icon: 'calendar', filterType: 'before', filterValue: fmt(subtract(730)), filterDisplayValue: t('date_before_730d'), filterColor: '#eab308' },
    ]
  }
}

export function buildOperatorItems(t: TFunction): SuggestionItem[] {
  return [
    { id: 'op-from',    type: 'operator', label: t('op_from_label'),    sublabel: t('op_from_sublabel'),    icon: 'user',       prefixInsert: 'from:',    group: 'people' },
    { id: 'op-sent-to', type: 'operator', label: t('op_sent_to_label'), sublabel: t('op_sent_to_sublabel'), icon: 'user-send',  prefixInsert: 'to:',      group: 'people', addSentFilter: true },
    { id: 'op-subject', type: 'operator', label: t('op_subject_label'), sublabel: t('op_subject_sublabel'), icon: 'heading',    prefixInsert: 'subject:', group: 'content' },
    { id: 'op-body',    type: 'operator', label: t('op_body_label'),    sublabel: t('op_body_sublabel'),    icon: 'align-left', prefixInsert: 'contenu:', group: 'content' },
    { id: 'op-label',   type: 'operator', label: t('op_label_label'),   sublabel: t('op_label_sublabel'),   icon: 'tag',        prefixInsert: 'label:',   group: 'content' },
    { id: 'op-after',   type: 'operator', label: t('op_after_label'),   sublabel: t('op_after_sublabel'),   icon: 'calendar',   prefixInsert: 'after:',   group: 'date' },
    { id: 'op-before',  type: 'operator', label: t('op_before_label'),  sublabel: t('op_before_sublabel'),  icon: 'calendar',   prefixInsert: 'before:',  group: 'date' },
    { id: 'op-in-all',   type: 'operator', label: t('op_in_all_label'),   sublabel: t('op_in_all_sublabel'),   icon: 'layers',    filterType: 'in', filterValue: 'all',   filterDisplayValue: t('op_in_all_display'),   filterColor: '#6366f1', group: 'folder' },
    { id: 'op-in-inbox', type: 'operator', label: t('op_in_inbox_label'), sublabel: t('op_in_inbox_sublabel'), icon: 'inbox',     filterType: 'in', filterValue: 'inbox', filterDisplayValue: t('op_in_inbox_display'), filterColor: '#3b82f6', group: 'folder' },
    { id: 'op-in-sent',  type: 'operator', label: t('op_in_sent_label'),  sublabel: t('op_in_sent_sublabel'),  icon: 'send',      filterType: 'in', filterValue: 'sent',  filterDisplayValue: t('op_in_sent_display'),  filterColor: '#10b981', group: 'folder' },
    { id: 'op-has-attachment', type: 'operator', label: t('op_attach_label'), sublabel: t('op_attach_sublabel'), icon: 'paperclip', filterType: 'has', filterValue: 'attachment', filterDisplayValue: t('op_attach_display'), filterColor: '#0d9488', group: 'content' },
  ]
}
