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

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
} from 'react'
import { useTranslation } from 'react-i18next'
import './GreetingInput.css'

type Mode = 'first_name' | 'civility_last_name'
type Token = 'first_name' | 'civility' | 'last_name'

interface GreetingInputProps {
  value: string
  placeholder?: string
  onCommit: (next: string) => void
  ariaLabel?: string
}

const TOKEN_RE = /\{(first_name|civility|last_name)\}/g

interface Segment {
  kind: 'text' | 'token'
  content: string
  token?: Token
}

function parse(value: string): Segment[] {
  const segments: Segment[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null
  TOKEN_RE.lastIndex = 0
  while ((match = TOKEN_RE.exec(value)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ kind: 'text', content: value.slice(lastIndex, match.index) })
    }
    segments.push({ kind: 'token', content: match[0], token: match[1] as Token })
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < value.length) {
    segments.push({ kind: 'text', content: value.slice(lastIndex) })
  }
  return segments
}

function detectMode(value: string): Mode {
  return value.includes('{civility}') || value.includes('{last_name}')
    ? 'civility_last_name'
    : 'first_name'
}

function swapMode(value: string, mode: Mode, defaultWord: string): string {
  if (mode === 'civility_last_name') {
    if (value.includes('{civility}') || value.includes('{last_name}')) return value
    if (value.includes('{first_name}')) {
      return value.replace(/\{first_name\}/g, '{civility} {last_name}')
    }
    const trimmed = value.trimEnd().replace(/,$/, '')
    return `${trimmed || defaultWord} {civility} {last_name},`
  }
  if (value.includes('{first_name}')) return value
  if (value.includes('{civility}') || value.includes('{last_name}')) {
    return value
      .replace(/\{civility\}\s*\{last_name\}/g, '{first_name}')
      .replace(/\{civility\}/g, '{first_name}')
      .replace(/\{last_name\}/g, '{first_name}')
  }
  const trimmed = value.trimEnd().replace(/,$/, '')
  return `${trimmed || defaultWord} {first_name},`
}

export function GreetingInput({ value, placeholder, onCommit, ariaLabel }: GreetingInputProps) {
  const { t } = useTranslation('agents')
  const [local, setLocal] = useState(value)
  const [editing, setEditing] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setLocal(value)
  }, [value])

  useEffect(() => {
    if (!menuOpen) return
    const onDocMouseDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false)
    }
    window.addEventListener('mousedown', onDocMouseDown)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('mousedown', onDocMouseDown)
      window.removeEventListener('keydown', onKey)
    }
  }, [menuOpen])

  const isEmpty = !local
  const previewValue = isEmpty ? (placeholder || '') : local
  const segments = useMemo(() => parse(previewValue), [previewValue])
  const mode = useMemo(() => detectMode(previewValue), [previewValue])

  // The greeting word(s) the user actually typed — text before the first token
  // and after the last — so the menu previews mirror the field instead of always
  // showing a hardcoded "Bonjour" (wrong word, and wrong language in EN/ES).
  const { lead, tail } = useMemo(() => {
    const matches = [...previewValue.matchAll(/\{(?:first_name|civility|last_name)\}/g)]
    if (matches.length === 0) {
      const word = previewValue.trimEnd().replace(/,\s*$/, '')
      return { lead: word ? `${word} ` : '', tail: ',' }
    }
    const first = matches[0]
    const last = matches[matches.length - 1]
    return {
      lead: previewValue.slice(0, first.index ?? 0),
      tail: previewValue.slice((last.index ?? 0) + last[0].length),
    }
  }, [previewValue])

  const tokenLabel = useCallback((token: Token): string => {
    const fallback = token === 'first_name' ? 'Prénom' : token === 'last_name' ? 'Nom' : 'M./Mme'
    return t(`greeting_token_${token}`, fallback)
  }, [t])

  const tokenTitle = useCallback((token: Token): string => {
    const fallbacks: Record<Token, string> = {
      first_name: 'Remplacé par le prénom du destinataire',
      last_name: 'Remplacé par le nom de famille du destinataire',
      civility: 'Remplacé par M. ou Mme selon le destinataire',
    }
    return t(`greeting_token_title_${token}`, fallbacks[token])
  }, [t])

  // Full label used in the popover menu + as the button tooltip
  const modeLabel = mode === 'first_name'
    ? t('greeting_mode_first_name', 'Prénom')
    : t('greeting_mode_civility_last_name', 'M./Mme + Nom')

  // Short label used on the inline button, so the field stays on one line
  // even inside narrow Settings columns (2 fields per row).
  const modeLabelShort = mode === 'first_name'
    ? t('greeting_mode_first_name_short', 'Prénom')
    : t('greeting_mode_civility_last_name_short', 'M.+Nom')

  // Localized fallback greeting word for empty fields / mode swaps, so an EN/ES
  // user clearing a greeting doesn't get a French "Bonjour" injected.
  const defaultWord = t('greeting_default_word', 'Bonjour')

  const commit = useCallback(() => {
    setEditing(false)
    if (local !== value) onCommit(local)
  }, [local, value, onCommit])

  const enterEdit = () => {
    setEditing(true)
    requestAnimationFrame(() => {
      const el = inputRef.current
      if (!el) return
      el.focus()
      el.setSelectionRange(el.value.length, el.value.length)
    })
  }

  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    setLocal(e.target.value)
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      commit()
    } else if (e.key === 'Escape') {
      e.preventDefault()
      setLocal(value)
      setEditing(false)
    }
  }

  const applyMode = (next: Mode) => {
    setMenuOpen(false)
    const source = isEmpty ? (placeholder || `${defaultWord} {first_name},`) : local
    const hasTokenForMode =
      next === 'first_name'
        ? source.includes('{first_name}')
        : source.includes('{civility}') || source.includes('{last_name}')
    if (hasTokenForMode) return
    const swapped = swapMode(source, next, defaultWord)
    setLocal(swapped)
    onCommit(swapped)
  }

  return (
    <div
      className={`gi-wrap${editing ? ' is-editing' : ''}${isEmpty ? ' is-empty' : ''}`}
      ref={wrapRef}
    >
      <div className="gi-field" role="group" aria-label={ariaLabel}>
        {editing ? (
          <input
            ref={inputRef}
            className="gi-input"
            value={local}
            placeholder={placeholder}
            aria-label={ariaLabel}
            onChange={handleChange}
            onBlur={commit}
            onKeyDown={handleKeyDown}
          />
        ) : (
          <button
            type="button"
            className="gi-display"
            onClick={enterEdit}
            aria-label={ariaLabel}
            title={isEmpty ? t('greeting_click_to_set', 'Cliquez pour définir la formule') : undefined}
          >
            {segments.map((seg, i) =>
              seg.kind === 'text' ? (
                <span key={i} className="gi-text">{seg.content}</span>
              ) : (
                <span
                  key={i}
                  className={`gi-chip gi-chip-${seg.token}`}
                  data-token={seg.token}
                  title={tokenTitle(seg.token!)}
                >
                  {tokenLabel(seg.token!)}
                </span>
              ),
            )}
          </button>
        )}

        <button
          type="button"
          className="gi-mode-btn"
          onClick={() => setMenuOpen(m => !m)}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          aria-label={`${t('greeting_mode_label', 'Address as')}: ${modeLabel}`}
          title={`${t('greeting_mode_label', 'Address as')} — ${modeLabel}`}
        >
          <span className="gi-mode-btn-label">{modeLabelShort}</span>
          <svg className="gi-mode-btn-caret" width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
            <path d="M2 4l3 3 3-3" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>

      {menuOpen && (
        <div className="gi-menu" role="menu" data-escape-owner="">
          <button
            type="button"
            role="menuitemradio"
            aria-checked={mode === 'first_name'}
            className={`gi-menu-item${mode === 'first_name' ? ' is-active' : ''}`}
            onClick={() => applyMode('first_name')}
          >
            <span className="gi-menu-preview">
              <span className="gi-text">{lead}</span>
              <span className="gi-chip gi-chip-first_name">{tokenLabel('first_name')}</span>
              <span className="gi-text">{tail}</span>
            </span>
            <span className="gi-menu-label">{t('greeting_mode_first_name', 'Prénom')}</span>
          </button>
          <button
            type="button"
            role="menuitemradio"
            aria-checked={mode === 'civility_last_name'}
            className={`gi-menu-item${mode === 'civility_last_name' ? ' is-active' : ''}`}
            onClick={() => applyMode('civility_last_name')}
          >
            <span className="gi-menu-preview">
              <span className="gi-text">{lead}</span>
              <span className="gi-chip gi-chip-civility">{tokenLabel('civility')}</span>
              <span className="gi-text">&nbsp;</span>
              <span className="gi-chip gi-chip-last_name">{tokenLabel('last_name')}</span>
              <span className="gi-text">{tail}</span>
            </span>
            <span className="gi-menu-label">{t('greeting_mode_civility_last_name', 'M./Mme + Nom')}</span>
          </button>
        </div>
      )}
    </div>
  )
}
