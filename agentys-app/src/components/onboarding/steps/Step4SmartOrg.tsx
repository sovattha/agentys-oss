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

import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchLabelCounts, createLabel, updateLabel } from '../../../api/labels'
import { API_URL } from '../../../config'
import { getAuthHeaders } from '../../../services/authToken'
import { apiClient } from '../../../services/api'
import type { LabelData } from '../useOnboardingWizard'
import { ContactAutocomplete } from '../../compose/ContactAutocomplete'
import { PlusIcon, CheckIcon } from '../../icons/ActionIcons'
import { generateColorFromString, getInitials } from '../../Avatar'
import '../../labels/LabelBadge.css'

interface SuggestedVip {
  name: string
  email: string
  sent_count: number
  received_count: number
}

interface Step4Props {
  onNext: () => void
  onBack: () => void
  onLabelData: (data: LabelData) => void
}

interface LabelInfo {
  name: string
  displayName: string
  description: string
  color: string
  count: number
}

const DEFAULT_COLORS = [
  '#22c55e', '#8b5cf6', '#f59e0b', '#ec4899', '#14b8a6',
  '#f97316', '#06b6d4', '#a855f7', '#3b82f6', '#ef4444',
]

interface DetectedLabel {
  name: string
  color: string
  source: 'provider' | 'manual'
  emailCount: number
  isProject: boolean
}

export function Step4SmartOrg({ onNext, onBack: _onBack, onLabelData }: Step4Props) {
  const { t } = useTranslation('onboarding')

  const LABEL_DEFS: Omit<LabelInfo, 'count'>[] = [
    { name: 'Action', displayName: t('step3_autolabel_action'), description: t('step3_autolabel_action_desc'), color: '#ef4444' },
    { name: 'FYI', displayName: t('step3_autolabel_fyi'), description: t('step3_autolabel_fyi_desc'), color: '#3b82f6' },
    { name: 'Noise', displayName: t('step3_autolabel_noise'), description: t('step3_autolabel_noise_desc'), color: '#6b7280' },
  ]

  const [labels, setLabels] = useState<LabelInfo[]>(LABEL_DEFS.map(l => ({ ...l, count: 0 })))
  const [loading, setLoading] = useState(true)
  const [detected, setDetected] = useState<DetectedLabel[]>([])
  const [enabledLabels, setEnabledLabels] = useState<Set<string>>(new Set())
  const [creating, setCreating] = useState(false)

  // Project details (title, number, abbreviation) per project name
  const [projectDetails, setProjectDetails] = useState<Record<string, { title: string; number: string; abbreviation: string }>>({})

  const updateProjectDetail = useCallback((name: string, field: 'title' | 'number' | 'abbreviation', value: string) => {
    setProjectDetails(prev => ({
      ...prev,
      [name]: { ...prev[name] || { title: name, number: '', abbreviation: '' }, [field]: value },
    }))
  }, [])

  // Initialize project details when detected labels arrive
  useEffect(() => {
    const projects = detected.filter(l => l.isProject)
    if (projects.length === 0) return
    setProjectDetails(prev => {
      const next = { ...prev }
      for (const p of projects) {
        if (!next[p.name]) {
          next[p.name] = { title: p.name, number: '', abbreviation: '' }
        }
      }
      return next
    })
  }, [detected])

  // Add form
  const [showAddForm, setShowAddForm] = useState(false)
  const [newName, setNewName] = useState('')
  const [addError, setAddError] = useState('')
  // Nom du projet fraîchement ajouté — déclenche une pill preview animée de
  // confirmation ("vos emails sur X seront regroupés ici") qui disparaît après ~2.6s.
  const [justAddedName, setJustAddedName] = useState<string | null>(null)
  const justAddedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Cleanup du setTimeout de la pill "just-added" : si l'utilisateur quitte
  // Step 4 pendant les 2.6s d'affichage, le timer continuerait à fire sur
  // un composant démonté → setState warning React.
  useEffect(() => {
    return () => {
      if (justAddedTimerRef.current) clearTimeout(justAddedTimerRef.current)
    }
  }, [])

  // VIP
  const [vipEmails, setVipEmails] = useState<string[]>([])
  const vipValue = useMemo(() => vipEmails.join(', '), [vipEmails])
  const handleVipChange = useCallback((val: string) => {
    const emails = val.split(',').map(e => e.trim()).filter(Boolean)
    setVipEmails(emails)
  }, [])

  // VIP suggestions — "legitimate" (bidirectional) contacts surfaced from the
  // scan so the user can one-click promote instead of typing names from
  // memory. Empty list (no scan data yet, or fetch failure) → the manual
  // ContactAutocomplete below is the only affordance. No loading spinner: the
  // chips just pop in when ready so a slow contacts call never blocks Step 4.
  const [suggestedVips, setSuggestedVips] = useState<SuggestedVip[]>([])
  useEffect(() => {
    let cancelled = false
    apiClient
      .getSuggestedVipContacts({ limit: 6 })
      .then(list => { if (!cancelled) setSuggestedVips(list) })
      .catch(() => { /* silent — manual autocomplete remains the fallback */ })
    return () => { cancelled = true }
  }, [])

  // Lowercased set of currently-selected VIP emails — drives the chip's
  // pressed state and dedups against anything typed into the autocomplete.
  const vipSet = useMemo(
    () => new Set(vipEmails.map(e => e.trim().toLowerCase())),
    [vipEmails],
  )

  const toggleVipSuggestion = useCallback((email: string) => {
    const lc = email.trim().toLowerCase()
    setVipEmails(prev =>
      prev.some(e => e.trim().toLowerCase() === lc)
        ? prev.filter(e => e.trim().toLowerCase() !== lc)
        : [...prev, email],
    )
  }, [])

  // Fetch label counts only. Auto-detected projects are intentionally NOT loaded:
  // the user explicitly asked for an opt-in flow where only manually-typed projects
  // (+ defaults + VIP) are created. The KnowledgeAgent's hallucinated "projects"
  // (e.g. "Tiptap", "12345", "123abc") are the reason this auto-flow was removed.
  useEffect(() => {
    const load = async () => {
      try {
        const data = await fetchLabelCounts()
        if (data?.counts) {
          setLabels(prev => prev.map(l => ({
            ...l,
            count: data.counts[l.name] || 0,
          })))
        }
      } catch { /* ignore */ }

      setDetected([])
      setEnabledLabels(new Set())
      setLoading(false)
    }
    load()
  }, [])

  const toggleLabel = useCallback((name: string) => {
    setEnabledLabels(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }, [])

  const handleAddLabel = useCallback(() => {
    const trimmed = newName.trim()
    if (!trimmed) return
    if (detected.some(l => l.name.toLowerCase() === trimmed.toLowerCase())) {
      setAddError(t('step4_label_exists'))
      return
    }
    setAddError('')

    const newLabel: DetectedLabel = {
      name: trimmed,
      color: DEFAULT_COLORS[detected.length % DEFAULT_COLORS.length],
      source: 'manual',
      emailCount: 0,
      isProject: true,
    }
    setDetected(prev => [...prev, newLabel])
    setEnabledLabels(prev => new Set(prev).add(trimmed))
    setNewName('')
    setShowAddForm(false)
    setJustAddedName(trimmed)
    // Reset après l'animation — on garde la pill ~2.6s pour laisser l'utilisateur
    // lire la confirmation tangible. ID capturé pour cleanup sur unmount.
    if (justAddedTimerRef.current) clearTimeout(justAddedTimerRef.current)
    justAddedTimerRef.current = setTimeout(() => {
      setJustAddedName((prev) => (prev === trimmed ? null : prev))
    }, 2600)
  }, [newName, detected, t])

  // (VIP add/remove handled by ContactAutocomplete chips)

  const handleContinue = useCallback(async () => {
    const counts: Record<string, number> = {}
    labels.forEach(l => { counts[l.name] = l.count })
    onLabelData({ autoLabelEnabled: true, labelCounts: counts })

    let failures = 0

    const toCreate = detected.filter(l => enabledLabels.has(l.name))
    if (toCreate.length > 0) {
      setCreating(true)
      try {
        await Promise.all(toCreate.map(async (l) => {
          const pd = projectDetails[l.name]
          try {
            await createLabel({
              name: l.name,
              color: l.color,
              description: '',
              is_project: l.isProject,
              is_favorite: l.isProject ? true : undefined,
              project_name: pd?.title || undefined,
              project_number: pd?.number || undefined,
              project_abbreviation: pd?.abbreviation || undefined,
            })
          } catch {
            // Label already exists — update it with new data
            await updateLabel(l.name, {
              color: l.color,
              is_project: l.isProject,
              is_favorite: l.isProject ? true : undefined,
              project_name: pd?.title || undefined,
              project_number: pd?.number || undefined,
              project_abbreviation: pd?.abbreviation || undefined,
            }).catch(() => { failures += 1 })
          }

          if (l.isProject) {
            const nameLC = l.name.toLowerCase()
            await Promise.all([
              fetch(`${API_URL}/api/labels/rules`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                body: JSON.stringify({ label_name: l.name, condition_type: 'subject', condition_value: nameLC, confidence: 0.9 }),
                // Audit 2026-06-11 F-02 : fetch résout sur 4xx/5xx — compter
                // aussi les réponses non-ok, pas seulement les rejets réseau.
              }).then((r) => { if (!r.ok) failures += 1 }, () => { failures += 1 }),
              fetch(`${API_URL}/api/labels/rules`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                body: JSON.stringify({ label_name: l.name, condition_type: 'body', condition_value: nameLC, confidence: 0.85 }),
              }).then((r) => { if (!r.ok) failures += 1 }, () => { failures += 1 }),
            ])
          }
        }))
      } catch { failures += 1 }
    }

    if (vipEmails.length > 0) {
      try {
        try {
          await createLabel({
            name: 'VIP',
            color: '#22c55e',
            description: t('step4_vip_desc'),
            is_favorite: true,
          })
        } catch {
          await updateLabel('VIP', {
            color: '#22c55e',
            description: t('step4_vip_desc'),
            is_favorite: true,
          }).catch(() => { failures += 1 })
        }

        await Promise.all(vipEmails.map(async (email) => {
          await fetch(`${API_URL}/api/labels/vip`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
            body: JSON.stringify({ email }),
          }).then((r) => { if (!r.ok) failures += 1 }, () => { failures += 1 })

          await fetch(`${API_URL}/api/labels/rules`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
            body: JSON.stringify({ label_name: 'VIP', condition_type: 'sender', condition_value: email, confidence: 1.0 }),
          }).then((r) => { if (!r.ok) failures += 1 }, () => { failures += 1 })
        }))
      } catch { failures += 1 }
    }

    setCreating(false)

    if (failures > 0) {
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: {
          message: t('step4_partial_create'),
          type: 'warning',
          duration: 6000,
        },
      }))
    }

    onNext()
  }, [labels, onLabelData, onNext, detected, enabledLabels, projectDetails, vipEmails, t])

  return (
    <>
      <h2 className="po-section-title">{t('step4_title')}</h2>
      <h3 className="po-section-label-heading">{t('step4_label_heading')}</h3>
      <p className="po-section-subtitle">
        {t('step4_subtitle')}
      </p>

      {loading ? (
        <div className="po-loading-center">
          <div className="po-spinner" />
        </div>
      ) : (
        <>
          <div className="po-label-cards">
            {labels.map(label => (
              <div key={label.name} className="po-label-card">
                <div className="po-label-card-header">
                  <span
                    className="label-badge label-badge-medium"
                    style={{ '--label-color': label.color } as React.CSSProperties}
                  >
                    <span className="label-badge-name">{label.displayName}</span>
                  </span>
                  <svg className="po-label-card-star" width="18" height="18" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="2">
                    <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                  </svg>
                </div>
                <p className="po-label-card-desc">{label.description}</p>
              </div>
            ))}
          </div>

          {/* Project labels — heading + manually added projects + add button */}
          <div className="po-add-label-section">
            <h3 className="po-suggested-header">{t('step4_project_labels_heading')}</h3>
            <p className="po-suggested-subtitle">{t('step4_project_labels_subtitle')}</p>

            {detected.filter(l => l.isProject).length > 0 && (
              <div className="po-suggested-list">
                {detected.filter(l => l.isProject).map(label => {
                  const isEnabled = enabledLabels.has(label.name)
                  const details = projectDetails[label.name] || { title: label.name, number: '', abbreviation: '' }
                  return (
                    <div key={label.name}>
                      <div className="po-suggested-row">
                        <span className="po-label-dot" style={{ background: label.color }} />
                        <div className="po-suggested-info">
                          <span className="po-suggested-name">{label.name}</span>
                        </div>
                        {label.emailCount > 0 && (
                          <span className="po-suggested-count">{label.emailCount}</span>
                        )}
                        <button
                          className={`po-toggle-switch${isEnabled ? ' active' : ''}`}
                          onClick={() => toggleLabel(label.name)}
                          aria-label={t('step4_enable_label', { name: label.name })}
                          aria-pressed={isEnabled}
                        />
                      </div>
                      {isEnabled && (
                        <div className="po-project-fields">
                          <div className="po-project-field">
                            <input
                              type="text"
                              value={details.number}
                              onChange={e => updateProjectDetail(label.name, 'number', e.target.value)}
                              placeholder={t('step4_project_number_placeholder', 'Project name e.g. Agentys')}
                              maxLength={50}
                            />
                          </div>
                          <div className="po-project-field">
                            <input
                              type="text"
                              value={details.abbreviation}
                              onChange={e => updateProjectDetail(label.name, 'abbreviation', e.target.value)}
                              placeholder={t('step4_project_abbr_placeholder', 'Abbrev. e.g. AGT')}
                              maxLength={20}
                            />
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}

            {justAddedName && (
              <div
                key={justAddedName}
                className="po-add-label-preview"
                role="status"
                aria-live="polite"
              >
                <span className="po-add-label-preview-icon" aria-hidden="true">
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                    <circle cx="8" cy="8" r="7" fill="currentColor" opacity="0.18"/>
                    <path d="M4.5 8.5l2.2 2.2L11.5 5.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
                  </svg>
                </span>
                <span className="po-add-label-preview-text">
                  {t('step4_project_added_preview', { name: justAddedName, defaultValue: 'Les emails « {{name}} » seront regroupés ici' })}
                </span>
              </div>
            )}

            {!showAddForm ? (
              <button
                type="button"
                className="po-add-label-btn"
                onClick={() => setShowAddForm(true)}
              >
                <PlusIcon size={16} />
                {t('step4_add_project')}
              </button>
            ) : (
              <div className="po-add-label-form">
                <input
                  type="text"
                  className="po-add-label-input"
                  placeholder={t('step4_project_placeholder')}
                  value={newName}
                  onChange={e => { setNewName(e.target.value); setAddError('') }}
                  onKeyDown={e => e.key === 'Enter' && handleAddLabel()}
                  autoFocus
                />
                <div className="po-add-label-actions">
                  <button type="button" className="po-add-label-confirm" onClick={handleAddLabel}>
                    {t('step4_add_btn')}
                  </button>
                  <button
                    type="button"
                    className="po-add-label-cancel"
                    onClick={() => { setShowAddForm(false); setNewName(''); setAddError('') }}
                  >
                    {t('step4_cancel_btn')}
                  </button>
                </div>
                {addError && <p className="po-add-label-error">{addError}</p>}
              </div>
            )}
          </div>

          {/* VIP section */}
          <div className="po-suggested-section">
            <h3 className="po-suggested-header">{t('step4_other_labels')}</h3>
            <div className="po-vip-box">
              <div className="po-vip-header">
                <span className="po-vip-icon">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                  </svg>
                </span>
                <div>
                  <h3 className="po-vip-title">{t('step4_vip_title')}</h3>
                  <p className="po-vip-desc">{t('step4_vip_desc')}</p>
                </div>
              </div>

              {suggestedVips.length > 0 && (
                <div className="po-vip-suggestions" role="group" aria-label={t('step4_vip_suggestions_hint')}>
                  <p className="po-vip-suggestions-hint">{t('step4_vip_suggestions_hint')}</p>
                  <div className="po-vip-suggestions-row">
                    {suggestedVips.map(c => {
                      const selected = vipSet.has(c.email.toLowerCase())
                      const label = (c.name || '').trim() || c.email.split('@')[0]
                      return (
                        <button
                          type="button"
                          key={c.email}
                          className={`po-vip-chip${selected ? ' active' : ''}`}
                          onClick={() => toggleVipSuggestion(c.email)}
                          aria-pressed={selected}
                          title={c.email}
                        >
                          <span
                            className="po-vip-chip-avatar"
                            aria-hidden="true"
                            style={{ background: generateColorFromString(c.email) }}
                          >
                            {getInitials(label, c.email)}
                          </span>
                          <span className="po-vip-chip-label">{label}</span>
                          {selected && (
                            <span className="po-vip-chip-check" aria-hidden="true">
                              <CheckIcon size={14} />
                            </span>
                          )}
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}

              <ContactAutocomplete
                value={vipValue}
                onChange={handleVipChange}
                placeholder={t('step4_vip_placeholder')}
                multi={true}
                className="po-vip-autocomplete"
              />
            </div>
          </div>
        </>
      )}

      <div className="po-sticky-cta">
        <button className="po-btn-primary" onClick={handleContinue} disabled={creating}>
          {creating ? (
            <><span className="po-spinner" /> {t('step4_creating')}</>
          ) : (
            <>
              <span>{t('step1_continue')}</span>
              <svg className="w0-btn-arrow" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
            </>
          )}
        </button>
      </div>
    </>
  )
}
