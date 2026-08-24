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

import { useState, useRef, useEffect, useCallback, useImperativeHandle, forwardRef } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import type { SlashCommand } from '../../utils/slash-commands'
import {
  getCurrentAccountId,
  getCachedAccountId,
  loadSaved,
  persistSaved,
  type SavedCmd,
} from './aiCommandStorage'
import { EditIcon, CloseIcon, PlusIcon, CheckIcon } from '../icons/ActionIcons'
import './AICommandMenu.css'

export interface AICommandMenuHandle {
  /** Inject du texte transcrit dans le champ customPrompt (utilisé quand
   *  l'utilisateur dicte via le mic — le parent route le transcript ici
   *  au lieu d'écrire dans le body). */
  injectText: (text: string) => void
  /** True quand la popup est visible. Lue par le parent pour décider de
   *  router les transcripts vocaux vers cette popup ou vers le body. */
  isOpen: () => boolean
}

interface AICommandMenuProps {
  commands: SlashCommand[]
  onCommandSelect: (cmd: SlashCommand) => void
  /** Soumis avec le texte tapé. Toujours en mode compose maintenant — le
   *  mode surgical est géré par la SurgicalEditBar inline (pas dans la popup). */
  onCustomSubmit: (prompt: string) => void
  onDictate: () => void
  disabled?: boolean
  disabledReason?: string
  isRecording: boolean
  isTranscribing: boolean
  onStopRecording: () => void
  showDictateOption: boolean
  dictationEnabled?: boolean
  transcriptionError: string | null
  /** True quand le brouillon contient du texte. Conditionne l'affichage de
   *  l'option "Modifier" dans la popup (sinon il n'y a rien à modifier). */
  bodyHasContent?: boolean
  /** Notifié à chaque transition open/close de la popup. Le parent l'utilise
   *  pour router les transcripts vocaux vers injectText quand la popup est
   *  ouverte. */
  onOpenChange?: (open: boolean) => void
  /** Click sur le preset "Modifier" → le parent ouvre la SurgicalEditBar
   *  inline (et ferme cette popup). */
  onEnterSurgicalMode?: () => void
  /** Une commande/prompt soumis est en cours d'exécution côté parent
   *  (refine LLM, 8-15 s de latence réelle). Le bouton montre un spinner et
   *  se désactive — sans ce feedback l'utilisateur conclut que le prompt ne
   *  fait rien et re-soumet (rapport 2026-06-09 « can't use prompt »). */
  busy?: boolean
}


const CMD_LABELS: Record<string, string> = {
  '/expand': 'cmd_expand',
}

// Détection plateforme une seule fois au chargement du module — utilisée
// pour choisir entre "Ctrl" et "⌘" dans les badges raccourci.
const platformIsMac = typeof navigator !== 'undefined'
  && (navigator.platform?.includes('Mac') || /Mac/i.test(navigator.userAgent))

const AI_CMD_POPOVER_MAX_WIDTH = 360
const AI_CMD_POPOVER_MARGIN = 16


// Suggested short label for a pinned instruction. Strips a few common
// filler openers ("Please…", "Make this…", etc.) then takes the first
// 3 words and caps the result at 28 chars. The user always sees and can
// override this in the inline "Save as" row, so the heuristic only needs
// to be right ~60 % of the time — when it's wrong, the rename is one
// keystroke away because the field is auto-focused and select-all'd.
const FILLER_OPENER = /^(please\s+|could\s+you\s+|can\s+you\s+|i\s+(?:want|need|would\s+like)\s+(?:you\s+)?to\s+|make\s+(?:this|it)\s+|transform\s+these\s+notes?\s+(?:into\s+an?\s+)?email\s*[:.]?\s*)/i
function suggestChipLabel(text: string): string {
  const stripped = text.replace(FILLER_OPENER, '').trim()
  const words = stripped.split(/\s+/).slice(0, 3).join(' ')
  const truncated = words.length > 28 ? words.slice(0, 27) + '…' : words
  return truncated.charAt(0).toUpperCase() + truncated.slice(1)
}

function getCommandIcon(command: string) {
  switch (command) {
    case '/expand':
      // Sparkle (matches the "AI generate from notes" intent — used in the
      // image mock as the featured chip glyph).
      return <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2v1"/><path d="M3.05 11H4"/><path d="M20 11h.95"/><path d="m4.93 4.93.7.7"/><path d="m18.36 4.93-.7.7"/><path d="M12 14a4 4 0 0 0 4-4 4 4 0 0 0-8 0 4 4 0 0 0 4 4Z"/></svg>
    default:
      return <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="1"/></svg>
  }
}

export const AICommandMenu = forwardRef<AICommandMenuHandle, AICommandMenuProps>(function AICommandMenu({
  commands,
  onCommandSelect,
  onCustomSubmit,
  onDictate,
  disabled,
  disabledReason,
  isRecording,
  isTranscribing,
  onStopRecording,
  showDictateOption,
  dictationEnabled = true,
  transcriptionError,
  bodyHasContent = false,
  onOpenChange,
  onEnterSurgicalMode,
  busy = false,
}, ref) {
  const { t } = useTranslation('compose')
  const [isOpen, setIsOpen] = useState(false)
  const [customPrompt, setCustomPrompt] = useState('')
  const [focusIndex, setFocusIndex] = useState(-1)
  const [accountId, setAccountId] = useState<string | null>(getCachedAccountId())
  const [savedCmds, setSavedCmds] = useState<SavedCmd[]>(() => loadSaved(getCachedAccountId()))
  const [editingId, setEditingId] = useState<number | null>(null)

  // Resolve the active account id once on mount (cached at module level),
  // then reload the saved commands list from the account-scoped storage key.
  useEffect(() => {
    let cancelled = false
    getCurrentAccountId().then(id => {
      if (cancelled) return
      setAccountId(id)
      setSavedCmds(loadSaved(id))
    }).catch(err => {
      // Audit Cluster D (2026-05-11) F-08: previously unhandled rejection.
      // Saved commands stay empty silently; user sees no personalised
      // shortcuts and has no clue why.
      console.warn('[AICommandMenu] account resolve failed:', err)
    })
    return () => { cancelled = true }
  }, [])

  // React to account switches dispatched elsewhere in the app
  useEffect(() => {
    const onAccountChanged = () => {
      getCurrentAccountId().then(id => {
        setAccountId(id)
        setSavedCmds(loadSaved(id))
      }).catch(err => {
        // Audit Cluster D F-08.
        console.warn('[AICommandMenu] account resolve failed on change:', err)
      })
    }
    window.addEventListener('agentys:account-changed', onAccountChanged)
    return () => window.removeEventListener('agentys:account-changed', onAccountChanged)
  }, [])
  const [editingValue, setEditingValue] = useState('')
  // Two-step pin flow : click 📌 sets `pendingSave` with the instruction
  // text + a suggested short label. The "Save as" row slides in below the
  // main input ; Enter / ✓ commits, Esc / ✕ cancels and restores the input.
  const [pendingSave, setPendingSave] = useState<{ instruction: string; label: string } | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const btnRef = useRef<HTMLButtonElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const editInputRef = useRef<HTMLInputElement>(null)
  const saveAsInputRef = useRef<HTMLInputElement>(null)
  const itemsRef = useRef<(HTMLDivElement | null)[]>([])
  // Spacebar PTT — flag pour distinguer "espace tapé pendant qu'on enregistre"
  // (insère un espace) de "espace maintenu pour PTT" (enregistre tant qu'on
  // tient). Le handler PTT global du useWhisperRecording bail-out dès que le
  // focus est dans un <input>, donc on doit câbler le PTT localement ici, comme
  // SurgicalEditBar le fait sur son propre input.
  const spacePttRef = useRef(false)
  const [popoverPos, setPopoverPos] = useState<{ bottom: number; left: number; width: number } | null>(null)

  const closeMenu = useCallback(() => {
    setIsOpen(false)
    setCustomPrompt('')
    setFocusIndex(-1)
    setPendingSave(null)
  }, [])

  // Track open state in a ref so parent's isOpen() always reads fresh value.
  const isOpenRef = useRef(false)
  useEffect(() => { isOpenRef.current = isOpen }, [isOpen])

  // Notify parent on open/close so it can route voice transcripts here.
  useEffect(() => { onOpenChange?.(isOpen) }, [isOpen, onOpenChange])

  // Imperative handle : permet au parent (NewMessageModal) d'injecter le
  // transcript Whisper directement dans le customPrompt quand la popup est
  // ouverte, plutôt que dans le body.
  useImperativeHandle(ref, () => ({
    injectText: (text: string) => {
      const cleaned = text.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
      if (!cleaned) return
      setCustomPrompt(prev => {
        if (!prev) return cleaned
        const sep = /[.!?…\s]$/.test(prev) ? '' : ' '
        return prev + sep + cleaned
      })
      setTimeout(() => inputRef.current?.focus(), 30)
    },
    isOpen: () => isOpenRef.current,
  }), [])

  // Click "Modifier" — ferme la popup et délègue au parent qui ouvre la
  // SurgicalEditBar inline (palette teal, dans la zone verte sous le body).
  const handleClickModifier = useCallback(() => {
    closeMenu()
    onEnterSurgicalMode?.()
  }, [closeMenu, onEnterSurgicalMode])

  // Compute popover position when open
  useEffect(() => {
    if (!isOpen || !btnRef.current) return
    const updatePos = () => {
      const rect = btnRef.current!.getBoundingClientRect()
      const width = Math.min(
        AI_CMD_POPOVER_MAX_WIDTH,
        Math.max(0, window.innerWidth - AI_CMD_POPOVER_MARGIN * 2)
      )
      const maxLeft = Math.max(AI_CMD_POPOVER_MARGIN, window.innerWidth - width - AI_CMD_POPOVER_MARGIN)
      const preferredLeft = rect.right - width
      const left = Math.min(Math.max(AI_CMD_POPOVER_MARGIN, preferredLeft), maxLeft)
      setPopoverPos({ bottom: window.innerHeight - rect.top + 8, left, width })
    }
    updatePos()
    window.addEventListener('scroll', updatePos, true)
    window.addEventListener('resize', updatePos)
    return () => {
      window.removeEventListener('scroll', updatePos, true)
      window.removeEventListener('resize', updatePos)
    }
  }, [isOpen])

  // Close on outside click
  useEffect(() => {
    if (!isOpen) return
    const handler = (e: MouseEvent) => {
      const target = e.target as Node
      if (menuRef.current?.contains(target)) return
      if (popoverRef.current?.contains(target)) return
      closeMenu()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [isOpen, closeMenu])

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') closeMenu() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [isOpen, closeMenu])

  // Ctrl+J / ⌘+J → open the popover. Listener mounted whenever the
  // component is mounted (i.e. whenever the host modal is open), so all
  // consumers (NewMessageModal, ReplyComposer, PendingDraftDetail) get
  // the shortcut for free without parent-side wiring. We preventDefault
  // because Chrome/Firefox bind Ctrl+J to "open Downloads" and would
  // otherwise hijack it.
  useEffect(() => {
    if (disabled || isTranscribing) return
    const handler = (e: KeyboardEvent) => {
      const isMeta = e.metaKey || e.ctrlKey
      if (!isMeta || e.shiftKey || e.altKey) return
      if (e.key.toLowerCase() !== 'j') return
      e.preventDefault()
      if (isRecording) { onStopRecording(); return }
      setIsOpen(true)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [disabled, isTranscribing, isRecording, onStopRecording])

  // Focus input when menu opens
  useEffect(() => {
    if (isOpen) setTimeout(() => inputRef.current?.focus(), 50)
  }, [isOpen])

  const handleCustomSubmit = useCallback(() => {
    if (disabled || !customPrompt.trim()) return
    onCustomSubmit(customPrompt.trim())
    closeMenu()
  }, [customPrompt, disabled, onCustomSubmit, closeMenu])

  // Click 📌 → don't save yet ; open the inline "Save as" row pre-filled
  // with a suggested short label. The user types a real name (or accepts
  // the default with Enter) before the chip is committed.
  const handleSaveCmd = useCallback(() => {
    const text = customPrompt.trim()
    if (!text) return
    setPendingSave({ instruction: text, label: suggestChipLabel(text) })
    // Auto-focus + select-all so the user can type-replace in one keystroke.
    setTimeout(() => {
      saveAsInputRef.current?.focus()
      saveAsInputRef.current?.select()
    }, 30)
  }, [customPrompt])

  const handleConfirmSave = useCallback(() => {
    if (!pendingSave) return
    const rawLabel = pendingSave.label.trim()
    // Fallback if the user empties the field — never persist an empty label.
    const label = rawLabel || suggestChipLabel(pendingSave.instruction)
    const next = [...savedCmds, { id: Date.now(), label, instruction: pendingSave.instruction }]
    setSavedCmds(next)
    persistSaved(accountId, next)
    setPendingSave(null)
    setCustomPrompt('')
    setTimeout(() => inputRef.current?.focus(), 30)
  }, [pendingSave, savedCmds, accountId])

  const handleCancelSave = useCallback(() => {
    setPendingSave(null)
    // Keep customPrompt intact — user may want to keep editing the instruction.
    setTimeout(() => inputRef.current?.focus(), 30)
  }, [])

  const handleDeleteSaved = useCallback((id: number) => {
    const next = savedCmds.filter(c => c.id !== id)
    setSavedCmds(next)
    persistSaved(accountId, next)
  }, [savedCmds, accountId])

  const handleStartEdit = useCallback((cmd: SavedCmd) => {
    setEditingId(cmd.id)
    setEditingValue(cmd.instruction)
    setTimeout(() => editInputRef.current?.select(), 30)
  }, [])

  const handleCommitEdit = useCallback((id: number) => {
    const text = editingValue.trim()
    if (!text) { setEditingId(null); return }
    const label = text.length > 28 ? text.slice(0, 28) + '…' : text
    const next = savedCmds.map(c => c.id === id ? { ...c, label, instruction: text } : c)
    setSavedCmds(next)
    persistSaved(accountId, next)
    setEditingId(null)
  }, [editingValue, savedCmds, accountId])

  const handleCancelEdit = useCallback(() => {
    setEditingId(null)
    setEditingValue('')
  }, [])

  const handleCommandClick = useCallback((cmd: SlashCommand) => {
    if (disabled) return
    onCommandSelect(cmd)
    closeMenu()
  }, [disabled, onCommandSelect, closeMenu])

  const handleDictateClick = useCallback(() => {
    if (!dictationEnabled) return
    closeMenu()
    onDictate()
  }, [dictationEnabled, onDictate, closeMenu])

  const handleButtonClick = useCallback(() => {
    if (disabled) return
    if (isRecording) { onStopRecording(); return }
    if (showDictateOption && !isOpen) {
      if (dictationEnabled) onDictate()
      return
    }
    setIsOpen(prev => !prev)
  }, [dictationEnabled, disabled, isRecording, onStopRecording, showDictateOption, isOpen, onDictate])

  // [DESKTOP-DISABLED 2026-05-06] Le preset "Modifier" + son raccourci Ctrl+M
  // sont désactivés sur desktop pour le moment. La feature SurgicalEditBar
  // reste entièrement en place (composant + onEnterSurgicalMode + Ctrl+M
  // handler dans NewMessageModal sont commentés en miroir) parce qu'elle
  // sera réutilisée dans l'app mobile. Pour ré-activer : flipper
  // showModifierPreset à true ici ET retirer le `&& false` dans
  // NewMessageModal.tsx (rechercher [DESKTOP-DISABLED 2026-05-06]).
  const showModifierPreset = false
  const modifierEnabled = bodyHasContent

  // Click "+ New" — focuses the input below so the user can type a fresh
  // instruction and pin it via the 📌 button. The pin button is invisible
  // until the user types something (opacity 0.2 when disabled), so a
  // first-time user wouldn't know how to save. Toggling `newHintShown` for
  // 3s does two things : swaps the placeholder to a save-flow hint, and
  // adds a one-shot teal pulse on the input wrap to draw the eye.
  const [newHintShown, setNewHintShown] = useState(false)
  const newHintTimerRef = useRef<number | null>(null)
  const handleClickNewChip = useCallback(() => {
    inputRef.current?.focus()
    setNewHintShown(true)
    if (newHintTimerRef.current !== null) window.clearTimeout(newHintTimerRef.current)
    newHintTimerRef.current = window.setTimeout(() => {
      setNewHintShown(false)
      newHintTimerRef.current = null
    }, 3000)
  }, [])
  useEffect(() => () => {
    if (newHintTimerRef.current !== null) window.clearTimeout(newHintTimerRef.current)
  }, [])

  // Flat list matching chip render order : commands (featured first) →
  // modifier → saved → dictate. Index i corresponds to itemsRef.current[i]
  // and drives keyboard navigation (ArrowUp/ArrowDown from the input).
  const orderedCommands = [...commands].sort((a, b) => Number(!!b.featured) - Number(!!a.featured))
  const allItems: ({ type: 'command'; cmd: SlashCommand } | { type: 'modifier' } | { type: 'saved'; savedId: number } | { type: 'dictate' })[] = [
    ...orderedCommands.map(cmd => ({ type: 'command' as const, cmd })),
    ...(showModifierPreset ? [{ type: 'modifier' as const }] : []),
    ...savedCmds.map(c => ({ type: 'saved' as const, savedId: c.id })),
    ...(showDictateOption ? [{ type: 'dictate' as const }] : []),
  ]

  const handleMenuKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (!isOpen) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setFocusIndex(i => {
        const next = i < allItems.length - 1 ? i + 1 : 0
        itemsRef.current[next]?.focus()
        return next
      })
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setFocusIndex(i => {
        if (i <= 0) { inputRef.current?.focus(); return -1 }
        const next = i - 1
        itemsRef.current[next]?.focus()
        return next
      })
    } else if (e.key === 'Enter' && focusIndex >= 0) {
      e.preventDefault()
      const item = allItems[focusIndex]
      if (item.type === 'dictate') handleDictateClick()
      else if (item.type === 'modifier') handleClickModifier()
      else if (item.type === 'command') handleCommandClick(item.cmd)
      else if (item.type === 'saved') {
        const saved = savedCmds.find(c => c.id === item.savedId)
        if (saved) { onCustomSubmit(saved.instruction); closeMenu() }
      }
    }
  }, [isOpen, allItems, focusIndex, handleDictateClick, handleCommandClick, handleClickModifier, savedCmds, onCustomSubmit, closeMenu])

  return (
    <div className="ai-cmd" ref={menuRef}>
      {/* Trigger button — la baguette ouvre la popup, point.
          On garde l'icône baguette stable même pendant un recording : la
          recording state est déjà visible (1) sur le mic du toolbar
          principal, (2) sur le mic inline dans la popup. La faire varier
          ici en plus crée une triple redondance confusante.
          Le mode "trigger button = mic" (showDictateOption=true) reste
          inchangé pour les autres consumers du composant. */}
      <button
        ref={btnRef}
        className={`ai-cmd-btn${isRecording && showDictateOption ? ' ai-cmd-recording' : ''}${isOpen ? ' ai-cmd-active' : ''}`}
        onClick={handleButtonClick}
        disabled={disabled || busy || (isTranscribing && showDictateOption) || (showDictateOption && !dictationEnabled && !isRecording)}
        title={
          isRecording && showDictateOption
            ? 'Stop'
            : disabledReason
              ? disabledReason
            : showDictateOption && !isOpen
              ? t('ai_cmd_dictate')
              : `${t('ai_cmd_open')} · ${platformIsMac ? '⌘ J' : 'Ctrl J'}`
        }
        type="button"
        data-testid="ai-command-trigger"
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-keyshortcuts={showDictateOption ? undefined : (platformIsMac ? 'Meta+J' : 'Control+J')}
      >
        {/* Si showDictateOption est false (cas Compose), le bouton est
            UNIQUEMENT le déclencheur de la popup → icône baguette stable.
            Si showDictateOption est true (autres consumers), on garde le
            comportement multi-état spinner/waveform/mic/wand. */}
        {busy ? (
          <span className="ai-cmd-spinner ai-cmd-spinner--accent" data-testid="ai-command-busy" />
        ) : showDictateOption && isTranscribing ? (
          <span className="ai-cmd-spinner" />
        ) : showDictateOption && isRecording ? (
          <svg width="20" height="20" viewBox="0 0 20 20" fill="var(--accent-primary, #0d9488)" aria-hidden="true">
            <rect className="ai-wf-1" x="1"  y="6" width="3" height="8"  rx="1.5"/>
            <rect className="ai-wf-2" x="6"  y="3" width="3" height="14" rx="1.5"/>
            <rect className="ai-wf-3" x="11" y="5" width="3" height="10" rx="1.5"/>
            <rect className="ai-wf-4" x="16" y="7" width="3" height="6"  rx="1.5"/>
          </svg>
        ) : showDictateOption && !isOpen ? (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/>
            <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
            <line x1="12" y1="19" x2="12" y2="22"/>
            <line x1="8" y1="22" x2="16" y2="22"/>
          </svg>
        ) : (
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="m21.64 3.64-1.28-1.28a1.21 1.21 0 0 0-1.72 0L2.36 18.64a1.21 1.21 0 0 0 0 1.72l1.28 1.28a1.2 1.2 0 0 0 1.72 0L21.64 5.36a1.2 1.2 0 0 0 0-1.72Z"/>
            <path d="m14 7 3 3"/>
            <path d="M5 6v4"/>
            <path d="M19 14v4"/>
            <path d="M10 2v2"/>
            <path d="M7 8H3"/>
            <path d="M21 16h-4"/>
            <path d="M11 3H9"/>
          </svg>
        )}
        {/* Verrou « plan » : disabledReason = désactivation par le paywall,
            pas par un état transitoire (génération). La raison reste dans
            title ; le cadenas la rend lisible sans survol. */}
        {disabled && disabledReason && !busy && (
          <span className="ai-cmd-lock" data-testid="ai-cmd-lock" aria-hidden="true">
            <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
              <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
            </svg>
          </span>
        )}
      </button>

      {/* Transcription error */}
      {transcriptionError && (
        <div className="ai-cmd-error">{transcriptionError}</div>
      )}

      {/* Popover menu — rendered via portal to escape overflow clipping */}
      {isOpen && !isRecording && popoverPos && createPortal(
        <div
          ref={popoverRef}
          className="ai-cmd-popover ai-cmd-popover--portal"
          role="menu"
          onKeyDown={handleMenuKeyDown}
          style={{ bottom: popoverPos.bottom, left: popoverPos.left, width: popoverPos.width }}
          data-escape-owner=""
        >

          {/* ── Chips row ──────────────────────────────────────────────
              Built-in commands (featured first) → Modifier → saved cmds →
              "+ New". Keyboard nav iterates this same flat order via the
              itemsRef array. */}
          <div className="ai-cmd-chips" role="group" aria-label={t('ai_cmd_title')}>
            {orderedCommands.map((cmd, i) => (
              <button
                key={cmd.command}
                type="button"
                ref={(el) => { itemsRef.current[i] = el as unknown as HTMLDivElement | null }}
                className={`ai-cmd-chip${cmd.featured ? ' ai-cmd-chip--featured' : ''} ai-cmd-row`}
                onClick={() => handleCommandClick(cmd)}
                role="menuitem"
                tabIndex={0}
              >
                <span className="ai-cmd-chip-icon">{getCommandIcon(cmd.command)}</span>
                <span className="ai-cmd-chip-label">{t(cmd.labelKey || CMD_LABELS[cmd.command] || cmd.label, cmd.label)}</span>
                {cmd.expand && <span className="ai-cmd-chip-kbd">{platformIsMac ? '⌘G' : 'Ctrl G'}</span>}
              </button>
            ))}

            {showModifierPreset && (
              <button
                type="button"
                ref={(el) => { itemsRef.current[orderedCommands.length] = el as unknown as HTMLDivElement | null }}
                className={`ai-cmd-chip ai-cmd-chip--modifier ai-cmd-row${modifierEnabled ? '' : ' ai-cmd-chip--disabled'}`}
                onClick={modifierEnabled ? handleClickModifier : undefined}
                role="menuitem"
                tabIndex={modifierEnabled ? 0 : -1}
                aria-disabled={!modifierEnabled}
                title={modifierEnabled ? '' : t('ai_cmd_modifier_disabled_tooltip')}
                disabled={!modifierEnabled}
                data-testid="ai-cmd-modifier"
              >
                <span className="ai-cmd-chip-icon">
                  <EditIcon size={13} />
                </span>
                <span className="ai-cmd-chip-label">{t('edit')}</span>
                <span className="ai-cmd-chip-kbd">{platformIsMac ? '⌘M' : 'Ctrl M'}</span>
              </button>
            )}

            {savedCmds.map((cmd, i) => {
              const idx = orderedCommands.length + (showModifierPreset ? 1 : 0) + i
              const isEditing = editingId === cmd.id
              return (
                <span
                  key={cmd.id}
                  ref={(el) => { itemsRef.current[idx] = el as unknown as HTMLDivElement | null }}
                  className={`ai-cmd-chip ai-cmd-chip--saved ai-cmd-row${isEditing ? ' ai-cmd-chip--editing ai-cmd-row-editing' : ''}`}
                  onClick={() => { if (!isEditing) { onCustomSubmit(cmd.instruction); closeMenu() } }}
                  onDoubleClick={(e) => { e.stopPropagation(); handleStartEdit(cmd) }}
                  role="menuitem"
                  tabIndex={0}
                >
                  {isEditing ? (
                    <input
                      ref={editInputRef}
                      className="ai-cmd-row-label-saved ai-cmd-edit-input"
                      value={editingValue}
                      onChange={(e) => setEditingValue(e.target.value)}
                      onClick={(e) => e.stopPropagation()}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') { e.preventDefault(); handleCommitEdit(cmd.id) }
                        if (e.key === 'Escape') { e.stopPropagation(); handleCancelEdit() }
                      }}
                      onBlur={() => handleCommitEdit(cmd.id)}
                      autoComplete="off"
                      spellCheck={false}
                    />
                  ) : (
                    <span className="ai-cmd-chip-label ai-cmd-row-label-saved" title={t('ai_cmd_chip_edit_tooltip')}>{cmd.label}</span>
                  )}
                  {!isEditing && (
                    <button type="button" className="ai-cmd-row-del ai-cmd-chip-del" onClick={(e) => { e.stopPropagation(); handleDeleteSaved(cmd.id) }} title={t('ai_cmd_chip_delete_tooltip')}><CloseIcon size={14} /></button>
                  )}
                </span>
              )
            })}

            <button
              type="button"
              className="ai-cmd-chip ai-cmd-chip--new"
              onClick={handleClickNewChip}
              title={t('ai_cmd_new_chip_tooltip')}
              aria-label={t('ai_cmd_new_chip_aria')}
              data-testid="ai-cmd-new"
            >
              <PlusIcon size={14} />
            </button>
          </div>

          {/* ── Custom prompt input ────────────────────────────────────
              Below the chips. Sparkle adornment matches the image mock,
              the trailing arrow submits, the pin saves the typed text as
              a new chip. The mic & ⌘I shortcut sit between for parity
              with the previous layout. */}
          <div className={`ai-cmd-input-wrap${newHintShown ? ' ai-cmd-input-wrap--pulse' : ''}`}>
            <input
              ref={inputRef}
              type="text"
              className="ai-cmd-input"
              value={customPrompt}
              onChange={(e) => setCustomPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleCustomSubmit(); return }
                if (e.key === 'Escape') { e.stopPropagation(); closeMenu(); return }
                if (e.key === 'ArrowDown') { e.preventDefault(); itemsRef.current[0]?.focus(); setFocusIndex(0); return }
                // PTT — Hold Space (input vide) → start recording, release → stop.
                // Mirror du pattern SurgicalEditBar.handleKeyDown. Le transcript
                // remonte via le useWhisperRecording du parent qui appelle
                // injectText(html) quand la popup est ouverte.
                if (e.key === ' ' && !customPrompt && !isRecording && !isTranscribing && !disabled && dictationEnabled) {
                  e.preventDefault()
                  if (!spacePttRef.current) {
                    spacePttRef.current = true
                    onDictate()
                  }
                }
              }}
              onKeyUp={(e) => {
                if (e.key === ' ' && spacePttRef.current) {
                  e.preventDefault()
                  spacePttRef.current = false
                  if (isRecording) onStopRecording()
                }
              }}
              onBlur={() => {
                // Garde-fou : si l'input perd le focus pendant une session PTT
                // (clic ailleurs, popup fermée), on stoppe l'enregistrement
                // sinon il continuerait jusqu'à la silence detection.
                if (spacePttRef.current && isRecording) {
                  spacePttRef.current = false
                  onStopRecording()
                }
              }}
              placeholder={newHintShown ? t('ai_cmd_pin_hint') : t('ai_cmd_custom_placeholder')}
              autoComplete="off"
              spellCheck={false}
            />
            <button type="button" className="ai-cmd-pin-btn" onClick={handleSaveCmd} disabled={!customPrompt.trim() || !!pendingSave} title={t('ai_cmd_pin_btn_tooltip')}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"/>
              </svg>
            </button>
            {/* Mic inline — déclenche le mic du parent (handleMicClick passé
                via onDictate). Le parent route le transcript ici via
                injectText quand la popup est ouverte (cf. forwardRef +
                aiCmdMenuRef côté NewMessageModal). */}
            <button
              type="button"
              className={`ai-cmd-inline-mic${isRecording ? ' ai-cmd-inline-mic--active' : ''}`}
              onClick={() => { if (isRecording) onStopRecording(); else onDictate() }}
              disabled={isTranscribing || (!dictationEnabled && !isRecording)}
              title={
                !dictationEnabled && !isRecording
                  ? t('dictation_requires_trial_or_plan')
                  : isRecording ? t('ai_cmd_mic_stop_tooltip') : t('ai_cmd_mic_start_tooltip')
              }
              aria-label={
                !dictationEnabled && !isRecording
                  ? t('dictation_unavailable')
                  : isRecording ? t('ai_cmd_mic_stop_tooltip') : t('ai_cmd_mic_start_tooltip')
              }
            >
              {isTranscribing ? (
                <span className="ai-cmd-inline-mic-spinner" aria-hidden="true" />
              ) : isRecording ? (
                <svg width="13" height="13" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                  <rect className="ai-cmd-wf-1" x="1"  y="6" width="3" height="8"  rx="1.5"/>
                  <rect className="ai-cmd-wf-2" x="6"  y="3" width="3" height="14" rx="1.5"/>
                  <rect className="ai-cmd-wf-3" x="11" y="5" width="3" height="10" rx="1.5"/>
                  <rect className="ai-cmd-wf-4" x="16" y="7" width="3" height="6"  rx="1.5"/>
                </svg>
              ) : (
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/>
                  <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                  <line x1="12" y1="19" x2="12" y2="22"/>
                  <line x1="8" y1="22" x2="16" y2="22"/>
                </svg>
              )}
            </button>
            <button type="button" className="ai-cmd-send-btn" onClick={handleCustomSubmit} disabled={disabled || !customPrompt.trim()} aria-label={t('generate')}>
              <span className="ai-cmd-send-arrow">&#8593;</span>
            </button>
          </div>

          {/* Save-as row — slides in below the main input when the user
              clicks 📌. The 'Save as' label is decorative ; the input is
              the only interactive thing. Enter / ✓ confirms, Esc / ✕
              cancels and restores the instruction in the main input above. */}
          {pendingSave && (
            <div className="ai-cmd-saveas-row" data-testid="ai-cmd-saveas-row">
              <span className="ai-cmd-saveas-prefix">{t('ai_cmd_saveas_prefix')}</span>
              <input
                ref={saveAsInputRef}
                type="text"
                className="ai-cmd-saveas-input"
                value={pendingSave.label}
                onChange={(e) => setPendingSave(p => p ? { ...p, label: e.target.value } : null)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') { e.preventDefault(); handleConfirmSave() }
                  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); handleCancelSave() }
                }}
                placeholder={t('ai_cmd_saveas_placeholder')}
                autoComplete="off"
                spellCheck={false}
                maxLength={32}
                aria-label={t('ai_cmd_saveas_input_aria')}
              />
              <button
                type="button"
                className="ai-cmd-saveas-btn ai-cmd-saveas-btn--cancel"
                onClick={handleCancelSave}
                title={t('ai_cmd_saveas_cancel_tooltip')}
                aria-label={t('ai_cmd_saveas_cancel_aria')}
              >
                <CloseIcon size={11} />
              </button>
              <button
                type="button"
                className="ai-cmd-saveas-btn ai-cmd-saveas-btn--confirm"
                onClick={handleConfirmSave}
                title={t('ai_cmd_saveas_confirm_tooltip')}
                aria-label={t('ai_cmd_saveas_confirm_aria')}
                data-testid="ai-cmd-saveas-confirm"
              >
                <CheckIcon size={11} />
              </button>
            </div>
          )}

          {/* Dictate row — only rendered for legacy consumers (showDictateOption=true).
              Compose & ReplyComposer pass false; the mic in the input above
              is the canonical entry point now. */}
          {showDictateOption && (
            <div
              ref={(el) => { itemsRef.current[orderedCommands.length + (showModifierPreset ? 1 : 0) + savedCmds.length] = el }}
              className="ai-cmd-row"
              onClick={handleDictateClick}
              role="menuitem"
              aria-disabled={!dictationEnabled}
              tabIndex={0}
            >
              <div className="ai-cmd-row-icon" style={{ background: '#eff6ff', color: '#3b82f6' }}>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.91-3c-.49 0-.9.36-.98.85C16.52 14.2 14.47 16 12 16s-4.52-1.8-4.93-4.15c-.08-.49-.49-.85-.98-.85-.61 0-1.09.54-1 1.14.49 3 2.89 5.35 5.91 5.78V20c0 .55.45 1 1 1s1-.45 1-1v-2.08c3.02-.43 5.42-2.78 5.91-5.78.1-.6-.39-1.14-1-1.14z"/>
                </svg>
              </div>
              <span className="ai-cmd-row-label">{t('ai_cmd_dictate')}</span>
            </div>
          )}

        </div>,
        document.body
      )}
    </div>
  )
})
