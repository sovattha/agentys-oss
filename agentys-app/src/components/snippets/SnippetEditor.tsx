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

import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import type { Snippet, CreateSnippetPayload } from '../../types/snippets'
import { SNIPPET_VARIABLES } from '../../types/snippets'
import { RichTextEditor, type RichTextEditorHandle, type PlaceholderSuggestion } from '../ui/RichTextEditor'
import { buildTokenChipHtml } from '../../utils/placeholderChips'
import { ChevronLeftIcon, CloseIcon } from '../icons/ActionIcons'
import './SnippetEditor.css'

interface SnippetEditorProps {
  isOpen: boolean
  onClose: () => void
  onBack?: () => void
  onSave: (snippet: CreateSnippetPayload) => Promise<void>
  snippet?: Snippet // If editing existing snippet
}

export function SnippetEditor({ isOpen, onClose, onBack, onSave, snippet }: SnippetEditorProps) {
  const { t } = useTranslation('settings')
  const [name, setName] = useState('')
  const [content, setContent] = useState('')
  const [subject, setSubject] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [to, setTo] = useState('')
  const [cc, setCc] = useState('')
  const [bcc, setBcc] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const nameRef = useRef<HTMLInputElement>(null)
  const contentRef = useRef<RichTextEditorHandle>(null)

  // Populate form when editing
  useEffect(() => {
    if (snippet) {
      setName(snippet.name)
      setContent(snippet.content)
      setSubject(snippet.subject || '')
      setTo(snippet.to?.join(', ') || '')
      setCc(snippet.cc?.join(', ') || '')
      setBcc(snippet.bcc?.join(', ') || '')
      if (snippet.subject || snippet.to?.length || snippet.cc?.length || snippet.bcc?.length) {
        setShowAdvanced(true)
      }
    } else {
      resetForm()
    }
  }, [snippet, isOpen])

  // Focus name input when opened
  useEffect(() => {
    if (isOpen && !snippet) {
      setTimeout(() => nameRef.current?.focus(), 100)
    }
  }, [isOpen, snippet])

  // Keyboard shortcuts
  useEffect(() => {
    if (!isOpen) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault()
        handleSave()
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose, name, content])

  const resetForm = () => {
    setName('')
    setContent('')
    setSubject('')
    setTo('')
    setCc('')
    setBcc('')
    setShowAdvanced(false)
    setError(null)
  }

  const handleSave = async () => {
    if (!name.trim()) {
      setError(t('snippet_editor_error_name'))
      nameRef.current?.focus()
      return
    }
    // Strip HTML tags to validate the content is not empty
    const plainContent = content.replace(/<[^>]*>/g, '').trim()
    if (!plainContent) {
      setError(t('snippet_editor_error_content'))
      contentRef.current?.focus()
      return
    }

    setIsSaving(true)
    setError(null)

    try {
      const payload: CreateSnippetPayload = {
        name: name.trim(),
        content: content.trim(),
        is_private: true,
      }

      if (subject.trim()) payload.subject = subject.trim()
      if (to.trim()) payload.to = to.split(',').map(e => e.trim()).filter(Boolean)
      if (cc.trim()) payload.cc = cc.split(',').map(e => e.trim()).filter(Boolean)
      if (bcc.trim()) payload.bcc = bcc.split(',').map(e => e.trim()).filter(Boolean)

      await onSave(payload)
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: { message: t('common:toasts.snippet_saved'), type: 'success' },
      }))
      resetForm()
      onClose()
    } catch (err: unknown) {
      setError((err as Error).message || t('snippet_editor_error_save'))
    } finally {
      setIsSaving(false)
    }
  }

  // `{x}` placeholder menu — Prénom / Nom only. Each item inserts a styled chip
  // whose token is the variable name (e.g. `first_name`), resolved by
  // `replaceSnippetVariables` when the snippet is dropped into a compose.
  const placeholders: PlaceholderSuggestion[] = SNIPPET_VARIABLES.filter(
    v => v.name === '{first_name}' || v.name === '{last_name}'
  ).map(v => {
    const token = v.name.replace(/[{}]/g, '')
    const label = t(v.labelKey)
    return {
      id: token,
      label,
      preview: v.name,
      buildHtml: () => buildTokenChipHtml(token, label),
    }
  })

  if (!isOpen) return null

  const isEditing = !!snippet

  return (
    <div className="snippet-editor-overlay" onClick={onClose}>
      <div className="snippet-editor" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="snippet-editor-header">
          <button className="snippet-back-btn" onClick={onBack || onClose} title={t('common:back')}>
            <ChevronLeftIcon />
          </button>
          <h2 className="snippet-editor-title">
            {isEditing ? t('snippet_editor_title_edit') : t('snippet_editor_title_new')}
          </h2>
          <button className="snippet-close-btn" onClick={onClose} title={t('common:close')}>
            <CloseIcon />
          </button>
        </div>

        {/* Form */}
        <div className="snippet-editor-body">
          {/* Name input */}
          <label htmlFor="snippet-name" className="sr-only">{t('snippet_editor_name_label')}</label>
          <input
            ref={nameRef}
            id="snippet-name"
            type="text"
            className="snippet-name-input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('snippet_editor_name_placeholder')}
            aria-describedby={error ? "snippet-editor-error" : undefined}
            aria-invalid={!!error && !name.trim()}
          />

          {/* Content editor — variables live in the editor's {x} menu */}
          <div className="snippet-content-wrap">
            <RichTextEditor
              ref={contentRef}
              value={content}
              onChange={setContent}
              placeholder={t('snippet_editor_content_placeholder')}
              ariaLabel={t('snippet_editor_content_label')}
              enableSnippets={false}
              placeholders={placeholders}
              minHeight={140}
            />
          </div>

          {/* Advanced fields */}
          {showAdvanced && (
            <div className="snippet-advanced-fields">
              <div className="snippet-field">
                <label htmlFor="snippet-subject">{t('snippet_editor_subject')}</label>
                <input
                  id="snippet-subject"
                  type="text"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  placeholder={t('snippet_editor_subject_placeholder')}
                />
              </div>
              <div className="snippet-field">
                <label htmlFor="snippet-to">{t('snippet_editor_to')}</label>
                <input
                  id="snippet-to"
                  type="text"
                  value={to}
                  onChange={(e) => setTo(e.target.value)}
                  placeholder={t('snippet_editor_to_placeholder')}
                />
              </div>
              <div className="snippet-field">
                <label htmlFor="snippet-cc">{t('snippet_editor_cc')}</label>
                <input
                  id="snippet-cc"
                  type="text"
                  value={cc}
                  onChange={(e) => setCc(e.target.value)}
                  placeholder={t('snippet_editor_cc_placeholder')}
                />
              </div>
              <div className="snippet-field">
                <label htmlFor="snippet-bcc">{t('snippet_editor_bcc')}</label>
                <input
                  id="snippet-bcc"
                  type="text"
                  value={bcc}
                  onChange={(e) => setBcc(e.target.value)}
                  placeholder={t('snippet_editor_bcc_placeholder')}
                />
              </div>
            </div>
          )}

          {error && <div id="snippet-editor-error" className="snippet-error" role="alert">{error}</div>}
        </div>

        {/* Footer */}
        <div className="snippet-editor-footer">
          <button
            className="snippet-save-btn"
            onClick={handleSave}
            disabled={isSaving || !name.trim() || !content.trim()}
          >
            {isSaving ? t('snippet_editor_saving') : t('snippet_editor_save')}
          </button>
        </div>
      </div>
    </div>
  )
}
