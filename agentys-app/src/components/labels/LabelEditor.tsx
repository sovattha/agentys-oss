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

import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { createLabel, updateLabel, deleteLabel, createRule, deleteRule, fetchRules } from '../../api/labels'
import type { Label, LabelingRule, CreateRulePayload } from '../../types/labels'
import { LABEL_COLORS, getLabelDisplayName } from '../../types/labels'
import { useContactGroups } from '../../hooks/useContactGroups'
import { useOptimisticMutation } from '../../hooks/useOptimisticMutation'
import { ChevronLeftIcon, CloseIcon, TrashIcon } from '../icons/ActionIcons'
import './LabelEditor.css'

const EXTENDED_PALETTE = [
  // Pastels
  '#fecaca', '#fed7aa', '#fef08a', '#bbf7d0', '#99f6e4', '#bfdbfe', '#ddd6fe', '#fbcfe8',
  // Vivid lights
  '#f87171', '#fb923c', '#facc15', '#4ade80', '#2dd4bf', '#60a5fa', '#a78bfa', '#f472b6',
  // Rich
  '#ef4444', '#ea580c', '#eab308', '#22c55e', '#14b8a6', '#3b82f6', '#8b5cf6', '#ec4899',
  // Deep
  '#b91c1c', '#c2410c', '#a16207', '#15803d', '#0f766e', '#1d4ed8', '#6d28d9', '#be185d',
  // Neutrals
  '#f5f5f4', '#d6d3d1', '#a8a29e', '#78716c', '#57534e', '#44403c', '#292524', '#0c0a09',
]

function hslToHex(h: number, s: number, l: number): string {
  const a = s * Math.min(l, 1 - l)
  const f = (n: number) => {
    const k = (n + h / 30) % 12
    const color = l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1)
    return Math.round(255 * Math.max(0, Math.min(1, color))).toString(16).padStart(2, '0')
  }
  return `#${f(0)}${f(8)}${f(4)}`
}

function hexToHue(hex: string): number {
  if (!/^#[0-9a-fA-F]{6}$/.test(hex)) return 0
  const r = parseInt(hex.slice(1, 3), 16) / 255
  const g = parseInt(hex.slice(3, 5), 16) / 255
  const b = parseInt(hex.slice(5, 7), 16) / 255
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const d = max - min
  if (d === 0) return 0
  let h: number
  if (max === r) h = ((g - b) / d + 6) % 6
  else if (max === g) h = (b - r) / d + 2
  else h = (r - g) / d + 4
  return Math.round(h * 60)
}

interface LabelEditorProps {
  label: Label | null
  isOpen: boolean
  onClose: () => void
  onSave: () => void
}

type RuleConditionType = 'sender' | 'subject' | 'body' | 'recipient'

interface RuleFormData {
  condition_type: RuleConditionType
  condition_value: string
}

export function LabelEditor({ label, isOpen, onClose, onSave }: LabelEditorProps) {
  const { t: tSettings } = useTranslation('settings')
  const { t: tErrors } = useTranslation('errors')
  const { t: tCommon } = useTranslation('common')
  const isEditing = label !== null

  // Form state
  const [name, setName] = useState('')
  const [color, setColor] = useState(LABEL_COLORS[0])
  const [description, setDescription] = useState('')
  const [isFavorite, setIsFavorite] = useState(false)
  const [isProject, setIsProject] = useState(false)
  const [projectName, setProjectName] = useState('')
  const [projectNumber, setProjectNumber] = useState('')
  const [projectAbbreviation, setProjectAbbreviation] = useState('')
  const [subjectPrefix, setSubjectPrefix] = useState('')
  const [aiPrompt, setAiPrompt] = useState('')

  // Custom color picker
  const isCustomColor = !LABEL_COLORS.includes(color)
  const [showExtendedPicker, setShowExtendedPicker] = useState(false)
  const [hexInput, setHexInput] = useState(LABEL_COLORS[0])
  const [hueValue, setHueValue] = useState(180)
  const colorPickerRef = useRef<HTMLDivElement>(null)

  // Rules state
  const [rules, setRules] = useState<LabelingRule[]>([])
  // Pending rules for new labels (not yet saved to backend)
  const [pendingRules, setPendingRules] = useState<RuleFormData[]>([])
  const [newRule, setNewRule] = useState<RuleFormData>({
    condition_type: 'sender',
    condition_value: '',
  })
  const [loadingRules, setLoadingRules] = useState(false)
  // F-07 (audit 2026-06-11) : false tant que fetchRules n'a pas réussi — le
  // sync de handleSave ne doit jamais déduper contre une liste vide mensongère
  // (il recréerait des doublons de règles projet à chaque save).
  const [rulesLoaded, setRulesLoaded] = useState(false)
  const [, setShowExclusions] = useState(false)
  const [activeFilter, setActiveFilter] = useState<RuleConditionType | null>(null)

  // Contact groups
  const { groups: allGroups } = useContactGroups()
  const linkedGroups = useMemo(
    () => (isEditing && label ? allGroups.filter(g => g.label_name === label.name) : []),
    [allGroups, isEditing, label],
  )

  // UI state
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Load label data — depend on label.name to avoid re-triggering on object reference changes
  const labelName = label?.name ?? null
  useEffect(() => {
    if (isOpen && label && labelName) {
      setName(label.name)
      setColor(label.color || LABEL_COLORS[0])
      setDescription(label.description || '')
      setIsFavorite(label.is_favorite)
      setIsProject(label.is_project ?? false)
      setProjectName(label.project_name || '')
      setProjectNumber(label.project_number || '')
      setProjectAbbreviation(label.project_abbreviation || '')
      setSubjectPrefix(label.subject_prefix || '')
      setAiPrompt(label.ai_prompt || '')
      setShowExtendedPicker(false)
      loadRules(label.name)
    } else if (isOpen && !labelName) {
      setName('')
      setColor(LABEL_COLORS[0])
      setDescription('')
      setIsFavorite(false)
      setIsProject(false)
      setProjectName('')
      setProjectNumber('')
      setProjectAbbreviation('')
      setSubjectPrefix('')
      setAiPrompt('')
      setRules([])
      setPendingRules([])
      setRulesLoaded(true) // nouveau label : rien à charger côté backend
      setShowExclusions(false)
      setActiveFilter(null)
      setShowExtendedPicker(false)
    }

  }, [isOpen, labelName])

  // Sync hex input & hue slider with color state
  useEffect(() => {
    setHexInput(color)
    setHueValue(hexToHue(color))
  }, [color])

  // Close extended color picker on outside click
  useEffect(() => {
    if (!showExtendedPicker) return
    const handleClick = (e: MouseEvent) => {
      if (colorPickerRef.current && !colorPickerRef.current.contains(e.target as Node)) {
        setShowExtendedPicker(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [showExtendedPicker])

  const loadRules = async (labelName: string) => {
    try {
      setLoadingRules(true)
      setRulesLoaded(false)
      const response = await fetchRules()
      const labelRules = response.rules.filter(r => r.label_name === labelName)
      setRules(labelRules)
      setRulesLoaded(true)
    } catch (err) {
      // F-07 (audit 2026-06-11) : la section règles s'affichait vide sans
      // signal — l'utilisateur croyait ses règles perdues, ou en recréait.
      console.error('Failed to load rules:', err)
      setError(tSettings('label_rules_load_error'))
    } finally {
      setLoadingRules(false)
    }
  }

  // Auto-derive subject/body rules from project fields
  const projectDerivedRules = useMemo((): RuleFormData[] => {
    if (!isProject) return []
    const keywords = [projectName.trim(), projectNumber.trim(), projectAbbreviation.trim()].filter(Boolean)
    const result: RuleFormData[] = []
    const seen = new Set<string>()
    for (const kw of keywords) {
      if (!seen.has(kw)) {
        seen.add(kw)
        result.push({ condition_type: 'subject', condition_value: kw })
        result.push({ condition_type: 'body', condition_value: kw })
      }
    }
    return result
  }, [isProject, projectName, projectNumber, projectAbbreviation])

  const handleSave = useCallback(async () => {
    if (!name.trim()) {
      setError(tSettings('label_name_required'))
      return
    }

    // Audit e2e 2026-06-10 F-01 : les échecs de createRule étaient avalés en
    // boucle (console.error) puis le toast succès partait quand même — label
    // créé mais auto-tri jamais actif, sans aucun signal.
    let failedRules = 0

    try {
      setSaving(true)
      setError(null)

      if (isEditing) {
        await updateLabel(label!.name, {
          color,
          description,
          is_favorite: isFavorite,
          is_project: isProject,
          project_name: isProject && projectName.trim() ? projectName.trim() : null,
          project_number: isProject && projectNumber.trim() ? projectNumber.trim() : null,
          project_abbreviation: isProject && projectAbbreviation.trim() ? projectAbbreviation.trim() : null,
          subject_prefix: isProject && subjectPrefix.trim() ? subjectPrefix.trimStart() : null,
          ai_prompt: aiPrompt || undefined,
        })
        // Sync project-derived rules for existing labels.
        // F-07 : skip si le load des règles a échoué — déduper contre une
        // liste vide mensongère recréerait des doublons à chaque save.
        if (rulesLoaded) {
          for (const rule of projectDerivedRules) {
            const exists = rules.some(r => r.condition_type === rule.condition_type && r.condition_value === rule.condition_value)
            if (!exists) {
              try {
                await createRule({ label_name: label!.name, condition_type: rule.condition_type, condition_value: rule.condition_value, priority: 50, confidence: 1.0 })
              } catch (err) {
                console.error('Failed to create project rule:', err)
                failedRules++
              }
            }
          }
        }
      } else {
        await createLabel({
          name: name.trim(),
          color,
          description,
          is_favorite: isFavorite,
          is_project: isProject,
          project_name: isProject && projectName.trim() ? projectName.trim() : null,
          project_number: isProject && projectNumber.trim() ? projectNumber.trim() : null,
          project_abbreviation: isProject && projectAbbreviation.trim() ? projectAbbreviation.trim() : null,
          subject_prefix: isProject && subjectPrefix.trim() ? subjectPrefix.trimStart() : null,
          ai_prompt: aiPrompt || undefined,
        })

        // Save manual + project-derived rules
        const allRulesToSave = [...pendingRules, ...projectDerivedRules]
        const seen = new Set<string>()
        for (const rule of allRulesToSave) {
          const key = `${rule.condition_type}:${rule.condition_value}`
          if (seen.has(key)) continue
          seen.add(key)
          try {
            await createRule({
              label_name: name.trim(),
              condition_type: rule.condition_type,
              condition_value: rule.condition_value,
              priority: 50,
              confidence: 1.0,
            })
          } catch (err) {
            console.error('Failed to create rule:', err)
            failedRules++
          }
        }
      }

      window.dispatchEvent(new CustomEvent('agentys:labels-updated'))
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: failedRules > 0
          ? {
              message: tCommon('toasts.label_saved_rules_failed', { count: failedRules }),
              type: 'warning',
            }
          : {
              message: tCommon(isEditing ? 'toasts.label_updated' : 'toasts.label_created'),
              type: 'success',
            },
      }))
      onSave()
    } catch (err) {
      console.error('Failed to save label:', err)
      setError(err instanceof Error ? err.message : tSettings('label_save_error'))
    } finally {
      setSaving(false)
    }
  }, [name, color, description, isFavorite, isProject, projectName, projectNumber, projectAbbreviation, subjectPrefix, aiPrompt, isEditing, label, onSave, pendingRules, projectDerivedRules, rules, rulesLoaded])

  const handleDelete = useCallback(async () => {
    if (!isEditing || !label) return
    if (!confirm(tSettings('label_delete_confirm', { name: getLabelDisplayName(label.name) }))) return

    try {
      setDeleting(true)
      setError(null)
      await deleteLabel(label.name)
      onSave()
    } catch (err) {
      console.error('Failed to delete label:', err)
      setError(err instanceof Error ? err.message : tSettings('label_delete_error'))
    } finally {
      setDeleting(false)
    }
  }, [isEditing, label, onSave])

  const handleAddRule = useCallback(async () => {
    if (!newRule.condition_value.trim()) {
      setError(tSettings('label_condition_required'))
      return
    }

    if (!isEditing) {
      // New label: store rule locally, will be saved with the label
      setError(null)
      setPendingRules(prev => [...prev, {
        condition_type: newRule.condition_type,
        condition_value: newRule.condition_value.trim(),
      }])
      setNewRule({ condition_type: 'sender', condition_value: '' })
      setActiveFilter(null)
      return
    }

    try {
      setError(null)
      const payload: CreateRulePayload = {
        label_name: label!.name,
        condition_type: newRule.condition_type,
        condition_value: newRule.condition_value.trim(),
        priority: 50,
        confidence: 1.0,
      }

      const response = await createRule(payload)
      setRules(prev => [...prev, response.rule])
      setNewRule({ condition_type: 'sender', condition_value: '' })
      setActiveFilter(null)
    } catch (err) {
      console.error('Failed to create rule:', err)
      setError(err instanceof Error ? err.message : tErrors('rule_create_error'))
    }
  }, [newRule, isEditing, label])

  // Audit Cluster D (2026-05-17) F-07 / #330: a failure here used to log
  // to console only. The rule stayed visible (since setRules runs after
  // the await) but the user got no feedback — they thought the button
  // bugged. Surface via toast.
  const runDeleteRule = useOptimisticMutation<void>({
    scope: 'label-editor-delete-rule',
    i18nKey: 'toasts.learning_delete_failed',
  })
  const handleDeleteRule = useCallback(async (ruleId: string) => {
    await runDeleteRule(async () => {
      await deleteRule(ruleId)
      setRules(prev => prev.filter(r => r.rule_id !== ruleId))
    })
  }, [runDeleteRule])

  const handleFilterClick = (type: RuleConditionType) => {
    if (activeFilter === type) {
      setActiveFilter(null)
    } else {
      setActiveFilter(type)
      setNewRule(prev => ({ ...prev, condition_type: type }))
    }
  }

  if (!isOpen) return null

  return (
    <>
    <div className="label-editor-overlay" onClick={onClose}>
      <div
        className="label-editor-container"
        style={{ '--le-accent': color } as React.CSSProperties}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="label-editor-panels">
          {/* ============ LEFT PANEL ============ */}
          <div className="label-editor-left">
            <div className="label-editor-left-header">
              <button className="label-editor-back" onClick={onClose}>
                <ChevronLeftIcon size={20} />
              </button>
              <span className="label-editor-left-title" role="heading" aria-level={2}>
                {isEditing ? tSettings('label_edit') : tSettings('label_new')}
              </span>
              {name.trim() && (
                <span className="label-editor-live-badge" style={{ background: color, color: '#fff' }}>
                  {name.trim()}
                </span>
              )}
              <button className="label-editor-close" onClick={onClose} aria-label={tSettings('label_close')}>
                <CloseIcon size={20} />
              </button>
            </div>

            <div className="label-editor-left-content">
              {/* Label Name + live preview */}
              <div className="label-editor-field">
                <label htmlFor="label-name">{tSettings('label_name')}</label>
                <div className="label-editor-name-row">
                  <input
                    id="label-name"
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={tSettings('label_name_placeholder')}
                    disabled={isEditing}
                    maxLength={50}
                    aria-describedby={error ? "label-editor-error" : undefined}
                    aria-invalid={!!error && !name.trim()}
                  />
                </div>
              </div>

              {/* Toggles — just below name */}
              <div className="label-editor-toggles-row">
                <label className="label-editor-toggle-label">
                  <span className="le-toggle">
                    <input
                      type="checkbox"
                      checked={isFavorite}
                      onChange={(e) => setIsFavorite(e.target.checked)}
                    />
                    <span className="le-toggle-track"><span className="le-toggle-thumb" /></span>
                  </span>
                  <span>{tSettings('label_navbar')}</span>
                </label>
                <label className="label-editor-toggle-label">
                  <span className="le-toggle">
                    <input
                      type="checkbox"
                      checked={isProject}
                      onChange={(e) => {
                        setIsProject(e.target.checked)
                        if (e.target.checked && !projectName.trim()) {
                          setProjectName(name.trim())
                        }
                      }}
                    />
                    <span className="le-toggle-track"><span className="le-toggle-thumb" /></span>
                  </span>
                  <span>{tSettings('label_project')}</span>
                </label>
              </div>

              {/* Project fields — visible when isProject */}
              {isProject && (
                <div className="label-editor-project-fields">
                  <div className="label-editor-field">
                    <label htmlFor="project-name">{tSettings('label_project_name')}</label>
                    <input
                      id="project-name"
                      type="text"
                      value={projectName}
                      onChange={(e) => setProjectName(e.target.value)}
                      placeholder={tSettings('label_project_name_placeholder')}
                      maxLength={100}
                    />
                  </div>
                  <div className="label-editor-field">
                    <label htmlFor="project-number">{tSettings('label_project_number')}</label>
                    <input
                      id="project-number"
                      type="text"
                      value={projectNumber}
                      onChange={(e) => setProjectNumber(e.target.value)}
                      placeholder={tSettings('label_project_number_placeholder')}
                      maxLength={50}
                    />
                  </div>
                  <div className="label-editor-field">
                    <label htmlFor="project-abbreviation">{tSettings('label_abbreviation')}</label>
                    <input
                      id="project-abbreviation"
                      type="text"
                      value={projectAbbreviation}
                      onChange={(e) => setProjectAbbreviation(e.target.value)}
                      placeholder={tSettings('label_abbreviation_placeholder')}
                      maxLength={20}
                    />
                  </div>
                  <div className="label-editor-field">
                    <label htmlFor="subject-prefix">{tSettings('label_subject_prefix')}</label>
                    <input
                      id="subject-prefix"
                      type="text"
                      value={subjectPrefix}
                      onChange={(e) => setSubjectPrefix(e.target.value)}
                      placeholder={tSettings('label_subject_prefix_placeholder')}
                      maxLength={80}
                    />
                  </div>

                  {/* Groupes de contacts liés — visible uniquement en édition */}
                  {isEditing && (
                    <div className="label-editor-field">
                      <label>{tSettings('label_linked_groups')}</label>
                      {linkedGroups.length > 0 && (
                        <div className="le-groups-list">
                          {linkedGroups.map(g => {
                            const prefix = label ? label.name + ' - ' : ''
                            const shortName = prefix && g.name.startsWith(prefix) ? g.name.slice(prefix.length) : g.name
                            return (
                              <div key={g.id} className="le-group-card">
                                <span className="le-group-emoji">{g.emoji || '👥'}</span>
                                <div className="le-group-info">
                                  <span className="le-group-name">{shortName}</span>
                                  <span className="le-group-members">
                                    {g.members.slice(0, 3).map(m => m.name || m.email.split('@')[0]).join(', ')}
                                    {g.members.length > 3 && ` +${g.members.length - 3}`}
                                  </span>
                                </div>
                                <span className="le-group-count">{g.members.length}</span>
                              </div>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* Color dots */}
              <div className="label-editor-field" ref={colorPickerRef}>
                <label>{tSettings('label_color')}</label>
                <div className="label-editor-colors">
                  {LABEL_COLORS.map((c) => (
                    <button
                      key={c}
                      type="button"
                      className={`label-editor-color ${color === c ? 'selected' : ''}`}
                      style={{ background: c }}
                      onClick={() => {
                        setColor(c)
                        setShowExtendedPicker(false)
                      }}
                      aria-label={tSettings('label_color_aria', { color: c })}
                    />
                  ))}
                  <button
                    type="button"
                    className={`label-editor-color label-editor-color-custom ${isCustomColor || showExtendedPicker ? 'selected' : ''}`}
                    style={{ '--swatch-bg': isCustomColor ? color : undefined } as React.CSSProperties}
                    onClick={() => setShowExtendedPicker(!showExtendedPicker)}
                    aria-label={tSettings('custom_color')}
                    title={tSettings('custom_color')}
                  >
                    {!isCustomColor && (
                      <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="10" />
                        <line x1="12" y1="8" x2="12" y2="16" />
                        <line x1="8" y1="12" x2="16" y2="12" />
                      </svg>
                    )}
                  </button>
                </div>

                {/* Extended color picker */}
                {showExtendedPicker && (
                  <div className="label-editor-extended-picker">
                    <div className="label-editor-extended-grid">
                      {EXTENDED_PALETTE.map((c) => (
                        <button
                          key={c}
                          type="button"
                          className={`label-editor-extended-swatch ${color === c ? 'selected' : ''}`}
                          style={{ background: c }}
                          onClick={() => setColor(c)}
                          aria-label={tSettings('label_color_aria', { color: c })}
                        />
                      ))}
                    </div>
                    <div className="label-editor-hue-row">
                      <input
                        type="range"
                        min="0"
                        max="360"
                        value={hueValue}
                        className="label-editor-hue-slider"
                        style={{ '--hue-thumb-color': hslToHex(hueValue, 0.7, 0.5) } as React.CSSProperties}
                        onChange={(e) => {
                          const h = Number(e.target.value)
                          setHueValue(h)
                          setColor(hslToHex(h, 0.7, 0.5))
                        }}
                        aria-label={tSettings('label_hue')}
                      />
                    </div>
                    <div className="label-editor-hex-row">
                      <span className="label-editor-hex-preview" style={{ background: color }} />
                      <input
                        type="text"
                        className="label-editor-hex-input"
                        value={hexInput}
                        onChange={(e) => {
                          const val = e.target.value
                          setHexInput(val)
                          const normalized = val.startsWith('#') ? val : '#' + val
                          if (/^#[0-9a-fA-F]{6}$/.test(normalized)) {
                            setColor(normalized.toLowerCase())
                          }
                        }}
                        maxLength={7}
                        placeholder="#000000"
                        spellCheck={false}
                      />
                    </div>
                  </div>
                )}
              </div>

              {/* Filter buttons */}
              <div className="label-editor-field">
                <label>{tSettings('label_filter_rules')}</label>
                <div className="label-editor-filters">
                  <button
                    className={`label-editor-filter-btn ${activeFilter === 'sender' ? 'active' : ''}`}
                    onClick={() => handleFilterClick('sender')}
                  >
                    {tCommon('sender')}
                  </button>
                  <button
                    className={`label-editor-filter-btn ${activeFilter === 'subject' ? 'active' : ''}`}
                    onClick={() => handleFilterClick('subject')}
                  >
                    {tSettings('label_subject')}
                  </button>
                  <button
                    className={`label-editor-filter-btn ${activeFilter === 'body' ? 'active' : ''}`}
                    onClick={() => handleFilterClick('body')}
                  >
                    {tSettings('label_body')}
                  </button>
                </div>
              </div>

              {/* Inline rule input when a filter is active */}
              {activeFilter && (
                <div className="label-editor-rule-inline">
                  <input
                    type="text"
                    value={newRule.condition_value}
                    onChange={(e) => setNewRule(prev => ({ ...prev, condition_value: e.target.value }))}
                    placeholder={
                      activeFilter === 'sender' ? 'email@example.com'
                        : activeFilter === 'body' ? tSettings('keyword_body_placeholder')
                        : tSettings('keyword_subject_placeholder')
                    }
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        handleAddRule()
                      }
                      if (e.key === 'Escape') {
                        setActiveFilter(null)
                      }
                    }}
                    autoFocus
                  />
                  <button
                    className="label-editor-rule-inline-add"
                    onClick={handleAddRule}
                    disabled={!newRule.condition_value.trim()}
                  >
                    {tSettings('label_add_rule')}
                  </button>
                </div>
              )}

              {/* Active rules list */}
              {(rules.length > 0 || pendingRules.length > 0 || projectDerivedRules.length > 0) && (
                <ul className="label-editor-rules-list">
                  {rules.map((rule) => (
                    <li key={rule.rule_id} className="label-editor-rule-item">
                      <div className="label-editor-rule-info">
                        <span className="label-editor-rule-type">
                          {rule.condition_type === 'sender' && tCommon('sender')}
                          {rule.condition_type === 'subject' && tSettings('label_subject')}
                          {rule.condition_type === 'body' && tSettings('label_body')}
                          {rule.condition_type === 'recipient' && tSettings('label_recipient')}
                          {rule.condition_type === 'cc' && tSettings('label_cc')}
                        </span>
                        <span className="label-editor-rule-value">{rule.condition_value}</span>
                        {rule.learned_from && (
                          <span className="label-editor-rule-learned">{tSettings('label_learned')}</span>
                        )}
                      </div>
                      <button
                        type="button"
                        className="label-editor-rule-delete icon-btn--delete"
                        onClick={() => handleDeleteRule(rule.rule_id)}
                        aria-label={tSettings('delete_rule')}
                      >
                        <CloseIcon size={14} />
                      </button>
                    </li>
                  ))}
                  {pendingRules.map((rule, idx) => (
                    <li key={`pending-${idx}`} className="label-editor-rule-item">
                      <div className="label-editor-rule-info">
                        <span className="label-editor-rule-type">
                          {rule.condition_type === 'sender' && tCommon('sender')}
                          {rule.condition_type === 'subject' && tSettings('label_subject')}
                          {rule.condition_type === 'body' && tSettings('label_body')}
                          {rule.condition_type === 'recipient' && tSettings('label_recipient')}
                        </span>
                        <span className="label-editor-rule-value">{rule.condition_value}</span>
                      </div>
                      <button
                        type="button"
                        className="label-editor-rule-delete icon-btn--delete"
                        onClick={() => setPendingRules(prev => prev.filter((_, i) => i !== idx))}
                        aria-label={tSettings('delete_rule')}
                      >
                        <CloseIcon size={14} />
                      </button>
                    </li>
                  ))}
                  {/* Derived project rules — deduplicated by value, with X to clear the source field */}
                  {Array.from(new Set(projectDerivedRules.map(r => r.condition_value)))
                    .filter(val => !rules.some(r => r.condition_value === val))
                    .map((val) => {
                      const types = new Set(projectDerivedRules.filter(r => r.condition_value === val).map(r => r.condition_type))
                      const typeLabel = types.has('subject') && types.has('body')
                        ? `${tSettings('label_subject')} + ${tSettings('label_body')}`
                        : types.has('subject') ? tSettings('label_subject') : tSettings('label_body')
                      return (
                    <li key={`proj-${val}`} className="label-editor-rule-item label-editor-rule-derived">
                      <div className="label-editor-rule-info">
                        <span className="label-editor-rule-type">{typeLabel}</span>
                        <span className="label-editor-rule-value">{val}</span>
                        <span className="label-editor-rule-tag">{tSettings('label_project_tag')}</span>
                      </div>
                      <button
                        type="button"
                        className="label-editor-rule-delete icon-btn--delete"
                        onClick={() => {
                          if (val === projectName.trim()) setProjectName('')
                          if (val === projectNumber.trim()) setProjectNumber('')
                          if (val === projectAbbreviation.trim()) setProjectAbbreviation('')
                        }}
                        aria-label={tSettings('delete_rule')}
                      >
                        <CloseIcon size={14} />
                      </button>
                    </li>
                  )})}
                </ul>
              )}



              {loadingRules && (
                <div className="label-editor-rules-loading">{tSettings('label_loading_rules')}</div>
              )}
            </div>

            {/* Footer */}
            <div className="label-editor-left-footer">
              {error && (
                <div id="label-editor-error" className="label-editor-error" role="alert">{error}</div>
              )}

              <div className="label-editor-footer-actions">
                {isEditing && !label?.is_default && (
                  <button
                    className="label-editor-btn label-editor-btn-delete"
                    onClick={handleDelete}
                    disabled={deleting}
                    aria-label={tSettings('label_delete')}
                    title={tSettings('label_delete')}
                  >
                    <TrashIcon size={16} />
                  </button>
                )}
                <div className="label-editor-footer-right">
                  <button
                    className="label-editor-btn label-editor-btn-cancel"
                    onClick={onClose}
                    disabled={saving}
                  >
                    {tCommon('cancel')}
                  </button>
                  <button
                    className="label-editor-btn label-editor-btn-save"
                    onClick={handleSave}
                    disabled={saving || !name.trim()}
                  >
                    {saving ? tSettings('label_saving') : tSettings('label_save')}
                  </button>
                </div>
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
    </>
  )
}
