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

import { useState, useEffect, useCallback, useId, useMemo, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { LearningProgressScreen, type StepInfo } from './onboarding'
import { getWebSocketClient, type WebSocketEvent } from '../services/websocket'
import { useLearningProgress } from '../hooks/useLearningProgress'
import { useOptimisticMutation, okOrThrow } from '../hooks/useOptimisticMutation'
import { API_URL } from '../config'
import { getAuthHeaders } from '../services/authToken'
import { clearAllUserData } from '../services/clearUserData'
import {
  type TrainingData,
  type KnowledgeCategory,
  type Pillar,
  type ContactStyleProfile,
  type DefaultStyleSettings,
  type FormalityLevel,
  type LanguageVariant,
  type DraftCorrectionItem,
  type DraftRuleItem,
  type AutoLabelRule,
  type AutoLabelCategory,
  emptyTrainingData,
  parseMarkdownToTraining,
  serializeTrainingToMarkdown,
} from '../types/training'
import { syncSavoirToKnowledgeEntries } from '../utils/savoirSync'
import { hasEscapeOwner } from '../utils/escapeOwner'
import { getKnowledgeEntries, createKnowledgeEntry } from '../services/api'
import i18n from '../i18n'
import type { AgentSteps, AgentStepStatus } from '../types/onboarding'
import { PillarNav } from './PillarNav'
import { PillarProfil } from './PillarProfil'
import { PillarStyle } from './PillarStyle'
import { PillarSavoir } from './PillarSavoir'
import { PillarAutoLabel } from './PillarAutoLabel'
import { TrainingFooter } from './TrainingFooter'
import { Button } from './ui/button'
import { ChevronLeftIcon, CloseIcon, TrashIcon } from './icons/ActionIcons'
import { fetchUserLearningCategories } from '../api/learning'
import './TrainingPage.css'
import './TrainingCommon.css'

interface TrainingPageProps {
  onClose: () => void
  onBack?: () => void
  accountId?: number
  accountEmail?: string
}

type RefreshState = 'idle' | 'running' | 'completed' | 'failed'

function genId(): string {
  return `t_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
}

export function TrainingPage({ onClose, onBack, accountId, accountEmail }: TrainingPageProps) {
  const { t } = useTranslation('agents')
  const dialogId = useId()

  // ── Pillar navigation ──
  const [activePillar, setActivePillar] = useState<Pillar>('profil')

  // ── Training data (profile, savoir, regles) ──
  const [data, setData] = useState<TrainingData>(emptyTrainingData())
  const [originalMd, setOriginalMd] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // ── Learned data ──
  const [draftRules, setDraftRules] = useState<DraftRuleItem[]>([])
  const [_draftCorrections, setDraftCorrections] = useState<DraftCorrectionItem[]>([])
  const [learnedSavoirs, setLearnedSavoirs] = useState<Array<{ id: string; rule_text: string; category: string; created_at?: string }>>([])
  const [autoLabelCategory, setAutoLabelCategory] = useState<AutoLabelCategory | null>(null)

  // ── Contact styles & default style ──
  const [contactStyles, setContactStyles] = useState<ContactStyleProfile[]>([])
  const [defaultStyle, setDefaultStyle] = useState<DefaultStyleSettings | null>(null)

  // Bulletproof save: when a contact card is in edit mode, the user's typed
  // values live in the card's local state. Clicking the main footer Save
  // would otherwise miss them. The card registers its commit fn here while
  // editing; ``handleSave`` flushes it before serializing the markdown so a
  // single click on the footer Save persists everything visible.
  const editingCardSaveRef = useRef<(() => Promise<{ error?: string } | void>) | null>(null)
  // ``data`` captured by closure is stale after the flush triggers a setData;
  // a ref updated inline at every render gives us the freshest snapshot to
  // serialize without waiting for React to commit.
  const dataRef = useRef(data)
  dataRef.current = data
  // Une fois les données chargées une première fois, les refetch d'arrière-plan
  // (bumps de `refreshKey` via les events WS learning:* / onboarding:*) ne
  // doivent PLUS repasser par l'écran de chargement plein écran : celui-ci
  // démonte tout le contenu (PillarStyle → ContactStyleEditor → la carte
  // « Ajouter un contact » en cours d'édition), perdant la saisie de
  // l'utilisateur (« la fenêtre se ferme avant de sauvegarder », 2026-06-23).
  const hasLoadedRef = useRef(false)


  const currentMd = serializeTrainingToMarkdown(data)
  const hasChanges = currentMd !== originalMd

  // ── Pillar detection & hints (match onboarding visuals) ──
  const pillarDetected = useMemo<Partial<Record<Pillar, boolean>>>(() => ({
    profil: !!data.profil.nom_complet,
    style: contactStyles.length > 0 || draftRules.length > 0 || !!defaultStyle,
    savoir: data.savoir.length > 0 || learnedSavoirs.length > 0,
    autolabel: !!autoLabelCategory && autoLabelCategory.items.length > 0,
  }), [data.profil.nom_complet, contactStyles.length, draftRules.length, defaultStyle, data.savoir.length, learnedSavoirs.length, autoLabelCategory])

  // Each pillar gets a "done" (possessive) hint when configured, or a parallel
  // "to configure" (action) hint when not — keeps the voice consistent across
  // the row instead of falling through to the generic 3rd-person default.
  const pillarHints = useMemo<Partial<Record<Pillar, string>>>(() => ({
    profil: pillarDetected.profil ? t('training_hint_profil') : t('training_todo_profil'),
    style: pillarDetected.style ? t('training_hint_style') : t('training_todo_style'),
    savoir: pillarDetected.savoir ? t('training_hint_savoir') : t('training_todo_savoir'),
    autolabel: pillarDetected.autolabel ? t('training_hint_autolabel') : t('training_todo_autolabel'),
  }), [pillarDetected, t])

  // ── Refresh state ──
  const REFRESH_STEPS: StepInfo[] = useMemo(() => [
    { key: 'knowledge', title: t('refresh_step_knowledge'), description: t('refresh_step_knowledge_desc') },
    { key: 'style', title: t('refresh_step_style'), description: t('refresh_step_style_desc') },
    { key: 'label', title: t('refresh_step_label'), description: t('refresh_step_label_desc') },
  ], [t])

  const { learningActivity, fetchLearningStatus } = useLearningProgress()
  const [refreshState, setRefreshState] = useState<RefreshState>('idle')
  const [refreshError, setRefreshError] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [refreshAgentSteps, setRefreshAgentSteps] = useState<AgentSteps>({
    profile: 'completed', style: 'pending', knowledge: 'pending', label: 'pending',
  })
  const [refreshEmailsTotal, setRefreshEmailsTotal] = useState(0)

  // ── Fetch training data ──
  const fetchMemory = useCallback(async (retries = 2) => {
    // Écran de chargement uniquement au tout premier fetch ; un refetch
    // d'arrière-plan reconcilie en place sans démonter l'éditeur (cf. hasLoadedRef).
    if (!hasLoadedRef.current) setLoading(true)
    setError(null)
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const response = await fetch(`${API_URL}/api/memory`, { headers: getAuthHeaders() })
        if (!response.ok) {
          const errBody = await response.json().catch(() => null)
          throw new Error(errBody?.error || `Server error (${response.status})`)
        }
        const json = await response.json()
        const parsed = parseMarkdownToTraining(json.content || '')

        // Merge FAQ entries from SQLite (knowledge_entries) — onboarding writes
        // FAQs there directly, and the training modal now persists on import.
        // memoire.md may lag behind until the user clicks Save, so without this
        // merge imported FAQs appear to "disappear" after reload.
        try {
          const faqFromDb = await getKnowledgeEntries('FAQ')
          const seen = new Set(parsed.savoir.map(s => s.question.trim().toLowerCase()))
          for (const entry of faqFromDb) {
            const key = entry.title.trim().toLowerCase()
            if (!key || seen.has(key)) continue
            seen.add(key)
            parsed.savoir.push({
              id: genId(),
              question: entry.title,
              answer: entry.content,
              category: 'FAQ' as KnowledgeCategory,
            })
          }
        } catch { /* silent — memoire.md is still usable without DB merge */ }

        setData(parsed)
        setOriginalMd(serializeTrainingToMarkdown(parsed))
        hasLoadedRef.current = true
        setLoading(false)
        return
      } catch (err) {
        if (attempt < retries) {
          await new Promise(r => setTimeout(r, 1000 * (attempt + 1)))
          continue
        }
        setError(err instanceof Error ? err.message : 'Unknown error')
      }
    }
    setLoading(false)
  }, [])

  // ── Fetch learned data ──
  const fetchLearnedData = useCallback(async () => {
    try {
      const categories = await fetchUserLearningCategories()

      const rulesCategory = categories.find(c => c.id === 'draft-rules')
      if (rulesCategory) setDraftRules(rulesCategory.items as DraftRuleItem[])

      const aiCategory = categories.find(c => c.id === 'draft-ai')
      if (aiCategory) setDraftCorrections(aiCategory.items as DraftCorrectionItem[])

      const savoirsCategory = categories.find(c => c.id === 'savoirs')
      if (savoirsCategory) {
        const NOISE_PREFIX = /^(Contact\s*:|Projet\s*:)/i
        setLearnedSavoirs(savoirsCategory.items
          .map(i => ({
            id: i.id,
            rule_text: (i as { rule_text?: string; text?: string }).rule_text || (i as { text?: string }).text || '',
            category: (i as { category?: string }).category || '',
            created_at: (i as { created_at?: string }).created_at,
          }))
          .filter(s => !NOISE_PREFIX.test(s.rule_text))
        )
      }

      const labelCategory = categories.find(c => c.id === 'auto-label')
      if (labelCategory) {
        setAutoLabelCategory({
          ...labelCategory,
          items: (labelCategory.items as Record<string, unknown>[]).map(r => ({
            id: r.id as string,
            rule_text: `${r.type ?? ''}: ${r.value ?? ''}`,
            category: (r.label as string) ?? '',
            confidence: r.precision == null ? null : (r.precision as number) / 100,
            active: (r.is_active as boolean) ?? true,
            created_at: r.created_at as string | undefined,
            total_matches: r.total_matches as number | undefined,
            total_corrections: r.corrections as number | undefined,
          })) as AutoLabelRule[],
        })
      }
    } catch {
      // silent
    }
  }, [])

  // ── Fetch contact styles & defaults ──
  const fetchContactStyles = useCallback(async () => {
    try {
      const [csRes, wsRes] = await Promise.all([
        fetch(`${API_URL}/api/writing-style/contacts`, { headers: getAuthHeaders() }),
        fetch(`${API_URL}/api/writing-style`, { headers: getAuthHeaders() }),
      ])
      if (csRes.ok) {
        const csJson = await csRes.json()
        const backendContacts: Array<{ email: string; nickname?: string | null }> = csJson.contacts || []
        setContactStyles(backendContacts as unknown as typeof contactStyles)
      }
      if (wsRes.ok) {
        const wsJson = await wsRes.json()
        if (wsJson.defaults) setDefaultStyle(wsJson.defaults)
      }
    } catch { /* silent */ }
  }, [])

  useEffect(() => {
    fetchMemory()
    fetchContactStyles()
    fetchLearnedData()
  }, [fetchMemory, fetchLearnedData, fetchContactStyles, refreshKey])

  // Escape key closes the training modal — skip when typing in fields so
  // inner popups (autocompletes, calendar dropdowns) handle Escape first.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      // Defer to an inner popover that owns Escape (greeting mode dropdown,
      // language/variant pickers, FAQ import…). The INPUT/TEXTAREA skip below
      // already covers text-field popovers, but button-triggered dropdowns
      // need this structural check. See utils/escapeOwner.ts.
      if (hasEscapeOwner()) return
      const tgt = e.target as HTMLElement | null
      if (tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA' || tgt.isContentEditable)) {
        return
      }
      onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  // ── Save ──
  const handleSave = async () => {
    setSaving(true)
    setError(null)
    try {
      // Flush any open contact-card edit so its local state is committed
      // (per-contact API + optimistic contactStyles update) BEFORE we
      // serialize the markdown.
      const pendingFlush = editingCardSaveRef.current
      if (pendingFlush) {
        const flushResult = await pendingFlush()
        if (flushResult && 'error' in flushResult && flushResult.error) {
          setError(flushResult.error)
          setSaving(false)
          return
        }
      }
      // Read fresh data via the ref — the per-card flush updates
      // ``dataRef.current`` inside its setData updater so we don't have to
      // wait for React to commit the re-render.
      const md = serializeTrainingToMarkdown(dataRef.current)
      const response = await fetch(`${API_URL}/api/memory`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ content: md }),
      })
      if (!response.ok) {
        const body = await response.json().catch(() => null)
        const detail = body?.error || body?.message || `HTTP ${response.status}`
        console.error('[TrainingPage] save failed:', response.status, body)
        throw new Error(detail)
      }
      await response.json()
      setOriginalMd(md)
      syncSavoirToKnowledgeEntries(data.savoir).catch((syncErr) => {
        console.error('[TrainingPage] savoir sync failed:', syncErr)
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: {
            message: i18n.t('common:toasts.faq_sync_partial'),
            type: 'warning',
            duration: 6000,
          },
        }))
      })
      onClose()
    } catch (err) {
      console.error('[TrainingPage] save exception:', err)
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setSaving(false)
    }
  }

  const handleReset = () => {
    const parsed = parseMarkdownToTraining(originalMd)
    setData(parsed)
  }

  // ── Profil handlers ──
  const updateProfil = useCallback((field: string, value: string) => {
    setData(prev => {
      if (field.startsWith('format.')) {
        const sub = field.slice(7);
        const defaults = { longueur: 'moyen' as const, complexite: 'standard' as const };
        return { ...prev, profil: { ...prev.profil, format: { ...defaults, ...prev.profil.format, [sub]: value } } };
      }
      return { ...prev, profil: { ...prev.profil, [field]: value } };
    })
  }, [])

  // ── Savoir handlers ──
  const addSavoir = useCallback((category: KnowledgeCategory = 'GENERAL') => {
    setData(prev => ({
      ...prev,
      savoir: [...prev.savoir, { id: genId(), question: '', answer: '', category }],
    }))
  }, [])

  const importFaq = useCallback((entries: Array<{ question: string; answer: string }>) => {
    // Optimistic UI update — show entries immediately.
    setData(prev => ({
      ...prev,
      savoir: [
        ...prev.savoir,
        ...entries.map(e => ({
          id: genId(),
          question: e.question,
          answer: e.answer,
          category: 'FAQ' as KnowledgeCategory,
        })),
      ],
    }))
    // Persist immediately to knowledge_entries so the import survives a reload
    // even if the user never clicks the top-level Save button. Without this,
    // imports existed only in local state and silently vanished.
    void (async () => {
      for (const entry of entries) {
        const title = entry.question.trim()
        const content = entry.answer.trim()
        if (!title || !content) continue
        try {
          await createKnowledgeEntry({ title, content, category: 'FAQ' })
        } catch { /* silent — sync on Save will retry */ }
      }
    })()
  }, [])

  const updateSavoir = useCallback((id: string, field: 'question' | 'answer' | 'context', value: string) => {
    setData(prev => ({ ...prev, savoir: prev.savoir.map(s => s.id === id ? { ...s, [field]: value } : s) }))
  }, [])

  const updateSavoirCategory = useCallback((id: string, category: string) => {
    setData(prev => ({ ...prev, savoir: prev.savoir.map(s => s.id === id ? { ...s, category: category as KnowledgeCategory } : s) }))
  }, [])

  const removeSavoir = useCallback((id: string) => {
    setData(prev => ({ ...prev, savoir: prev.savoir.filter(s => s.id !== id) }))
  }, [])

  // ── Learned data handlers ──
  // Audit 2026-06-11 F-01 : le PATCH brut sans okOrThrow résolvait sur 4xx/5xx
  // → faux succès (règle toujours active backend, switch éteint à l'écran).
  const runToggleRule = useOptimisticMutation<void>({
    scope: 'training-toggle-rule',
    i18nKey: 'toasts.learning_toggle_failed',
  })
  const handleToggleRule = useCallback(async (id: string, active: boolean) => {
    const newActive = !active
    setDraftRules(prev => prev.map(r => r.id === id ? { ...r, active: newActive } : r))
    await runToggleRule(
      async () => {
        okOrThrow(await fetch(`${API_URL}/api/learning/rules/${encodeURIComponent(id)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify({ active: newActive }),
        }))
      },
      () => {
        setDraftRules(prev => prev.map(r => r.id === id ? { ...r, active } : r))
      },
    )
  }, [runToggleRule])

  // Audit Cluster D (2026-05-17) F-08 / #330: optimistic deletes used to
  // silently swallow the network/auth failure, so an item would resurrect
  // on the next reload with no explanation. Helper surfaces a warning toast
  // and rolls the local state back so the UI matches the backend truth.
  //
  // Audit regressions (2026-05-17 batch4) F-05: the rollback now re-adds
  // ONLY the failed item (id-keyed, idempotent guard) instead of restoring
  // a whole-array `prev` snapshot. Rapid concurrent deletes on different
  // rows had a stale-closure race: A's slow-fail rollback would restore
  // `prev_A = [A,B,C]` and resurrect B that the user had successfully
  // deleted in between. Per-item rollback composes correctly.
  const runDeleteDraftRule = useOptimisticMutation<void>({
    scope: 'training-delete-rule',
    i18nKey: 'toasts.learning_delete_failed',
  })
  const handleDeleteRule = useCallback(async (id: string) => {
    const removed = draftRules.find(r => r.id === id)
    setDraftRules(p => p.filter(r => r.id !== id))
    await runDeleteDraftRule(
      async () => {
        okOrThrow(await fetch(`${API_URL}/api/learning/rules/${encodeURIComponent(id)}`, { method: 'DELETE', headers: getAuthHeaders() }))
      },
      () => {
        if (!removed) return
        setDraftRules(p => (p.some(r => r.id === id) ? p : [...p, removed]))
      },
    )
  }, [draftRules, runDeleteDraftRule])

  const runDeleteSavoir = useOptimisticMutation<void>({
    scope: 'training-delete-savoir',
    i18nKey: 'toasts.learning_delete_failed',
  })
  const handleDeleteLearnedSavoir = useCallback(async (id: string) => {
    const removed = learnedSavoirs.find(s => s.id === id)
    setLearnedSavoirs(p => p.filter(s => s.id !== id))
    await runDeleteSavoir(
      async () => {
        okOrThrow(await fetch(`${API_URL}/api/learning/savoirs/${encodeURIComponent(id)}`, { method: 'DELETE', headers: getAuthHeaders() }))
      },
      () => {
        if (!removed) return
        setLearnedSavoirs(p => (p.some(s => s.id === id) ? p : [...p, removed]))
      },
    )
  }, [learnedSavoirs, runDeleteSavoir])

  // ── Contact style handlers ──
  const handleSaveContactStyle = useCallback(async (payload: {
    contact_email: string;
    formality_override: FormalityLevel | null;
    preferred_greeting: string | null;
    preferred_closing: string | null;
    langue_variante?: LanguageVariant | null;
    langue?: string | null;
    nickname?: string | null;
    formality_locked?: boolean;
  }): Promise<{ error?: string }> => {
    try {
      const res = await fetch(`${API_URL}/api/writing-style/contact-style`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify(payload),
      })
      const json = await res.json().catch(() => ({ error: `Server error (${res.status})` }))
      if (!res.ok) {
        console.error('[TrainingPage] contact-style save failed:', res.status, json)
        if (res.status === 401) return { error: t('contact_style_session_expired', 'Session expirée — reconnectez-vous') }
        if (res.status === 404) return { error: 'Endpoint indisponible sur le serveur' }
        return { error: json.error || `Server error (${res.status})` }
      }
      // Optimistic contactStyles update — drives the card view mode fields
      // AND the nickname badge (single source of truth, post-2026-05-14).
      // We do NOT re-fetch from the backend here: fetchContactStyles() can
      // return stale SQLite data and overwrite the just-saved nickname with
      // the old value, making it look like the save never happened.
      setContactStyles(prev => {
        const email = payload.contact_email.toLowerCase()
        const exists = prev.some(c => c.email.toLowerCase() === email)
        const updated = prev.map(c => c.email.toLowerCase() !== email ? c : {
          ...c,
          formality_override: payload.formality_override,
          preferred_greeting: payload.preferred_greeting,
          preferred_closing: payload.preferred_closing,
          langue_variante: payload.langue_variante ?? null,
          langue: payload.langue ?? null,
          nickname: payload.nickname ?? null,
          formality_locked: payload.formality_locked ?? c.formality_locked,
        })
        // Upsert : un contact AJOUTÉ (absent de prev) doit être appended, sinon
        // l'ancien `.map` (update-only) ne l'insérait jamais — le PUT backend
        // réussissait mais le contact disparaissait de la liste à la fermeture
        // de la carte (onCreated), donnant l'impression que « l'ajout ne
        // s'enregistre pas » (bug signalé 2026-06-23).
        if (exists) return updated
        return [...updated, {
          email,
          formality_override: payload.formality_override,
          preferred_greeting: payload.preferred_greeting,
          preferred_closing: payload.preferred_closing,
          langue_variante: payload.langue_variante ?? null,
          langue: payload.langue ?? null,
          nickname: payload.nickname ?? null,
          formality_locked: payload.formality_locked ?? false,
        }]
      })
      return {}
    } catch (e) {
      console.error('[TrainingPage] contact-style network error:', e)
      return { error: 'Network error' }
    }
  }, [t])

  const runDeleteContactStyle = useOptimisticMutation<void>({
    scope: 'training-delete-contact-style',
    i18nKey: 'toasts.learning_delete_failed',
  })
  const handleDeleteContactStyle = useCallback(async (email: string) => {
    // F-05: id-keyed rollback (see handleDeleteRule above).
    const normalizedEmail = email.toLowerCase()
    const removed = contactStyles.find(c => c.email.toLowerCase() === normalizedEmail)
    setContactStyles(p => p.filter(c => c.email.toLowerCase() !== normalizedEmail))
    await runDeleteContactStyle(
      async () => {
        okOrThrow(await fetch(`${API_URL}/api/writing-style/contact-style`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify({ contact_email: email }),
        }))
      },
      () => {
        if (!removed) return
        setContactStyles(p => (p.some(c => c.email.toLowerCase() === normalizedEmail) ? p : [...p, removed]))
      },
    )
  }, [contactStyles, runDeleteContactStyle])

  // Audit Cluster D (2026-05-17) F-09: previously a non-2xx PATCH didn't
  // run setDefaultStyle so the UI snapped back to the old value with zero
  // message — the toggle looked like it reset itself. Now we surface a
  // toast on save failure so the user knows to retry.
  const runUpdateDefaultStyle = useOptimisticMutation<void>({
    scope: 'training-update-default-style',
    i18nKey: 'toasts.learning_update_failed',
  })
  const handleUpdateDefaultStyle = useCallback(async (field: string, value: string) => {
    await runUpdateDefaultStyle(async () => {
      const res = okOrThrow(await fetch(`${API_URL}/api/writing-style/defaults`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ [field]: value }),
      }))
      const json = await res.json()
      if (json.defaults) {
        setDefaultStyle(prev => prev ? { ...prev, ...json.defaults } : json.defaults)
      }
    })
  }, [runUpdateDefaultStyle])

  // ── Refresh WebSocket ──
  useEffect(() => {
    if (refreshState !== 'running') return
    const ws = getWebSocketClient()
    const unsubscribe = ws.subscribe((event: WebSocketEvent) => {
      const eventType = event.type as string
      const eventData = event.data as Record<string, unknown>
      if (!eventData.refresh || eventData.deep) return

      if (eventType === 'onboarding:progress_updated') {
        const total = eventData.total as number | undefined
        const step = eventData.step as string | undefined
        const stepStatus = eventData.step_status as AgentStepStatus | undefined
        if (total && total > 0) setRefreshEmailsTotal(total)
        if (step && stepStatus && (step === 'knowledge' || step === 'rules' || step === 'categories' || step === 'labeling')) {
          setRefreshAgentSteps(prev => ({ ...prev, [step]: stepStatus }))
        }
      } else if (eventType === 'onboarding:learning_completed') {
        if (eventData.status === 'failed') {
          setRefreshState('failed')
          setRefreshError((eventData.error as string) || t('error_unknown'))
        } else {
          setRefreshState('completed')
          setRefreshAgentSteps({ profile: 'completed', style: 'completed', knowledge: 'completed', label: 'completed' })
          fetchLearningStatus()
          setRefreshKey(k => k + 1)
        }
      }
    })
    return unsubscribe
  }, [refreshState, t, fetchLearningStatus])

  // Auto-refresh on label correction
  useEffect(() => {
    const ws = getWebSocketClient()
    let debounceTimer: ReturnType<typeof setTimeout> | null = null
    const unsubscribe = ws.subscribe((event: WebSocketEvent) => {
      const eventType = event.type as string
      if (eventType === 'learning:label_corrected' || eventType === 'learning:correction_recorded') {
        if (debounceTimer) clearTimeout(debounceTimer)
        debounceTimer = setTimeout(() => setRefreshKey(k => k + 1), 1000)
      }
    })
    return () => { unsubscribe(); if (debounceTimer) clearTimeout(debounceTimer) }
  }, [])

  // Auto-refresh when the INITIAL onboarding completes. The refresh-flow
  // effect above only listens when refreshState==='running' AND when the
  // event carries `refresh=true` — so an initial onboarding completing
  // while this modal is already open would leave contactStyles/default
  // style stale (users saw "No per-contact styles configured" until they
  // manually closed & reopened the modal).
  useEffect(() => {
    const ws = getWebSocketClient()
    const unsubscribe = ws.subscribe((event: WebSocketEvent) => {
      if (event.type !== 'onboarding:learning_completed') return
      const data = event.data as Record<string, unknown>
      if (data.refresh) return // handled by the refresh-flow effect above
      if (data.status === 'failed') return
      setRefreshKey(k => k + 1)
    })
    return unsubscribe
  }, [])

  const handleRefresh = useCallback(async () => {
    if (!accountId || !accountEmail) return
    let days = 7
    if (learningActivity.lastRefreshAt) {
      const lastRefresh = new Date(learningActivity.lastRefreshAt)
      days = Math.max(1, Math.ceil((Date.now() - lastRefresh.getTime()) / (1000 * 60 * 60 * 24)))
    }
    setRefreshState('running')
    setRefreshError(null)
    setRefreshEmailsTotal(0)
    setRefreshAgentSteps({ profile: 'completed', style: 'pending', knowledge: 'pending', label: 'pending' })
    try {
      const response = await fetch(`${API_URL}/api/onboarding/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ account_id: accountId, user_email: accountEmail, days }),
      })
      if (!response.ok) {
        const err = await response.json().catch(() => ({ error: t('error_unknown') }))
        setRefreshState('failed')
        setRefreshError(err.error || t('error_start_failed'))
      }
    } catch {
      setRefreshState('failed')
      setRefreshError(t('error_server_unreachable'))
    }
  }, [accountId, accountEmail, learningActivity.lastRefreshAt, t])

  // ── Danger zone ──
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deleteState, setDeleteState] = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const [deleteError, setDeleteError] = useState<string | null>(null)

  // Reset total unifié avec AccountManager.confirmDelete :
  //   1. clearAllUserData() itère DELETE /api/accounts/<id> (scoped JWT), puis
  //      vide localStorage + sessionStorage + IndexedDB.
  //   2. window.location.reload() pour repartir sur l'onboarding.
  // L'ancien appel à /api/dev/reset-all-data (loopback-only) est retiré : en prod
  // il retournait 403 et faisait échouer tout le flow avant le nettoyage local.
  const handleDeleteAll = useCallback(async () => {
    setDeleteState('running')
    setDeleteError(null)
    try {
      await clearAllUserData()
      setDeleteState('done')
      setTimeout(() => { window.location.reload() }, 600)
    } catch (err) {
      setDeleteState('error')
      setDeleteError(err instanceof Error ? err.message : t('error_delete_failed'))
    }
  }, [t])

  const showRefreshScreen = refreshState === 'running' || refreshState === 'failed'

  const refreshProgress = showRefreshScreen ? {
    isActive: refreshState === 'running',
    emailsProcessed: 0,
    emailsTotal: refreshEmailsTotal,
    patterns: [],
    confidenceScore: 0,
    currentPhase: '',
    agentSteps: refreshAgentSteps,
    error: refreshError,
    // Refresh path doesn't surface per-finding narration yet — pass an
    // empty buffer to satisfy the LearningProgress contract.
    discoveries: [],
  } : null


  if (loading) {
    return (
      <div className="training-page">
        <div className="training-page-loading">
          <div className="training-spinner" />
          <span>{t('training_loading')}</span>
        </div>
      </div>
    )
  }

  return (
    <div className="training-page">
      <div className="training-page-header">
        <div className="training-page-header-left">
          {onBack && (
            <button className="training-page-back" onClick={onBack} aria-label={t('common:back')} title={t('common:back')}>
              <ChevronLeftIcon size={20} />
            </button>
          )}
          <div>
            <h2>{t('training_title')}</h2>
          </div>
        </div>
        <div className="training-page-header-actions">
          <button className="settings-close" onClick={onClose} aria-label={t('common:close')}>
            <CloseIcon />
          </button>
        </div>
      </div>

      <div className="training-page-content">
        {showRefreshScreen && refreshProgress ? (
          <LearningProgressScreen
            progress={refreshProgress}
            onRetry={refreshState === 'failed' ? handleRefresh : undefined}
            title={refreshState === 'failed' ? t('refresh_failed') : t('refresh_in_progress')}
            subtitle={t('refresh_subtitle')}
            steps={REFRESH_STEPS}
          />
        ) : (
          <>
            {error && (
              <div className="training-error">
                {error}
                <button onClick={() => handleSave()} className="training-retry-btn" disabled={saving}>{t('retry', { ns: 'common' })}</button>
              </div>
            )}
            <PillarNav activePillar={activePillar} onSelect={setActivePillar} detected={pillarDetected} markIncomplete hintOverrides={pillarHints} />

            <div className="training-pillar-content" key={activePillar}>
              {activePillar === 'profil' && (
                <PillarProfil profil={data.profil} onUpdate={updateProfil} />
              )}

              {activePillar === 'style' && (
                <PillarStyle
                  profil={data.profil}
                  onUpdateProfil={updateProfil}
                  rules={draftRules}
                  onToggleRule={handleToggleRule}
                  onDeleteRule={handleDeleteRule}
                  contactStyles={contactStyles}
                  defaultStyle={defaultStyle || undefined}
                  onSaveContactStyle={handleSaveContactStyle}
                  onDeleteContactStyle={handleDeleteContactStyle}
                  onUpdateDefaultStyle={handleUpdateDefaultStyle}
                  pendingCardSaveRef={editingCardSaveRef}
                />
              )}

              {activePillar === 'savoir' && (
                <PillarSavoir
                  savoir={data.savoir}
                  learnedSavoirs={learnedSavoirs}
                  onAddSavoir={addSavoir}
                  onUpdateSavoir={updateSavoir}
                  onUpdateSavoirCategory={updateSavoirCategory}
                  onRemoveSavoir={removeSavoir}
                  onDeleteLearnedSavoir={handleDeleteLearnedSavoir}
                  onImportFaq={importFaq}
                />
              )}

              {activePillar === 'autolabel' && (
                <PillarAutoLabel
                  category={autoLabelCategory}
                />
              )}
            </div>
          </>
        )}
      </div>

      {!showRefreshScreen && (
        <div className="training-page-footer-area">
          <div className="training-danger-zone-minimal">
            <button
              className="training-danger-link"
              onClick={() => setShowDeleteConfirm(true)}
            >
              <TrashIcon size={13} />
              {t('danger_zone_btn')}
            </button>
          </div>
        </div>
      )}

      <TrainingFooter
        hasChanges={hasChanges}
        saving={saving}
        onSave={handleSave}
        onReset={handleReset}
      />

      {showDeleteConfirm && (
        <div className="training-danger-overlay" role="dialog" aria-modal="true" aria-labelledby={dialogId}>
          <div className="training-danger-modal">
            <h3 id={dialogId} className="training-danger-modal-title">{t('danger_confirm_title')}</h3>
            <p className="training-danger-modal-body">{t('danger_confirm_body_simple')}</p>
            {deleteState === 'error' && (
              <p className="training-danger-modal-error">{t('danger_error', { error: deleteError })}</p>
            )}
            {deleteState === 'done' && (
              <p className="training-danger-modal-success">{t('danger_done')}</p>
            )}
            <div className="training-danger-modal-actions">
              <Button
                type="button"
                variant="outline"
                onClick={() => { setShowDeleteConfirm(false); setDeleteState('idle') }}
                disabled={deleteState === 'running'}
              >
                {t('danger_cancel')}
              </Button>
              <Button
                type="button"
                variant="destructive"
                onClick={handleDeleteAll}
                disabled={deleteState === 'running' || deleteState === 'done'}
              >
                {deleteState === 'running' ? t('danger_deleting') : t('danger_delete_btn')}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
