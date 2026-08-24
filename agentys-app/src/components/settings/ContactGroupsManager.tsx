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

import { useState, useCallback, useEffect, useRef, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { AlertCircle, Video, Tag } from 'lucide-react'
import { ChevronLeftIcon, CloseIcon, TrashIcon, CheckIcon, SearchIcon } from '../icons/ActionIcons'
import { useContactGroups, type ContactGroupMember } from '../../hooks/useContactGroups'
import { Avatar } from '../Avatar'
import { GhostAddRow } from '../ui/GhostAddRow'
import { ContactAutocomplete } from '../compose/ContactAutocomplete'
import { fetchLabels } from '../../api/labels'
import type { Label } from '../../types/labels'
import './ContactGroupsManager.css'

interface ContactGroupsManagerProps {
  onClose: () => void
  /** When set, only shows/creates groups linked to this project label */
  projectLabelName?: string
}

// Quick-create suggestions for project sub-groups. `key` is the French
// fallback label; `labelKey` (settings namespace) is resolved at render so
// the chips — and the group name created from them — follow the UI language.
const SUB_GROUP_TEMPLATES: { key: string; labelKey: string; emoji: string }[] = [
  { key: 'Ingénierie', labelKey: 'contact_groups_template_engineering', emoji: '🔧' },
  { key: 'Gestion', labelKey: 'contact_groups_template_management', emoji: '📋' },
  { key: 'Interne', labelKey: 'contact_groups_template_internal', emoji: '🏢' },
  { key: 'Externe', labelKey: 'contact_groups_template_external', emoji: '🌐' },
  { key: 'Direction', labelKey: 'contact_groups_template_leadership', emoji: '👔' },
  { key: 'Partenaires', labelKey: 'contact_groups_template_partners', emoji: '🤝' },
]

export function ContactGroupsManager({ onClose, projectLabelName }: ContactGroupsManagerProps) {
  const { groups: allGroups, loading, error: loadError, createGroup, updateGroup, deleteGroup } = useContactGroups()
  const { t } = useTranslation('common')
  const { t: tSettings } = useTranslation('settings')
  const overlayRef = useRef<HTMLDivElement>(null)

  const scopedGroups = projectLabelName
    ? allGroups.filter(g => g.label_name === projectLabelName)
    : allGroups

  const [searchQuery, setSearchQuery] = useState('')

  const groups = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    if (!q) return scopedGroups
    return scopedGroups.filter(g => {
      if (g.name.toLowerCase().includes(q)) return true
      if ((g.label_name || '').toLowerCase().includes(q)) return true
      return g.members.some(
        m => m.name.toLowerCase().includes(q) || m.email.toLowerCase().includes(q),
      )
    })
  }, [scopedGroups, searchQuery])

  const [editingId, setEditingId] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [formName, setFormName] = useState('')
  const [formEmoji, setFormEmoji] = useState('')
  const [formLabelName, setFormLabelName] = useState<string>('')
  const [formMembers, setFormMembers] = useState<ContactGroupMember[]>([])
  const [formVirtualMeeting, setFormVirtualMeeting] = useState(false)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [projectLabels, setProjectLabels] = useState<Label[]>([])
  const [showLabelPicker, setShowLabelPicker] = useState(false)
  const labelPickerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (projectLabelName !== undefined) return
    let cancelled = false
    fetchLabels().then(res => {
      if (!cancelled) setProjectLabels(res.labels.filter(l => l.is_project === true))
    }).catch(err => console.warn('[ContactGroupsManager] project-label fetch failed:', err))
    return () => { cancelled = true }
  }, [projectLabelName])

  // Close label picker on outside click
  useEffect(() => {
    if (!showLabelPicker) return
    const handler = (e: MouseEvent) => {
      if (!labelPickerRef.current?.contains(e.target as Node)) {
        setShowLabelPicker(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [showLabelPicker])

  const resetForm = useCallback(() => {
    setFormName('')
    setFormEmoji('')
    setFormLabelName('')
    setFormMembers([])
    setFormVirtualMeeting(false)
    setEditingId(null)
    setShowForm(false)
    setError('')
  }, [])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        // Escape on the open project-label dropdown dismisses only the
        // dropdown — it must NOT fall through to resetForm(), which would wipe
        // the in-progress name/members/label. Same class as the LocalePickers
        // fix: a nested popup must not let Escape reach its host's close path.
        if (showLabelPicker) {
          e.preventDefault()
          e.stopPropagation()
          setShowLabelPicker(false)
          return
        }
        if (showForm) resetForm()
        else onClose()
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [showForm, showLabelPicker, onClose, resetForm])

  const handleEditGroup = useCallback((group: typeof groups[0]) => {
    setFormName(group.name)
    setFormEmoji(group.emoji || '')
    setFormLabelName(group.label_name || '')
    setFormMembers([...group.members])
    setFormVirtualMeeting(Boolean(group.virtual_meeting))
    setEditingId(group.id)
    setShowForm(true)
    setError('')
  }, [])

  // ContactAutocomplete drives the member field. We keep {name, email} locally
  // because the backend expects members: {name, email}[] — not just emails.
  // membersValue is encoded as "Name <email>" (fallback: plain email) so names
  // persist through chip rendering when editing a saved group. Parent parses
  // the value back on every onChange.
  const membersValue = useMemo(
    () => formMembers
      .map(m => (m.name ? `${m.name} <${m.email}>` : m.email))
      .join(', '),
    [formMembers],
  )

  const parseChipToPair = (chip: string): { name: string; email: string } | null => {
    const trimmed = chip.trim()
    if (!trimmed) return null
    const match = trimmed.match(/^(.+?)\s*<(.+?)>$/)
    const name = match ? match[1].trim() : ''
    const email = (match ? match[2].trim() : trimmed).toLowerCase()
    if (!email.includes('@')) return null
    return { name, email }
  }

  const handleMembersChange = useCallback((newValue: string) => {
    const pairs = newValue
      .split(',')
      .map(parseChipToPair)
      .filter((p): p is { name: string; email: string } => p !== null)
    setFormMembers(prev => {
      const byEmail = new Map(prev.map(m => [m.email.toLowerCase(), m]))
      const seen = new Set<string>()
      const next: ContactGroupMember[] = []
      for (const p of pairs) {
        if (seen.has(p.email)) continue
        seen.add(p.email)
        const existing = byEmail.get(p.email)
        next.push(existing ?? { name: p.name, email: p.email })
      }
      return next
    })
    if (error) setError('')
  }, [error])

  const handleContactSelected = useCallback((contact: { name: string; email: string }) => {
    if (!contact.email) return
    const email = contact.email.toLowerCase()
    setFormMembers(prev => {
      const idx = prev.findIndex(m => m.email.toLowerCase() === email)
      if (idx === -1) {
        // onChange hasn't fired yet — append so we don't lose the name
        return [...prev, { name: contact.name || '', email }]
      }
      if (contact.name && !prev[idx].name) {
        const next = [...prev]
        next[idx] = { ...next[idx], name: contact.name }
        return next
      }
      return prev
    })
  }, [])

  const handleSave = useCallback(async () => {
    if (saving) return
    if (!formName.trim()) {
      setError(t('groups_name_required'))
      return
    }
    if (formMembers.length === 0) {
      setError(t('groups_min_members'))
      return
    }
    const effectiveLabelName = projectLabelName !== undefined
      ? projectLabelName
      : (formLabelName || null)

    setSaving(true)
    try {
      if (editingId) {
        await updateGroup(editingId, {
          name: formName.trim(),
          emoji: formEmoji.trim() || undefined,
          members: formMembers,
          label_name: effectiveLabelName,
          virtual_meeting: formVirtualMeeting,
        })
      } else {
        await createGroup({
          name: formName.trim(),
          emoji: formEmoji.trim() || undefined,
          members: formMembers,
          label_name: effectiveLabelName,
          virtual_meeting: formVirtualMeeting,
        })
      }
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: {
          message: t(editingId ? 'toasts.group_updated' : 'toasts.group_created'),
          type: 'success',
        },
      }))
      resetForm()
    } catch (err: unknown) {
      setError((err as Error)?.message || t('groups_save_error'))
    } finally {
      setSaving(false)
    }
  }, [saving, formName, formEmoji, formMembers, formLabelName, formVirtualMeeting, editingId, createGroup, updateGroup, resetForm, projectLabelName, t])

  const handleDelete = useCallback(async (id: string) => {
    try {
      await deleteGroup(id)
      setConfirmDeleteId(null)
    } catch (err: unknown) {
      setError((err as Error)?.message || t('groups_delete_error'))
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: {
          message: (err as Error)?.message || t('groups_delete_error'),
          type: 'error',
        },
      }))
    }
  }, [deleteGroup, t])

  const handleOverlayMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.target === overlayRef.current) onClose()
  }, [onClose])

  const headerTitle = showForm
    ? (editingId ? t('groups_edit_group') : t('groups_new_group'))
    : (projectLabelName ? t('groups_for_label', { label: projectLabelName }) : t('groups_contact_groups'))

  return createPortal(
    <div className="cg-overlay" ref={overlayRef} onMouseDown={handleOverlayMouseDown}>
      <div className="cg-modal" role="dialog" aria-modal="true">
        <span className="cg-modal-glow" aria-hidden="true" />
        {/* Header */}
        <div className="cg-modal-header">
          <div className="cg-header-left">
            <button
              className="cg-back-btn"
              onClick={showForm ? resetForm : onClose}
              aria-label={t('back')}
              title={t('back')}
            >
              <ChevronLeftIcon />
            </button>
            <h2 className="cg-modal-title">{headerTitle}</h2>
          </div>
          <button className="cg-close-btn" onClick={onClose} aria-label={t('close')}>
            <CloseIcon />
          </button>
        </div>

        {/* Body */}
        <div className="cg-modal-body">
          {!showForm ? (
            <>
              {/* F-10 (audit 2026-06-11) : le cache localStorage masquait un
                  échec de chargement — la liste affichée peut être périmée. */}
              {loadError && (
                <p className="cg-form-error" role="alert">
                  <AlertCircle size={15} strokeWidth={2} />
                  {t('groups_load_error')}
                </p>
              )}

              {scopedGroups.length > 3 && (
                <div className="cg-search">
                  <SearchIcon size={15} className="cg-search-icon" />
                  <input
                    type="search"
                    className="cg-search-input"
                    placeholder={t('groups_search_placeholder')}
                    value={searchQuery}
                    onChange={e => setSearchQuery(e.target.value)}
                  />
                  {searchQuery && (
                    <button
                      type="button"
                      className="cg-search-clear"
                      onClick={() => setSearchQuery('')}
                      aria-label={t('close')}
                    >
                      <CloseIcon size={13} />
                    </button>
                  )}
                </div>
              )}

              {projectLabelName && (
                <div className="cg-templates">
                  <p className="cg-templates-label">{t('groups_quick_templates')}</p>
                  <div className="cg-templates-row">
                    {SUB_GROUP_TEMPLATES.map(tpl => {
                      const label = tSettings(tpl.labelKey, tpl.key)
                      const fullName = `${projectLabelName} - ${label}`
                      const exists = groups.some(g => g.name.toLowerCase() === fullName.toLowerCase())
                      return (
                        <button
                          key={tpl.key}
                          className={`cg-template-chip${exists ? ' cg-template-chip--done' : ''}`}
                          disabled={exists}
                          onClick={() => {
                            setFormName(fullName)
                            setFormEmoji(tpl.emoji)
                            setShowForm(true)
                          }}
                        >
                          <span className="cg-template-emoji">{tpl.emoji}</span>
                          {label}
                          {exists && <CheckIcon className="cg-template-check" size={12} />}
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}

              <div className="cg-list">
                <GhostAddRow
                  label={t('groups_new_group')}
                  onClick={() => {
                    setShowForm(true)
                    if (projectLabelName) setFormName(`${projectLabelName} - `)
                  }}
                />
                {groups.map((group) => {
                  return (
                    <div
                      key={group.id}
                      className="cg-item"
                      onClick={() => handleEditGroup(group)}
                    >
                      <div className="cg-item-body">
                        <div className="cg-item-title-row">
                          <span className="cg-item-name">{group.name}</span>
                          {group.virtual_meeting && (
                            <span className="cg-item-flag" title={t('groups_virtual_meeting')}>
                              <Video size={11} strokeWidth={2.25} />
                            </span>
                          )}
                        </div>
                        <div className="cg-item-meta">
                          <span className="cg-item-count">
                            {t('groups_member', { count: group.members.length })}
                          </span>
                          {group.label_name && (
                            <span className="cg-item-project" title={group.label_name}>
                              <Tag size={10} strokeWidth={2.25} />
                              {group.label_name}
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="cg-avatars" aria-hidden="true">
                        {group.members.length > 5 && (
                          <span
                            className="cg-avatar-overflow"
                            title={group.members.slice(5).map(m => m.name || m.email).join(', ')}
                          >
                            +{group.members.length - 5}
                          </span>
                        )}
                        {group.members.slice(0, 5).map(m => (
                          <Avatar
                            key={m.email}
                            name={m.name || null}
                            email={m.email}
                            size="md"
                          />
                        ))}
                      </div>
                      <div className="cg-item-actions">
                        {confirmDeleteId === group.id ? (
                          <button
                            className="cg-action-btn cg-action-btn--danger-confirm"
                            onClick={e => { e.stopPropagation(); handleDelete(group.id) }}
                          >
                            {t('groups_confirm_delete')}
                          </button>
                        ) : (
                          <>
                            <button
                              className="cg-action-btn cg-action-btn--danger"
                              onClick={e => { e.stopPropagation(); setConfirmDeleteId(group.id) }}
                              aria-label={t('delete')}
                              title={t('delete')}
                            >
                              <TrashIcon size={14} />
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>

              {loading && groups.length === 0 && (
                <div className="cg-empty">
                  <p className="cg-empty-text">{t('loading')}</p>
                </div>
              )}

              {!loading && scopedGroups.length > 0 && groups.length === 0 && (
                <div className="cg-empty">
                  <p className="cg-empty-text">{t('groups_no_results')}</p>
                </div>
              )}
            </>
          ) : (
            <div className="cg-form">
              <div className="cg-form-section">
                <label className="cg-form-label" htmlFor="cg-form-name-input">
                  {t('groups_group_name')}
                </label>
                <input
                  id="cg-form-name-input"
                  type="text"
                  className="cg-form-input"
                  placeholder={t('groups_name_placeholder')}
                  value={formName}
                  onChange={e => setFormName(e.target.value)}
                  autoFocus
                />
              </div>

              {projectLabelName === undefined && (
                <div className="cg-form-section">
                  <span className="cg-form-label">{t('groups_label_project')}</span>
                  <div className="cg-project-chips" ref={labelPickerRef}>
                    {/* Trigger — opens the dropdown */}
                    <button
                      type="button"
                      className={`cg-project-chip cg-project-chip--header${showLabelPicker ? ' is-open' : ''}`}
                      onClick={() => setShowLabelPicker(v => !v)}
                      aria-expanded={showLabelPicker}
                      aria-haspopup="listbox"
                    >
                      <Tag size={13} strokeWidth={2} />
                      <span>
                        {formLabelName
                          ? projectLabels.find(l => l.name === formLabelName)?.name ?? t('groups_no_label')
                          : t('groups_no_label')}
                      </span>
                    </button>

                    {/* Dropdown */}
                    {showLabelPicker && (
                      <div className="cg-label-dropdown" role="listbox">
                        <button
                          type="button"
                          role="option"
                          aria-selected={formLabelName === ''}
                          className={`cg-label-option${formLabelName === '' ? ' is-selected' : ''}`}
                          onClick={() => { setFormLabelName(''); setShowLabelPicker(false) }}
                        >
                          <span className="cg-label-option-dot cg-label-option-dot--none" />
                          <span className="cg-label-option-name">{t('groups_no_label')}</span>
                          {formLabelName === '' && (
                            <CheckIcon size={13} className="cg-label-option-check" />
                          )}
                        </button>
                        {projectLabels.map(l => {
                          const isSelected = formLabelName === l.name
                          return (
                            <button
                              key={l.name}
                              type="button"
                              role="option"
                              aria-selected={isSelected}
                              className={`cg-label-option${isSelected ? ' is-selected' : ''}`}
                              onClick={() => { setFormLabelName(l.name); setShowLabelPicker(false) }}
                            >
                              <span className="cg-label-option-dot" style={{ background: l.color }} />
                              <span className="cg-label-option-name">{l.name}</span>
                              {isSelected && (
                                <CheckIcon size={13} className="cg-label-option-check" />
                              )}
                            </button>
                          )
                        })}
                      </div>
                    )}
                  </div>
                </div>
              )}

              <div className="cg-form-card">
                <div className="cg-form-card-header">
                  <span className="cg-form-card-label">{t('members')}</span>
                </div>
                <ContactAutocomplete
                  multi
                  includeAllContacts
                  includeSelf
                  value={membersValue}
                  onChange={handleMembersChange}
                  onContactSelect={handleContactSelected}
                  placeholder={t('groups_member_placeholder')}
                  className="cg-form-member-autocomplete"
                />
              </div>

              <label className="cg-toggle">
                <span className="cg-toggle-icon">
                  <Video size={15} strokeWidth={2} />
                </span>
                <div className="cg-toggle-body">
                  <span className="cg-toggle-label">{t('groups_virtual_meeting')}</span>
                  <span className="cg-toggle-hint">{t('groups_virtual_meeting_hint')}</span>
                </div>
                <input
                  type="checkbox"
                  checked={formVirtualMeeting}
                  onChange={(e) => setFormVirtualMeeting(e.target.checked)}
                  aria-label={t('groups_virtual_meeting')}
                />
                <span className="cg-switch" />
              </label>

              {error && (
                <p className="cg-form-error">
                  <AlertCircle size={15} strokeWidth={2} />
                  {error}
                </p>
              )}
            </div>
          )}
        </div>

        {/* Footer (form only) */}
        {showForm && (
          <div className="cg-modal-footer">
            <button className="cg-footer-btn cg-footer-btn--cancel" onClick={resetForm} disabled={saving}>
              {t('cancel')}
            </button>
            <button className="cg-footer-btn cg-footer-btn--save" onClick={handleSave} disabled={saving}>
              {editingId ? t('update') : t('groups_create_group')}
            </button>
          </div>
        )}
      </div>
    </div>,
    document.body
  )
}
