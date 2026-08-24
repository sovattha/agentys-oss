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

import { useState, useCallback, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { API_URL } from '../../config'
import { getAuthHeaders } from '../../services/authToken'
import './FaqSourceStep.css'

interface FaqEntry {
  question: string
  answer: string
  source?: string
  selected?: boolean
}

export type FaqSourceMode = 'choose' | 'url' | 'document' | 'preview'

interface FaqSourceStepProps {
  onConfirm: (entries: FaqEntry[]) => void
  /** Optional skip handler — kept for onboarding flows that still render a skip CTA */
  onSkip?: () => void
  /** Compact mode for modal usage (PillarSavoir) */
  compact?: boolean
  /** Notify parent of mode changes (for header back-arrow visibility) */
  onModeChange?: (mode: FaqSourceMode) => void
  /** Parent-writable ref that holds a back handler when mode !== 'choose' */
  backHandlerRef?: React.MutableRefObject<(() => void) | null>
}

export function FaqSourceStep({ onConfirm, onSkip, compact, onModeChange, backHandlerRef }: FaqSourceStepProps) {
  const { t } = useTranslation('onboarding')
  const [mode, setMode] = useState<FaqSourceMode>('choose')
  const [url, setUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [entries, setEntries] = useState<FaqEntry[]>([])
  const [extractionTier, setExtractionTier] = useState('')
  const [hiddenTabs, setHiddenTabs] = useState<string[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    onModeChange?.(mode)
    if (backHandlerRef) {
      backHandlerRef.current = mode === 'choose'
        ? null
        : () => {
            setMode('choose')
            setEntries([])
            setError(null)
          }
    }
    return () => {
      if (backHandlerRef) backHandlerRef.current = null
    }
  }, [mode, onModeChange, backHandlerRef])

  const handleScanUrl = useCallback(async () => {
    if (!url.trim()) return
    setLoading(true)
    setError(null)

    try {
      const resp = await fetch(`${API_URL}/api/knowledge/scan-url`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ url: url.trim() }),
      })
      const data = await resp.json()

      if (data.error && (!data.faq || data.faq.length === 0)) {
        setError(data.error)
        return
      }

      const faq = (data.faq || []).map((e: FaqEntry) => ({ ...e, selected: true }))
      if (faq.length === 0) {
        setError(t('faq_no_results'))
        return
      }

      setEntries(faq)
      setExtractionTier(data.extraction_tier || '')
      setHiddenTabs(data.hidden_tabs || [])
      setMode('preview')
    } catch {
      setError(t('faq_scan_error'))
    } finally {
      setLoading(false)
    }
  }, [url, t])

  const handleFileUpload = useCallback(async (file: File) => {
    setLoading(true)
    setError(null)

    const formData = new FormData()
    formData.append('file', file)

    try {
      const resp = await fetch(`${API_URL}/api/knowledge/scan-document`, {
        method: 'POST',
        headers: { ...getAuthHeaders() },
        body: formData,
      })
      const data = await resp.json()

      if (data.error && (!data.faq || data.faq.length === 0)) {
        setError(data.error)
        return
      }

      const faq = (data.faq || []).map((e: FaqEntry) => ({ ...e, selected: true }))
      if (faq.length === 0) {
        setError(t('faq_no_results'))
        return
      }

      setEntries(faq)
      setExtractionTier(data.extraction_tier || '')
      setMode('preview')
    } catch {
      setError(t('faq_scan_error'))
    } finally {
      setLoading(false)
    }
  }, [t])

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) handleFileUpload(file)
  }, [handleFileUpload])

  const toggleEntry = useCallback((index: number) => {
    setEntries(prev => prev.map((e, i) => i === index ? { ...e, selected: !e.selected } : e))
  }, [])

  const updateEntry = useCallback((index: number, field: 'question' | 'answer', value: string) => {
    setEntries(prev => prev.map((e, i) => i === index ? { ...e, [field]: value } : e))
  }, [])

  const handleConfirm = useCallback(() => {
    const selected = entries.filter(e => e.selected)
    onConfirm(selected)
  }, [entries, onConfirm])

  const selectedCount = entries.filter(e => e.selected).length

  // ── Choose mode (3 options) ──
  if (mode === 'choose') {
    return (
      <div className={`faq-source-step${compact ? ' faq-source-compact' : ''}`}>
        {!compact && (
          <>
            <h3 className="faq-source-title">{t('faq_source_title')}</h3>
            <p className="faq-source-desc">{t('faq_source_desc')}</p>
          </>
        )}

        <div className="faq-source-options">
          <button
            type="button"
            className="faq-source-option"
            onClick={() => setMode('url')}
          >
            <div className="faq-source-option-icon">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10"/>
                <line x1="2" y1="12" x2="22" y2="12"/>
                <path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/>
              </svg>
            </div>
            <div className="faq-source-option-text">
              <span className="faq-source-option-label">{t('faq_option_website')}</span>
              <span className="faq-source-option-hint">{t('faq_option_website_hint')}</span>
            </div>
          </button>

          <button
            type="button"
            className="faq-source-option"
            onClick={() => fileInputRef.current?.click()}
          >
            <div className="faq-source-option-icon">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="12" y1="18" x2="12" y2="12"/>
                <line x1="9" y1="15" x2="15" y2="15"/>
              </svg>
            </div>
            <div className="faq-source-option-text">
              <span className="faq-source-option-label">{t('faq_option_document')}</span>
              <span className="faq-source-option-hint">{t('faq_option_document_hint')}</span>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.txt,.docx,.doc,.md"
              onChange={handleFileChange}
              className="faq-source-file-input"
            />
          </button>
        </div>

        {!compact && onSkip && (
          <button
            type="button"
            className="faq-source-skip"
            onClick={onSkip}
          >
            {t('faq_option_skip')}
          </button>
        )}

        {error && <p className="faq-source-error">{error}</p>}
        {loading && (
          <div className="faq-source-loading">
            <div className="faq-source-spinner" />
            <span>{t('faq_scanning')}</span>
          </div>
        )}
      </div>
    )
  }

  // ── URL input mode ──
  if (mode === 'url') {
    return (
      <div className={`faq-source-step${compact ? ' faq-source-compact' : ''}`}>
        <h3 className="faq-source-title">{t('faq_url_title')}</h3>
        <p className="faq-source-desc">{t('faq_url_desc')}</p>

        <div className="faq-source-url-row">
          <input
            type="url"
            className="faq-source-url-input"
            placeholder="https://example.com/faq"
            value={url}
            onChange={e => setUrl(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleScanUrl() }}
            autoFocus
          />
          <button
            type="button"
            className="onboarding-btn onboarding-btn-primary"
            onClick={handleScanUrl}
            disabled={loading || !url.trim()}
          >
            {loading ? t('faq_scanning') : t('faq_scan_btn')}
          </button>
        </div>

        {error && <p className="faq-source-error">{error}</p>}
        {loading && (
          <div className="faq-source-loading">
            <div className="faq-source-spinner" />
            <span>{t('faq_scanning')}</span>
          </div>
        )}
      </div>
    )
  }

  // ── Preview mode (review extracted FAQ) ──
  return (
    <div className={`faq-source-step faq-source-preview-mode${compact ? ' faq-source-compact' : ''}`}>
      <h3 className="faq-source-title">{t('faq_preview_title')}</h3>
      <p className="faq-source-desc">
        {t('faq_preview_desc', { count: entries.length })}
        {extractionTier && (
          <span className="faq-source-tier-badge">{extractionTier}</span>
        )}
      </p>

      {hiddenTabs.length > 0 && (
        <div className="faq-hidden-tabs-warning">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="8" x2="12" y2="12"/>
            <line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          <span>{t('faq_hidden_tabs', { tabs: hiddenTabs.join(', '), count: hiddenTabs.length })}</span>
        </div>
      )}

      <div className="faq-source-preview-list">
        {entries.map((entry, i) => (
          <div key={i} className={`faq-preview-card${entry.selected ? '' : ' faq-preview-card-disabled'}`}>
            <label className="faq-preview-checkbox">
              <input
                type="checkbox"
                checked={entry.selected ?? true}
                onChange={() => toggleEntry(i)}
              />
            </label>
            <div className="faq-preview-content">
              <input
                className="faq-preview-question"
                value={entry.question}
                onChange={e => updateEntry(i, 'question', e.target.value)}
                placeholder={t('faq_preview_question_placeholder')}
              />
              <textarea
                className="faq-preview-answer"
                value={entry.answer}
                onChange={e => updateEntry(i, 'answer', e.target.value)}
                placeholder={t('faq_preview_answer_placeholder')}
                rows={2}
              />
            </div>
          </div>
        ))}
      </div>

      <div className="faq-source-preview-actions">
        <button
          type="button"
          className="onboarding-btn onboarding-btn-primary"
          onClick={handleConfirm}
          disabled={selectedCount === 0}
        >
          {t('faq_import_btn', { count: selectedCount })}
        </button>
      </div>
    </div>
  )
}
