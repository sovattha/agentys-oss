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

import { useState, useEffect, useRef, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import type { OnboardingState } from '../useOnboardingWizard'

interface FinalScorecardProps {
  state: OnboardingState
  onFinish: () => void
}

function toneKey(rawTone: string): string | null {
  const normalized = rawTone
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, '_')

  if (!normalized) return null
  if (normalized === 'professionnel') return 'tone_professional'
  return `tone_${normalized}`
}

/**
 * Final celebration screen — auto-transitions to inbox in ~1.3s.
 *
 * Product requirement: the whole "All set" page must stay under 1.5s.
 * onFinish fires at 1000ms, then PremiumOnboarding plays a 300ms shell
 * fade-out, so the screen is fully gone by ~1.3s (comfortable margin).
 *
 * Phase timeline:
 *   0ms    → Phase 1: checkmark + ring burst
 *   100ms  → Phase 2: title + subtitle glow in
 *   250ms  → Phase 3: stats + particle burst
 *   1000ms → Phase 4: call onFinish (triggers shell exit animation)
 */
export function FinalScorecard({ state, onFinish }: FinalScorecardProps) {
  const { t } = useTranslation('onboarding')
  const [phase, setPhase] = useState(1)

  // Stats extracted from onboarding data
  const stats = useMemo(() => {
    const items: { value: string; label: string }[] = []

    if (state.trainingData?.emailsAnalysed) {
      items.push({
        value: String(state.trainingData.emailsAnalysed),
        label: t('final_stat_emails', 'emails analysés'),
      })
    }

    if (state.trainingData?.tone) {
      const key = toneKey(state.trainingData.tone)
      items.push({
        value: key ? t(key, state.trainingData.tone) : state.trainingData.tone,
        label: t('final_stat_tone', 'ton détecté'),
      })
    }

    if (state.trainingData?.contactsCount) {
      items.push({
        value: String(state.trainingData.contactsCount),
        label: t('final_stat_contacts', 'contacts appris'),
      })
    }

    const labelCount = state.labelData
      ? Object.keys(state.labelData.labelCounts).length
      : 0
    if (labelCount > 0) {
      items.push({
        value: String(labelCount),
        label: t('final_stat_labels', 'labels configurés'),
      })
    }

    // Fallback if data is sparse
    if (items.length < 2) {
      items.push({ value: '✓', label: t('final_stat_ready', 'IA configurée') })
    }

    return items
  }, [state, t])

  // Ref pour éviter que onFinish instable (recréé à chaque render parent) ne réinitialise les timers
  const onFinishRef = useRef(onFinish)
  onFinishRef.current = onFinish
  // Phase progression.
  useEffect(() => {
    const timers = [
      setTimeout(() => setPhase(2), 100),
      setTimeout(() => setPhase(3), 250),
    ]
    return () => timers.forEach(clearTimeout)
  }, [])

  // Auto-finish in 1.0s. PremiumOnboarding then runs a 300ms shell fade-out,
  // so the whole "All set" page stays well under the required 1.5s (~1.3s total).
  useEffect(() => {
    const timer = setTimeout(() => onFinishRef.current(), 1000)
    return () => clearTimeout(timer)
  }, [])

  // Toutes les sections sont montées dès le départ (réservation d'espace pour
  // que la carte ait sa taille finale immédiatement et que le checkmark ne bouge
  // pas visuellement). Les animations sont pilotées par la classe --p{N} sur le
  // container (déclenchées par CSS, pas par mount React).
  return (
    <div
      className={`po-final-celebration po-final-celebration--p${phase}`}
    >
      {/* Ambient glow */}
      <div className="po-final-glow-orb" />

      {/* Phase 1: Checkmark + ring burst */}
      <div className="po-final-check-wrap">
        <div className="po-final-ring" />
        <div className="po-final-ring po-final-ring-2" />
        <div className="po-final-check">
          <svg
            aria-hidden="true"
            width="40"
            height="40"
            viewBox="0 0 40 40"
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M10 20l8 8 12-15" />
          </svg>
        </div>
      </div>

      {/* Phase 2: Title + subtitle — toujours monté, animé via --p2/--p3 */}
      <div
        className="po-final-text"
        aria-hidden={phase < 2 ? 'true' : undefined}
      >
        <h2 className="po-final-title">
          {t('final_ready_title', 'Tout est prêt !')}
        </h2>
        <p className="po-final-subtitle">
          {t('final_ready_subtitle_v2', 'Votre assistant email est configuré et prêt à vous aider.')}
        </p>
      </div>

      {/* Phase 3: Stats + particles — toujours monté, animé via --p3 */}
      <div
        className="po-final-stats"
        aria-hidden={phase < 3 ? 'true' : undefined}
      >
        {stats.map((stat, i) => (
          <div
            key={stat.label}
            className="po-final-stat"
            style={{ animationDelay: `${i * 0.12}s` }}
          >
            <span className="po-final-stat-value">{stat.value}</span>
            <span className="po-final-stat-label">{stat.label}</span>
          </div>
        ))}
      </div>

      {phase >= 3 && (
        <div className="po-final-particles" aria-hidden="true">
          {Array.from({ length: 16 }, (_, i) => (
            <div key={i} className="po-final-particle" />
          ))}
        </div>
      )}

      {/* Auto-transition progress bar */}
      <div className="po-final-auto-progress">
        <div className="po-final-auto-bar" />
      </div>
    </div>
  )
}
