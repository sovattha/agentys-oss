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

/**
 * QuickStepsManager — Settings → "Quick Steps" section.
 *
 * Manages user-defined action chains (archive, label, forward, reply with
 * template, ...) bound to a hotkey. Pure CRUD UI; execution happens in
 * QuickStepsBar.tsx (email view) and the dynamic shortcut dispatcher in
 * App.tsx. No LLM calls anywhere.
 */
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import ConfirmationDialog from '../ConfirmationDialog'
import { ContactAutocomplete } from '../compose/ContactAutocomplete'
import { RichTextEditor, type PlaceholderSuggestion } from '../ui/RichTextEditor'
import { SignatureFooter } from '../ui/SignatureFooter'
import { buildTokenChipHtml } from '../../utils/placeholderChips'
import { Button } from '../ui/button'
import {
  CheckIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  ChevronUpIcon,
  CloseIcon,
  PlusIcon,
  TrashIcon,
} from '../icons/ActionIcons'
import {
  createQuickStep,
  deleteQuickStep,
  listQuickSteps,
  reorderQuickSteps,
  updateQuickStep,
} from '../../services/api'
import {
  QUICK_STEP_TEMPLATE_VARIABLES,
  defaultTriggerValue,
  makeAction,
  normalizeQuickStep,
  type ForwardPayload,
  type MarkReadPayload,
  type QuickStep,
  type QuickStepAction,
  type QuickStepActionType,
  type ReplyTemplatePayload,
  type RsvpMeetingPayload,
  type CreateSnoozedFollowupDraftPayload,
  type MarkWithEmojiPayload,
  type ApplyLabelPayload,
  type CreateReminderPayload,
  type CreateCalendarEventPayload,
  type QuickStepEmoji,
  QUICK_STEP_EMOJI_WHITELIST,
  type TriggerCondition,
  type TriggerConditionType,
  type TriggerMatchMode,
  TRIGGER_MATCH_MODES,
  triggerTypeHasMatchMode,
  defaultTriggerMatchMode,
} from '../../types/quickStep'
import { fetchLabels } from '../../api/labels'
import { getLabelDisplayName, LABEL_COLORS } from '../../types/labels'
import { useContactGroups } from '../../hooks/useContactGroups'
import './QuickStepsManager.css'

// --------------------------------------------------------------------------- //
// Seeded starter rules — locale overlay
// --------------------------------------------------------------------------- //
// Starter rules (app/quicksteps/defaults.py) are stored under their canonical
// ENGLISH name + description. That English name is also the matching key for
// the Settings discovery surface (Settings.tsx) and the deterministic uuid5
// seed id, so it must stay English in storage. To avoid a half-English UI on
// FR/ES inboxes we overlay a locale-aware copy at RENDER time, keyed off that
// English name. Shared by QuickStepCard (list + discovery) and QuickStepEditor
// so the two surfaces can't drift. Keep in sync with the rule names in
// defaults.py and the `quicksteps_seeded_*` keys in locales/*/settings.json.
const SEEDED_NAME_TO_KEY: Record<string, string> = {
  'archive after reply': 'seeded_archive_after_reply',
  'follow-up new thread': 'seeded_followup_new_thread',
  'follow-up existing thread': 'seeded_followup_existing_thread',
  'archive info emails once read': 'seeded_archive_info_emails_once_read',
  'accept meeting invitation': 'seeded_accept_meeting_invitation',
  'reply, forward and archive': 'seeded_reply_forward_and_archive',
}

/**
 * i18n key suffix for a seeded starter rule, matched on its canonical
 * (English) name. Returns undefined for user-authored / renamed rules, which
 * fall through to their stored name + description.
 */
function seededStepKey(name: string | undefined | null): string | undefined {
  return SEEDED_NAME_TO_KEY[(name ?? '').trim().toLowerCase()]
}

// --------------------------------------------------------------------------- //
// Preview — mock substitution so users can verify the template looks right
// --------------------------------------------------------------------------- //

const PREVIEW_CTX: Record<string, string> = {
  'sender.firstname': 'Marie',
  'sender.lastname': 'Dupont',
  'sender.name': 'Marie Dupont',
  'sender.email': 'marie.dupont@exemple.com',
  'subject': 'Re: Suivi de dossier',
  'date': new Date().toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' }),
  'me.firstname': 'Vous',
  'me.name': 'Vous',
  'me.email': 'vous@exemple.com',
}

function renderPreview(html: string): string {
  return html.replace(/\{([a-zA-Z_]+(?:\.[a-zA-Z_]+)?)\}/g, (_m, key) =>
    PREVIEW_CTX[key] !== undefined
      ? `<span class="qs-preview-value">${PREVIEW_CTX[key]}</span>`
      : _m,
  )
}

// --------------------------------------------------------------------------- //
// Quick Start templates — opinionated starting points, not seeded defaults.
// --------------------------------------------------------------------------- //

interface QuickStartTemplate {
  key: string
  defaultName: string
  description: string
  build: () => Omit<QuickStep, 'id'>
}

function buildQuickStartTemplates(t: TFn): QuickStartTemplate[] {
  const replyForwardName = t('quicksteps_rail_reply_forward_name', {
    defaultValue: 'Répondre + Transférer',
  })
  const forwardArchiveName = t('quicksteps_rail_forward_archive_name', {
    defaultValue: 'Transférer + Archiver',
  })
  return [
    {
      key: 'reply_then_forward',
      defaultName: replyForwardName,
      description: t('quicksteps_rail_reply_forward_desc', {
        defaultValue: 'Envoie une réponse rapide puis transfère l\'email à un contact.',
      }),
      build: () => ({
        name: replyForwardName,
        icon: 'forward',
        shortcut: '1',
        enabled: true,
        confirmBeforeRun: true,
        autoEnabled: false,
        showAutoBadge: true,
        triggerOperator: 'AND' as const,
        triggers: [],
        firesOn: 'received' as const,
        actions: [
          {
            type: 'reply_template',
            payload: {
              // Localized at creation time (Quick Start = opinionated starting
              // point, NOT a seeded default — no discovery-match contract).
              // `{sender.firstname}` uses single braces: opaque to i18next
              // interpolation, resolved later by the Quick Step template engine.
              body: t('quicksteps_rail_reply_forward_body', {
                defaultValue: '<p>Bonjour {sender.firstname},</p><p>Bien reçu, merci.</p>',
              }),
              replyAll: false,
              includeQuoted: true,
            },
          },
          {
            type: 'forward',
            payload: { to: [] },
          },
        ],
      }),
    },
    {
      key: 'forward_archive',
      defaultName: forwardArchiveName,
      description: t('quicksteps_rail_forward_archive_desc', {
        defaultValue: 'Transfère à un destinataire fixe puis archive l\'original.',
      }),
      build: () => ({
        name: forwardArchiveName,
        icon: 'forward',
        shortcut: '2',
        enabled: true,
        confirmBeforeRun: true,
        autoEnabled: false,
        showAutoBadge: true,
        triggerOperator: 'AND' as const,
        triggers: [],
        firesOn: 'received' as const,
        actions: [
          {
            type: 'forward',
            payload: { to: [] },
          },
          { type: 'archive' },
        ],
      }),
    },
    {
      key: 'auto_spam_noise',
      defaultName: t('quicksteps_recipe_noise_name', { defaultValue: 'Auto-spam : bruit' }),
      description: t('quicksteps_recipe_noise_desc', {
        defaultValue: 'Déplace en spam tout email étiqueté « bruit ». Auto-déclenchement.',
      }),
      build: () => ({
        name: t('quicksteps_recipe_noise_name', { defaultValue: 'Auto-spam : bruit' }),
        icon: 'spam',
        shortcut: null,
        enabled: true,
        confirmBeforeRun: false,
        autoEnabled: true,
        showAutoBadge: true,
        triggerOperator: 'OR' as const,
        triggers: [{ type: 'has_label' as const, value: 'noise' }],
        firesOn: 'received' as const,
        actions: [{ type: 'move_to_spam' }],
      }),
    },
    {
      key: 'vip_triage',
      defaultName: t('quicksteps_recipe_vip_name', { defaultValue: 'Triage VIP' }),
      description: t('quicksteps_recipe_vip_desc', {
        defaultValue: 'Épingle et marque non lu les emails d\'un domaine VIP. Auto-déclenchement.',
      }),
      build: () => ({
        name: t('quicksteps_recipe_vip_name', { defaultValue: 'Triage VIP' }),
        icon: 'pin',
        shortcut: null,
        enabled: true,
        confirmBeforeRun: false,
        autoEnabled: true,
        showAutoBadge: true,
        triggerOperator: 'AND' as const,
        triggers: [{ type: 'sender_domain' as const, value: '' }],
        firesOn: 'received' as const,
        actions: [
          { type: 'pin' },
          { type: 'mark_read', payload: { value: false } },
        ],
      }),
    },
    {
      key: 'rsvp_archive',
      defaultName: t('quicksteps_recipe_rsvp_name', { defaultValue: 'Accepter + Archiver' }),
      description: t('quicksteps_recipe_rsvp_desc', {
        defaultValue: 'Réponds OUI à une invitation puis archive l\'email.',
      }),
      build: () => ({
        name: t('quicksteps_recipe_rsvp_name', { defaultValue: 'Accepter + Archiver' }),
        icon: 'rsvp_meeting',
        shortcut: null,
        enabled: true,
        confirmBeforeRun: true,
        autoEnabled: false,
        showAutoBadge: true,
        triggerOperator: 'AND' as const,
        triggers: [],
        firesOn: 'received' as const,
        actions: [
          {
            type: 'rsvp_meeting',
            payload: { response: 'accepted' as const },
          },
          { type: 'archive' },
        ],
      }),
    },
  ]
}

// --------------------------------------------------------------------------- //
// Top-level component
// --------------------------------------------------------------------------- //

interface QuickStepsManagerProps {
  onEditingChange?: (state: { title: string; onCancel: () => void } | null) => void
}

export function QuickStepsManager({ onEditingChange }: QuickStepsManagerProps = {}) {
  const { t } = useTranslation('settings')
  const quickStartTemplates = useMemo(() => buildQuickStartTemplates(t), [t])
  const [steps, setSteps] = useState<QuickStep[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<QuickStep | null>(null)
  // List filter — purely client-side, never persisted. "all" is the default;
  // the chip row hides itself entirely when the list has ≤ 1 step so the
  // header doesn't bloat for first-time users.
  const [filter, setFilter] = useState<'all' | 'auto' | 'manual' | 'disabled'>('all')

  // Drag-to-reorder state
  const dragIndexRef = useRef<number | null>(null)
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null)

  // Custom confirmation modal — replaces native window.confirm() so the
  // delete prompt matches the rest of the app.
  const [pendingDelete, setPendingDelete] = useState<{ id: string; name: string } | null>(null)

  useEffect(() => {
    if (!onEditingChange) return
    if (editing) {
      const title = editing.name
        || t('quicksteps_editor_new', { defaultValue: 'Nouvelle quick action' })
      onEditingChange({ title, onCancel: () => setEditing(null) })
    } else {
      onEditingChange(null)
    }
  }, [editing, onEditingChange, t])

  const reload = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listQuickSteps()
      // Backend degrades to {quick_steps: [], warning: 'transient_load_failure'}
      // with HTTP 200 when load_quick_steps raises (see app/api/quicksteps.py).
      // Treat that as an error — otherwise the user sees the Quick-Start
      // template empty-state and thinks their saved rules vanished.
      if (data.warning === 'transient_load_failure') {
        setSteps([])
        setError(t('quicksteps_load_transient', {
          defaultValue: 'Could not load your quick actions right now. Your saved rules are safe — please retry.',
        }))
        return
      }
      // Normalize incoming steps so we don't carry partial/legacy shapes
      // into the editor (which would crash on `triggers.length`, etc.).
      setSteps((data.quick_steps || []).map(normalizeQuickStep))
    } catch (err) {
      setError((err as Error).message || t('quicksteps_load_failed', {
        defaultValue: 'Failed to load quick actions',
      }))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    void reload()
  }, [reload])

  const startNew = () => {
    // Clear any stale list-load/save error so it doesn't bleed into the editor.
    setError(null)
    setEditing({
      id: crypto.randomUUID(),
      name: '',
      icon: null,
      shortcut: null,
      enabled: true,
      confirmBeforeRun: false,
      autoEnabled: false,
      showAutoBadge: true,
      triggerOperator: 'AND',
      triggers: [],
      actions: [makeAction('archive')],
      firesOn: 'received',
    })
  }

  const startFromTemplate = (template: QuickStartTemplate) => {
    setError(null)
    setEditing({ id: crypto.randomUUID(), ...template.build() })
  }

  const handleSave = async (draft: QuickStep) => {
    setError(null)
    try {
      const existing = steps.find(s => s.id === draft.id)
      const saved = existing
        ? await updateQuickStep(draft.id, draft)
        : await createQuickStep(draft)
      // Editing must NOT move the card — replace in place. Only brand-new
      // steps land at the bottom of the list. Drag-and-drop remains the
      // single mechanism for changing position.
      setSteps(prev => {
        const existingIdx = prev.findIndex(s => s.id === saved.id)
        if (existingIdx >= 0) {
          const next = prev.slice()
          next[existingIdx] = saved
          return next
        }
        return [...prev, saved]
      })
      setEditing(null)
      window.dispatchEvent(new CustomEvent('agentys:quicksteps-changed'))
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: { message: t('common:toasts.quickstep_saved'), type: 'success' },
      }))
    } catch (err) {
      setError((err as Error).message || t('quicksteps_save_failed', {
        defaultValue: 'Failed to save quick action',
      }))
    }
  }

  // Two-step delete: clicking the X queues the rule (modal opens via
  // `pendingDelete`); the confirm button triggers the actual API call.
  // Cancel just clears the queued rule.
  const requestDelete = (step: QuickStep) => {
    setPendingDelete({ id: step.id, name: (step.name ?? '').trim() })
  }

  const handleConfirmDelete = async () => {
    if (!pendingDelete) return
    const stepId = pendingDelete.id
    setPendingDelete(null)
    try {
      await deleteQuickStep(stepId)
      setSteps(prev => prev.filter(s => s.id !== stepId))
      if (editing?.id === stepId) setEditing(null)
      window.dispatchEvent(new CustomEvent('agentys:quicksteps-changed'))
    } catch (err) {
      setError((err as Error).message || t('quicksteps_delete_failed', {
        defaultValue: 'Failed to delete quick action',
      }))
    }
  }

  // Inline enable/disable from the card switch. Optimistic local update
  // first so the toggle feels instant; a PATCH error rolls it back.
  const handleToggleEnabled = async (stepId: string, next: boolean) => {
    const before = steps
    setSteps(prev => prev.map(s => (s.id === stepId ? { ...s, enabled: next } : s)))
    try {
      await updateQuickStep(stepId, { enabled: next })
      window.dispatchEvent(new CustomEvent('agentys:quicksteps-changed'))
    } catch (err) {
      setSteps(before)
      setError((err as Error).message || t('quicksteps_save_failed', {
        defaultValue: 'Failed to save quick action',
      }))
    }
  }


  const handleDragStart = (index: number) => {
    dragIndexRef.current = index
  }

  const handleDragOver = (e: React.DragEvent, index: number) => {
    e.preventDefault()
    setDragOverIndex(index)
  }

  const handleDrop = async (e: React.DragEvent, toIndex: number) => {
    e.preventDefault()
    const fromIndex = dragIndexRef.current
    dragIndexRef.current = null
    setDragOverIndex(null)
    if (fromIndex === null || fromIndex === toIndex) return

    const next = [...steps]
    const [item] = next.splice(fromIndex, 1)
    next.splice(toIndex, 0, item)
    setSteps(next)

    try {
      await reorderQuickSteps(next.map(s => s.id))
      window.dispatchEvent(new CustomEvent('agentys:quicksteps-changed'))
    } catch (err) {
      // Audit 2026-05-11 F-04: silent revert was the same anti-pattern that
      // Cluster D (#618) explicitly remediated. Toast first, then reload.
      const message =
        (err as Error)?.message ||
        t('quicksteps_reorder_failed', { defaultValue: 'Réorganisation impossible. Réessaie.' })
      window.dispatchEvent(
        new CustomEvent('agentys:toast', { detail: { type: 'error', message } }),
      )
      void reload()
    }
  }

  const handleDragEnd = () => {
    dragIndexRef.current = null
    setDragOverIndex(null)
  }

  if (editing) {
    return (
      <section className="quicksteps-panel" aria-labelledby="quicksteps-heading">
        {error && <div className="quicksteps-panel__error" role="alert">{error}</div>}
        <QuickStepEditor
          draft={editing}
          siblings={steps.filter(s => s.id !== editing.id)}
          onCancel={() => setEditing(null)}
          onSave={handleSave}
        />
      </section>
    )
  }

  return (
    <section className="quicksteps-panel" aria-labelledby="quicksteps-heading">
      {error && (
        <div className="quicksteps-panel__error" role="alert">
          <span>{error}</span>
          <button
            type="button"
            className="quicksteps-panel__error-retry"
            onClick={() => void reload()}
          >
            {t('quicksteps_retry', { defaultValue: 'Retry' })}
          </button>
        </div>
      )}

      {loading ? (
        <div className="quicksteps-panel__placeholder">
          <span className="quicksteps-skeleton" />
          <span className="quicksteps-skeleton" />
        </div>
      ) : error && steps.length === 0 ? (
        // Load failed — hide the Quick-Start template grid so the user
        // doesn't think their rules vanished. The error banner above
        // (with Retry) is the only thing they should see.
        null
      ) : steps.length === 0 ? (
        <EmptyState
          templates={quickStartTemplates}
          onPickTemplate={startFromTemplate}
          onCreateBlank={startNew}
        />
      ) : (
        <>
          <header className="quicksteps-list-header">
            {/* Filter chips — hidden when the list is too short to justify a
                filter row (no point showing "All / Auto / Manual / Disabled"
                over a single card). Drag is disabled while a non-"all" filter
                is active because reorder writes the index of the FILTERED
                list back as the new global order, which would silently move
                hidden rows. */}
            {steps.length > 1 && (
              <div className="quicksteps-filter-bar" role="tablist" aria-label={t('quicksteps_filter_aria', { defaultValue: 'Filtrer les quick actions' })}>
                {(['all', 'auto', 'manual', 'disabled'] as const).map((key) => {
                  const count = key === 'all'
                    ? steps.length
                    : key === 'auto'
                      ? steps.filter(s => s.autoEnabled && s.enabled).length
                      : key === 'manual'
                        ? steps.filter(s => !s.autoEnabled && s.enabled).length
                        : steps.filter(s => !s.enabled).length
                  const label = key === 'all'
                    ? t('quicksteps_filter_all', { defaultValue: 'Tous' })
                    : key === 'auto'
                      ? t('quicksteps_filter_auto', { defaultValue: 'Auto' })
                      : key === 'manual'
                        ? t('quicksteps_filter_manual', { defaultValue: 'Manuels' })
                        : t('quicksteps_filter_disabled', { defaultValue: 'Désactivés' })
                  return (
                    <button
                      key={key}
                      type="button"
                      role="tab"
                      aria-selected={filter === key}
                      data-active={filter === key || undefined}
                      className="quicksteps-filter-chip"
                      onClick={() => setFilter(key)}
                    >
                      {label}
                      <span className="quicksteps-filter-chip__count">{count}</span>
                    </button>
                  )
                })}
              </div>
            )}
            <button
              type="button"
              className="quicksteps-panel__primary"
              onClick={startNew}
            >
              <PlusIcon size={14} />
              {t('quicksteps_new', { defaultValue: 'Nouvelle' })}
            </button>
          </header>
          <ul className="quicksteps-list">
            {steps
              .map((step, index) => ({ step, index }))
              .filter(({ step }) => {
                if (filter === 'all') return true
                if (filter === 'auto') return step.autoEnabled && step.enabled
                if (filter === 'manual') return !step.autoEnabled && step.enabled
                return !step.enabled
              })
              .map(({ step, index }) => (
              <li
                key={step.id}
                draggable={filter === 'all'}
                onDragStart={() => handleDragStart(index)}
                onDragOver={e => handleDragOver(e, index)}
                onDrop={e => handleDrop(e, index)}
                onDragEnd={handleDragEnd}
                data-drag-over={dragOverIndex === index || undefined}
              >
                <QuickStepCard
                  step={step}
                  onEdit={() => {
                    // Clear stale error so the editor opens with a clean slate.
                    setError(null)
                    setEditing(normalizeQuickStep({ ...step }))
                  }}
                  onDelete={() => requestDelete(step)}
                  onToggleEnabled={(next) => handleToggleEnabled(step.id, next)}
                />
              </li>
            ))}
            {steps.length > 0 && steps.every(s => {
              if (filter === 'all') return false
              if (filter === 'auto') return !(s.autoEnabled && s.enabled)
              if (filter === 'manual') return !(!s.autoEnabled && s.enabled)
              return s.enabled
            }) && (
              <li className="quicksteps-list__empty-filter">
                {t('quicksteps_filter_empty', { defaultValue: 'Aucune quick action dans ce filtre.' })}
              </li>
            )}
          </ul>
        </>
      )}

      <ConfirmationDialog
        isOpen={pendingDelete !== null}
        onConfirm={handleConfirmDelete}
        onCancel={() => setPendingDelete(null)}
        title={t('quicksteps_confirm_delete_title', { defaultValue: 'Supprimer cette quick action ?' })}
        message={pendingDelete?.name
          ? t('quicksteps_confirm_delete_msg_named', {
              defaultValue: '« {{name}} » sera supprimée définitivement. Cette action est irréversible.',
              name: pendingDelete.name,
            })
          : t('quicksteps_confirm_delete_msg', {
              defaultValue: 'Cette quick action sera supprimée définitivement. Cette action est irréversible.',
            })}
        confirmLabel={t('quicksteps_delete', { defaultValue: 'Supprimer' })}
        destructive
      />
    </section>
  )
}

// --------------------------------------------------------------------------- //
// Empty state
// --------------------------------------------------------------------------- //

interface EmptyStateProps {
  templates: QuickStartTemplate[]
  onPickTemplate: (template: QuickStartTemplate) => void
  onCreateBlank: () => void
}

function EmptyState({ templates, onPickTemplate, onCreateBlank }: EmptyStateProps) {
  const { t } = useTranslation('settings')
  return (
    <div className="quicksteps-empty">
      <p className="quicksteps-empty__caption">
        {t('quicksteps_rail_title', { defaultValue: 'Pour démarrer' })}
      </p>
      <div className="quicksteps-empty__grid">
        {templates.map(tpl => (
          <button
            key={tpl.key}
            type="button"
            className="quicksteps-template"
            onClick={() => onPickTemplate(tpl)}
          >
            <span className="quicksteps-template__icon" aria-hidden="true">
              <TemplateIcon templateKey={tpl.key} />
            </span>
            <span className="quicksteps-template__body">
              <span className="quicksteps-template__name">{tpl.defaultName}</span>
              <span className="quicksteps-template__desc">{tpl.description}</span>
            </span>
            <span className="quicksteps-template__chev" aria-hidden="true">
              <ChevronRightIcon size={16} />
            </span>
          </button>
        ))}
        <button
          type="button"
          className="quicksteps-template quicksteps-template--blank"
          onClick={onCreateBlank}
        >
          <span className="quicksteps-template__icon" aria-hidden="true">
            <PlusIcon size={14} />
          </span>
          <span className="quicksteps-template__body">
            <span className="quicksteps-template__name">
              {t('quicksteps_new', { defaultValue: 'Nouvelle' })}
            </span>
            <span className="quicksteps-template__desc">
              {t('quicksteps_blank_desc', { defaultValue: 'Partir de zéro avec une chaîne vide.' })}
            </span>
          </span>
          <span className="quicksteps-template__chev" aria-hidden="true">
            <ChevronRightIcon size={16} />
          </span>
        </button>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- //
// Card — list item
// --------------------------------------------------------------------------- //

interface QuickStepCardProps {
  step: QuickStep
  onEdit: () => void
  /** Omitted when the card is rendered as a discovery preview (e.g. inside
   *  Settings → Automation) — the user manages deletion from the full modal. */
  onDelete?: () => void
  /** Inline enabled toggle on the card. When provided, render a switch that
   *  flips ``step.enabled`` without opening the editor. The handler is
   *  responsible for persisting via ``updateQuickStep`` AND refreshing any
   *  shared cache (e.g. dispatching ``agentys:quicksteps-changed``). */
  onToggleEnabled?: (next: boolean) => void
  /** Discovery mode: hides the drag handle so the card reads as a static
   *  preview rather than a sortable list item. */
  embedded?: boolean
}

export function QuickStepCard({ step, onEdit, onDelete, onToggleEnabled, embedded }: QuickStepCardProps) {
  const { t } = useTranslation('settings')
  // Description is the only source of truth for the card's secondary line.
  // No more auto-generated trigger/action summary — those are already
  // conveyed by the action-icon stack on the left and the rule name above,
  // and forcing a redundant text line for unattended rules pushed users
  // to ignore the description field instead of writing intent. Empty
  // description → empty line, which is honest signal that a rule could
  // use a sentence describing its purpose.
  // Audit 2026-05-18: seeded default rules ship with English name +
  // description on the backend. Detect the canonical ones by name and
  // overlay the locale-aware copy from the `quicksteps` namespace so the
  // FR/ES inboxes don't render a half-English UI. User-renamed rules and
  // user-authored rules fall through to step.name / step.description.
  const _seededKey = seededStepKey(step.name)
  const displayName = _seededKey
    ? t(`quicksteps_${_seededKey}_name`, { defaultValue: step.name })
    : (step.name || t('quicksteps_unnamed', { defaultValue: '(Sans nom)' }))
  const summary = _seededKey
    ? t(`quicksteps_${_seededKey}_desc`, { defaultValue: step.description?.trim() ?? '' })
    : (step.description?.trim() ?? '')
  // 2026-05-13 visual pass: dropped the per-action colored left bar — it
  // was decorative, fought with the icon stack for "what kind of action is
  // this?", and gave the impression rows encoded category data that they
  // didn't. The icon-chip stack already carries action semantics with the
  // correct color tokens. The card itself is now neutral, and hover/focus
  // states use the app's single accent token instead of a per-row hue.
  return (
    <article
      className="quickstep-card"
      data-disabled={!step.enabled || undefined}
      data-embedded={embedded || undefined}
      onClick={onEdit}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onEdit() } }}
    >
      {!embedded && (
        <span
          className="quickstep-card__drag"
          aria-hidden="true"
          title={t('quicksteps_drag_to_reorder', { defaultValue: 'Glisser pour réordonner' })}
          onClick={e => e.stopPropagation()}
        >
          <DragHandleIcon />
        </span>
      )}
      {!embedded && (
        <span className="quickstep-card__stack" aria-hidden="true">
          {step.actions.slice(0, 3).map((a, i) => (
            <span key={i} style={{ display: 'contents' }}>
              {i > 0 && <span className="quickstep-card__flow-sep">›</span>}
              <span className="quickstep-card__chip" data-action={a.type}>
                <ActionIcon type={a.type} />
              </span>
            </span>
          ))}
        </span>
      )}
      <div className="quickstep-card__main">
        <div className="quickstep-card__header">
          <span className="quickstep-card__name">
            {displayName}
          </span>
          {!step.enabled && (
            <span className="quickstep-card__badge">
              {t('quicksteps_disabled', { defaultValue: 'Désactivé' })}
            </span>
          )}
          {step.autoEnabled && (
            <span
              className="quickstep-card__badge quickstep-card__badge--auto"
              title={t('quicksteps_auto_badge', { defaultValue: 'Déclenchement automatique actif' })}
            >
              <ZapIcon />
              {t('quicksteps_auto_badge_label', { defaultValue: 'Auto' })}
            </span>
          )}
        </div>
        {summary && <div className="quickstep-card__summary">{summary}</div>}
      </div>
      <div className="quickstep-card__meta">
        {onToggleEnabled && (
          <label
            className="quickstep-card__toggle"
            data-state={step.enabled ? 'on' : 'off'}
            onClick={(e) => e.stopPropagation()}
            // Tooltip now states the CURRENT state ("Activé — clic pour
            // désactiver") rather than only the destination verb. At-a-glance
            // legibility was the codex-flagged regression: users couldn't
            // tell off from on without color memory.
            title={step.enabled
              ? t('quicksteps_toggle_on_hint', { defaultValue: 'Activé — cliquer pour désactiver' })
              : t('quicksteps_toggle_off_hint', { defaultValue: 'Désactivé — cliquer pour activer' })}
          >
            <input
              type="checkbox"
              checked={step.enabled}
              onChange={(e) => onToggleEnabled(e.target.checked)}
              aria-label={step.enabled
                ? t('quicksteps_disable_rule', { defaultValue: 'Désactiver cette quick action' })
                : t('quicksteps_enable_rule', { defaultValue: 'Activer cette quick action' })}
            />
            <span className="quickstep-card__switch" />
          </label>
        )}
        {onDelete && (
          <button
            type="button"
            className="quickstep-card__icon-btn danger"
            onClick={(e) => { e.stopPropagation(); onDelete() }}
            aria-label={t('quicksteps_delete', { defaultValue: 'Supprimer' })}
            title={t('quicksteps_delete', { defaultValue: 'Supprimer' })}
          >
            <CloseIcon size={14} />
          </button>
        )}
      </div>
    </article>
  )
}

type TFn = (key: string, opts?: Record<string, unknown>) => string

function actionLabel(action: QuickStepAction, t: TFn): string {
  switch (action.type) {
    case 'archive':
      return t('quicksteps_action_archive', { defaultValue: 'Archiver' })
    case 'unarchive':
      return t('quicksteps_action_unarchive', { defaultValue: 'Ramener en inbox' })
    case 'create_snoozed_followup_draft':
      return t('quicksteps_action_snoozed_draft_count', {
        defaultValue: 'Follow-up draft in {{count}}d',
        count: action.payload?.delay_days ?? 7,
      })
    case 'delete':
      return t('quicksteps_action_delete', { defaultValue: 'Supprimer' })
    case 'mark_read':
      return action.payload.value
        ? t('quicksteps_mark_as_read', { defaultValue: 'Marquer comme lu' })
        : t('quicksteps_mark_as_unread', { defaultValue: 'Marquer comme non lu' })
    case 'move_to_spam':
      return t('quicksteps_action_move_to_spam', { defaultValue: 'Déplacer en spam' })
    case 'pin':
      return t('quicksteps_action_pin', { defaultValue: 'Épingler' })
    case 'reply_template':
      return t('quicksteps_action_reply_template', { defaultValue: 'Répondre (modèle)' })
    case 'forward': {
      const emailCount = action.payload.to?.length || 0
      const groupCount = action.payload.to_groups?.length || 0
      const total = emailCount + groupCount
      return total === 0
        ? t('quicksteps_action_forward', { defaultValue: 'Transférer' })
        : t('quicksteps_action_forward_count', { defaultValue: 'Transférer ({{count}})', count: total })
    }
    case 'rsvp_meeting': {
      const labelMap = {
        accepted: t('quicksteps_rsvp_accepted', { defaultValue: 'Accepter réunion' }),
        declined: t('quicksteps_rsvp_declined', { defaultValue: 'Décliner réunion' }),
        tentative: t('quicksteps_rsvp_tentative', { defaultValue: 'Réunion : peut-être' }),
      }
      return labelMap[action.payload.response] ?? t('quicksteps_rsvp_accepted', { defaultValue: 'Accepter réunion' })
    }
    case 'mark_with_emoji': {
      const emoji = action.payload?.emoji ?? '⏰'
      const text = action.payload?.text?.trim()
      if (text) {
        return t('quicksteps_action_mark_with_emoji_text', {
          defaultValue: 'Marquer {{emoji}} {{text}}',
          emoji, text,
        })
      }
      return t('quicksteps_action_mark_with_emoji', {
        defaultValue: 'Marquer {{emoji}}',
        emoji,
      })
    }
    case 'apply_label': {
      const label = action.payload?.label?.trim()
      if (label) {
        return t('quicksteps_action_apply_label_named', {
          defaultValue: 'Étiqueter « {{label}} »',
          label,
        })
      }
      return t('quicksteps_action_apply_label', { defaultValue: 'Étiqueter' })
    }
    case 'create_reminder':
      return t('quicksteps_action_create_reminder_count', {
        defaultValue: 'Rappel {{count}}j avant',
        count: action.payload?.days_before ?? 2,
      })
    case 'create_calendar_event':
      return t('quicksteps_action_create_calendar_event_count', {
        defaultValue: 'Rencontre, {{count}}j avant',
        count: action.payload?.days_before ?? 2,
      })
    default:
      return t('quicksteps_action_unknown', {
        defaultValue: '{{type}}',
        type: (action as QuickStepAction).type,
      })
  }
}

// --------------------------------------------------------------------------- //
// Editor (inline panel; full-page modal would fight the Settings layout)
// --------------------------------------------------------------------------- //

// --------------------------------------------------------------------------- //
// Step — numbered wrapper used by the editor to lay out its 4 logical steps.
// --------------------------------------------------------------------------- //

interface StepProps {
  n: 1 | 2 | 3 | 4
  active?: boolean
  label?: string
  hint?: string
  children: React.ReactNode
}

function Step({ n, active, label, hint, children }: StepProps) {
  return (
    <section className="qs-step">
      <span
        className="qs-step__num"
        data-active={active || undefined}
        aria-hidden="true"
      >
        {active ? <CheckIcon size={14} /> : n}
      </span>
      <div className="qs-step__body">
        {(label || hint) && (
          <header className="qs-step__head">
            {label && <h3 className="qs-step__label">{label}</h3>}
            {hint && <p className="qs-step__hint">{hint}</p>}
          </header>
        )}
        {children}
      </div>
    </section>
  )
}

interface QuickStepEditorProps {
  draft: QuickStep
  siblings: QuickStep[]
  onCancel: () => void
  onSave: (step: QuickStep) => void | Promise<void>
}

export function QuickStepEditor({ draft, siblings, onCancel, onSave }: QuickStepEditorProps) {
  const { t } = useTranslation('settings')
  // Belt-and-braces: normalize on entry so the editor never trips on a
  // partial/legacy step object (missing triggers, triggerOperator, etc.).
  const [step, setStep] = useState<QuickStep>(() => normalizeQuickStep(draft))
  const [localError, setLocalError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const errorRef = useRef<HTMLDivElement>(null)
  const nameInputRef = useRef<HTMLInputElement>(null)
  // HTML5 DnD state for action reordering. ``draggedIndex`` is the row the
  // user grabbed; ``dragOverIndex`` is the row we'll insert above on drop.
  // Both reset on dragend so the visuals don't get stuck after the browser
  // cancels a drag (Escape, drop outside).
  const [draggedIndex, setDraggedIndex] = useState<number | null>(null)
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null)
  // Description-touched gate (2026-05-13 post-incident): if the user never
  // interacts with the description textarea during this editor session,
  // the save payload must NOT carry `description` — JSON.stringify drops
  // undefined fields, the backend's PATCH merge preserves the existing
  // value. Without this gate, the textarea's bound empty value would
  // round-trip as `description: ""` and the validator would normalize it
  // to None, silently wiping descriptions when the user only meant to
  // edit some other field.
  const descriptionTouchedRef = useRef(false)
  // Same gate for the name field. Seeded starter rules are stored under their
  // canonical English name (the Settings discovery surface matches on it) but
  // we DISPLAY the locale-aware label below. `step.name` therefore stays the
  // canonical English in state until the user actually edits the field — at
  // which point it becomes their own (custom) name and we persist that.
  const nameTouchedRef = useRef(false)
  // For brand-new drafts (empty name) put the cursor in the name field on
  // open. On edit we don't want to steal focus — the user usually came in
  // to tweak a deeper field, not rename.
  const isNewDraft = !draft.name?.trim()
  useEffect(() => {
    if (isNewDraft) {
      nameInputRef.current?.focus()
    }

  }, [])

  const update = (patch: Partial<QuickStep>) => setStep(prev => {
    const next = { ...prev, ...patch }
    // Auto is the default mode for every rule that CAN auto-fire (product
    // decision 2026-06-09): the schema rejects autoEnabled without triggers,
    // so the flip happens the moment the rule gains its first condition.
    // The user can still pick Manuel afterwards — later edits (2nd condition,
    // value tweaks) never re-flip. Removing the last condition downgrades
    // back to Manuel so the editor never strands an autoEnabled rule the
    // backend would reject on save.
    if (patch.triggers) {
      if (prev.triggers.length === 0 && patch.triggers.length > 0 && !prev.autoEnabled) {
        next.autoEnabled = true
      } else if (patch.triggers.length === 0 && prev.autoEnabled) {
        next.autoEnabled = false
      }
    }
    return next
  })

  const updateAction = (index: number, next: QuickStepAction) => {
    setStep(prev => {
      const updated: QuickStep = {
        ...prev,
        actions: prev.actions.map((a, i) => (i === index ? next : a)),
      }
      // Same cross-flow guard as addAction: switching an existing action
      // to a sent-only type via the inline picker must auto-flip firesOn
      // so the backend validator doesn't reject the rule on save.
      if (SENT_ONLY_ACTIONS.includes(next.type) && updated.firesOn !== 'sent') {
        updated.firesOn = 'sent'
      }
      return updated
    })
  }

  const removeAction = (index: number) => {
    setStep(prev => ({
      ...prev,
      actions: prev.actions.filter((_, i) => i !== index),
    }))
  }

  const moveAction = (index: number, delta: number) => {
    const target = index + delta
    setStep(prev => {
      if (target < 0 || target >= prev.actions.length) return prev
      const next = [...prev.actions]
      ;[next[index], next[target]] = [next[target], next[index]]
      return { ...prev, actions: next }
    })
  }

  const moveActionTo = (from: number, to: number) => {
    if (from === to || from < 0 || to < 0) return
    setStep(prev => {
      if (from >= prev.actions.length || to >= prev.actions.length) return prev
      const next = [...prev.actions]
      const [moved] = next.splice(from, 1)
      next.splice(to, 0, moved)
      return { ...prev, actions: next }
    })
  }

  const handleActionDragStart = (event: React.DragEvent<HTMLLIElement>, index: number) => {
    // Only initiate drag from the dedicated handle. Without this gate, the
    // <li>'s draggable=true would let the user drag from inside the action
    // picker, snippet body, etc. — wrecking text selection and clicks.
    const target = event.target as HTMLElement | null
    if (!target?.closest('.quickstep-actions__handle')) {
      event.preventDefault()
      return
    }
    setDraggedIndex(index)
    event.dataTransfer.effectAllowed = 'move'
    // Firefox requires *something* in the dataTransfer or the drag is cancelled.
    event.dataTransfer.setData('text/plain', String(index))
  }

  const handleActionDragOver = (event: React.DragEvent<HTMLLIElement>, index: number) => {
    if (draggedIndex === null) return
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
    if (dragOverIndex !== index) setDragOverIndex(index)
  }

  const handleActionDrop = (event: React.DragEvent<HTMLLIElement>, dropIndex: number) => {
    event.preventDefault()
    if (draggedIndex === null) return
    moveActionTo(draggedIndex, dropIndex)
    setDraggedIndex(null)
    setDragOverIndex(null)
  }

  const handleActionDragEnd = () => {
    setDraggedIndex(null)
    setDragOverIndex(null)
  }

  const addAction = (type: QuickStepActionType) => {
    setStep(prev => {
      const next: QuickStep = { ...prev, actions: [...prev.actions, makeAction(type)] }
      // create_snoozed_followup_draft only works on the sent flow — set
      // firesOn automatically so the backend save validator doesn't reject
      // the rule the user just built.
      if (SENT_ONLY_ACTIONS.includes(type) && next.firesOn !== 'sent') {
        next.firesOn = 'sent'
      }
      return next
    })
  }

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (submitting) return
    setLocalError(null)
    const localFail = validateLocally(step, siblings, t)
    if (localFail) {
      setLocalError(localFail)
      requestAnimationFrame(() => {
        errorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      })
      return
    }
    // Drop `description` from the outgoing payload when the user didn't
    // touch the textarea this session. JSON.stringify will then omit the
    // field and the backend's PATCH merge preserves whatever description
    // was already stored. The textarea's bound `step.description ?? ''`
    // initial value is otherwise enough to round-trip "" back on a save
    // that only meant to edit name/triggers/actions/etc. — and "" is
    // normalized to None server-side, which wipes the description.
    const payload = descriptionTouchedRef.current
      ? step
      : { ...step, description: undefined }
    setSubmitting(true)
    try {
      await onSave(payload)
    } finally {
      // On success the parent unmounts this editor (setEditing(null)); the
      // state update is then a harmless no-op. On failure the editor stays
      // mounted, so resetting re-enables the button for a retry.
      setSubmitting(false)
    }
  }

  // Seeded starter rules carry an English name + description in storage; show
  // the locale-aware copy in the fields (the card overlays the same). The
  // *TouchedRef gates keep the canonical English in `step` until the user
  // actually edits, so an untouched save never rewrites them (cf. handleSubmit
  // + the discovery name-match in Settings.tsx).
  const _seededKey = seededStepKey(step.name)
  const localizedName = _seededKey
    ? t(`quicksteps_${_seededKey}_name`, { defaultValue: step.name })
    : step.name
  const localizedDescription = _seededKey
    ? t(`quicksteps_${_seededKey}_desc`, { defaultValue: step.description ?? '' })
    : (step.description ?? '')

  return (
    <div className="quickstep-editor" role="dialog" aria-modal="true">
      <form onSubmit={handleSubmit}>
        <Step
          n={1}
          active={Boolean(step.name.trim())}
          label={t('quicksteps_step_description_label', { defaultValue: 'Description' })}
          hint={t('quicksteps_step_description_hint', {
            defaultValue: 'Donnez un nom et un raccourci à votre quick action.',
          })}
        >
          <div className="quickstep-editor__row">
            <label className="quickstep-editor__field">
              <span>{t('quicksteps_name', { defaultValue: 'Nom' })}</span>
              <input
                ref={nameInputRef}
                type="text"
                value={nameTouchedRef.current ? step.name : localizedName}
                maxLength={80}
                placeholder={t('quicksteps_name_placeholder', {
                  defaultValue: 'ex. Triage rapide',
                })}
                onChange={e => {
                  nameTouchedRef.current = true
                  update({ name: e.target.value })
                }}
                required
              />
            </label>

            <label className="quickstep-editor__field">
              <span>{t('quicksteps_shortcut', { defaultValue: 'Raccourci' })}</span>
              <ShortcutCapture
                value={step.shortcut}
                onChange={shortcut => update({ shortcut })}
              />
            </label>
          </div>

          <label className="quickstep-editor__field quickstep-editor__field--full">
            <span>{t('quicksteps_description_label', { defaultValue: 'Description' })}</span>
            <textarea
              value={descriptionTouchedRef.current ? (step.description ?? '') : localizedDescription}
              maxLength={200}
              rows={3}
              placeholder={t('quicksteps_description_placeholder', {
                defaultValue: 'Description of your quick action',
              })}
              onChange={e => {
                descriptionTouchedRef.current = true
                update({ description: e.target.value })
              }}
            />
          </label>
        </Step>

        <Step
          n={2}
          active={step.triggers.length > 0}
          label={t('quicksteps_step_conditions_label', { defaultValue: 'Conditions' })}
          hint={t('quicksteps_step_conditions_hint', {
            defaultValue: 'Pour quels emails cette quick action s\'applique.',
          })}
        >
          <ConditionsSection
            triggers={step.triggers}
            triggerOperator={step.triggerOperator}
            firesOn={step.firesOn ?? 'received'}
            onChange={patch => update(patch)}
            siblingSteps={siblings}
          />
        </Step>

        <Step
          n={3}
          active={step.actions.length > 0}
          label={t('quicksteps_step_actions_label', { defaultValue: 'Actions' })}
          hint={t('quicksteps_step_actions_hint', {
            defaultValue: 'Que faire quand cette quick action se déclenche.',
          })}
        >
          <fieldset className="quickstep-editor__actions">
            <legend className="sr-only">{t('quicksteps_actions', { defaultValue: 'Actions' })}</legend>
            <ActionChainPreview actions={step.actions} />
          <ol className="quickstep-actions">
            {step.actions.map((action, index) => (
              // Audit 2026-05-11 F-02: stable key per action so React doesn't
              // swap TipTap / ContactAutocomplete state across rows on drag-
              // reorder. Falls back to type+index for legacy rows that
              // pre-date the uid mint in makeAction.
              <li
                key={(action as { uid?: string }).uid ?? `${action.type}-${index}`}
                className="quickstep-actions__item"
                draggable={step.actions.length > 1}
                onDragStart={e => handleActionDragStart(e, index)}
                onDragOver={e => handleActionDragOver(e, index)}
                onDrop={e => handleActionDrop(e, index)}
                onDragEnd={handleActionDragEnd}
                data-dragging={draggedIndex === index || undefined}
                data-drag-over={(dragOverIndex === index && draggedIndex !== index) || undefined}
              >
                {index > 0 && (
                  <div className="quickstep-actions__sep" aria-hidden="true">
                    <ChevronDownIcon size={14} />
                    <span>{t('quicksteps_then', { defaultValue: 'puis' })}</span>
                  </div>
                )}
                <div className="quickstep-actions__head">
                  {/* Reorder handle only when there's something to reorder.
                      A single-action step has no order to change, so showing a
                      "drag to reorder" grip is a dead affordance — gated on the
                      same `actions.length > 1` as the up/down/remove controls. */}
                  {step.actions.length > 1 && (
                    <button
                      type="button"
                      className="quickstep-actions__handle"
                      aria-label={t('quicksteps_reorder_handle', {
                        defaultValue: 'Glisser pour réordonner',
                      })}
                      title={t('quicksteps_reorder_handle', {
                        defaultValue: 'Glisser pour réordonner',
                      })}
                      // Visual affordance only — the parent <li> is the actual
                      // draggable. handleActionDragStart only proceeds when the
                      // drag started inside this button, so a click anywhere
                      // else on the row won't initiate a drag.
                      onClick={e => e.preventDefault()}
                    >
                      <DragHandleIcon />
                    </button>
                  )}
                  <span className="quickstep-actions__icon" data-action={action.type} aria-hidden="true">
                    <ActionIcon type={action.type} />
                  </span>
                  <ActionTypePicker
                    value={action.type}
                    onChange={type => updateAction(index, makeAction(type))}
                  />
                  {step.actions.length > 1 && (
                    <div className="quickstep-actions__controls">
                      {/* Up/down kept as keyboard-only A11Y fallback (drag is
                          pointer-only). Visually subordinate to the handle —
                          see .quickstep-actions__icon-btn--a11y in CSS. */}
                      {index > 0 && (
                        <button
                          type="button"
                          className="quickstep-actions__icon-btn quickstep-actions__icon-btn--a11y"
                          onClick={() => moveAction(index, -1)}
                          aria-label={t('quicksteps_move_up', { defaultValue: 'Monter' })}
                          title={t('quicksteps_move_up', { defaultValue: 'Monter' })}
                        >
                          <ChevronUpIcon size={14} />
                        </button>
                      )}
                      {index < step.actions.length - 1 && (
                        <button
                          type="button"
                          className="quickstep-actions__icon-btn quickstep-actions__icon-btn--a11y"
                          onClick={() => moveAction(index, +1)}
                          aria-label={t('quicksteps_move_down', { defaultValue: 'Descendre' })}
                          title={t('quicksteps_move_down', { defaultValue: 'Descendre' })}
                        >
                          <ChevronDownIcon size={14} />
                        </button>
                      )}
                      <button
                        type="button"
                        className="quickstep-actions__icon-btn danger"
                        onClick={() => removeAction(index)}
                        aria-label={t('quicksteps_remove_action', { defaultValue: 'Supprimer' })}
                        title={t('quicksteps_remove_action', { defaultValue: 'Supprimer' })}
                      >
                        <CloseIcon size={14} />
                      </button>
                    </div>
                  )}
                </div>
                <ActionForm
                  action={action}
                  onChange={next => updateAction(index, next)}
                />
              </li>
            ))}
          </ol>

            <AddActionButton onPick={addAction} />
          </fieldset>
        </Step>

        <Step
          n={4}
          active
          label={t('quicksteps_step_trigger_mode_label', { defaultValue: 'Comment déclencher' })}
          hint={t('quicksteps_step_trigger_mode_hint', {
            defaultValue: 'Choisis comment cette quick action démarre : à la main, ou automatiquement.',
          })}
        >
          <TriggerModeCards
            autoEnabled={step.autoEnabled}
            hasShortcut={Boolean(step.shortcut)}
            triggerCount={step.triggers.length}
            onChange={patch => update(patch)}
          />
          {step.autoEnabled && (
            <>
              <FiresOnSelector
                firesOn={step.firesOn ?? 'received'}
                hasFollowUpAction={step.actions.some(a => SENT_ONLY_ACTIONS.includes(a.type))}
                onChange={fo => update({ firesOn: fo })}
              />
              <AutoBadgeToggle
                showAutoBadge={step.showAutoBadge ?? true}
                onChange={v => update({ showAutoBadge: v })}
              />
            </>
          )}
        </Step>

        {localError && (
          <div ref={errorRef} className="quickstep-editor__error" role="alert">
            {localError}
          </div>
        )}

        <div className="quickstep-editor__footer">
          <div className="quickstep-editor__summary" aria-live="polite">
            <span data-count={step.triggers.length} className="quickstep-editor__summary-pill">
              {/* Audit 2026-05-11 F-11: i18next uses _one/_other suffixes,
                  not _plural. Pre-2026 _plural was a no-op so callers saw
                  "5 condition" instead of "5 conditions" when the JSON
                  key was missing. */}
              {t('quicksteps_summary_conditions', {
                defaultValue: '{{count}} condition',
                defaultValue_one: '{{count}} condition',
                defaultValue_other: '{{count}} conditions',
                count: step.triggers.length,
              })}
            </span>
            <span className="quickstep-editor__summary-dot" aria-hidden="true">•</span>
            <span data-count={step.actions.length} className="quickstep-editor__summary-pill">
              {t('quicksteps_summary_actions', {
                defaultValue: '{{count}} action',
                defaultValue_one: '{{count}} action',
                defaultValue_other: '{{count}} actions',
                count: step.actions.length,
              })}
            </span>
            {step.autoEnabled && (
              <>
                <span className="quickstep-editor__summary-dot" aria-hidden="true">•</span>
                <span className="quickstep-editor__summary-pill quickstep-editor__summary-pill--auto">
                  <ZapIcon />
                  {t('quicksteps_summary_auto', { defaultValue: 'auto' })}
                </span>
              </>
            )}
          </div>
          <div className="quickstep-editor__actions-row">
            <Button
              type="button"
              variant="outline"
              onClick={onCancel}
              disabled={submitting}
            >
              {t('quicksteps_cancel', { defaultValue: 'Annuler' })}
            </Button>
            <Button
              type="submit"
              disabled={submitting || !step.name.trim() || step.actions.length === 0}
            >
              {t('quicksteps_save', { defaultValue: 'Enregistrer' })}
            </Button>
          </div>
        </div>
      </form>
    </div>
  )
}

function isHtmlVisuallyEmpty(html: string | undefined | null): boolean {
  if (!html) return true
  return !html.replace(/<[^>]*>/g, '').replace(/&nbsp;/g, ' ').trim()
}

function validateLocally(step: QuickStep, siblings: QuickStep[], t: TFn): string | null {
  if (!step.name.trim()) {
    return t('quicksteps_validation_name_required', { defaultValue: 'Le nom est obligatoire.' })
  }
  if (step.actions.length === 0) {
    return t('quicksteps_validation_actions_required', { defaultValue: 'Ajoutez au moins une action.' })
  }
  for (let i = 0; i < step.actions.length - 1; i += 1) {
    if (step.actions[i].type === 'delete') {
      return t('quicksteps_validation_delete_terminal', {
        defaultValue: 'L\'action « Supprimer » doit être la dernière de la chaîne.',
      })
    }
  }
  for (const action of step.actions) {
    if (action.type === 'reply_template') {
      const p = action.payload
      if (!p.snippet_id && isHtmlVisuallyEmpty(p.body)) {
        return t('quicksteps_validation_reply_body_required', {
          defaultValue: 'Le corps de la réponse modèle ne peut pas être vide.',
        })
      }
    }
    if (action.type === 'forward') {
      const p = action.payload
      const hasEmails = p.to.length > 0
      const hasGroups = (p.to_groups?.length ?? 0) > 0
      if (!hasEmails && !hasGroups) {
        return t('quicksteps_validation_forward_recipient_required', {
          defaultValue: 'Ajoutez au moins un destinataire pour le transfert.',
        })
      }
    }
  }
  if (step.autoEnabled && step.triggers.length === 0) {
    return t('quicksteps_validation_triggers_required', {
      defaultValue: 'Ajoutez au moins une condition pour le déclenchement automatique.',
    })
  }
  if (step.shortcut) {
    const collision = siblings.find(s => s.shortcut === step.shortcut)
    if (collision) {
      return t('quicksteps_validation_shortcut_collision', {
        defaultValue: 'Le raccourci « {{shortcut}} » est déjà utilisé par « {{name}} ».',
        shortcut: formatShortcut(step.shortcut),
        name: collision.name,
      })
    }
  }
  return null
}

// --------------------------------------------------------------------------- //
// Shared picker hook — close on outside-click + Escape, flip-up logic,
// arrow-key navigation, Home/End/Enter selection.
// --------------------------------------------------------------------------- //

interface UsePickerArgs<T> {
  options: readonly T[]
  estimatedRowHeight?: number
  onSelect: (option: T) => void
}

// Module-level registry so only one picker can be open at a time across the
// whole modal. Without this, clicking a second picker's trigger races with the
// first picker's outside-mousedown listener and both menus can render at once.
let activePickerCloser: (() => void) | null = null

function usePicker<T>({ options, estimatedRowHeight = 36, onSelect }: UsePickerArgs<T>) {
  const [open, setOpen] = useState(false)
  const [placement, setPlacement] = useState<'down' | 'up'>('down')
  const [maxHeight, setMaxHeight] = useState<number | null>(null)
  const [highlightIndex, setHighlightIndex] = useState(-1)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const closeSelfRef = useRef(() => setOpen(false))

  // Register/unregister this picker as the globally-open one so opening
  // another picker automatically closes this one.
  useEffect(() => {
    if (!open) return
    // Snapshot the ref now: closeSelfRef.current is stable for this render
    // but eslint can't prove it, and copying eliminates the "ref value
    // will likely have changed by cleanup time" warning.
    const myCloser = closeSelfRef.current
    if (activePickerCloser && activePickerCloser !== myCloser) {
      activePickerCloser()
    }
    activePickerCloser = myCloser
    return () => {
      if (activePickerCloser === myCloser) {
        activePickerCloser = null
      }
    }
  }, [open])

  // Latest values in refs so document listeners stay correct without re-binding.
  const optionsRef = useRef(options)
  const onSelectRef = useRef(onSelect)
  const highlightRef = useRef(highlightIndex)
  optionsRef.current = options
  onSelectRef.current = onSelect
  highlightRef.current = highlightIndex

  useEffect(() => {
    if (!open) {
      setHighlightIndex(-1)
      return
    }
    const onPointerDown = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    const onKeyDown = (e: KeyboardEvent) => {
      const opts = optionsRef.current
      if (e.key === 'Escape') {
        // Without stopPropagation, the same Escape also bubbles to the
        // editor/modal listener and closes the whole panel — the user
        // expects Escape to dismiss only the open dropdown.
        e.stopPropagation()
        e.preventDefault()
        setOpen(false)
        return
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setHighlightIndex(i => (i + 1 + opts.length) % opts.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setHighlightIndex(i => {
          if (i <= 0) return opts.length - 1
          return i - 1
        })
        return
      }
      if (e.key === 'Home') {
        e.preventDefault()
        setHighlightIndex(0)
        return
      }
      if (e.key === 'End') {
        e.preventDefault()
        setHighlightIndex(opts.length - 1)
        return
      }
      if (e.key === 'Enter') {
        e.preventDefault()
        const idx = highlightRef.current
        if (idx >= 0 && idx < opts.length) {
          onSelectRef.current(opts[idx])
          setOpen(false)
        }
      }
    }
    // Capture phase so handlers higher in the tree that call stopPropagation
    // (e.g. some custom inputs / focus traps in the modal) can't prevent the
    // outside-click detection from running. Same idea for keydown.
    document.addEventListener('mousedown', onPointerDown, true)
    document.addEventListener('keydown', onKeyDown, true)
    return () => {
      document.removeEventListener('mousedown', onPointerDown, true)
      document.removeEventListener('keydown', onKeyDown, true)
    }
  }, [open])

  // Flip up when there's not enough room below — measured against the closest
  // scroll/clip ancestor (e.g. modal body) so the menu doesn't overflow it.
  // Also clamp the menu height to the available space so items below the
  // modal body's clipping rectangle remain reachable via the menu's internal
  // scroll (without this, position:absolute clips them off the visible area).
  useEffect(() => {
    if (!open || !wrapperRef.current) return
    const rect = wrapperRef.current.getBoundingClientRect()
    const constraint = (wrapperRef.current.closest(
      '.quick-actions-modal-body, [data-popover-boundary]',
    ) as HTMLElement | null)?.getBoundingClientRect()
    const topBound = constraint?.top ?? 0
    const bottomBound = constraint?.bottom ?? window.innerHeight
    const estimatedMenuHeight = options.length * estimatedRowHeight + 16
    // 14px = 6px gap below the trigger (top: calc(100% + 6px)) + 8px breathing room
    const spaceBelow = Math.max(0, bottomBound - rect.bottom - 14)
    const spaceAbove = Math.max(0, rect.top - topBound - 14)
    const useUp = spaceBelow < estimatedMenuHeight && spaceAbove > spaceBelow
    setPlacement(useUp ? 'up' : 'down')
    setMaxHeight(useUp ? spaceAbove : spaceBelow)
  }, [open, options.length, estimatedRowHeight])

  // Pre-highlight current value when opening with ArrowDown from trigger
  const onTriggerKeyDown = (e: React.KeyboardEvent, currentIndex: number) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      if (!open) {
        setOpen(true)
        setHighlightIndex(currentIndex >= 0 ? currentIndex : 0)
      }
    }
  }

  return {
    open,
    setOpen,
    placement,
    maxHeight,
    highlightIndex,
    setHighlightIndex,
    wrapperRef,
    onTriggerKeyDown,
  }
}

// --------------------------------------------------------------------------- //
// ValueDropdown — generic styled picker shared by has_label and
// previously_auto_actioned_by triggers. Replaces the native <select> so the
// dropdown matches the rest of the Quick Steps UI (rounded card, shadow,
// hover/active states, optional color swatch).
// --------------------------------------------------------------------------- //

interface ValueDropdownOption {
  id: string
  label: string
  color?: string
}

interface ValueDropdownProps {
  value: string
  options: ValueDropdownOption[]
  placeholder: string
  ariaLabel: string
  onSelect: (id: string) => void
}

function ValueDropdown({ value, options, placeholder, ariaLabel, onSelect }: ValueDropdownProps) {
  const picker = usePicker<ValueDropdownOption>({
    options,
    onSelect: opt => onSelect(opt.id),
  })
  const current = options.find(o => o.id === value)

  return (
    <div className="qs-value-dropdown" ref={picker.wrapperRef}>
      <button
        type="button"
        className="qs-value-dropdown__trigger"
        aria-haspopup="listbox"
        aria-expanded={picker.open}
        aria-label={ariaLabel}
        onClick={() => picker.setOpen(!picker.open)}
      >
        {current ? (
          <span className="qs-value-dropdown__current">
            {current.color && (
              <span
                className="qs-value-dropdown__swatch"
                style={{ background: current.color }}
                aria-hidden="true"
              />
            )}
            <span className="qs-value-dropdown__current-label">{current.label}</span>
          </span>
        ) : (
          <span className="qs-value-dropdown__placeholder">{placeholder}</span>
        )}
        <ChevronDownIcon size={12} />
      </button>
      {picker.open && (
        <ul
          className="qs-value-dropdown__menu"
          role="listbox"
          data-placement={picker.placement}
          style={picker.maxHeight != null ? { maxHeight: picker.maxHeight } : undefined}
        >
          {options.length === 0 ? (
            <li className="qs-value-dropdown__empty">{placeholder}</li>
          ) : (
            options.map((opt, idx) => (
              <li key={opt.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={value === opt.id}
                  data-active={value === opt.id || undefined}
                  data-highlighted={picker.highlightIndex === idx || undefined}
                  className="qs-value-dropdown__option"
                  onMouseEnter={() => picker.setHighlightIndex(idx)}
                  onClick={() => {
                    onSelect(opt.id)
                    picker.setOpen(false)
                  }}
                >
                  {opt.color && (
                    <span
                      className="qs-value-dropdown__swatch"
                      style={{ background: opt.color }}
                      aria-hidden="true"
                    />
                  )}
                  <span className="qs-value-dropdown__option-label">{opt.label}</span>
                  {value === opt.id && (
                    <CheckIcon size={14} className="qs-value-dropdown__check" />
                  )}
                </button>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  )
}


// --------------------------------------------------------------------------- //
// Action type picker — categorised dropdown shared between the inline editor
// (ActionTypePicker) and the standalone "+ Add an action" button.
// --------------------------------------------------------------------------- //

type ActionCategory = 'email' | 'compose' | 'calendar' | 'workflow'

// Actions that ONLY make sense on outgoing emails (operate on what the
// user sent). The backend validator (schema.py:_SENT_ONLY_ACTIONS) rejects
// these paired with firesOn="received", so the editor auto-flips firesOn
// when one of them is added or selected via the inline picker.
const SENT_ONLY_ACTIONS: QuickStepActionType[] = [
  'create_snoozed_followup_draft',
]

const ACTION_TYPE_CATEGORY: Record<QuickStepActionType, ActionCategory> = {
  archive: 'email',
  unarchive: 'email',
  pin: 'email',
  mark_read: 'email',
  move_to_spam: 'email',
  delete: 'email',
  reply_template: 'compose',
  forward: 'compose',
  rsvp_meeting: 'calendar',
  create_snoozed_followup_draft: 'workflow',
  mark_with_emoji: 'email',
  apply_label: 'email',
  create_reminder: 'workflow',
  create_calendar_event: 'calendar',
}

// Ordered list — the picker iterates this and groups by category.
// Order within a category is intentional (most-used first).
const QUICK_STEP_ACTION_TYPES_ORDERED: readonly QuickStepActionType[] = [
  'archive', 'unarchive', 'pin', 'mark_read', 'apply_label', 'move_to_spam', 'delete', 'mark_with_emoji',
  'reply_template', 'forward',
  'rsvp_meeting', 'create_calendar_event',
  'create_snoozed_followup_draft', 'create_reminder',
]

const ACTION_CATEGORY_ORDER: readonly ActionCategory[] = ['email', 'compose', 'calendar', 'workflow']

function actionCategoryLabel(category: ActionCategory, t: TFn): string {
  switch (category) {
    case 'email':
      return t('quicksteps_action_cat_email', { defaultValue: 'Actions email' })
    case 'compose':
      return t('quicksteps_action_cat_compose', { defaultValue: 'Rédaction' })
    case 'calendar':
      return t('quicksteps_action_cat_calendar', { defaultValue: 'Agenda' })
    case 'workflow':
      return t('quicksteps_action_cat_workflow', { defaultValue: 'Workflow' })
  }
}

interface ActionPickerMenuProps {
  value?: QuickStepActionType
  highlightIndex: number
  onPick: (type: QuickStepActionType) => void
  onHover: (idx: number) => void
  standalone?: boolean
  placement: 'down' | 'up'
  maxHeight: number | null
}

/**
 * Categorised dropdown body — shared between ActionTypePicker (inline editor)
 * and AddActionButton (the standalone "+ Add an action" button).
 *
 * ``highlightIndex`` is an absolute index into ``QUICK_STEP_ACTION_TYPES_ORDERED``
 * so arrow-key navigation cycles through the flat list, while the visual
 * grouping is purely presentational.
 */
function ActionPickerMenu({
  value, highlightIndex, onPick, onHover, standalone, placement, maxHeight,
}: ActionPickerMenuProps) {
  const { t } = useTranslation('settings')
  return (
    <ul
      role="listbox"
      className={
        standalone
          ? 'qs-action-picker__menu qs-action-picker__menu--standalone'
          : 'qs-action-picker__menu'
      }
      data-placement={placement}
      style={maxHeight != null ? { maxHeight } : undefined}
    >
      {ACTION_CATEGORY_ORDER.map(cat => {
        const items = QUICK_STEP_ACTION_TYPES_ORDERED.filter(
          opt => ACTION_TYPE_CATEGORY[opt] === cat,
        )
        if (items.length === 0) return null
        return (
          <li key={cat} className="qs-action-picker__group">
            <div className="qs-action-picker__group-label">
              {actionCategoryLabel(cat, t)}
            </div>
            {items.map(opt => {
              const idx = QUICK_STEP_ACTION_TYPES_ORDERED.indexOf(opt)
              const selected = value !== undefined && opt === value
              return (
                <button
                  key={opt}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  data-active={selected || undefined}
                  data-highlighted={idx === highlightIndex || undefined}
                  className="qs-action-picker__option"
                  onClick={() => onPick(opt)}
                  onMouseEnter={() => onHover(idx)}
                >
                  <span className="qs-action-picker__option-icon" data-action={opt} aria-hidden="true">
                    <ActionIcon type={opt} />
                  </span>
                  <span className="qs-action-picker__option-label">
                    {actionTypeOptionLabel(opt, t)}
                  </span>
                  {selected && (
                    <span className="qs-action-picker__option-check" aria-hidden="true">
                      <CheckIcon size={14} />
                    </span>
                  )}
                </button>
              )
            })}
          </li>
        )
      })}
    </ul>
  )
}

interface ActionTypePickerProps {
  value: QuickStepActionType
  onChange: (type: QuickStepActionType) => void
}

function ActionTypePicker({ value, onChange }: ActionTypePickerProps) {
  const { t } = useTranslation('settings')
  const picker = usePicker({
    options: QUICK_STEP_ACTION_TYPES_ORDERED,
    onSelect: onChange,
  })
  const currentIndex = QUICK_STEP_ACTION_TYPES_ORDERED.indexOf(value)

  return (
    <div className="qs-action-picker" ref={picker.wrapperRef}>
      <button
        type="button"
        className="qs-action-picker__btn"
        onClick={() => picker.setOpen(o => !o)}
        onKeyDown={e => picker.onTriggerKeyDown(e, currentIndex)}
        data-open={picker.open || undefined}
        aria-haspopup="listbox"
        aria-expanded={picker.open}
      >
        <span className="qs-action-picker__btn-label">
          {actionTypeOptionLabel(value, t)}
        </span>
        <span className="qs-action-picker__btn-chev" aria-hidden="true">
          <ChevronDownIcon size={14} />
        </span>
      </button>
      {picker.open && (
        <ActionPickerMenu
          value={value}
          highlightIndex={picker.highlightIndex}
          placement={picker.placement}
          maxHeight={picker.maxHeight}
          onPick={(opt) => {
            onChange(opt)
            picker.setOpen(false)
          }}
          onHover={picker.setHighlightIndex}
        />
      )}
    </div>
  )
}

function actionTypeOptionLabel(type: QuickStepActionType, t: TFn): string {
  switch (type) {
    case 'archive':
      return t('quicksteps_action_archive', { defaultValue: 'Archiver' })
    case 'unarchive':
      return t('quicksteps_action_unarchive', { defaultValue: 'Ramener en inbox' })
    case 'delete':
      return t('quicksteps_action_delete', { defaultValue: 'Supprimer' })
    case 'mark_read':
      return t('quicksteps_action_mark_read', { defaultValue: 'Marquer lu / non lu' })
    case 'move_to_spam':
      return t('quicksteps_action_move_to_spam', { defaultValue: 'Déplacer en spam' })
    case 'pin':
      return t('quicksteps_action_pin', { defaultValue: 'Épingler en haut' })
    case 'reply_template':
      return t('quicksteps_action_reply_template', { defaultValue: 'Répondre avec un modèle' })
    case 'forward':
      return t('quicksteps_action_forward', { defaultValue: 'Transférer' })
    case 'rsvp_meeting':
      return t('quicksteps_action_rsvp_meeting', { defaultValue: 'Accepter / Décliner réunion' })
    case 'create_snoozed_followup_draft':
      return t('quicksteps_action_snoozed_draft', {
        defaultValue: 'Prepare a follow-up draft',
      })
    case 'mark_with_emoji':
      return t('quicksteps_action_mark_with_emoji_picker', {
        defaultValue: 'Tag with a custom chip',
      })
    case 'apply_label':
      return t('quicksteps_action_apply_label_picker', {
        defaultValue: 'Apply a label',
      })
    case 'create_reminder':
      return t('quicksteps_action_create_reminder', {
        defaultValue: 'Créer un rappel',
      })
    case 'create_calendar_event':
      return t('quicksteps_action_create_calendar_event', {
        defaultValue: 'Créer une rencontre',
      })
    default:
      return type
  }
}

interface AddActionButtonProps {
  onPick: (type: QuickStepActionType) => void
}

function AddActionButton({ onPick }: AddActionButtonProps) {
  const { t } = useTranslation('settings')
  const picker = usePicker({
    options: QUICK_STEP_ACTION_TYPES_ORDERED,
    onSelect: onPick,
  })

  return (
    <div className="quickstep-actions__add" ref={picker.wrapperRef}>
      <button
        type="button"
        onClick={() => picker.setOpen(o => !o)}
        onKeyDown={e => picker.onTriggerKeyDown(e, 0)}
        data-open={picker.open || undefined}
        aria-haspopup="listbox"
        aria-expanded={picker.open}
      >
        <PlusIcon size={14} />
        {t('quicksteps_add_action', { defaultValue: 'Ajouter une action' })}
      </button>
      {picker.open && (
        <ActionPickerMenu
          highlightIndex={picker.highlightIndex}
          placement={picker.placement}
          maxHeight={picker.maxHeight}
          standalone
          onPick={(opt) => {
            onPick(opt)
            picker.setOpen(false)
          }}
          onHover={picker.setHighlightIndex}
        />
      )}
    </div>
  )
}

// --------------------------------------------------------------------------- //
// Per-action sub-form
// --------------------------------------------------------------------------- //

// --------------------------------------------------------------------------- //
// --------------------------------------------------------------------------- //
// Action chain preview — live summary of the action flow shown in the editor.
// --------------------------------------------------------------------------- //

interface ActionChainPreviewProps {
  actions: QuickStepAction[]
}

function ActionChainPreview({ actions }: ActionChainPreviewProps) {
  const { t } = useTranslation('settings')
  if (actions.length === 0) return null
  return (
    <div
      className="qs-chain-preview"
      role="status"
      aria-label={t('quicksteps_chain_preview_aria', { defaultValue: 'Aperçu de la chaîne d\'actions' })}
    >
      <span className="qs-chain-preview__label">
        {t('quicksteps_chain_preview', { defaultValue: 'Aperçu' })}
      </span>
      <div className="qs-chain-preview__flow">
        {actions.map((action, idx) => (
          <div className="qs-chain-preview__group" key={idx}>
            {idx > 0 && (
              <span className="qs-chain-preview__sep" aria-hidden="true">
                <ChevronRightIcon size={16} />
              </span>
            )}
            <span className="qs-chain-preview__chip" data-action={action.type}>
              <span className="qs-chain-preview__chip-icon" aria-hidden="true">
                <ActionIcon type={action.type} />
              </span>
              <span className="qs-chain-preview__chip-label">
                {actionLabel(action, t)}
              </span>
              {action.if && (action.if.triggers?.length ?? 0) > 0 && (
                <span
                  className="qs-chain-preview__chip-if"
                  title={t('quicksteps_chain_preview_if_title', {
                    defaultValue: 'Avec une condition',
                  })}
                  aria-hidden="true"
                >
                  if
                </span>
              )}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

interface ActionFormProps {
  action: QuickStepAction
  onChange: (next: QuickStepAction) => void
}

function ActionForm({ action, onChange }: ActionFormProps) {
  switch (action.type) {
    case 'archive':
    case 'unarchive':
    case 'delete':
    case 'move_to_spam':
      return null

    case 'mark_read':
      return (
        <MarkReadForm
          payload={action.payload}
          onChange={p => onChange({ type: 'mark_read', payload: p })}
        />
      )

    case 'reply_template':
      return (
        <ReplyTemplateForm
          payload={action.payload}
          onChange={p => onChange({ type: 'reply_template', payload: p })}
        />
      )

    case 'forward':
      return (
        <ForwardForm
          payload={action.payload}
          onChange={p => onChange({ type: 'forward', payload: p })}
        />
      )

    case 'rsvp_meeting':
      return (
        <RsvpMeetingForm
          payload={action.payload}
          onChange={p => onChange({ type: 'rsvp_meeting', payload: p })}
        />
      )

    case 'create_snoozed_followup_draft':
      return (
        <CreateSnoozedFollowupDraftForm
          payload={action.payload}
          onChange={p => onChange({ type: 'create_snoozed_followup_draft', payload: p })}
        />
      )

    case 'mark_with_emoji':
      return (
        <MarkWithEmojiForm
          payload={action.payload}
          onChange={p => onChange({ type: 'mark_with_emoji', payload: p })}
        />
      )

    case 'apply_label':
      return (
        <ApplyLabelForm
          payload={action.payload}
          onChange={p => onChange({ type: 'apply_label', payload: p })}
        />
      )

    case 'create_reminder':
      return (
        <CreateReminderForm
          payload={action.payload}
          onChange={p => onChange({ type: 'create_reminder', payload: p })}
        />
      )

    case 'create_calendar_event':
      return (
        <CreateCalendarEventForm
          payload={action.payload}
          onChange={p => onChange({ type: 'create_calendar_event', payload: p })}
        />
      )

    default:
      return null
  }
}

interface MarkReadFormProps {
  payload: MarkReadPayload
  onChange: (next: MarkReadPayload) => void
}

function MarkReadForm({ payload, onChange }: MarkReadFormProps) {
  const { t } = useTranslation('settings')
  return (
    <div className="quickstep-action-body">
      <div className="qs-segmented" role="radiogroup">
        <button
          type="button"
          role="radio"
          aria-checked={payload.value}
          className="qs-segmented__opt"
          data-active={payload.value || undefined}
          onClick={() => onChange({ value: true })}
        >
          <CheckCircleIcon />
          {t('quicksteps_mark_as_read', { defaultValue: 'Marquer comme lu' })}
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={!payload.value}
          className="qs-segmented__opt"
          data-active={!payload.value || undefined}
          onClick={() => onChange({ value: false })}
        >
          <DotIcon />
          {t('quicksteps_mark_as_unread', { defaultValue: 'Marquer comme non lu' })}
        </button>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- //
// RsvpMeetingForm — response picker + availability check toggle
// --------------------------------------------------------------------------- //

interface RsvpMeetingFormProps {
  payload: RsvpMeetingPayload
  onChange: (next: RsvpMeetingPayload) => void
}

function RsvpMeetingForm({ payload, onChange }: RsvpMeetingFormProps) {
  const { t } = useTranslation('settings')
  const nameBase = `rsvp-response-${Math.random().toString(36).slice(2)}`
  return (
    <div className="quickstep-action-body">
      <div className="quickstep-action-body__field">
        <span className="quickstep-action-body__label">
          {t('quicksteps_rsvp_response_label', { defaultValue: 'Réponse' })}
        </span>
        <div className="qs-rsvp-options">
          {(['accepted', 'declined', 'tentative'] as const).map(r => (
            <label key={r} className="qs-rsvp-option">
              <input
                type="radio"
                name={nameBase}
                value={r}
                checked={payload.response === r}
                onChange={() => onChange({ ...payload, response: r })}
              />
              {r === 'accepted'
                ? t('quicksteps_rsvp_accepted', { defaultValue: 'Accepter' })
                : r === 'declined'
                  ? t('quicksteps_rsvp_declined', { defaultValue: 'Décliner' })
                  : t('quicksteps_rsvp_tentative', { defaultValue: 'Peut-être' })}
            </label>
          ))}
        </div>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- //
// CreateSnoozedFollowupDraftForm — template body + snooze delay
// --------------------------------------------------------------------------- //

interface CreateSnoozedFollowupDraftFormProps {
  payload: CreateSnoozedFollowupDraftPayload
  onChange: (next: CreateSnoozedFollowupDraftPayload) => void
}

function CreateSnoozedFollowupDraftForm({
  payload, onChange,
}: CreateSnoozedFollowupDraftFormProps) {
  const { t } = useTranslation('settings')
  const idBase = `qs-snoozed-draft-${Math.random().toString(36).slice(2)}`
  const days = payload.delay_days || 7
  // `{x}` champs-dynamiques menu. Tokens are double-brace (`{{recipient_name}}`)
  // here — the chip carries the bare name in data-ar-token and the backend
  // (_render_body in create_snoozed_followup_draft.py) converts pills → {{token}}.
  const placeholders: PlaceholderSuggestion[] = [
    {
      id: 'recipient_name',
      label: t('quicksteps_snoozed_draft_var_recipient_label', { defaultValue: 'Recipient name' }),
    },
    {
      id: 'recipient_first_name',
      label: t('quicksteps_snoozed_draft_var_first_name_label', { defaultValue: 'First name' }),
    },
    {
      id: 'original_subject',
      label: t('quicksteps_snoozed_draft_var_subject_label', { defaultValue: 'Original subject' }),
    },
  ].map(v => ({
    ...v,
    preview: `{{${v.id}}}`,
    buildHtml: () => buildTokenChipHtml(v.id, v.label),
  }))

  return (
    <div className="quickstep-action-body">
      <div className="qs-snoozed-draft-explainer">
        <div className="qs-snoozed-draft-explainer__title">
          {t('quicksteps_snoozed_draft_explainer_title', {
            defaultValue: 'How this works',
          })}
        </div>
        <ol className="qs-snoozed-draft-explainer__steps">
          <li>
            <strong>
              {t('quicksteps_snoozed_draft_explainer_now', {
                defaultValue: 'Now',
              })}
            </strong>
            {' — '}
            {t('quicksteps_snoozed_draft_explainer_step1', {
              defaultValue: 'creates a follow-up draft and tucks it into Later.',
            })}
          </li>
          <li>
            <strong>
              {t('quicksteps_snoozed_draft_explainer_then', {
                defaultValue: days === 1 ? 'In {{count}} day' : 'In {{count}} days',
                count: days,
              })}
            </strong>
            {' — '}
            {t('quicksteps_snoozed_draft_explainer_step2', {
              defaultValue: 'checks whether the recipient replied to your original email.',
            })}
          </li>
          <li>
            <strong>
              {t('quicksteps_snoozed_draft_explainer_outcome', {
                defaultValue: 'Then',
              })}
            </strong>
            {' — '}
            {t('quicksteps_snoozed_draft_explainer_step3', {
              defaultValue:
                'Reply found → draft deleted. No reply → the original thread comes back to your inbox top with the draft pre-loaded (also visible in Drafts with the ⚡ Auto badge).',
            })}
          </li>
        </ol>
      </div>
      <div className="quickstep-action-body__field">
        <label className="quickstep-action-body__label" htmlFor={`${idBase}-days`}>
          {t('quicksteps_snoozed_draft_delay_label', {
            defaultValue: 'Days before the draft appears',
          })}
        </label>
        <input
          id={`${idBase}-days`}
          type="number"
          min={1}
          max={365}
          value={payload.delay_days}
          onChange={e => {
            const n = Math.max(
              1,
              Math.min(365, Number.parseInt(e.target.value, 10) || 1),
            )
            onChange({ ...payload, delay_days: n })
          }}
          style={{ width: '6rem' }}
        />
      </div>
      <div className="quickstep-action-body__field">
        <label className="quickstep-action-body__label" htmlFor={`${idBase}-body`}>
          {t('quicksteps_snoozed_draft_body_label', {
            defaultValue: 'Draft body',
          })}
        </label>
        <RichTextEditor
          value={payload.body}
          onChange={body => onChange({ ...payload, body })}
          placeholder={t('quicksteps_snoozed_draft_body_placeholder', {
            defaultValue:
              'Hi {{recipient_name}},\n\nJust wanted to follow up on my last email. Let me know if you need anything from my side.',
          })}
          ariaLabel={t('quicksteps_snoozed_draft_body_label', { defaultValue: 'Draft body' })}
          minHeight={120}
          enableSnippets={false}
          placeholders={placeholders}
        />
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- //
// CreateReminderForm / CreateCalendarEventForm — deadline-driven actions.
// Both schedule something `days_before` the deadline detected on the email
// (pair with the has_deadline_detected trigger). The reminder is local
// (reminder_service); the calendar event writes to the connected calendar.
// --------------------------------------------------------------------------- //

interface CreateReminderFormProps {
  payload: CreateReminderPayload
  onChange: (next: CreateReminderPayload) => void
}

function CreateReminderForm({ payload, onChange }: CreateReminderFormProps) {
  const { t } = useTranslation('settings')
  const idBase = `qs-reminder-${Math.random().toString(36).slice(2)}`
  return (
    <div className="quickstep-action-body">
      <div className="quickstep-action-body__field">
        <label className="quickstep-action-body__label" htmlFor={`${idBase}-days`}>
          {t('quicksteps_deadline_days_before_label', { defaultValue: "Jours avant l'échéance" })}
        </label>
        <input
          id={`${idBase}-days`}
          type="number"
          min={0}
          max={365}
          value={payload.days_before}
          onChange={e => {
            const n = Math.max(0, Math.min(365, Number.parseInt(e.target.value, 10) || 0))
            onChange({ ...payload, days_before: n })
          }}
          style={{ width: '6rem' }}
        />
        <span className="quickstep-action-body__hint">
          {t('quicksteps_reminder_hint', {
            defaultValue:
              "Crée un rappel local quand une échéance est détectée sur l'email. 0 = le jour même.",
          })}
        </span>
      </div>
    </div>
  )
}

interface CreateCalendarEventFormProps {
  payload: CreateCalendarEventPayload
  onChange: (next: CreateCalendarEventPayload) => void
}

function CreateCalendarEventForm({ payload, onChange }: CreateCalendarEventFormProps) {
  const { t } = useTranslation('settings')
  const idBase = `qs-calevent-${Math.random().toString(36).slice(2)}`
  return (
    <div className="quickstep-action-body">
      <div className="quickstep-action-body__field">
        <label className="quickstep-action-body__label" htmlFor={`${idBase}-days`}>
          {t('quicksteps_deadline_days_before_label', { defaultValue: "Jours avant l'échéance" })}
        </label>
        <input
          id={`${idBase}-days`}
          type="number"
          min={0}
          max={365}
          value={payload.days_before}
          onChange={e => {
            const n = Math.max(0, Math.min(365, Number.parseInt(e.target.value, 10) || 0))
            onChange({ ...payload, days_before: n })
          }}
          style={{ width: '6rem' }}
        />
      </div>
      <div className="quickstep-action-body__field">
        <label className="quickstep-action-body__label" htmlFor={`${idBase}-duration`}>
          {t('quicksteps_calendar_event_duration_label', { defaultValue: 'Durée (minutes)' })}
        </label>
        <input
          id={`${idBase}-duration`}
          type="number"
          min={1}
          max={1440}
          value={payload.duration_minutes}
          onChange={e => {
            const n = Math.max(1, Math.min(1440, Number.parseInt(e.target.value, 10) || 1))
            onChange({ ...payload, duration_minutes: n })
          }}
          style={{ width: '6rem' }}
        />
        <span className="quickstep-action-body__hint">
          {t('quicksteps_calendar_event_hint', {
            defaultValue:
              "Crée un événement dans ton agenda connecté avant l'échéance détectée.",
          })}
        </span>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- //
// MarkWithEmojiForm — curated emoji grid + optional text + "include deadline"
// --------------------------------------------------------------------------- //

interface MarkWithEmojiFormProps {
  payload: MarkWithEmojiPayload
  onChange: (next: MarkWithEmojiPayload) => void
}

// Exported for unit testing (MarkWithEmojiForm.test.tsx) — it's an internal
// sub-form of the manager, but the swatch picker + chip toggle interactions
// are worth exercising in isolation.
export function MarkWithEmojiForm({ payload, onChange }: MarkWithEmojiFormProps) {
  const { t } = useTranslation('settings')
  const idBase = useId()
  const selected: QuickStepEmoji | '' = payload.emoji ?? '⏰'
  const text = payload.text ?? ''
  return (
    <div className="quickstep-action-body">
      <div className="quickstep-action-body__field">
        <span className="quickstep-action-body__label">
          {t('quicksteps_mark_emoji_label', { defaultValue: 'Emoji' })}
        </span>
        <div className="qs-emoji-grid" role="radiogroup" aria-label={t('quicksteps_mark_emoji_label', { defaultValue: 'Emoji' })}>
          {/* "No emoji" tile — builds a text-only marker (emoji=""). The
              backend accepts it as long as `text` is non-empty. */}
          <button
            type="button"
            data-testid="qs-marker-emoji-none"
            className={`qs-emoji-grid__item qs-emoji-grid__item--none${selected === '' ? ' qs-emoji-grid__item--selected' : ''}`}
            role="radio"
            aria-checked={selected === ''}
            aria-label={t('quicksteps_mark_emoji_none', { defaultValue: 'No emoji' })}
            title={t('quicksteps_mark_emoji_none', { defaultValue: 'No emoji' })}
            onClick={() => onChange({ ...payload, emoji: '' })}
          />
          {QUICK_STEP_EMOJI_WHITELIST.map(e => (
            <button
              key={e}
              type="button"
              className={`qs-emoji-grid__item${e === selected ? ' qs-emoji-grid__item--selected' : ''}`}
              role="radio"
              aria-checked={e === selected}
              onClick={() => onChange({ ...payload, emoji: e })}
            >
              {e}
            </button>
          ))}
        </div>
      </div>
      <div className="quickstep-action-body__field">
        <label className="quickstep-action-body__label" htmlFor={`${idBase}-text`}>
          {t('quicksteps_mark_emoji_text_label', { defaultValue: 'Text' })}
        </label>
        <input
          id={`${idBase}-text`}
          type="text"
          value={text}
          maxLength={24}
          placeholder={t('quicksteps_mark_emoji_text_placeholder', {
            defaultValue: 'e.g. "Stripe", "VIP", "Urgent"',
          })}
          onChange={e => onChange({ ...payload, text: e.target.value })}
          style={{ width: '100%' }}
        />
        <span className="quickstep-action-body__hint">
          {t('quicksteps_mark_emoji_text_hint', {
            defaultValue: 'Shown next to the emoji on the inbox row (max 24 chars).',
          })}
        </span>
      </div>
      <div className="quickstep-action-body__field">
        <span className="quickstep-action-body__label">
          {t('quicksteps_mark_emoji_color_label', { defaultValue: 'Color' })}
        </span>
        <div
          className="qs-color-grid"
          role="radiogroup"
          aria-label={t('quicksteps_mark_emoji_color_label', { defaultValue: 'Color' })}
        >
          {/* Default monochrome tile — clears the color back to the quiet chip. */}
          <button
            type="button"
            data-testid="qs-marker-color-none"
            className={`qs-color-grid__item qs-color-grid__item--none${
              !payload.color ? ' qs-color-grid__item--selected' : ''
            }`}
            role="radio"
            aria-checked={!payload.color}
            aria-label={t('quicksteps_mark_emoji_color_none', { defaultValue: 'No color' })}
            title={t('quicksteps_mark_emoji_color_none', { defaultValue: 'No color' })}
            onClick={() => onChange({ ...payload, color: undefined })}
          />
          {LABEL_COLORS.map(c => (
            <button
              key={c}
              type="button"
              className={`qs-color-grid__item${
                c === payload.color ? ' qs-color-grid__item--selected' : ''
              }`}
              role="radio"
              aria-checked={c === payload.color}
              aria-label={c}
              title={c}
              style={{ backgroundColor: c }}
              onClick={() => onChange({ ...payload, color: c })}
            />
          ))}
        </div>
      </div>
      <div className="quickstep-action-body__field">
        <label className="quickstep-action-body__check">
          <input
            type="checkbox"
            data-testid="qs-marker-chip-toggle"
            checked={payload.chip !== false}
            onChange={e => onChange({ ...payload, chip: e.target.checked })}
          />
          <span>
            {t('quicksteps_mark_emoji_chip_label', { defaultValue: 'Show as a chip' })}
          </span>
        </label>
        <span className="quickstep-action-body__hint">
          {t('quicksteps_mark_emoji_chip_hint', {
            defaultValue: 'Off renders the emoji and text bare, with no background.',
          })}
        </span>
      </div>
      <div className="quickstep-action-body__field">
        <label className="quickstep-action-body__check">
          <input
            type="checkbox"
            checked={!!payload.include_deadline}
            onChange={e => onChange({ ...payload, include_deadline: e.target.checked })}
          />
          <span>
            {t('quicksteps_mark_emoji_include_deadline', {
              defaultValue: 'Merge the auto-detected deadline into this chip',
            })}
          </span>
        </label>
        <span className="quickstep-action-body__hint">
          {t('quicksteps_mark_emoji_include_deadline_hint', {
            defaultValue: 'When the email has a detected deadline, render it as "{{emoji}} text · Mar 15th" and hide the standalone clock chip.',
            emoji: selected,
          })}
        </span>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- //
// ApplyLabelForm — pick a label to stamp on the email. Reuses the same
// label list + ValueDropdown as the has_label condition so the action and
// the condition that reads it share one picker.
// --------------------------------------------------------------------------- //

interface ApplyLabelFormProps {
  payload: ApplyLabelPayload
  onChange: (next: ApplyLabelPayload) => void
}

function ApplyLabelForm({ payload, onChange }: ApplyLabelFormProps) {
  const { t } = useTranslation('settings')
  const [labels, setLabels] = useState<{ name: string; color: string }[]>([])

  useEffect(() => {
    fetchLabels()
      .then(res => setLabels(res.labels.map(l => ({ name: l.name, color: l.color }))))
      .catch(err => console.warn('[QuickStepsManager] label fetch failed:', err))
  }, [])

  return (
    <div className="quickstep-action-body">
      <div className="quickstep-action-body__field">
        <span className="quickstep-action-body__label">
          {t('quicksteps_apply_label_field', { defaultValue: 'Label' })}
        </span>
        <ValueDropdown
          value={payload.label}
          options={labels.map(l => ({
            id: l.name,
            label: getLabelDisplayName(l.name),
            color: l.color,
          }))}
          placeholder={t('quicksteps_apply_label_placeholder', {
            defaultValue: '— Choisir un label —',
          })}
          ariaLabel={t('quicksteps_apply_label_field', { defaultValue: 'Label' })}
          onSelect={v => onChange({ ...payload, label: v })}
        />
        <span className="quickstep-action-body__hint">
          {t('quicksteps_apply_label_hint', {
            defaultValue:
              'Le label est ajouté à l\'email. Un label de catégorie (Action, Info, Bruit) remplace la catégorie ; les autres s\'ajoutent à côté.',
          })}
        </span>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- //
// ReplyTemplateForm — variable chips, live preview, snippet picker
// --------------------------------------------------------------------------- //

interface ReplyTemplateFormProps {
  payload: ReplyTemplatePayload
  onChange: (next: ReplyTemplatePayload) => void
}

function ReplyTemplateForm({ payload, onChange }: ReplyTemplateFormProps) {
  const { t } = useTranslation('settings')
  const placeholders = useQuickStepPlaceholders()

  return (
    <div className="quickstep-action-body">
      <label className="quickstep-action-body__check">
        <input
          type="checkbox"
          checked={payload.replyAll}
          onChange={e => onChange({ ...payload, replyAll: e.target.checked })}
        />
        {t('quicksteps_reply_all', { defaultValue: 'Répondre à tous' })}
      </label>
      {!payload.snippet_id && (
        <>
          <RichTextEditor
            value={payload.body}
            onChange={body => onChange({ ...payload, body })}
            placeholder={t('quicksteps_reply_placeholder', {
              defaultValue: 'Bonjour {sender.firstname}, ...',
            })}
            minHeight={160}
            enableSnippets={false}
            placeholders={placeholders}
          />

          <SignatureFooter className="qs-signature-footer" />
        </>
      )}
    </div>
  )
}

// --------------------------------------------------------------------------- //
// ForwardForm — variable chips, live preview, contact group picker
// --------------------------------------------------------------------------- //

interface ForwardFormProps {
  payload: ForwardPayload
  onChange: (next: ForwardPayload) => void
}

function ForwardForm({ payload, onChange }: ForwardFormProps) {
  const { t } = useTranslation('settings')
  const [preview, setPreview] = useState(false)
  const { groups } = useContactGroups()
  const placeholders = useQuickStepPlaceholders()

  const recipientsText = payload.to.join(', ')
  const selectedGroupIds = payload.to_groups ?? []

  const toggleGroup = (id: string) => {
    const next = selectedGroupIds.includes(id)
      ? selectedGroupIds.filter(g => g !== id)
      : [...selectedGroupIds, id]
    onChange({ ...payload, to_groups: next.length > 0 ? next : undefined })
  }

  return (
    <div className="quickstep-action-body">
      <div className="quickstep-action-body__field">
        <FieldLabel
          label={t('quicksteps_recipients', { defaultValue: 'Destinataires' })}
        />
        <ContactAutocomplete
          value={recipientsText}
          onChange={value =>
            onChange({
              ...payload,
              to: value
                .split(',')
                .map(s => s.trim())
                .filter(Boolean),
            })
          }
          placeholder={t('quicksteps_recipients_placeholder', {
            defaultValue: 'support@agentys.io',
          })}
          fieldId="to"
          multi
          includeAllContacts
          includeSelf
        />
      </div>

      {groups.length > 0 && (
        <div className="quickstep-action-body__field">
          <FieldLabel
            label={t('quicksteps_groups', { defaultValue: 'Groupes de contacts' })}
            hint={t('quicksteps_groups_hint', { defaultValue: 'optionnel' })}
          />
          <div className="qs-group-chips">
            {groups.map(g => {
              const selected = selectedGroupIds.includes(g.id)
              return (
                <button
                  key={g.id}
                  type="button"
                  className={`qs-group-chip${selected ? ' qs-group-chip--selected' : ''}`}
                  onClick={() => toggleGroup(g.id)}
                  title={g.members.map(m => m.email).join(', ')}
                >
                  {g.emoji && <span aria-hidden="true">{g.emoji} </span>}
                  {g.name}
                  <span className="qs-group-chip__count">{g.members.length}</span>
                  {selected && <span className="qs-group-chip__check" aria-hidden="true">✓</span>}
                </button>
              )
            })}
          </div>
        </div>
      )}

      <div className="quickstep-action-body__field">
        {(payload.body || preview) && (
          <div className="qs-body-header">
            <button
              type="button"
              className={`qs-preview-toggle${preview ? ' qs-preview-toggle--active' : ''}`}
              onClick={() => setPreview(p => !p)}
            >
              <EyeIcon />
              {preview
                ? t('quicksteps_preview_off', { defaultValue: 'Éditer' })
                : t('quicksteps_preview_on', { defaultValue: 'Aperçu' })}
            </button>
          </div>
        )}

        {preview ? (
          <div
            className="qs-preview-pane"
            dangerouslySetInnerHTML={{ __html: renderPreview(payload.body || '') }}
          />
        ) : (
          <RichTextEditor
            value={payload.body || ''}
            onChange={body => onChange({ ...payload, body: body || undefined })}
            placeholder=""
            minHeight={140}
            enableSnippets={false}
            placeholders={placeholders}
          />
        )}

        {!preview && <SignatureFooter className="qs-signature-footer" />}
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- //
// Auto-trigger section — configure conditions that run the step automatically
// --------------------------------------------------------------------------- //

type TriggerCategory = 'sender' | 'content' | 'classification' | 'advanced'

interface TriggerTypeMeta {
  type: TriggerConditionType
  category: TriggerCategory
}

// Picker display order: 3 plain-language groups first, then "Advanced"
// (rule-chaining + sent/reply-side helpers) last.
const TRIGGER_CONDITION_TYPES_GROUPED: TriggerTypeMeta[] = [
  { type: 'sender', category: 'sender' },
  { type: 'sender_domain', category: 'sender' },
  { type: 'recipient', category: 'sender' },
  { type: 'email_text', category: 'content' },
  { type: 'has_attachment', category: 'content' },
  { type: 'has_deadline_detected', category: 'content' },
  { type: 'has_label', category: 'classification' },
  { type: 'is_read', category: 'classification' },
  { type: 'calendar_invite', category: 'classification' },
  { type: 'email_older_than_days', category: 'classification' },
  { type: 'no_reply_after_days', category: 'advanced' },
  { type: 'is_new_thread', category: 'advanced' },
  { type: 'thread_has_user_reply', category: 'advanced' },
  { type: 'previously_auto_actioned_by', category: 'advanced' },
  { type: 'has_emoji_marker', category: 'advanced' },
]

const TRIGGER_CONDITION_TYPES: TriggerConditionType[] =
  TRIGGER_CONDITION_TYPES_GROUPED.map(m => m.type)

function triggerCategoryLabel(category: TriggerCategory, t: TFn): string {
  switch (category) {
    case 'sender':
      return t('quicksteps_trigger_cat_sender', { defaultValue: 'Qui l\'envoie' })
    case 'content':
      return t('quicksteps_trigger_cat_content', { defaultValue: 'Ce qu\'il contient' })
    case 'classification':
      return t('quicksteps_trigger_cat_classification', { defaultValue: 'Ce que c\'est' })
    case 'advanced':
      return t('quicksteps_trigger_cat_advanced', { defaultValue: 'Avancé' })
  }
}

/** Optional context that makes some labels read more naturally:
 *  - `negate`: when set, the function returns the inverse phrasing for
 *    boolean-typed conditions so the row doesn't read as a double-negative
 *    (e.g. ``is_new_thread`` becomes "Sent emails in existing thread"
 *    when negate=true on a sent rule).
 *  - `firesOn`: scopes the phrasing to the mail flow the rule runs on.
 *    Sent-side rules talk about "Sent emails…"; received-side rules talk
 *    about incoming threads. Without this, the same label has to be
 *    flow-neutral and ends up less readable.
 *  Both are optional — the picker dropdown calls without context and falls
 *  back to the base label.
 */
interface TriggerLabelOpts {
  negate?: boolean
  firesOn?: 'received' | 'sent'
  matchMode?: TriggerMatchMode
}

function triggerTypeLabel(type: TriggerConditionType, t: TFn, opts: TriggerLabelOpts = {}): string {
  switch (type) {
    case 'sender':
      return t('quicksteps_trigger_sender', { defaultValue: 'Expéditeur' })
    case 'sender_domain':
      return t('quicksteps_trigger_sender_domain', { defaultValue: 'Domaine expéditeur' })
    case 'recipient':
      return t('quicksteps_trigger_recipient', { defaultValue: 'Destinataire' })
    case 'email_text':
      return t('quicksteps_trigger_email_text', { defaultValue: 'Texte de l\'email' })
    case 'has_label':
      return t('quicksteps_trigger_has_label', { defaultValue: 'Label' })
    case 'has_attachment':
      return t('quicksteps_trigger_has_attachment', { defaultValue: 'Pièce jointe' })
    case 'is_read':
      return t('quicksteps_trigger_is_read', { defaultValue: 'Lu / non lu' })
    case 'calendar_invite':
      return t('quicksteps_trigger_calendar_invite', { defaultValue: 'Invitation' })
    case 'has_deadline_detected':
      return t('quicksteps_trigger_has_deadline_detected', { defaultValue: 'Échéance détectée' })
    case 'has_emoji_marker':
      return t('quicksteps_trigger_has_emoji_marker', { defaultValue: 'Marqueur emoji' })
    case 'email_older_than_days':
      return t('quicksteps_trigger_email_older_than', { defaultValue: 'Plus ancien que' })
    case 'no_reply_after_days':
      return t('quicksteps_trigger_no_reply_after', { defaultValue: 'Sans réponse depuis' })
    case 'previously_auto_actioned_by':
      return t('quicksteps_trigger_previously_auto_actioned_by', {
        defaultValue: 'Déjà traité par une règle',
      })
    case 'is_new_thread': {
      // 4 phrasings depending on (firesOn, negate). The default for the
      // picker dropdown (no opts passed) is the sent+positive variant —
      // by far the most common use case for this condition.
      const sent = opts.firesOn !== 'received'
      if (sent && opts.negate) {
        return t('quicksteps_trigger_is_new_thread_sent_negated', {
          defaultValue: 'Sent emails in existing thread',
        })
      }
      if (sent) {
        return t('quicksteps_trigger_is_new_thread_sent', {
          defaultValue: 'Sent emails in a new thread',
        })
      }
      if (opts.negate) {
        return t('quicksteps_trigger_is_new_thread_received_negated', {
          defaultValue: 'Reply in an existing thread',
        })
      }
      return t('quicksteps_trigger_is_new_thread_received', {
        defaultValue: 'New incoming thread (not a reply)',
      })
    }
    case 'thread_has_user_reply':
      return t('quicksteps_trigger_thread_has_user_reply', {
        defaultValue: 'I replied to this thread',
      })
    default: {
      // Exhaustiveness guard: forces a TS error if a new TriggerConditionType
      // is added without a matching case here.
      const _exhaustive: never = type
      return _exhaustive
    }
  }
}

function triggerValuePlaceholder(type: TriggerConditionType, matchMode?: TriggerMatchMode): string {
  // The "matches" mode wants a regex pattern example, not a literal one.
  if (matchMode === 'matches') {
    switch (type) {
      case 'sender': return 'noreply|no-reply|donotreply'
      case 'sender_domain': return '\\.google\\.com$'
      case 'recipient': return 'alerts\\+\\w+@'
      default: break
    }
  }
  switch (type) {
    case 'sender': return 'boss@exemple.com'
    case 'sender_domain': return 'exemple.com'
    case 'recipient': return 'team@exemple.com'
    case 'email_text': return 'facture'
    case 'has_label': return 'VIP'
    case 'has_attachment': return 'true'
    case 'is_read': return 'true'
    case 'calendar_invite': return 'true'
    case 'email_older_than_days': return '7'
    case 'no_reply_after_days': return '3'
    case 'previously_auto_actioned_by': return ''
    case 'is_new_thread': return 'true'
    case 'thread_has_user_reply': return 'true'
    case 'has_deadline_detected': return 'true'
    case 'has_emoji_marker': return '🔥'
  }
}

/**
 * Short contextual hint shown below the row's value input. Helps users grok
 * what a regex condition actually matches (the #1 source of "I typed the
 * pattern but my QuickStep never fires" support questions). Returned `null`
 * → no hint rendered.
 */
function triggerValueHint(
  type: TriggerConditionType,
  matchMode: TriggerMatchMode | undefined,
  t: TFn,
): string | null {
  // match_mode-specific hints come first — the #1 "I typed the pattern
  // but my rule never fires" confusion is the regex mode.
  if (matchMode === 'matches') {
    return t('quicksteps_trigger_hint_matches', {
      defaultValue: 'Motif regex (insensible à la casse) cherché n\'importe où dans le champ. Ex : noreply|no-reply attrape les 2 variantes.',
    })
  }
  if (type === 'recipient' && matchMode === 'is') {
    return t('quicksteps_trigger_hint_recipient_is', {
      defaultValue: 'Match si le texte est exactement l\'une des adresses To / Cc.',
    })
  }
  if (type === 'calendar_invite' && matchMode === 'free') {
    return t('quicksteps_trigger_hint_calendar_invite_free', {
      defaultValue: 'Match seulement si ton agenda ET tes blocs de concentration sont libres pendant le créneau proposé — idéal pour auto-accepter quand tu es vraiment dispo.',
    })
  }
  switch (type) {
    case 'previously_auto_actioned_by':
      return t('quicksteps_trigger_hint_previously_auto_actioned_by', {
        defaultValue: 'Match si la quick action choisie s\'est déjà déclenchée automatiquement sur un email de ce thread. Permet de réagir à ses propres décisions (ex : auto-archivée puis nouvelle réponse → ramener en inbox).',
      })
    case 'thread_has_user_reply':
      return t('quicksteps_trigger_hint_thread_has_user_reply', {
        defaultValue: 'Match dès que tu as envoyé au moins un message dans le thread. Combine avec l\'action Archiver pour reproduire « auto-archive après réponse ».',
      })
    default:
      return null
  }
}

/** Conditions whose value is a positive integer with a unit (days / minutes). */
function triggerValueUnit(type: TriggerConditionType, t: TFn): string | null {
  switch (type) {
    case 'email_older_than_days':
    case 'no_reply_after_days':
      return t('quicksteps_unit_days', { defaultValue: 'jours' })
    default:
      return null
  }
}

// Negation makes no sense for temporal "older than N" conditions — the label
// already carries the comparison ("Older than 7 days") so the =/≠ toggle just
// looks like a misleading equality operator.
function triggerSupportsNegate(type: TriggerConditionType): boolean {
  return type !== 'email_older_than_days' && type !== 'no_reply_after_days'
}

/** Conditions rendered as a static badge (the type itself carries the meaning). */
function triggerValueIsBadge(type: TriggerConditionType): boolean {
  return type === 'calendar_invite'
    || type === 'has_attachment'
    || type === 'is_read'
    || type === 'is_new_thread'
    || type === 'thread_has_user_reply'
    || type === 'has_deadline_detected'
    || type === 'has_emoji_marker'
}

function triggerValueBadgeLabel(type: TriggerConditionType, t: TFn, opts: TriggerLabelOpts = {}): string {
  switch (type) {
    case 'calendar_invite':
      return opts.matchMode === 'free'
        ? t('quicksteps_trigger_calendar_invite_free_badge', {
            defaultValue: 'invitation + agenda libre',
          })
        : t('quicksteps_trigger_calendar_invite_badge', {
            defaultValue: 'email avec invitation',
          })
    case 'has_attachment':
      return t('quicksteps_trigger_has_attachment_badge', { defaultValue: 'avec pièce jointe' })
    case 'is_read':
      return t('quicksteps_trigger_is_read_badge', { defaultValue: 'email lu' })
    case 'is_new_thread': {
      const sent = opts.firesOn !== 'received'
      if (sent && opts.negate) {
        return t('quicksteps_trigger_is_new_thread_sent_negated_badge', {
          defaultValue: 'in existing thread',
        })
      }
      if (sent) {
        return t('quicksteps_trigger_is_new_thread_sent_badge', {
          defaultValue: 'in a new thread',
        })
      }
      if (opts.negate) {
        return t('quicksteps_trigger_is_new_thread_received_negated_badge', {
          defaultValue: 'reply in existing thread',
        })
      }
      return t('quicksteps_trigger_is_new_thread_received_badge', {
        defaultValue: 'thread starter',
      })
    }
    case 'thread_has_user_reply':
      return t('quicksteps_trigger_thread_has_user_reply_badge', {
        defaultValue: 'I replied to this thread',
      })
    case 'has_deadline_detected':
      return t('quicksteps_trigger_has_deadline_detected_badge', {
        defaultValue: 'deadline detected in body',
      })
    case 'has_emoji_marker':
      return t('quicksteps_trigger_has_emoji_marker_badge', {
        defaultValue: 'emoji marker present',
      })
    default:
      return ''
  }
}

/**
 * Human label for a `match_mode` value. The value strings are globally
 * unique across the three groups (text / scope / invite), so one switch
 * covers every condition type.
 */
function triggerMatchModeLabel(mode: TriggerMatchMode, t: TFn): string {
  switch (mode) {
    case 'is':
      return t('quicksteps_match_mode_is', { defaultValue: 'est exactement' })
    case 'contains':
      return t('quicksteps_match_mode_contains', { defaultValue: 'contient' })
    case 'matches':
      return t('quicksteps_match_mode_matches', { defaultValue: 'correspond au motif' })
    case 'anywhere':
      return t('quicksteps_match_mode_anywhere', { defaultValue: 'n\'importe où' })
    case 'subject':
      return t('quicksteps_match_mode_subject', { defaultValue: 'dans le sujet' })
    case 'body':
      return t('quicksteps_match_mode_body', { defaultValue: 'dans le corps' })
    case 'any':
      return t('quicksteps_match_mode_any', { defaultValue: 'n\'importe laquelle' })
    case 'free':
      return t('quicksteps_match_mode_free', { defaultValue: 'quand je suis libre' })
  }
}

/** ValueDropdown options for a type's allowed match_modes (display order). */
function triggerMatchModeOptions(type: TriggerConditionType, t: TFn): ValueDropdownOption[] {
  return TRIGGER_MATCH_MODES[type].map(mode => ({
    id: mode,
    label: triggerMatchModeLabel(mode, t),
  }))
}

// --------------------------------------------------------------------------- //
// Step 2 — Conditions: standalone, always visible. Decoupled from auto-trigger
// so the user can think "when does this apply?" before "should it auto-fire?".
// --------------------------------------------------------------------------- //

interface ConditionsSectionProps {
  triggers: TriggerCondition[]
  triggerOperator: 'AND' | 'OR'
  firesOn: 'received' | 'sent'
  onChange: (patch: Partial<QuickStep>) => void
  siblingSteps: QuickStep[]
}

function ConditionsSection({ triggers, triggerOperator, firesOn, onChange, siblingSteps }: ConditionsSectionProps) {
  const { t } = useTranslation('settings')
  const [labels, setLabels] = useState<{ name: string; color: string }[]>([])

  useEffect(() => {
    fetchLabels()
      .then(res => setLabels(res.labels.map(l => ({ name: l.name, color: l.color }))))
      .catch(err => console.warn('[QuickStepsManager] label fetch failed:', err))
  }, [])

  const addCondition = () => {
    if (triggers.length >= 5) return
    const type: TriggerConditionType = 'sender'
    const next: TriggerCondition = { type, value: defaultTriggerValue(type) }
    const mm = defaultTriggerMatchMode(type)
    if (mm) next.match_mode = mm
    onChange({ triggers: [...triggers, next] })
  }

  const updateCondition = (index: number, next: TriggerCondition) => {
    onChange({ triggers: triggers.map((c, i) => (i === index ? next : c)) })
  }

  const removeCondition = (index: number) => {
    onChange({ triggers: triggers.filter((_, i) => i !== index) })
  }

  return (
    <div className="qs-conditions">
      {triggers.length >= 2 && (
        <div className="qs-trigger-operator">
          <span className="qs-trigger-operator__label">
            {t('quicksteps_autotrigger_operator', { defaultValue: 'Correspondance' })}
          </span>
          <div className="qs-trigger-pills" role="radiogroup">
            <button
              type="button"
              role="radio"
              aria-checked={triggerOperator === 'AND'}
              className="qs-trigger-pill"
              data-active={triggerOperator === 'AND' || undefined}
              onClick={() => onChange({ triggerOperator: 'AND' })}
            >
              {t('quicksteps_autotrigger_op_and', { defaultValue: 'Toutes les conditions' })}
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={triggerOperator === 'OR'}
              className="qs-trigger-pill"
              data-active={triggerOperator === 'OR' || undefined}
              onClick={() => onChange({ triggerOperator: 'OR' })}
            >
              {t('quicksteps_autotrigger_op_or', { defaultValue: 'Au moins une' })}
            </button>
          </div>
        </div>
      )}

      {triggers.length > 0 && (
        <ul className="qs-trigger-list">
          {triggers.map((cond, index) => (
            // Audit 2026-05-11 F-02: composite key keeps TriggerTypePicker
            // open-state and TextInput refs from leaking across rows when
            // the user inserts/removes a condition mid-list.
            <li key={`${cond.type}-${index}`}>
              <TriggerConditionRow
                condition={cond}
                index={index}
                firesOn={firesOn}
                onChange={next => updateCondition(index, next)}
                onRemove={() => removeCondition(index)}
                labels={labels}
                siblingSteps={siblingSteps}
              />
            </li>
          ))}
        </ul>
      )}

      {triggers.length < 5 && (
        <button
          type="button"
          className="qs-trigger-add"
          onClick={addCondition}
        >
          <PlusIcon size={14} />
          {t('quicksteps_autotrigger_add_condition', { defaultValue: 'Ajouter une condition' })}
        </button>
      )}
    </div>
  )
}

// --------------------------------------------------------------------------- //
// Step 4 — Auto-trigger: a single toggle that says "fire automatically when
// the conditions above match". Disabled when no conditions exist (the schema
// rejects autoEnabled+empty-triggers anyway, so the UI hides the footgun).
// --------------------------------------------------------------------------- //

interface TriggerModeCardsProps {
  autoEnabled: boolean
  hasShortcut: boolean
  triggerCount: number
  onChange: (patch: Partial<QuickStep>) => void
}

/**
 * Step 4 — choose how the Quick Action fires: by user shortcut (manual)
 * or automatically when an incoming email matches the conditions.
 *
 * Two cards side-by-side replace the buried "(optional) auto-trigger" toggle.
 * Auto mode is disabled unless step.triggers has at least one entry — the
 * schema rejects autoEnabled+empty-triggers, and surfacing that here keeps
 * the user out of an invalid state.
 */
function TriggerModeCards({
  autoEnabled, hasShortcut, triggerCount, onChange,
}: TriggerModeCardsProps) {
  const { t } = useTranslation('settings')
  const autoDisabled = triggerCount === 0

  return (
    <div className="qs-mode-cards" role="radiogroup"
      aria-label={t('quicksteps_step_trigger_mode_label', { defaultValue: 'Comment déclencher' })}
    >
      <button
        type="button"
        role="radio"
        aria-checked={!autoEnabled}
        className="qs-mode-card"
        data-active={!autoEnabled || undefined}
        onClick={() => onChange({ autoEnabled: false })}
      >
        <div className="qs-mode-card__icon" aria-hidden="true">
          <KeyboardIcon />
        </div>
        <div className="qs-mode-card__text">
          <h3 className="qs-mode-card__title">
            {t('quicksteps_mode_manual_title', { defaultValue: 'Manuel' })}
          </h3>
          <p className="qs-mode-card__hint">
            {hasShortcut
              ? t('quicksteps_mode_manual_hint_shortcut', {
                  defaultValue: 'Déclenche au raccourci configuré à l\'étape 1, ou depuis l\'email.',
                })
              : t('quicksteps_mode_manual_hint_noshortcut', {
                  defaultValue: 'Lance depuis l\'email. Configure un raccourci à l\'étape 1 pour aller plus vite.',
                })}
          </p>
        </div>
      </button>
      <button
        type="button"
        role="radio"
        aria-checked={autoEnabled}
        className="qs-mode-card"
        data-active={autoEnabled || undefined}
        data-disabled={autoDisabled || undefined}
        disabled={autoDisabled}
        onClick={() => onChange({ autoEnabled: true })}
      >
        <div className="qs-mode-card__icon" aria-hidden="true">
          <ZapIcon />
        </div>
        <div className="qs-mode-card__text">
          <h3 className="qs-mode-card__title">
            {t('quicksteps_mode_auto_title', { defaultValue: 'Automatique' })}
          </h3>
          <p className="qs-mode-card__hint">
            {autoDisabled
              ? t('quicksteps_mode_auto_hint_needs_conditions', {
                  defaultValue: 'Ajoute au moins une condition à l\'étape 2 pour activer l\'auto.',
                })
              : t('quicksteps_mode_auto_hint', {
                  defaultValue: 'Se lance sans clic dès qu\'un email correspond aux conditions de l\'étape 2.',
                })}
          </p>
        </div>
      </button>
    </div>
  )
}


// --------------------------------------------------------------------------- //
// FiresOnSelector — sent vs received auto-flow toggle, shown once autoEnabled
// is on. Decides whether the daemon evaluates this Quick Action against
// incoming inbox emails or against the user's sent emails.
// --------------------------------------------------------------------------- //

interface FiresOnSelectorProps {
  firesOn: 'received' | 'sent'
  hasFollowUpAction: boolean
  onChange: (next: 'received' | 'sent') => void
}

function FiresOnSelector({ firesOn, hasFollowUpAction, onChange }: FiresOnSelectorProps) {
  const { t } = useTranslation('settings')
  // create_snoozed_followup_draft only makes sense on sent — the schema rejects
  // pairing it with received. Surface that here so the editor doesn't let users
  // build a config the backend will refuse to save.
  const sentForced = hasFollowUpAction
  return (
    <div
      className="qs-fires-on"
      role="radiogroup"
      aria-label={t('quicksteps_fires_on_label', { defaultValue: 'Sur quel flux' })}
      style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}
    >
      <span style={{ alignSelf: 'center', fontSize: 12, opacity: 0.7 }}>
        {t('quicksteps_fires_on_label', { defaultValue: 'Évalue sur :' })}
      </span>
      <button
        type="button"
        role="radio"
        aria-checked={firesOn === 'received'}
        data-active={firesOn === 'received' || undefined}
        disabled={sentForced}
        onClick={() => onChange('received')}
        className="quickstep-editor__chip"
      >
        {t('quicksteps_fires_on_received', { defaultValue: 'Emails reçus' })}
      </button>
      <button
        type="button"
        role="radio"
        aria-checked={firesOn === 'sent'}
        data-active={firesOn === 'sent' || undefined}
        onClick={() => onChange('sent')}
        className="quickstep-editor__chip"
      >
        {t('quicksteps_fires_on_sent', { defaultValue: 'Emails envoyés' })}
      </button>
      {sentForced && (
        <span style={{ alignSelf: 'center', fontSize: 11, opacity: 0.6 }}>
          {t('quicksteps_fires_on_locked_sent', {
            defaultValue: 'Verrouillé sur « envoyés » car la règle contient une action de relance.',
          })}
        </span>
      )}
    </div>
  )
}


// --------------------------------------------------------------------------- //
// AutoBadgeToggle — opt out of the ⚡ Auto chip on inbox rows this rule
// auto-actions. Default ON (transparency) ; user flips off per-rule when
// the badge contradicts intent (silent label-only rules).
// --------------------------------------------------------------------------- //

interface AutoBadgeToggleProps {
  showAutoBadge: boolean
  onChange: (next: boolean) => void
}

function AutoBadgeToggle({ showAutoBadge, onChange }: AutoBadgeToggleProps) {
  const { t } = useTranslation('settings')
  return (
    <label className="qs-auto-badge-toggle" data-on={showAutoBadge || undefined}>
      <span className="qs-auto-badge-toggle__sentence">
        {t('quicksteps_show_auto_badge_prefix', { defaultValue: 'Afficher le badge' })}
        {' '}
        <span className="qs-auto-badge-preview" aria-hidden="true">
          <svg
            width="11" height="11" viewBox="0 0 24 24"
            fill="none" stroke="currentColor" strokeWidth="2.4"
            strokeLinejoin="round" strokeLinecap="round" aria-hidden="true"
          >
            <path d="M13 2 L4 14 L11 14 L10 22 L20 9 L13 9 Z" />
          </svg>
          Auto
        </span>
      </span>
      <input
        type="checkbox"
        className="qs-switch__input"
        role="switch"
        aria-checked={showAutoBadge}
        checked={showAutoBadge}
        onChange={e => onChange(e.target.checked)}
      />
      <span className="qs-switch" aria-hidden="true">
        <span className="qs-switch__thumb" />
      </span>
    </label>
  )
}


interface TriggerConditionRowProps {
  condition: TriggerCondition
  index: number
  firesOn: 'received' | 'sent'
  onChange: (next: TriggerCondition) => void
  onRemove: () => void
  labels?: { name: string; color: string }[]
  siblingSteps?: QuickStep[]
}

function TriggerConditionRow({ condition, index, firesOn, onChange, onRemove, labels = [], siblingSteps = [] }: TriggerConditionRowProps) {
  const { t } = useTranslation('settings')
  const unit = triggerValueUnit(condition.type, t)
  const hint = triggerValueHint(condition.type, condition.match_mode, t)
  return (
    <div className="qs-trigger-row-wrapper">
    <div className="qs-trigger-row" data-negated={condition.negate || undefined}>
      <TriggerTypePicker
        value={condition.type}
        firesOn={firesOn}
        negate={condition.negate ?? false}
        onChange={type => {
          // Type change resets value + match_mode (the old match_mode may
          // be invalid for the new type). negate is carried over only if
          // the new type still exposes the toggle — otherwise the user
          // would have no UI to undo a stale `negate=true` and the backend
          // would silently invert the temporal comparison (audit F-03).
          const next: TriggerCondition = { type, value: defaultTriggerValue(type) }
          const mm = defaultTriggerMatchMode(type)
          if (mm) next.match_mode = mm
          if (condition.negate && triggerSupportsNegate(type)) next.negate = true
          onChange(next)
        }}
      />
      {triggerTypeHasMatchMode(condition.type) && (
        <ValueDropdown
          value={condition.match_mode ?? ''}
          options={triggerMatchModeOptions(condition.type, t)}
          placeholder={t('quicksteps_trigger_match_mode_placeholder', { defaultValue: '— Mode —' })}
          ariaLabel={t('quicksteps_trigger_match_mode_aria', {
            defaultValue: 'Mode de correspondance de la condition {{n}}',
            n: index + 1,
          })}
          onSelect={v => onChange({ ...condition, match_mode: v as TriggerMatchMode })}
        />
      )}
      {triggerSupportsNegate(condition.type) && (
        <button
          type="button"
          className="qs-trigger-row__negate"
          data-active={condition.negate || undefined}
          onClick={() => onChange({ ...condition, negate: !condition.negate })}
          aria-pressed={Boolean(condition.negate)}
          aria-label={t('quicksteps_trigger_negate_aria', {
            defaultValue: 'Inverser la condition',
          })}
          title={
            condition.negate
              ? t('quicksteps_trigger_negate_on', { defaultValue: 'Condition inversée — clique pour rétablir' })
              : t('quicksteps_trigger_negate_off', { defaultValue: 'Cliquer pour inverser (NON)' })
          }
        >
          {condition.negate ? '≠' : '='}
        </button>
      )}
      {triggerValueIsBadge(condition.type) ? (
        <span className="qs-trigger-row__value qs-trigger-row__value--badge">
          {triggerValueBadgeLabel(condition.type, t, {
            firesOn,
            negate: condition.negate,
            matchMode: condition.match_mode,
          })}
        </span>
      ) : condition.type === 'has_label' ? (
        <ValueDropdown
          value={condition.value}
          options={labels.map(l => ({ id: l.name, label: getLabelDisplayName(l.name), color: l.color }))}
          placeholder={t('quicksteps_trigger_label_placeholder', { defaultValue: '— Choisir un label —' })}
          ariaLabel={t('quicksteps_trigger_value', {
            defaultValue: 'Valeur de la condition {{n}}',
            n: index + 1,
          })}
          onSelect={v => onChange({ ...condition, value: v })}
        />
      ) : condition.type === 'previously_auto_actioned_by' ? (
        <ValueDropdown
          value={condition.value}
          options={siblingSteps.map(s => ({ id: s.id, label: s.name }))}
          placeholder={t('quicksteps_trigger_step_placeholder', { defaultValue: '— Choisir une quick action —' })}
          ariaLabel={t('quicksteps_trigger_value', {
            defaultValue: 'Valeur de la condition {{n}}',
            n: index + 1,
          })}
          onSelect={v => onChange({ ...condition, value: v })}
        />
      ) : condition.type === 'sender' && condition.match_mode !== 'matches' ? (
        <div className="qs-trigger-row__value qs-trigger-row__value--autocomplete">
          <ContactAutocomplete
            value={condition.value}
            onChange={val => onChange({ ...condition, value: val })}
            placeholder={triggerValuePlaceholder(condition.type, condition.match_mode)}
            multi={false}
            className="qs-trigger-row__autocomplete"
          />
        </div>
      ) : (
        <div className="qs-trigger-row__value qs-trigger-row__value--with-unit">
          <input
            className="qs-trigger-row__value qs-trigger-row__value--input"
            type="text"
            value={condition.value}
            maxLength={200}
            placeholder={triggerValuePlaceholder(condition.type, condition.match_mode)}
            onChange={e => onChange({ ...condition, value: e.target.value })}
            autoComplete="off"
            aria-label={t('quicksteps_trigger_value', {
              defaultValue: 'Valeur de la condition {{n}}',
              n: index + 1,
            })}
          />
          {unit && <span className="qs-trigger-row__value-unit">{unit}</span>}
        </div>
      )}
      <button
        type="button"
        className="qs-trigger-row__remove"
        onClick={onRemove}
        aria-label={t('quicksteps_trigger_remove', { defaultValue: 'Supprimer la condition' })}
        title={t('quicksteps_trigger_remove', { defaultValue: 'Supprimer la condition' })}
      >
        <CloseIcon size={14} />
      </button>
    </div>
      {hint && (
        <p className="qs-trigger-row__hint" role="note">
          {hint}
        </p>
      )}
    </div>
  )
}

interface TriggerTypePickerProps {
  value: TriggerConditionType
  firesOn: 'received' | 'sent'
  negate: boolean
  onChange: (type: TriggerConditionType) => void
}

function TriggerTypePicker({ value, firesOn, negate, onChange }: TriggerTypePickerProps) {
  const { t } = useTranslation('settings')
  const picker = usePicker({
    options: TRIGGER_CONDITION_TYPES,
    onSelect: onChange,
    estimatedRowHeight: 34,
  })
  const currentIndex = TRIGGER_CONDITION_TYPES.indexOf(value)

  return (
    <div className="qs-trigger-type-picker" ref={picker.wrapperRef}>
      <button
        type="button"
        className="qs-trigger-type-picker__btn"
        onClick={() => picker.setOpen(o => !o)}
        onKeyDown={e => picker.onTriggerKeyDown(e, currentIndex)}
        data-open={picker.open || undefined}
        aria-haspopup="listbox"
        aria-expanded={picker.open}
        aria-label={t('quicksteps_trigger_type', { defaultValue: 'Type de condition' })}
      >
        <span className="qs-trigger-type-picker__btn-icon" data-type={value} aria-hidden="true">
          <TriggerTypeIcon type={value} />
        </span>
        <span className="qs-trigger-type-picker__btn-label">
          {triggerTypeLabel(value, t, { firesOn, negate })}
        </span>
        <span className="qs-trigger-type-picker__btn-chev" aria-hidden="true">
          <ChevronDownIcon size={14} />
        </span>
      </button>
      {picker.open && (
        <ul
          role="listbox"
          className="qs-trigger-type-picker__menu"
          data-placement={picker.placement}
          style={picker.maxHeight != null ? { maxHeight: picker.maxHeight } : undefined}
        >
          {(['sender', 'content', 'classification', 'advanced'] as TriggerCategory[]).map(cat => {
            const items = TRIGGER_CONDITION_TYPES_GROUPED.filter(m => m.category === cat)
            if (items.length === 0) return null
            return (
              <li key={cat} className="qs-trigger-type-picker__group">
                <div className="qs-trigger-type-picker__group-label">
                  {triggerCategoryLabel(cat, t)}
                </div>
                {items.map(({ type: opt }) => {
                  const idx = TRIGGER_CONDITION_TYPES.indexOf(opt)
                  return (
                    <button
                      key={opt}
                      type="button"
                      role="option"
                      aria-selected={opt === value}
                      data-active={opt === value || undefined}
                      data-highlighted={idx === picker.highlightIndex || undefined}
                      className="qs-trigger-type-picker__option"
                      onClick={() => {
                        onChange(opt)
                        picker.setOpen(false)
                      }}
                      onMouseEnter={() => picker.setHighlightIndex(idx)}
                    >
                      <span className="qs-trigger-type-picker__option-icon" data-type={opt} aria-hidden="true">
                        <TriggerTypeIcon type={opt} />
                      </span>
                      <span className="qs-trigger-type-picker__option-label">
                        {triggerTypeLabel(opt, t, { firesOn })}
                      </span>
                      {opt === value && (
                        <span className="qs-trigger-type-picker__option-check" aria-hidden="true">
                          <CheckIcon size={14} />
                        </span>
                      )}
                    </button>
                  )
                })}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

function TriggerTypeIcon({ type }: { type: TriggerConditionType }) {
  switch (type) {
    case 'sender':
      return (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
          <circle cx="12" cy="7" r="4" />
        </svg>
      )
    case 'sender_domain':
      return (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-3.92 7.94" />
        </svg>
      )
    case 'has_label':
      return (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" />
          <line x1="7" y1="7" x2="7.01" y2="7" />
        </svg>
      )
    case 'recipient':
      return (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
          <circle cx="9" cy="7" r="4" />
          <path d="M22 11h-6" />
          <path d="M19 8v6" />
        </svg>
      )
    case 'email_text':
      return (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          <line x1="8" y1="9" x2="16" y2="9" />
          <line x1="8" y1="13" x2="14" y2="13" />
        </svg>
      )
    case 'has_attachment':
      return (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21.44 11.05 12.25 20.24a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.49" />
        </svg>
      )
    case 'calendar_invite':
      return (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
          <line x1="16" y1="2" x2="16" y2="6" />
          <line x1="8" y1="2" x2="8" y2="6" />
          <line x1="3" y1="10" x2="21" y2="10" />
          <path d="M8 14h.01M12 14h.01M16 14h.01" strokeWidth="3" strokeLinecap="round" />
        </svg>
      )
    case 'email_older_than_days':
    case 'no_reply_after_days':
      return (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <polyline points="12 7 12 12 15 14" />
        </svg>
      )
    case 'is_read':
      return (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M2 6l10 7 10-7" />
          <rect x="2" y="6" width="20" height="14" rx="2" />
          <polyline points="6 11 9 14 14 9" />
        </svg>
      )
    case 'previously_auto_actioned_by':
      return (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
          <polyline points="3 3 3 8 8 8" />
        </svg>
      )
    case 'has_deadline_detected':
      // Hourglass — "time running out" reads as deadline; deliberately
      // distinct from the plain clock used for email age / no-reply.
      return (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 3h12" />
          <path d="M6 21h12" />
          <path d="M7 3l5 9-5 9" />
          <path d="M17 3l-5 9 5 9" />
        </svg>
      )
    case 'is_new_thread':
      return (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="16" />
          <line x1="8" y1="12" x2="16" y2="12" />
        </svg>
      )
    case 'thread_has_user_reply':
      return (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <polyline points="9 14 4 9 9 4" />
          <path d="M20 20v-7a4 4 0 0 0-4-4H4" />
        </svg>
      )
    case 'has_emoji_marker':
      return (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
        </svg>
      )
  }
}

// --------------------------------------------------------------------------- //
// Quick-step template variables → `{x}` placeholder menu entries. Each item
// inserts a styled chip whose token (e.g. `sender.firstname`) is resolved by
// the backend renderer (app/quicksteps/template.py) when the step runs.
// --------------------------------------------------------------------------- //

function useQuickStepPlaceholders(): PlaceholderSuggestion[] {
  const { t } = useTranslation('settings')
  return useMemo(() => {
    // Prénom / Nom of the sender only. Labels reuse the snippet-variable keys
    // (already "Prénom" / "Nom"); tokens stay `sender.firstname` /
    // `sender.lastname` so app/quicksteps/template.py resolves them.
    const labelByToken: Record<string, string> = {
      'sender.firstname': t('snippet_var_first_name_label', { defaultValue: 'Prénom' }),
      'sender.lastname': t('snippet_var_last_name_label', { defaultValue: 'Nom' }),
    }
    return QUICK_STEP_TEMPLATE_VARIABLES.filter(
      v => v.token === 'sender.firstname' || v.token === 'sender.lastname'
    ).map(v => {
      const label = labelByToken[v.token]
      return {
        id: v.token,
        label,
        preview: `{${v.token}}`,
        buildHtml: () => buildTokenChipHtml(v.token, label),
      }
    })
  }, [t])
}

interface FieldLabelProps {
  label: string
  hint?: string
}

function FieldLabel({ label, hint }: FieldLabelProps) {
  return (
    <span className="quickstep-action-body__label">
      {label}
      {hint && <span className="quickstep-action-body__label-hint">— {hint}</span>}
    </span>
  )
}

// --------------------------------------------------------------------------- //
// Shortcut capture
// --------------------------------------------------------------------------- //

interface ShortcutCaptureProps {
  value: string | null
  onChange: (next: string | null) => void
}

const MODIFIER_KEY_NAMES = new Set([
  'control', 'ctrl', 'shift', 'alt', 'meta', 'os', 'altgraph',
])

function ShortcutCapture({ value, onChange }: ShortcutCaptureProps) {
  const { t } = useTranslation('settings')
  const [recording, setRecording] = useState(false)
  const inputRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!recording) return
    const handler = (e: KeyboardEvent) => {
      e.preventDefault()
      e.stopPropagation()
      const key = e.key
      if (key === 'Escape') {
        setRecording(false)
        return
      }
      if (key === 'Backspace' || key === 'Delete') {
        if (e.ctrlKey || e.metaKey) {
          onChange(null)
          setRecording(false)
        } else {
          setRecording(false)
        }
        return
      }
      const parts: string[] = []
      if (e.ctrlKey) parts.push('ctrl')
      if (e.shiftKey) parts.push('shift')
      if (e.altKey) parts.push('alt')
      if (e.metaKey) parts.push('meta')
      const baseKey = key.toLowerCase()
      if (MODIFIER_KEY_NAMES.has(baseKey)) {
        return
      }
      parts.push(baseKey)
      onChange(parts.join('+'))
      setRecording(false)
    }
    window.addEventListener('keydown', handler, true)
    return () => window.removeEventListener('keydown', handler, true)
  }, [recording, onChange])

  return (
    <div className="shortcut-capture">
      <button
        ref={inputRef}
        type="button"
        className="shortcut-capture__btn"
        onClick={() => setRecording(true)}
        data-recording={recording || undefined}
        data-has-value={value && !recording ? '' : undefined}
      >
        {recording
          ? t('quicksteps_press_a_key', { defaultValue: 'Appuyez sur une touche…' })
          : value
            ? formatShortcut(value)
            : t('quicksteps_click_to_record', { defaultValue: 'Cliquer pour enregistrer une touche' })}
      </button>
      {value && !recording && (
        <button
          type="button"
          className="shortcut-capture__clear"
          onClick={() => onChange(null)}
          aria-label={t('quicksteps_clear_shortcut', { defaultValue: 'Effacer le raccourci' })}
        >
          ✕
        </button>
      )}
    </div>
  )
}

function formatShortcut(value: string): string {
  return value
    .split('+')
    .map(part => (part.length === 1 ? part.toUpperCase() : capitalize(part)))
    .join(' + ')
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

// --------------------------------------------------------------------------- //
// Inline SVG icons — match the rest of the codebase (no lucide-react dep).
// --------------------------------------------------------------------------- //

function DragHandleIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <circle cx="9" cy="6" r="1.5" /><circle cx="15" cy="6" r="1.5" />
      <circle cx="9" cy="12" r="1.5" /><circle cx="15" cy="12" r="1.5" />
      <circle cx="9" cy="18" r="1.5" /><circle cx="15" cy="18" r="1.5" />
    </svg>
  )
}

function EyeIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}

function CheckCircleIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
      <polyline points="22 4 12 14.01 9 11.01" />
    </svg>
  )
}

function DotIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
    </svg>
  )
}


function KeyboardIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="2" y="6" width="20" height="12" rx="2" />
      <path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M8 14h8" />
    </svg>
  )
}

function ZapIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true">
      <path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z" />
    </svg>
  )
}

function ActionIcon({ type }: { type: QuickStepActionType }) {
  switch (type) {
    case 'archive':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <polyline points="21 8 21 21 3 21 3 8" />
          <rect x="1" y="3" width="22" height="5" />
          <line x1="10" y1="12" x2="14" y2="12" />
        </svg>
      )
    case 'unarchive':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <polyline points="21 8 21 21 3 21 3 8" />
          <rect x="1" y="3" width="22" height="5" />
          <polyline points="9 16 12 13 15 16" />
          <line x1="12" y1="13" x2="12" y2="20" />
        </svg>
      )
    case 'delete':
      return <TrashIcon size={14} />
    case 'mark_read':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
          <polyline points="22 4 12 14.01 9 11.01" />
        </svg>
      )
    case 'move_to_spam':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
          <line x1="12" y1="9" x2="12" y2="13" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
      )
    case 'pin':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 17v5" />
          <path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1Z" />
        </svg>
      )
    case 'reply_template':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <polyline points="9 17 4 12 9 7" />
          <path d="M20 18v-2a4 4 0 0 0-4-4H4" />
        </svg>
      )
    case 'forward':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <polyline points="15 17 20 12 15 7" />
          <path d="M4 18v-2a4 4 0 0 1 4-4h12" />
        </svg>
      )
    case 'rsvp_meeting':
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
          <line x1="16" y1="2" x2="16" y2="6" />
          <line x1="8" y1="2" x2="8" y2="6" />
          <line x1="3" y1="10" x2="21" y2="10" />
          <path d="M9 16l2 2 4-4" />
        </svg>
      )
    case 'create_snoozed_followup_draft':
      // Pencil-on-clock — a clock (the follow-up delay) plus a "draft is
      // being written" pencil, distinct from the other action icons in
      // the picker.
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="10" cy="13" r="7" />
          <polyline points="10 9 10 13 12 14" />
          <path d="M16 4l4 4-3 3-4-4z" />
        </svg>
      )
    case 'mark_with_emoji':
      // Bookmark — "mark this email"; matches the has_emoji_marker
      // condition icon so the action that stamps the marker and the
      // condition that reads it share one glyph.
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
        </svg>
      )
    case 'apply_label':
      // Tag — matches the has_label condition icon so the action that
      // applies a label and the condition that reads it share one glyph.
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" />
          <line x1="7" y1="7" x2="7.01" y2="7" />
        </svg>
      )
    case 'create_reminder':
      // Bell — a reminder fires at a future time.
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
          <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        </svg>
      )
    case 'create_calendar_event':
      // Calendar-plus — adds an event to the connected calendar.
      return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
          <line x1="16" y1="2" x2="16" y2="6" />
          <line x1="8" y1="2" x2="8" y2="6" />
          <line x1="3" y1="10" x2="21" y2="10" />
          <line x1="12" y1="14" x2="12" y2="18" />
          <line x1="10" y1="16" x2="14" y2="16" />
        </svg>
      )
    default:
      return null
  }
}

function TemplateIcon({ templateKey }: { templateKey: string }) {
  if (templateKey === 'reply_then_forward') {
    return (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M3 12a9 9 0 0 1 14-7.5" />
        <polyline points="14 4 17 4.5 17 7.5" />
        <polyline points="15 20 20 15 15 10" />
        <path d="M20 15H8a4 4 0 0 1-4-4" />
      </svg>
    )
  }
  if (templateKey === 'forward_archive') {
    return (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <polyline points="15 17 20 12 15 7" />
        <path d="M4 18v-2a4 4 0 0 1 4-4h12" />
        <rect x="3" y="3" width="6" height="4" rx="1" />
      </svg>
    )
  }
  return <PlusIcon size={14} />
}
