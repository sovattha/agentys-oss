import { useState, useEffect, useRef, useMemo, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { Snippet } from '../../types/snippets'
import type { SharedSnippet } from '../../types/snippets'
import { SearchIcon, PlusIcon } from '../icons/ActionIcons'
import { htmlToPreviewText } from '../../utils/emailContent'
import { chipsToTokens } from '../../utils/placeholderChips'
import './SnippetSelector.css'

/** Render snippet preview with {variables} highlighted as chips.
 *
 *  Snippet content is stored as RichTextEditor HTML (token pill spans plus
 *  `<div>`/`<br>` structure), so we first convert the pills back to their
 *  `{token}` form and strip the remaining tags to a clean preview — otherwise
 *  the raw markup leaks into the row (e.g. `<span class="ar-token"...>`). */
function renderPreviewWithVars(rawContent: string, maxLen = 80): ReactNode {
  const text = htmlToPreviewText(chipsToTokens(rawContent), { maxChars: maxLen })
  const parts = text.split(/(\{[a-z_.]+\})/gi)
  if (parts.length === 1) return text
  return parts.map((part, i) =>
    /^\{[a-z_.]+\}$/i.test(part) ? (
      <span key={i} className="snippet-var-chip">{part}</span>
    ) : (
      <span key={i}>{part}</span>
    )
  )
}

interface SnippetSelectorProps {
  isOpen: boolean
  onClose: () => void
  snippets: Snippet[]
  sharedSnippets?: SharedSnippet[]
  onSelect: (snippet: Snippet) => void
  onCreateNew: () => void
  anchorRef?: React.RefObject<HTMLElement>
  loading?: boolean
}

export function SnippetSelector({
  isOpen,
  onClose,
  snippets,
  sharedSnippets = [],
  onSelect,
  onCreateNew,
  anchorRef,
  loading = false,
}: SnippetSelectorProps) {
  const { t } = useTranslation('common')
  const [search, setSearch] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const searchRef = useRef<HTMLInputElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Filter snippets based on search
  const filteredSnippets = snippets.filter(
    (s) =>
      s.name.toLowerCase().includes(search.toLowerCase()) ||
      s.content.toLowerCase().includes(search.toLowerCase())
  )

  // Filter shared snippets based on search
  const filteredShared = useMemo(() =>
    sharedSnippets.filter(
      (s) =>
        s.name.toLowerCase().includes(search.toLowerCase()) ||
        s.content.toLowerCase().includes(search.toLowerCase())
    ),
    [sharedSnippets, search]
  )

  // Combined list for keyboard navigation
  const allItems = useMemo(() => [
    ...filteredSnippets,
    ...filteredShared,
  ], [filteredSnippets, filteredShared])

  // Reset selection when filtered list changes
  useEffect(() => {
    setSelectedIndex(0)
  }, [search])

  // Focus search input when opened
  useEffect(() => {
    if (isOpen) {
      setSearch('')
      setSelectedIndex(0)
      setTimeout(() => searchRef.current?.focus(), 50)
    }
  }, [isOpen])

  // Close on click outside
  useEffect(() => {
    if (!isOpen) return

    const handleClickOutside = (e: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node) &&
        anchorRef?.current &&
        !anchorRef.current.contains(e.target as Node)
      ) {
        onClose()
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isOpen, onClose, anchorRef])

  // Keyboard navigation
  useEffect(() => {
    if (!isOpen) return

    const handleKeyDown = (e: KeyboardEvent) => {
      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault()
          setSelectedIndex((prev) =>
            prev < allItems.length - 1 ? prev + 1 : prev
          )
          break
        case 'ArrowUp':
          e.preventDefault()
          setSelectedIndex((prev) => (prev > 0 ? prev - 1 : 0))
          break
        case 'Enter':
          e.preventDefault()
          if (allItems[selectedIndex]) {
            onSelect(allItems[selectedIndex])
            onClose()
          }
          break
        case 'Escape':
          e.preventDefault()
          onClose()
          break
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, allItems, selectedIndex, onSelect, onClose])

  if (!isOpen) return null

  return (
    <div className="snippet-selector" ref={dropdownRef} data-escape-owner="">
      <div className="snippet-selector-header">
        <div className="snippet-search-wrapper">
          <SearchIcon size={16} className="snippet-search-icon" />
          <input
            ref={searchRef}
            type="text"
            className="snippet-search-input"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('snippets_search')}
          />
        </div>
      </div>

      <div className="snippet-selector-list">
        {loading ? (
          <div className="snippet-selector-loading">
            <span className="snippet-selector-spinner" />
            {t('loading')}
          </div>
        ) : allItems.length === 0 ? (
          <div className="snippet-selector-empty">
            <svg className="snippet-selector-empty-icon" aria-hidden="true" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
            </svg>
            {search
              ? t('snippets_no_results')
              : t('snippets_empty')}
          </div>
        ) : (
          <>
            {filteredSnippets.map((snippet, index) => (
              <button
                key={snippet.id}
                className={`snippet-selector-item ${
                  index === selectedIndex ? 'selected' : ''
                }`}
                onClick={() => {
                  onSelect(snippet)
                  onClose()
                }}
                onMouseEnter={() => setSelectedIndex(index)}
              >
                <div className="snippet-item-name">{snippet.name}</div>
                <div className="snippet-item-preview">
                  {renderPreviewWithVars(snippet.content)}
                </div>
              </button>
            ))}
            {filteredShared.length > 0 && (
              <>
                <div className="snippet-selector-section">{t('snippets_shared')}</div>
                {filteredShared.map((snippet, index) => {
                  const globalIndex = filteredSnippets.length + index
                  return (
                    <button
                      key={snippet.share_id}
                      className={`snippet-selector-item snippet-selector-item--shared ${
                        globalIndex === selectedIndex ? 'selected' : ''
                      }`}
                      onClick={() => {
                        onSelect(snippet)
                        onClose()
                      }}
                      onMouseEnter={() => setSelectedIndex(globalIndex)}
                    >
                      <div className="snippet-item-name">{snippet.name}</div>
                      <div className="snippet-item-preview">
                        {renderPreviewWithVars(snippet.content)}
                      </div>
                    </button>
                  )
                })}
              </>
            )}
          </>
        )}
      </div>

      <div className="snippet-selector-footer">
        <button className="snippet-create-btn" onClick={onCreateNew}>
          <PlusIcon size={14} />
          {t('snippets_create_new')}
        </button>
      </div>
    </div>
  )
}
