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

import { useEffect, useState, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { getAvailableSpecialties, purchaseSpecialty, deactivateSpecialty, type SpecialtySummary } from '../../services/specialties'
import { useOptimisticMutation } from '../../hooks/useOptimisticMutation'
import { ChevronLeftIcon, CloseIcon } from '../icons/ActionIcons'
import './ApprentissagesModal.css'

// ── Static metadata by specialty ID ──────────────────────────────────────

type IconType = 'trending-up' | 'scale' | 'home'

const SPECIALTY_META: Record<string, { color: string; colorVar: string; icon: IconType; topicKeys: string[]; domainKey: string; descKey: string }> = {
  'real-estate-qc': {
    color: '#f97316',
    colorVar: '#f97316',
    icon: 'home',
    domainKey: 'specialty_domain_real_estate',
    descKey: 'specialty_desc_real_estate_qc',
    topicKeys: ['specialty_topic_offers', 'specialty_topic_inspection', 'specialty_topic_financing', 'specialty_topic_coownership'],
  },
}

// ── Icon components ───────────────────────────────────────────────────────

function SpecialtyIcon({ icon }: { icon: IconType }) {
  const props = { 'aria-hidden': true as const, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
  if (icon === 'trending-up') return (
    <svg {...props}>
      <polyline points="23 6 13.5 15.5 8.5 10.5 1 18" />
      <polyline points="17 6 23 6 23 12" />
    </svg>
  )
  if (icon === 'scale') return (
    <svg {...props}>
      <line x1="12" y1="3" x2="12" y2="21" />
      <path d="M3 6l9-3 9 3" />
      <path d="M3 18l9 3 9-3" />
      <line x1="3" y1="12" x2="3" y2="18" />
      <line x1="21" y1="12" x2="21" y2="18" />
    </svg>
  )
  return (
    <svg {...props}>
      <path d="M3 9.5L12 3l9 6.5V20a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9.5z" />
      <path d="M9 21V12h6v9" />
    </svg>
  )
}

// ── Specialty Card ────────────────────────────────────────────────────────

interface CardProps {
  specialty: SpecialtySummary
  meta: typeof SPECIALTY_META[string]
  index: number
  onToggle: (id: string, isActive: boolean) => Promise<void>
  loading: boolean
  t: (key: string, opts?: Record<string, unknown>) => string
}

function SpecialtyCard({ specialty, meta, index, onToggle, loading, t }: CardProps) {
  return (
    <article
      className="ssc-card"
      style={{ '--ssc-color': meta.colorVar, '--ssc-card-delay': index } as React.CSSProperties}
    >
      <div className="ssc-card-halo" aria-hidden="true" />

      {/* ── Left: icon + identity + actions ── */}
      <div className="ssc-card-left">
        <span className="ssc-card-icon">
          <SpecialtyIcon icon={meta.icon} />
        </span>
        <h3 className="ssc-card-name">{specialty.name}</h3>
        <span className="ssc-card-meta">
          {t('expert_count', { count: specialty.expert_count })} · {t(meta.domainKey)}
        </span>
        <div className="ssc-card-footer">
          {specialty.is_active ? (
            <span className="ssc-badge ssc-badge--active">{t('specialty_active_badge')}</span>
          ) : (
            <span className="ssc-badge ssc-badge--price">{t('specialty_price_monthly', { price: specialty.price_monthly })}</span>
          )}
          <button
            className={`ssc-card-btn${specialty.is_active ? ' ssc-card-btn--deactivate' : ''}`}
            onClick={() => onToggle(specialty.id, specialty.is_active)}
            disabled={loading}
            type="button"
          >
            {loading ? '…' : specialty.is_active ? t('common:deactivate') : t('common:activate')}
          </button>
        </div>
      </div>

      {/* ── Divider ── */}
      <div className="ssc-card-divider" aria-hidden="true" />

      {/* ── Right: description + topic chips ── */}
      <div className="ssc-card-right">
        <p className="ssc-card-desc">{t(meta.descKey, { defaultValue: specialty.description })}</p>
        <div className="ssc-card-topics">
          {meta.topicKeys.map(key => (
            <span key={key} className="ssc-card-topic">{t(key)}</span>
          ))}
        </div>
      </div>

      <div className="ssc-card-shimmer" aria-hidden="true" />
    </article>
  )
}

// ── Main modal ────────────────────────────────────────────────────────────

interface Props {
  isOpen: boolean
  onClose: () => void
  onChanged: () => void
}

export function ApprentissagesModal({ isOpen, onClose, onChanged }: Props) {
  const { t } = useTranslation('agents')
  const [specialties, setSpecialties] = useState<SpecialtySummary[]>([])
  const [loadingId, setLoadingId] = useState<string | null>(null)
  const bodyRef = useRef<HTMLDivElement>(null)

  // Load specialties and scroll to top when opening
  useEffect(() => {
    if (!isOpen) return
    getAvailableSpecialties()
      .then(setSpecialties)
      .catch(() => setSpecialties([]))
    // Scroll to top of modal body
    if (bodyRef.current) {
      bodyRef.current.scrollTop = 0
    }
  }, [isOpen])

  // Audit Cluster D (2026-05-17) Toast Site 4 / #330: previously `catch
  // { /* silently ignore */ }`. On failure the toggle snapped back via the
  // refresh-from-server with no message — looked like an unstable button.
  const runToggleSpecialty = useOptimisticMutation<void>({
    scope: 'apprentissages-toggle-specialty',
    i18nKey: 'toasts.specialty_toggle_failed',
  })
  const handleToggle = async (id: string, isActive: boolean) => {
    setLoadingId(id)
    await runToggleSpecialty(async () => {
      if (isActive) {
        await deactivateSpecialty(id)
      } else {
        await purchaseSpecialty(id)
      }
      const updated = await getAvailableSpecialties()
      setSpecialties(updated)
      onChanged()
    })
    setLoadingId(null)
  }

  const activeCount = specialties.filter(s => s.is_active).length
  const knownSpecialties = specialties.filter(s => SPECIALTY_META[s.id])

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent showCloseButton={false} className="ssc-modal" aria-describedby={undefined}>
        {/* ── Header ── */}
        <header className="ssc-header">
          <button
            className="ssc-back"
            onClick={onClose}
            aria-label={t('common:back')}
            title={t('common:back')}
            type="button"
          >
            <ChevronLeftIcon size={20} />
          </button>
          <div className="ssc-header-text">
            <DialogTitle id="ssc-title" className="ssc-title">{t('specialties_title')}</DialogTitle>
            <p className="ssc-subtitle">{t('specialties_subtitle')}</p>
          </div>
          <button className="ssc-close" onClick={onClose} type="button" aria-label={t('common:close')} title={t('common:close')}>
            <CloseIcon />
          </button>
        </header>

        {/* ── Scrollable Body ── */}
        <div className="ssc-body" ref={bodyRef}>

          {/* ── Hero Banner ── */}
          <section className="ssc-hero" aria-label={t('specialties_summary_aria')}>
            <div className="ssc-hero-content">
              <span className="ssc-hero-count">
                {activeCount > 0
                  ? t('specialties_active', { count: activeCount })
                  : t('specialties_none_active')}
              </span>
              <span className="ssc-hero-tagline">
                {t('specialties_tagline')}
              </span>
            </div>
            <div className="ssc-hero-sweep" aria-hidden="true" />
          </section>

          {/* ── Cards Grid ── */}
          <section className="ssc-grid" aria-label={t('specialties_available_aria')}>
            {knownSpecialties.map((spec, i) => (
              <SpecialtyCard
                key={spec.id}
                specialty={spec}
                meta={SPECIALTY_META[spec.id]}
                index={i}
                onToggle={handleToggle}
                loading={loadingId === spec.id}
                t={t}
              />
            ))}
            {specialties.length === 0 && (
              <p className="ssc-empty">{t('specialties_loading')}</p>
            )}
          </section>
        </div>

      </DialogContent>
    </Dialog>
  )
}
