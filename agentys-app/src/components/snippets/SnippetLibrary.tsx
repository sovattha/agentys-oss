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

import { useState, useMemo, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import type { Snippet, CreateSnippetPayload, UpdateSnippetPayload } from '../../types/snippets'
import { useSnippets } from '../../hooks/useSnippets'
import { useAnimatedUnmount } from '../../hooks/useAnimatedUnmount'
import { useOptimisticMutation } from '../../hooks/useOptimisticMutation'
import { SnippetEditor } from './SnippetEditor'
import { GhostAddCard } from '../ui/GhostAddCard'
import { Button } from '../ui/button'
import { ChevronLeftIcon, CloseIcon, EditIcon, TrashIcon } from '../icons/ActionIcons'
import { htmlToPreviewText } from '../../utils/emailContent'
import { chipsToTokens } from '../../utils/placeholderChips'
import './SnippetLibrary.css'

interface SnippetLibraryProps {
  isOpen: boolean
  onClose: () => void
  onBack?: () => void
  accountId?: number
}

export function SnippetLibrary({ isOpen, onClose, onBack, accountId }: SnippetLibraryProps) {
  const { t } = useTranslation('settings')
  const { shouldRender, isClosing, handleClose } = useAnimatedUnmount(isOpen, onClose)

  const {
    snippets,
    loading,
    error,
    createSnippet,
    updateSnippet,
    deleteSnippet,
    refreshSnippets,
  } = useSnippets(accountId)

  const [showEditor, setShowEditor] = useState(false)
  const [editingSnippet, setEditingSnippet] = useState<Snippet | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)

  // Group own snippets by category
  const groupedSnippets = useMemo(() => {
    const groups: Record<string, Snippet[]> = {
      _uncategorized: [],
    }

    for (const snippet of snippets) {
      const category = snippet.category || '_uncategorized'
      if (!groups[category]) {
        groups[category] = []
      }
      groups[category].push(snippet)
    }

    // Sort snippets within each group by use_count then name
    for (const category of Object.keys(groups)) {
      groups[category].sort((a, b) => {
        if (b.use_count !== a.use_count) return b.use_count - a.use_count
        return a.name.localeCompare(b.name)
      })
    }

    return groups
  }, [snippets])

  const handleCreateNew = () => {
    setEditingSnippet(null)
    setShowEditor(true)
  }

  const handleEdit = (snippet: Snippet) => {
    setEditingSnippet(snippet)
    setShowEditor(true)
  }

  const handleSave = async (payload: CreateSnippetPayload) => {
    if (editingSnippet) {
      await updateSnippet(editingSnippet.id, payload as UpdateSnippetPayload)
    } else {
      await createSnippet(payload)
    }
    setShowEditor(false)
    setEditingSnippet(null)
  }

  // Audit Cluster D (2026-05-17) Toast Site 8 / #330: previously zero
  // try/catch; an onClick handler swallowed the promise rejection so the
  // list never refreshed and the user got no feedback.
  const runDeleteSnippet = useOptimisticMutation<void>({
    scope: 'snippet-library-delete',
    i18nKey: 'toasts.snippet_delete_failed',
  })
  const handleDelete = async (id: string) => {
    await runDeleteSnippet(async () => {
      await deleteSnippet(id)
    })
    setDeleteConfirm(null)
  }

  // Escape key closes the library — skip when typing in fields and when the
  // editor is open on top (the editor owns Escape; otherwise both close at
  // once and the user loses in-progress edits).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (showEditor) return
      const tgt = e.target as HTMLElement | null
      if (tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA' || tgt.isContentEditable)) {
        return
      }
      handleClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [handleClose, showEditor])

  if (!shouldRender) return null

  return (
    <div className="snippet-library-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget && !showEditor) handleClose() }}>
      <div className={`snippet-library${isClosing ? ' closing' : ''}`}>
        {/* Header */}
        <div className="snippet-library-header">
          <button className="snippet-library-back" onClick={onBack || handleClose}>
            <ChevronLeftIcon size={20} />
          </button>
          <h2>{t('snippets_title')}</h2>
          <button className="snippet-library-close" onClick={handleClose}>
            <CloseIcon />
          </button>
        </div>

        {/* Content */}
        <div className="snippet-library-content">
          {loading ? (
              <div className="snippet-library-loading">
                <span className="snippet-library-spinner" />
                {t('snippets_loading')}
              </div>
            ) : error ? (
              <div className="snippet-library-error">
                <p>{error}</p>
                <button onClick={refreshSnippets}>{t('snippets_error_retry')}</button>
              </div>
            ) : snippets.length === 0 ? (
              <div className="snippet-library-empty">
                <span className="snippet-library-empty-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M9 4H7a2 2 0 0 0-2 2v3a2 2 0 0 1-2 2 2 2 0 0 1 2 2v3a2 2 0 0 0 2 2h2" />
                    <path d="M15 4h2a2 2 0 0 1 2 2v3a2 2 0 0 0 2 2 2 2 0 0 0-2 2v3a2 2 0 0 1-2 2h-2" />
                  </svg>
                </span>
                <p className="snippet-library-empty-title">{t('snippets_empty_title')}</p>
                <p className="snippet-library-hint">
                  {t('snippets_empty_hint')}
                </p>
                <button className="snippet-library-create-btn" onClick={handleCreateNew}>
                  {t('snippets_empty_create')}
                </button>
              </div>
            ) : (
              <div className="snippet-library-list">
                {Object.entries(groupedSnippets).map(([category, categorySnippets]) => {
                  // _uncategorized always renders — it hosts the GhostAddCard so
                  // the create affordance has a stable home at the top of the
                  // grid even when every snippet is categorised.
                  if (category !== '_uncategorized' && categorySnippets.length === 0) return null

                  return (
                    <div key={category} className="snippet-category">
                      {category !== '_uncategorized' && (
                        <h3 className="snippet-category-title">{category}</h3>
                      )}
                      <div className="snippet-category-items">
                        {category === '_uncategorized' && (
                          <GhostAddCard label={t('snippets_new')} onClick={handleCreateNew} />
                        )}
                        {categorySnippets.map((snippet) => (
                          <div key={snippet.id} className="snippet-card">
                            <div className="snippet-card-header">
                              <span className="snippet-card-name">{snippet.name}</span>
                            </div>
                            <div className="snippet-card-content">
                              {htmlToPreviewText(chipsToTokens(snippet.content), { maxChars: 150 })}
                            </div>
                            <div className="snippet-card-actions">
                              <button
                                className="snippet-card-btn snippet-card-edit"
                                onClick={() => handleEdit(snippet)}
                                title={t('snippets_edit')}
                              >
                                <EditIcon size={14} />
                              </button>
                              {deleteConfirm === snippet.id ? (
                                <>
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => setDeleteConfirm(null)}
                                  >
                                    {t('shortcuts_cancel')}
                                  </Button>
                                  <Button
                                    variant="default"
                                    size="sm"
                                    onClick={() => handleDelete(snippet.id)}
                                  >
                                    {t('snippets_confirm')}
                                  </Button>
                                </>
                              ) : (
                                <button
                                  className="snippet-card-btn snippet-card-delete"
                                  onClick={() => setDeleteConfirm(snippet.id)}
                                  title={t('snippets_delete')}
                                >
                                  <TrashIcon size={14} />
                                </button>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            )
          }
        </div>

      </div>

      {/* Editor modal */}
      <SnippetEditor
        isOpen={showEditor}
        onClose={() => {
          setShowEditor(false)
          setEditingSnippet(null)
        }}
        onBack={() => {
          setShowEditor(false)
          setEditingSnippet(null)
        }}
        onSave={handleSave}
        snippet={editingSnippet || undefined}
      />

    </div>
  )
}
