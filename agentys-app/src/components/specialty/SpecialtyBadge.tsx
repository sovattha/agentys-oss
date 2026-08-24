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

import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import type { SpecialtyInfo, SpecialtyMatchInfo } from '../../types/specialty'
import { isSpecialtyMatch } from '../../types/specialty'
import { CloseIcon } from '../icons/ActionIcons'
import './SpecialtyBadge.css'

interface SpecialtyBadgeProps {
  info: SpecialtyInfo | null
  message: { type: 'info' | 'warning' | 'error'; text: string } | null
  onDismiss: () => void
}

/**
 * Visual feedback for the Ctrl+Shift+G expert-mode flow.
 *
 * Renders two possible elements, stacked vertically:
 *
 * 1. A message banner (info/warning/error) when the backend reports a warning
 *    (no active specialty, no keyword match, rate limit, classification
 *    error, or a degraded fallback). Always visible when a message is set.
 *
 * 2. A colored pill badge when the classification produced a full match,
 *    with the specialty name, category, source count tooltip, a "Voir
 *    raisonnement" link that opens a modal with the Sonnet plan, and a
 *    dismiss (✕) button. Pill color follows the match's risk level.
 *
 * The component assumes the parent holds the state — it only calls
 * `onDismiss` when the user clicks the ✕ button (parent should clear
 * both `info` and `message`).
 */
export function SpecialtyBadge({ info, message, onDismiss }: SpecialtyBadgeProps) {
  const { t } = useTranslation('compose')
  const { t: tAgents } = useTranslation('agents')
  const [showPlan, setShowPlan] = useState(false)

  // Escape key closes the plan modal when it's open — skip when typing in
  // fields so inner popups handle Escape themselves first.
  useEffect(() => {
    if (!showPlan) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      const tgt = e.target as HTMLElement | null
      if (tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA' || tgt.isContentEditable)) {
        return
      }
      setShowPlan(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [showPlan])

  if (!info && !message) return null

  const match: SpecialtyMatchInfo | null = info && isSpecialtyMatch(info) ? info : null

  return (
    <div className="specialty-area">
      {message && (
        <div className={`specialty-message specialty-message--${message.type}`} role="status">
          {message.text}
        </div>
      )}

      {match && (
        <div
          className={`specialty-badge specialty-badge--${match.risk_level}`}
          role="status"
          aria-label={tAgents('specialty_badge_aria', {
            defaultValue: 'Expertise appliquée : {{name}}, catégorie {{category}}, niveau de risque {{risk}}',
            name: match.specialty_name,
            category: match.category,
            risk: tAgents(`specialty_risk_${match.risk_level}`, match.risk_level),
          })}
        >
          <span className="specialty-badge__icon" aria-hidden="true">
            {iconFor(match.specialty_id)}
          </span>
          <span className="specialty-badge__name">{match.specialty_name}</span>
          <span className="specialty-badge__sep" aria-hidden="true">·</span>
          <span className="specialty-badge__category">{humanizeCategory(match.category)}</span>

          {match.applied_sources && match.applied_sources.length > 0 && (
            <span
              className="specialty-badge__sources"
              title={match.applied_sources.join(', ')}
            >
              · {match.applied_sources.length} source{match.applied_sources.length > 1 ? 's' : ''}
            </span>
          )}

          {match.plan_preview && (
            <button
              type="button"
              className="specialty-badge__plan-link"
              onClick={() => setShowPlan(true)}
              aria-label={t('specialty_view_reasoning_aria')}
            >
              {t('specialty_view_reasoning_label')}
            </button>
          )}

          <button
            type="button"
            className="specialty-badge__dismiss"
            onClick={onDismiss}
            aria-label={t('specialty_remove_tooltip')}
            title={t('specialty_remove_tooltip')}
          >
            <CloseIcon size={14} />
          </button>
        </div>
      )}

      {showPlan && match?.plan_preview && (
        <div
          className="specialty-plan-modal"
          role="dialog"
          aria-modal="true"
          aria-label="Raisonnement expert"
          data-escape-owner=""
          onClick={(e) => { if (e.target === e.currentTarget) setShowPlan(false) }}
        >
          <div className="specialty-plan-modal__panel">
            <div className="specialty-plan-modal__header">
              <span>
                <span aria-hidden="true">{iconFor(match.specialty_id)}</span>{' '}
                Raisonnement — {match.specialty_name}
              </span>
              <button
                type="button"
                className="specialty-plan-modal__close"
                onClick={() => setShowPlan(false)}
                aria-label="Close"
              >
                <CloseIcon size={14} />
              </button>
            </div>
            <pre className="specialty-plan-modal__body">{match.plan_preview}</pre>
            {match.expert_names.length > 0 && (
              <div className="specialty-plan-modal__footer">
                Experts consultés : {match.expert_names.join(', ')}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function iconFor(specialtyId: string): string {
  if (specialtyId.startsWith('real-estate')) return '🏠'
  if (specialtyId.startsWith('legal')) return '⚖️'
  if (specialtyId.startsWith('hr') || specialtyId.startsWith('people')) return '👥'
  if (specialtyId.startsWith('sales')) return '💼'
  if (specialtyId.startsWith('finance') || specialtyId.startsWith('tax')) return '💰'
  return '🧠'
}

function humanizeCategory(category: string): string {
  if (!category) return ''
  return category.replace(/_/g, ' ')
}
