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

import { useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useAnimatedUnmount } from '../hooks/useAnimatedUnmount'
import { useShortcutsStore } from '../hooks/useShortcutsStore'
import { formatShortcutForDisplay } from '../types/shortcuts'
import { ChevronLeftIcon, CloseIcon } from './icons/ActionIcons'
import './ShortcutSettings.css'

interface ShortcutsHelpPanelProps {
  isOpen: boolean
  onClose: () => void
  onBack?: () => void
}

const CATEGORIES = [
  { key: 'navigation' as const, label: 'Navigation' },
  { key: 'composition' as const, label: 'Composition' },
  { key: 'application' as const, label: 'Application' },
]

export function ShortcutsHelpPanel({ isOpen, onClose, onBack }: ShortcutsHelpPanelProps) {
  const { t: tc } = useTranslation('common')
  const { t } = useTranslation('settings')
  const { shouldRender, isClosing, handleClose } = useAnimatedUnmount(isOpen, onClose)
  const { shortcuts } = useShortcutsStore()

  // Close on Escape
  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        handleClose()
      }
    },
    [handleClose]
  )

  useEffect(() => {
    if (!isOpen) return
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen, handleKeyDown])

  if (!shouldRender) return null

  return (
    <div className="shortcuts-help-overlay" onClick={handleClose}>
      <div className={`shortcuts-help-panel${isClosing ? ' closing' : ''}`} onClick={(e) => e.stopPropagation()}>
        <div className="shortcuts-help-header">
          <div className="shortcuts-help-header-left">
            {onBack && (
              <button className="shortcuts-help-back" onClick={onBack} aria-label={tc('back')} title={tc('back')}>
                <ChevronLeftIcon size={20} />
              </button>
            )}
            <h2>{t('shortcuts_title')}</h2>
          </div>
          <div className="shortcuts-help-header-actions">
            <button className="close-button" onClick={handleClose} aria-label={t('shortcuts_title')}>
              <CloseIcon />
            </button>
          </div>
        </div>

        <div className="shortcuts-help-content">
          {CATEGORIES.map(({ key, label }) => {
            const categoryShortcuts = shortcuts.filter(s => s.category === key)
            if (categoryShortcuts.length === 0) return null
            return (
              <section key={key} className="shortcuts-section">
                <h3>{label}</h3>
                <ul className="shortcuts-list">
                  {categoryShortcuts.map(shortcut => (
                    <li key={shortcut.id} className="shortcut-item">
                      <span className="shortcut-label">{t(shortcut.label)}</span>
                      <kbd className="shortcut-kbd">
                        {formatShortcutForDisplay(shortcut.currentBinding)}
                      </kbd>
                    </li>
                  ))}
                </ul>
              </section>
            )
          })}
        </div>
      </div>
    </div>
  )
}
