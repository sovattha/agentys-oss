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

import { useState, useEffect, useRef, useMemo, useCallback, Suspense, type ReactNode } from 'react'
import DOMPurify from 'dompurify'
import { createPortal } from 'react-dom'
import { lazyWithRetry as lazy } from '../../utils/lazyWithRetry'
import { useTranslation } from 'react-i18next'

import { apiClient, hideContact } from '../../services/api'
import { useWhisperRecording } from '../../hooks/useWhisperRecording'
import { useVoiceLanguage } from '../../hooks/useVoiceLanguage'
import { useVoiceDictationAccess } from '../../hooks/useVoiceDictationAccess'
import { useContactLanguages, extractEmails } from '../../hooks/useContactLanguages'
import { VoiceLanguageBadge } from './VoiceLanguageBadge'
import { detectForgottenAttachment, type AttachmentDetectionResult } from '../../utils/attachmentDetector'
import { isHtmlContent } from '../../utils/emailContent'
import { formatLongDateFromDate, formatDayMonthYear } from '../../utils/dateFormat'
import { silentFailLog, silentFailWithToast } from '../../utils/silentFail'
import i18nInstance from '../../i18n'
import { fetchAccounts } from '../../api/accounts'
import { useAccountSignature } from '../../hooks/useAccountSignature'
import { useSignatureLibrary } from '../../hooks/useSignatureLibrary'
import { SnippetSelector, SnippetEditor } from '../snippets'
import { useSnippets } from '../../hooks/useSnippets'
import { replaceSnippetVariables, findUnreplacedVariables } from '../../api/snippets'
import { snippetContentToInsertionHtml } from '../../utils/snippetInsertion'
import { preserveInlineImages } from '../../utils/preserveInlineImages'
import { ContactAutocomplete } from './ContactAutocomplete'
import { SendButtonSplit } from './SendButtonSplit'
import { InsertAvailabilityButton } from '../availability/InsertAvailabilityButton'
import { RecordingWaveform } from './RecordingWaveform'
import './SchedulePicker.css'
import { useContactGroups } from '../../hooks/useContactGroups'
import type { Snippet, CreateSnippetPayload } from '../../types/snippets'
import type { SpecialtyInfo } from '../../types/specialty'
import { isSpecialtyMatch } from '../../types/specialty'
import { SpecialtyBadge } from '../specialty/SpecialtyBadge'
import { saveComposeDraft, deleteSavedDraft, hasContent, type SavedComposeDraft } from '../../services/draftStorage'
import { hasEscapeOwner } from '../../utils/escapeOwner'
import { isDeleteDraftShortcut } from '../../utils/keyboard'
import { useFocusTrap } from '../../hooks/useFocusTrap'
import { registerPendingSend } from '../../hooks/usePendingSends'
import { getUndoSendDelay } from '../../hooks/useUndoSendSetting'
import { useAutoReminderOnCommitment } from '../../hooks/useAutoReminderOnCommitment'
import { FollowupDatePicker, detectDateFromBody } from '../FollowupDatePicker'
import '../PendingDraftDetail.css'
import '../reply/ReplyComposer.css'
import './NewMessageModal.css'
import { SLASH_COMMANDS } from '../../utils/slash-commands'
import { AICommandMenu, type AICommandMenuHandle } from './AICommandMenu'
import { SurgicalEditBar } from './SurgicalEditBar'
import { useComposeFontPrefs } from '../../hooks/useComposeFontPrefs'
import { DraftEditor } from '../DraftEditor'
import type { DraftEditorHandle } from '../DraftEditor'
import { useInlineImage } from '../../hooks/useInlineImage'
import { useFileDrop } from '../../hooks/useFileDrop'
import { FileDropOverlay } from '../FileDropOverlay'
import { AttachmentCard } from './AttachmentCard'
import { subscribeDraftStream, clearDraftStreamState } from '../../hooks/useWebSocketSync'
import { StageFlow } from '../pipeline/PipelineCards'
import { ThoughtStream } from '../pipeline/ThoughtStream'
import { AIProcessButton } from '../pipeline/AIProcessButton'
import { useDraftStream } from '../../hooks/useDraftStream'
import { useLabels } from '../../hooks/useLabels'
import { ThinkingIndicator } from '../ThinkingIndicator'
import { CloseIcon, TrashIcon, ChevronDownIcon, MagicDraftIcon } from '../icons/ActionIcons'
import { MicPermissionDialog } from './MicPermissionDialog'

const AttachmentReminderModal = lazy(() => import('../AttachmentReminderModal').then(m => ({ default: m.AttachmentReminderModal })))


// ── Inline word-level diff ───────────────────────────────────────────────────
type DiffPart = { type: 'same' | 'add' | 'del'; text: string }

function computeWordDiff(oldText: string, newText: string): DiffPart[] {
  const oldWords = oldText.split(/(\s+)/)
  const newWords = newText.split(/(\s+)/)
  const parts: DiffPart[] = []

  // Simple LCS-based diff
  const m = oldWords.length, n = newWords.length
  // Build LCS table (optimized for small texts)
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0))
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      dp[i][j] = oldWords[i - 1] === newWords[j - 1]
        ? dp[i - 1][j - 1] + 1
        : Math.max(dp[i - 1][j], dp[i][j - 1])
    }
  }

  // Backtrack to build diff
  let i = m, j = n
  const ops: DiffPart[] = []
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldWords[i - 1] === newWords[j - 1]) {
      ops.push({ type: 'same', text: oldWords[i - 1] })
      i--; j--
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      ops.push({ type: 'add', text: newWords[j - 1] })
      j--
    } else {
      ops.push({ type: 'del', text: oldWords[i - 1] })
      i--
    }
  }
  ops.reverse()

  // Merge consecutive same-type tokens
  for (const op of ops) {
    if (parts.length > 0 && parts[parts.length - 1].type === op.type) {
      parts[parts.length - 1].text += op.text
    } else {
      parts.push({ ...op })
    }
  }
  return parts
}

function renderSubtleDiff(parts: DiffPart[]): ReactNode[] {
  let changeIdx = 0
  return parts.flatMap((p, i) => {
    if (p.type === 'del') return []  // deleted text is gone — only show result
    if (p.type === 'same') return [<span key={i}>{p.text}</span>]
    const delay = changeIdx * 0.06
    changeIdx++
    return [
      <span key={i} className="nm-diff-add nm-diff-anim" style={{ animationDelay: `${delay}s` }}>
        {p.text}
      </span>
    ]
  })
}

function countChanges(parts: DiffPart[]): number {
  let count = 0
  for (let i = 0; i < parts.length; i++) {
    if (parts[i].type === 'del') {
      count++
      if (i + 1 < parts.length && parts[i + 1].type === 'add') i++
    } else if (parts[i].type === 'add') {
      count++
    }
  }
  return count
}


interface Attachment {
  name: string
  size: number
  file: File
}

interface NewMessageModalProps {
  isOpen: boolean
  onClose: () => void
  initialDraft?: SavedComposeDraft
  onDraftSaved?: () => void
  accountId?: number
  aiEnabled?: boolean
  onUpgradeRequired?: () => void
}

// Note: la prop `onSend` a été retirée — le composant gère maintenant l'envoi
// lui-même via `registerPendingSend` (audit Send-HIGH "Email lost if app/window
// closes during 15s undo-send"). Si vous cherchez la fonction d'envoi pour la
// surcharger depuis App.tsx, regardez plutôt `usePendingSends`.
export function NewMessageModal({ isOpen, onClose, initialDraft, onDraftSaved, accountId, aiEnabled = true, onUpgradeRequired }: NewMessageModalProps) {
  const { t, i18n } = useTranslation('compose')
  const { t: tCommon } = useTranslation('common')
  const { fontFamilyCss, fontSizeCss } = useComposeFontPrefs()
  const aiLocked = aiEnabled === false
  const paidAiMessage = t('ai_paid_required', { defaultValue: 'Les brouillons IA sont réservés aux abonnements payants.' })
  const showPaidAiBlocked = useCallback(() => {
    window.dispatchEvent(new CustomEvent('agentys:toast', {
      detail: { message: paidAiMessage, type: 'info', duration: 6000 },
    }))
    onUpgradeRequired?.()
  }, [onUpgradeRequired, paidAiMessage])
  const [to, setTo] = useState('')
  // Display names from autocomplete picks → /refine-text `senderName`, so the
  // Ctrl+G prompt opens with "Bonjour <FirstName>," instead of the email-
  // username fallback. Direct-typed emails: backend contacts-DB lookup covers.
  const [recipientNamesByEmail, setRecipientNamesByEmail] = useState<Record<string, string>>({})
  const [cc, setCc] = useState('')
  const [bcc, setBcc] = useState('')
  const [showCc, setShowCc] = useState(false)
  const [showBcc, setShowBcc] = useState(false)
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const sigHtmlRef = useRef<string>('')
  // Holds the pending debounced-autosave timer so a send can cancel it.
  // Without this, sending right after typing lets the ~1s autosave fire AFTER
  // the draft was deleted on send → the sent email reappears as a ghost draft.
  const autosaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [isGenerating, setIsGenerating] = useState(false)
  // Flips true after 15s of generation to switch the ThinkingIndicator label
  // from "Réflexion..." to "Toujours en cours…" — covers Ctrl+G cold-start
  // round-trips (~50s observed) so the user doesn't assume silent failure.
  const [isLongWait, setIsLongWait] = useState(false)
  const [isSending, setIsSending] = useState(false)
  // Audit F-10 (2026-05-16): re-entry guard for doSend / doScheduleSend.
  // `isSending` is a setState — the new value is only visible on the next
  // render, so a second keydown (held Ctrl+Enter / rapid double-tap)
  // fired in the same tick reads the closure's stale `false` and
  // re-enters doSend. ReplyComposer already uses this pattern
  // (ReplyComposer.tsx:898) — mirror it here.
  const sendingRef = useRef(false)
  const [showSnippetSelector, setShowSnippetSelector] = useState(false)
  const [showSnippetEditor, setShowSnippetEditor] = useState(false)
  const [diffOverlay, setDiffOverlay] = useState<DiffPart[] | null>(null)
  // Specialty expertise state — populated when Ctrl+Shift+G triggers a match,
  // cleared on every new generation. Warnings (no match, no active specialty,
  // rate limit, classification error) land in specialtyMessage so the user
  // always sees a visible fallback path instead of a silent downgrade.
  const [specialtyInfo, setSpecialtyInfo] = useState<SpecialtyInfo | null>(null)
  const [specialtyMessage, setSpecialtyMessage] = useState<{ type: 'info' | 'warning' | 'error'; text: string } | null>(null)
  const [streamStage, setStreamStage] = useState<string | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const isStreamingRef = useRef(false)
  // Shared AI drafting narration. `composeId` is set when a generation kicks
  // off; `useDraftStream` then subscribes to WebSocket chunks tagged with that
  // id so ThoughtStream can show the live stage / version / critique. The
  // compose backend (POST /api/emails/compose) does not run the Drafter→Critic
  // pipeline today — see issue #235 — so the post-generation RecapBanner and
  // PipelineDisclosure panels are intentionally not mounted here.
  const [composeId, setComposeId] = useState<string | null>(null)
  const [showPipeline, setShowPipeline] = useState(false)
  const streamView = useDraftStream(composeId, isGenerating)

  // Stable per-session id so autosave + close upsert the same localStorage
  // entry. Restoring a saved draft reuses its id so we don't duplicate it; a
  // fresh modal mints a new id so closing it adds a new entry to the Drafts
  // tab instead of overwriting the previous closed compose.
  const sessionIdRef = useRef<string>('')

  // ── Project prefix picker ──────────────────────────────────────────────────
  const { projectLabels } = useLabels()
  const projectsWithPrefix = useMemo(
    () => projectLabels.filter(l => l.subject_prefix?.trim()),
    [projectLabels]
  )
  const [appliedPrefix, setAppliedPrefix] = useState('')
  const appliedPrefixRef = useRef('')
  const [projectPickerOpen, setProjectPickerOpen] = useState(false)
  const projectPickerRef = useRef<HTMLDivElement>(null)
  const { groups: contactGroups } = useContactGroups()

  const suggestedGroups = useMemo(() => {
    if (!appliedPrefix) return []
    const label = projectsWithPrefix.find(l => l.subject_prefix === appliedPrefix)
    if (!label) return []
    return contactGroups.filter(g => g.label_name === label.name && g.members.length > 0)
  }, [appliedPrefix, projectsWithPrefix, contactGroups])

  const pendingSuggestedGroups = useMemo(() => {
    if (!suggestedGroups.length) return []
    // Hide a suggestion once every member already lives in any recipient field
    // (To, Cc, or Bcc) — otherwise the chip would re-suggest adding to Cc the
    // same people the user already routed there.
    const recipientEmails = new Set(
      `${to},${cc},${bcc}`.toLowerCase().split(',').map(s => s.trim()).filter(Boolean)
    )
    return suggestedGroups.filter(g =>
      !g.members.every(m => recipientEmails.has(m.email.toLowerCase()))
    )
  }, [suggestedGroups, to, cc, bcc])

  // Smart-default routing for group suggestions. Tracks the recipient field
  // the user last focused so a single click on a group chip lands the
  // members in the most likely target (To by default; Cc/Bcc once they
  // click into those rows). Override is one extra click via the chevron.
  const [lastFocusedField, setLastFocusedField] = useState<'to' | 'cc' | 'bcc'>('to')
  const [openGroupMenuId, setOpenGroupMenuId] = useState<string | null>(null)
  const groupChipsRef = useRef<HTMLDivElement>(null)

  const addGroupToField = useCallback((group: typeof contactGroups[number], field: 'to' | 'cc' | 'bcc') => {
    const newEmails = group.members.map(m => m.email)
    const setter = field === 'to' ? setTo : field === 'cc' ? setCc : setBcc
    setter(prev => {
      const existing = prev.split(',').map(s => s.trim()).filter(Boolean)
      const seen = new Set(existing.map(e => e.toLowerCase()))
      const merged = [...existing]
      newEmails.forEach(email => {
        if (!seen.has(email.toLowerCase())) {
          merged.push(email)
          seen.add(email.toLowerCase())
        }
      })
      return merged.join(', ')
    })
    if (field === 'cc') setShowCc(true)
    if (field === 'bcc') setShowBcc(true)
    setOpenGroupMenuId(null)
  }, [])

  // Sync ref with state so closures (suggestSubject callbacks) read current value
  useEffect(() => { appliedPrefixRef.current = appliedPrefix }, [appliedPrefix])

  // Close picker on outside click
  useEffect(() => {
    if (!projectPickerOpen) return
    const handler = (e: MouseEvent) => {
      if (projectPickerRef.current && !projectPickerRef.current.contains(e.target as Node)) {
        setProjectPickerOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [projectPickerOpen])

  // Close the per-chip routing menu on outside click / Esc.
  useEffect(() => {
    if (!openGroupMenuId) return
    const onDown = (e: MouseEvent) => {
      if (groupChipsRef.current && !groupChipsRef.current.contains(e.target as Node)) {
        setOpenGroupMenuId(null)
      }
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpenGroupMenuId(null)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [openGroupMenuId])

  const applyProjectPrefix = useCallback((prefix: string) => {
    const base = appliedPrefixRef.current
      ? subject.startsWith(appliedPrefixRef.current)
        ? subject.slice(appliedPrefixRef.current.length)
        : subject
      : subject
    setAppliedPrefix(prefix)
    setSubject(prefix + base)
    setProjectPickerOpen(false)
  }, [subject])

  const clearProjectPrefix = useCallback(() => {
    if (appliedPrefixRef.current && subject.startsWith(appliedPrefixRef.current)) {
      setSubject(subject.slice(appliedPrefixRef.current.length))
    }
    setAppliedPrefix('')
    setProjectPickerOpen(false)
  }, [subject])

  const [currentAccountId, setCurrentAccountId] = useState<string | undefined>()
  const [isClosing, setIsClosing] = useState(false)
  // Agrandir/réduire le modal (CSS .new-message-modal.gmail-style.maximized).
  // Réinitialisé à chaque ouverture : le composant est monté conditionnellement.
  const [isMaximized, setIsMaximized] = useState(false)
  const focusTrapRef = useFocusTrap(isOpen)
  const toInputRef = useRef<HTMLInputElement>(null)
  const editorRef = useRef<DraftEditorHandle>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { imageInputRef, handleImageInsert, imageError, clearImageError } = useInlineImage(editorRef)
  const ccInputRef = useRef<HTMLInputElement>(null)
  const bccInputRef = useRef<HTMLInputElement>(null)
  const snippetBtnRef = useRef<HTMLButtonElement>(null)
  const diffTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Guard: track if the body has been initialized (prevents async signature from overwriting user text)
  const bodyInitializedRef = useRef(false)

  const dismissDiff = useCallback(() => {
    setDiffOverlay(null)
    if (diffTimerRef.current) { clearTimeout(diffTimerRef.current); diffTimerRef.current = null }
  }, [])

  // Derived plain text from body HTML — used for expand-by-default and dynamic placeholder
  const bodyPlainText = useMemo(
    () => body.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim(),
    [body]
  )

  // Ref vers la popup AI Commands pour y injecter les transcripts Whisper
  // quand elle est ouverte (cas dictée d'une commande IA en mode compose).
  const aiCmdMenuRef = useRef<AICommandMenuHandle | null>(null)
  const aiPopupOpenRef = useRef(false)

  // SurgicalEditBar — barre inline pour modifier un détail. Visible quand
  // surgicalEditOpen=true. Voice transcripts y sont routés via le ref de l'
  // état (lu par handleVoiceTranscript) pour éviter une closure stale.
  const [surgicalEditOpen, setSurgicalEditOpen] = useState(false)
  const [surgicalInstruction, setSurgicalInstruction] = useState('')
  const surgicalEditOpenRef = useRef(false)
  useEffect(() => { surgicalEditOpenRef.current = surgicalEditOpen }, [surgicalEditOpen])

  // Voice dictation (Whisper) — shared hook.
  //
  // Routing du transcript par ordre de priorité :
  //   1. SurgicalEditBar ouverte → setSurgicalInstruction (mode édition)
  //   2. Popup AI Commands ouverte → aiCmdMenuRef.injectText (mode commande)
  //   3. Sinon → insère au curseur dans l'éditeur (dictée standard)
  const handleVoiceTranscript = useCallback((html: string) => {
    const plain = html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
    const isBlank = (s: string) =>
      !s
        .replace(/<[^>]*>/g, '')
        .replace(/&nbsp;|&#160;/gi, '')
        .replace(/\u00A0/g, '')
        .replace(/ /g, '')
        .trim()
    if (surgicalEditOpenRef.current && plain) {
      setSurgicalInstruction(prev => {
        if (!prev) return plain
        const sep = /[.!?…\s]$/.test(prev) ? '' : ' '
        return prev + sep + plain
      })
      return
    }
    if (aiPopupOpenRef.current && aiCmdMenuRef.current) {
      aiCmdMenuRef.current.injectText(html)
      return
    }
    // Insert at the caret so the user sees the words land where the cursor is,
    // and so chained dictations stack at that point. The editor's onChange
    // syncs `body`; fall back to a plain append if the ref isn't available.
    if (editorRef.current) {
      editorRef.current.insertDictation(html)
    } else {
      setBody(prev => (isBlank(prev) ? html : prev + html))
    }
  }, [])
  // Voice dictation language : default to the recipient's preferred language
  // (from Settings → Training contact data), let the user override via the
  // VoiceLanguageBadge picker. Auto-detect when no recipient match.
  const { aggregate: aggregateContactLanguages } = useContactLanguages()
  const recipientEmails = useMemo(
    () => extractEmails(to, cc, bcc),
    [to, cc, bcc],
  )
  const recipientDefaultLang = useMemo(
    () => aggregateContactLanguages(recipientEmails),
    [aggregateContactLanguages, recipientEmails],
  )
  const {
    language: voiceLanguage,
    languageParam: voiceLanguageParam,
    setLanguage: setVoiceLanguage,
  } = useVoiceLanguage(recipientDefaultLang)
  // Langue « du fil » : choix explicite du picker, sinon langue préférée du
  // destinataire (Settings → Entraînement). Le micro DÉMARRE désormais sur cette
  // langue ; si elle ne correspond pas à la parole réelle, useWhisperRecording
  // rejoue en auto-détection (incident 2026-06-11 neutralisé — voir useVoiceLanguage).
  const threadLanguageHint = voiceLanguage !== 'auto' ? voiceLanguage : recipientDefaultLang
  const voiceDictationAllowed = useVoiceDictationAccess()
  const voiceVocabulary = useMemo(
    () => projectLabels.map(label => label.name).filter(Boolean),
    [projectLabels],
  )

  const { isRecording, isTranscribing, transcriptionError, showMicButton: _showMicButton, handleMicClick, audioLevels, silenceDetected: _silenceDetected, silenceCountdown: _silenceCountdown, forceResetTranscription, prewarmMic, softAskOpen, confirmSoftAsk, dismissSoftAsk } = useWhisperRecording(
    bodyPlainText.length === 0,
    true,
    handleVoiceTranscript,
    { language: voiceLanguageParam, promptVocabulary: voiceVocabulary, surfaceSelector: '.new-message-modal', enabled: voiceDictationAllowed },
  )

  // When dictation starts, make sure the editor caret is visible so the user
  // sees where spoken words will land. Only focuses if the editor isn't already
  // focused (push-to-talk holds focus, so its caret position is preserved).
  useEffect(() => {
    if (isRecording) editorRef.current?.focusForDictation()
  }, [isRecording])

  // Reset forcé du flag isTranscribing quand la modale se ferme. Évite l'état
  // "Transcribing..." persistant si la modale est masquée pendant qu'une
  // requête Whisper est en vol (mountedRef devient false → finally skip le
  // setIsTranscribing(false), et au re-open l'état serait stale).
  useEffect(() => {
    if (!isOpen) forceResetTranscription()
  }, [isOpen, forceResetTranscription])

  // Dead-man's switch for streaming generation. The WS `state.isComplete`
  // path that clears `isGenerating`/`isStreaming` can be missed (server
  // restart, disconnect, lost frame) — and once stuck, the mic button stays
  // disabled (`disabled={isTranscribing || isGenerating}`) and Ctrl+G is
  // silently no-op'd by the `if (isGenerating || isStreamingRef.current)
  // return` guard. After 120 s of continuous streaming, force-reset and
  // surface a toast so the user knows what happened and isn't locked out
  // of dictation + AI compose for the rest of the session.
  useEffect(() => {
    if (!isGenerating && !isStreaming) return
    const guard = setTimeout(() => {
      // Diagnostic logging intentionally omitted — the toast below is the
      // user-visible signal, and the frontend log-statement budget enforced
      // by tests/test_speed_optimizations.py is at its ratchet ceiling.
      // Sentry captures the toast dispatch if we ever need post-hoc context.
      setIsGenerating(false)
      setIsStreaming(false)
      isStreamingRef.current = false
      setStreamStage(null)
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: {
          message: i18n.t('toasts.generation_failed', { ns: 'common', detail: 'timeout' }),
          type: 'error',
          duration: 6000,
        },
      }))
    }, 120_000)
    return () => clearTimeout(guard)
  }, [isGenerating, isStreaming])

  // Snippets
  const {
    snippets,
    sharedSnippets,
    loading: snippetsLoading,
    createSnippet,
    trackSnippetUsage,
  } = useSnippets(accountId)

  const { html: rawAccountSignatureHtml, text: rawAccountSignatureText } = useAccountSignature()
  // BUG-P3-002 : signature HTML depuis l'API backend — sanitiser avec DOMPurify avant rendu
  const accountSignatureHtml = useMemo(() => {
    if (!rawAccountSignatureHtml) return null;
    const clean = DOMPurify.sanitize(rawAccountSignatureHtml, { USE_PROFILES: { html: true } });
    return clean
      .replace(/border-top\s*:[^;"]*/gi, 'border-top:none')
      .replace(/padding-top\s*:\s*[^;"]*/gi, 'padding-top:0');
  }, [rawAccountSignatureHtml])

  // Éditeur de signature portée message — même UI que le ReplyComposer (chips
  // de bibliothèque + textarea + ✓/✕), mais le ✓ applique à CE message
  // seulement : pas de destinataire fiable ici pour un override par contact,
  // et l'édition durable reste dans Réglages.
  const [signatureEditorOpen, setSignatureEditorOpen] = useState(false)
  const [signatureDraft, setSignatureDraft] = useState('')
  const [pendingEntry, setPendingEntry] = useState<{ id: string; html: string; text: string } | null>(null)
  const [chosenSignature, setChosenSignature] = useState<{ id: string | null; html: string; text: string } | null>(null)
  const signatureLibrary = useSignatureLibrary(signatureEditorOpen)
  const displaySignatureHtml = chosenSignature?.html ?? accountSignatureHtml

  const signatureClickable = !signatureEditorOpen && Boolean(displaySignatureHtml)
  const activeSignatureId = pendingEntry?.id ?? chosenSignature?.id ?? null

  const sanitizeSignatureHtml = useCallback((raw: string) => (
    DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } })
      .replace(/border-top\s*:[^;"]*/gi, 'border-top:none')
      .replace(/padding-top\s*:\s*[^;"]*/gi, 'padding-top:0')
  ), [])

  const openSignatureEditor = useCallback(() => {
    setSignatureDraft(chosenSignature?.text ?? rawAccountSignatureText ?? '')
    setPendingEntry(null)
    setSignatureEditorOpen(true)
  }, [chosenSignature, rawAccountSignatureText])

  const handleSignatureClick = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
    // Laisser vivre les liens contenus dans la signature et la sélection de texte.
    if ((event.target as HTMLElement).closest('a')) return
    if (window.getSelection()?.toString()) return
    openSignatureEditor()
  }, [openSignatureEditor])

  const handleSignatureKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      openSignatureEditor()
    }
  }, [openSignatureEditor])

  const applySignatureDraft = useCallback(() => {
    const draft = signatureDraft.trim()
    if (!draft) {
      // Vidé = retour à la signature par défaut du compte (évite un footer
      // disparu donc plus cliquable).
      setChosenSignature(null)
      sigHtmlRef.current = accountSignatureHtml || ''
      setSignatureEditorOpen(false)
      return
    }
    // Bascule pure (chip non retouché) : on garde le HTML de la bibliothèque
    // (liens, mise en forme). Texte édité : échappé puis \n → <br>.
    const clean = (pendingEntry && draft === (pendingEntry.text || '').trim())
      ? sanitizeSignatureHtml(pendingEntry.html || draft.replace(/\n/g, '<br>'))
      : draft.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>')
    setChosenSignature({ id: pendingEntry?.id ?? null, html: clean, text: draft })
    sigHtmlRef.current = clean
    setSignatureEditorOpen(false)
  }, [signatureDraft, pendingEntry, sanitizeSignatureHtml, accountSignatureHtml])

  // Initialize body when modal opens
  useEffect(() => {
    if (!isOpen) {
      bodyInitializedRef.current = false
      sigHtmlRef.current = ''
      setChosenSignature(null)
      setSignatureEditorOpen(false)
      setPendingEntry(null)
      setSignatureDraft('')
      return
    }

    if (!bodyInitializedRef.current) {
      bodyInitializedRef.current = true

      let initialBody = ''

      // Restore from saved draft if provided
      if (initialDraft) {
        setTo(initialDraft.to)
        setCc(initialDraft.cc)
        setBcc(initialDraft.bcc)
        setShowCc(!!initialDraft.cc)
        setShowBcc(!!initialDraft.bcc)
        setSubject(initialDraft.subject)
        initialBody = initialDraft.body.includes('\n--\n')
          ? initialDraft.body.slice(0, initialDraft.body.indexOf('\n--\n'))
          : initialDraft.body
        sessionIdRef.current = initialDraft.id
      } else {
        sessionIdRef.current = `compose_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
      }

      setBody(initialBody)

      setTimeout(() => {
        toInputRef.current?.focus()
      }, 100)
    }

    // BS2-003: cancel flag prevents a slow fetchAccounts from writing to
    // sigHtmlRef / setCurrentAccountId after the modal has been closed —
    // a stale resolve would otherwise leak a previous session's signature
    // into the next compose mount on fast open→close→open.
    let cancelled = false
    fetchAccounts().then(({ accounts, current_account_id }) => {
      if (cancelled) return
      const currentAccount = current_account_id
        ? accounts.find(a => a.id === current_account_id)
        : accounts[0]
      if (currentAccount) setCurrentAccountId(currentAccount.id)
      const html = currentAccount?.signature_html || currentAccount?.signature || ''
      if (html && !sigHtmlRef.current) sigHtmlRef.current = DOMPurify.sanitize(html, { USE_PROFILES: { html: true } })
    }).catch((err) => {
      // Audit 2026-06-11 F-09 : sans comptes résolus, l'email part sans
      // signature et sans compte explicite — prévenir au lieu de log-only.
      if (cancelled) return
      silentFailWithToast('compose-accounts', {
        message: i18nInstance.t('common:toasts.signature_unavailable'),
      })(err)
    })
    return () => { cancelled = true }
  }, [isOpen, initialDraft])

  // Keep sigHtmlRef in sync when the signature loads asynchronously.
  // This is separate from the init effect so the init effect doesn't re-fire
  // every time the signature changes (which caused a potential double-init race).
  useEffect(() => {
    if (accountSignatureHtml && !sigHtmlRef.current) {
      sigHtmlRef.current = accountSignatureHtml
    }
  }, [accountSignatureHtml])


  // (AI prompt is always visible, no toggle needed)

  // Handle keyboard shortcuts
  useEffect(() => {
    if (!isOpen) return

    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl+Shift+G → Rédiger AVEC expertise active (mode expert, Sonnet plan + Haiku draft)
      // Doit être testé AVANT le Ctrl+G plain, sinon le Shift est ignoré.
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'g') {
        e.preventDefault()
        e.stopPropagation()
        if (aiLocked) {
          showPaidAiBlocked()
          return
        }
        // Re-entrancy guard: ignore if a generation is already in flight
        // (audit Ctrl+G HIGH "no re-entrancy guard during generation").
        if (isGenerating || isStreamingRef.current) return
        const expandCmd = SLASH_COMMANDS.find(c => c.expand)
        if (expandCmd) handleAiSubmitRef.current(expandCmd.instruction, { useSpecialty: true })
        return
      }
      // Ctrl+G → Rédiger à partir de notes (standard, Haiku seul)
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'g') {
        e.preventDefault()
        e.stopPropagation()
        if (aiLocked) {
          showPaidAiBlocked()
          return
        }
        if (isGenerating || isStreamingRef.current) return
        const expandCmd = SLASH_COMMANDS.find(c => c.expand)
        if (expandCmd) handleAiSubmitRef.current(expandCmd.instruction)
      }

      // Ctrl+M → Ouvre la SurgicalEditBar inline pour modifier un détail
      // sans toucher au reste du brouillon. Conditions : body non vide,
      // pas de génération en cours.
      // Test e.code === 'KeyM' en plus de e.key pour couvrir les dispositions
      // clavier exotiques (AZERTY, Dvorak).
      // [DESKTOP-DISABLED 2026-05-06] Le `&& false` désactive le raccourci
      // sur desktop (la feature reste portée pour mobile). Pour ré-activer,
      // retirer le `&& false` ici ET flipper showModifierPreset dans
      // AICommandMenu.tsx (rechercher [DESKTOP-DISABLED 2026-05-06]).
      // eslint-disable-next-line no-constant-condition, no-constant-binary-expression
      if (false && (e.ctrlKey || e.metaKey) && !e.shiftKey && (e.key.toLowerCase() === 'm' || e.code === 'KeyM')) {
        e.preventDefault()
        e.stopPropagation()
        if (isGenerating || isStreamingRef.current) return
        const bodyText = body.replace(/<[^>]*>/g, '').trim()
        if (!bodyText) {
          setSpecialtyMessage({
            type: 'warning',
            text: t('err_no_content_to_edit'),
          })
          return
        }
        setSurgicalInstruction('')
        setSurgicalEditOpen(true)
        return
      }

      // Escape ferme comme le bouton X : si le brouillon contient déjà du
      // contenu, handleClose le sauvegarde localement avant de fermer. La
      // suppression volontaire reste portée par la corbeille.
      // MAIS : si un popover interne possède Échap (SchedulePicker, menu IA,
      // autocomplete, snippet, dispo, relance, badge expert, popover lien…),
      // on le laisse se fermer seul sans fermer tout le compose. Ce handler
      // écoute en capture sur window, donc il passe AVANT le listener du
      // popover — d'où la garde structurelle plutôt qu'un stopPropagation.
      // Voir utils/escapeOwner.ts. Un 2e Échap (popover fermé) ferme le compose.
      if (e.key === 'Escape') {
        if (hasEscapeOwner()) return
        e.preventDefault()
        handleClose()
      }
    }

    // Double-attache (window + document, capture). Si une extension navigateur
    // intercepte un des canaux (DeepL, Vimium, etc.), l'autre reste actif.
    // Garde anti-double-fire via e.defaultPrevented.
    const guarded = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return
      handleKeyDown(e)
    }
    window.addEventListener('keydown', handleKeyDown, true)
    document.addEventListener('keydown', guarded, true)
    return () => {
      window.removeEventListener('keydown', handleKeyDown, true)
      document.removeEventListener('keydown', guarded, true)
    }
  }, [isOpen, to, cc, bcc, subject, body, aiLocked, showPaidAiBlocked, t])

  const [isSentAnim, setIsSentAnim] = useState(false)
  const [followupDate, setFollowupDate] = useState<Date | null>(null)
  const [followupPickerPos, setFollowupPickerPos] = useState<{ x: number; y: number; buttonTop?: number; forceCalendar?: boolean } | null>(null)
  const followupOverrideRef = useRef(false)
  const followupBtnRef = useRef<HTMLButtonElement>(null)
  const { autoReminderOnCommitment } = useAutoReminderOnCommitment(accountId)

  const formatFollowupDate = (date: Date): string => {
    return formatLongDateFromDate(date, i18n.language)
  }

  // Auto-sync followupDate with a date detected in the body while typing
  useEffect(() => {
    if (!autoReminderOnCommitment) return
    if (followupOverrideRef.current) return
    const detected = detectDateFromBody(body)
    setFollowupDate(prev => {
      const nextTime = detected?.date.getTime() ?? null
      const prevTime = prev?.getTime() ?? null
      if (prevTime === nextTime) return prev
      return detected?.date ?? null
    })
  }, [autoReminderOnCommitment, body])

  const [attachmentReminder, setAttachmentReminder] = useState<AttachmentDetectionResult | null>(null)

  // ── Custom placeholder fill modal ────────────────────────────────────────
  const [pendingPlaceholders, setPendingPlaceholders] = useState<{
    variables: string[]
    values: Record<string, string>
    processedContent: string
    snippet: Snippet
    baseVariables: Record<string, string>
  } | null>(null)

  // ── Cross-field chip drag-and-drop ────────────────────────────────────────
  const [dragState, setDragState] = useState<{ email: string; sourceField: 'to' | 'cc' | 'bcc' } | null>(null)
  const [dragOverField, setDragOverField] = useState<'to' | 'cc' | 'bcc' | null>(null)

  // ── To: field wrap detection ──────────────────────────────────────────────
  // When the To: chip stack wraps to a second row, the inline Cc/Bcc toggles
  // get vertically centered against the wrapped stack and visually orphan in
  // the middle of the rows (see the screenshot reported on 2026-05-17). Watch
  // the autocomplete's height with a ResizeObserver and, when it grows past
  // a single chip row, promote the toggles to a dedicated row below the To:
  // field. Single-line To: still gets the compact inline layout.
  const toFieldRef = useRef<HTMLDivElement>(null)
  const [toFieldMultiline, setToFieldMultiline] = useState(false)
  useEffect(() => {
    const field = toFieldRef.current
    if (!field) return
    const autocomplete = field.querySelector('.contact-autocomplete') as HTMLElement | null
    if (!autocomplete) return
    // Single chip row is ~28-30px tall (chip body + flex padding); wrapping
    // pushes the autocomplete past ~40px. 36px is the conservative break.
    const update = () => setToFieldMultiline(autocomplete.offsetHeight > 36)
    update()
    const ro = new ResizeObserver(update)
    ro.observe(autocomplete)
    return () => ro.disconnect()
  }, [])

  const handleChipDragStart = (email: string, sourceField: string) => {
    setDragState({ email, sourceField: sourceField as 'to' | 'cc' | 'bcc' })
    setShowCc(true)
    setShowBcc(true)
  }

  const handleHideContact = useCallback((email: string) => {
    // Audit Cluster D (2026-05-11) toast site 4: log-only meant the contact
    // reappeared at the next refresh with no explanation. Now warn the user.
    hideContact(email).catch(silentFailWithToast('hide-contact', {
      message: t('common:toasts.contact_hide_failed'),
    }))
  }, [t])

  const handleChipDragEnd = () => {
    setDragState(null)
    setDragOverField(null)
    // Close Cc/Bcc if they were auto-opened and are still empty
    setShowCc(v => v && !cc.trim() ? false : v)
    setShowBcc(v => v && !bcc.trim() ? false : v)
  }

  const handleFieldDrop = (e: React.DragEvent, targetField: 'to' | 'cc' | 'bcc') => {
    e.preventDefault()
    if (!dragState || dragState.sourceField === targetField) {
      setDragOverField(null)
      return
    }
    const { email, sourceField } = dragState
    const removeEmail = (val: string) =>
      val.split(',').map(s => s.trim()).filter(s => s && s.toLowerCase() !== email.toLowerCase()).join(', ')
    const addEmail = (val: string) => {
      const existing = val.split(',').map(s => s.trim()).filter(Boolean)
      if (existing.some(e => e.toLowerCase() === email.toLowerCase())) return val
      return [...existing, email].join(', ')
    }
    if (sourceField === 'to')  setTo(prev => removeEmail(prev))
    if (sourceField === 'cc')  setCc(prev => removeEmail(prev))
    if (sourceField === 'bcc') setBcc(prev => removeEmail(prev))
    if (targetField === 'to')  setTo(prev => addEmail(prev))
    if (targetField === 'cc')  { setCc(prev => addEmail(prev)); setShowCc(true) }
    if (targetField === 'bcc') { setBcc(prev => addEmail(prev)); setShowBcc(true) }
    setDragState(null)
    setDragOverField(null)
  }

  /** Expand any @groupname chips to actual member emails */
  const resolveGroupChips = useCallback((fieldValue: string): string => {
    if (!contactGroups.length) return fieldValue
    const chips = fieldValue.split(',').map(s => s.trim()).filter(Boolean)
    const resolved = chips.flatMap(chip => {
      if (!chip.startsWith('@')) return [chip]
      const name = chip.slice(1).toLowerCase()
      const group = contactGroups.find(g => g.name.toLowerCase() === name || g.name.toLowerCase().replace(/\s+/g, '') === name)
      if (group && group.members.length > 0) return group.members.map(m => m.email)
      // Fallback: @ProjectName → expand all sub-groups for that project label
      const projectGroups = contactGroups.filter(g => g.label_name && g.label_name.toLowerCase() === name)
      if (projectGroups.length > 0) {
        const seen = new Set<string>()
        return projectGroups.flatMap(g => g.members).filter(m => {
          const key = m.email.toLowerCase()
          if (seen.has(key)) return false
          seen.add(key)
          return true
        }).map(m => m.email)
      }
      return [chip] // keep as-is if no match (will fail validation gracefully)
    })
    return resolved.join(', ')
  }, [contactGroups])

  const doSend = async (explicitFollowupDate?: Date | null) => {
    if (!to.trim()) return
    // F-10 guard: ref flip is synchronous, so a second invocation from
    // the same tick (held Ctrl+Enter, rapid double-click) returns here
    // before duplicating the send. setIsSending stays for the UI label.
    if (sendingRef.current) return
    sendingRef.current = true
    setIsSending(true)

    const files = attachments.map(a => a.file)
    const resolvedTo = resolveGroupChips(to.trim())
    const resolvedCc = cc.trim() ? resolveGroupChips(cc.trim()) : undefined
    const resolvedBcc = bcc.trim() ? resolveGroupChips(bcc.trim()) : undefined
    const sigHtml = sigHtmlRef.current || undefined

    const delay = getUndoSendDelay()
    // F-11: defense-in-depth against duplicate sendIds. Even if a second
    // doSend slips past the sendingRef guard (e.g. via a future code
    // path), keying on the stable per-modal `sessionIdRef` collapses
    // duplicate calls into one sendId — backend pendingSend dedupe + the
    // reminder createReminder are both keyed on the sendId, so a single
    // identifier prevents both double-sends AND double-reminders.
    const sendId = `sent:compose-${sessionIdRef.current}`

    // Pre-encode attachments to base64 BEFORE registering — fixes silent-failure
    // (audit Send-HIGH "attachment base64 conversion") and ensures the persisted
    // payload is fully serializable for boot rehydration.
    let serializedAttachments: { filename: string; data: string; content_type: string }[] | undefined
    if (files.length > 0) {
      const fileToBase64 = (file: File): Promise<string> => new Promise((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(((reader.result as string) || '').split(',')[1] || '')
        reader.onerror = () => reject(new Error(`Lecture du fichier "${file.name}" impossible`))
        reader.readAsDataURL(file)
      })
      try {
        serializedAttachments = await Promise.all(files.map(async (file) => ({
          filename: file.name,
          data: await fileToBase64(file),
          content_type: file.type || 'application/octet-stream',
        })))
      } catch (err) {
        const message = err instanceof Error ? err.message : t('err_attachment_unreadable')
        setIsSending(false)
        sendingRef.current = false  // F-10: release guard on early-return
        window.dispatchEvent(new CustomEvent('agentys:send-failed', {
          detail: {
            error: message,
            to: resolvedTo,
            subject: subject.trim() || '(sans objet)',
            validation: true,
          },
        }))
        return
      }
    }

    // Track AI usage for metrics (Send-HIGH "ai_assisted always false").
    const wasAiAssisted = composeId !== null

    // Register delayed send — payload is persisted to localStorage; the store
    // re-fires on boot if the window closed during the undo window
    // (audit Send-HIGH "Email lost if app/window closes during 15s undo-send").
    registerPendingSend(sendId, {
      to: resolvedTo,
      subject: subject.trim(),
      body: body.trim(),
      cc: resolvedCc,
      bcc: resolvedBcc,
      attachments: serializedAttachments,
      aiAssisted: wasAiAssisted,
      skipSignature: true,
      signatureHtml: sigHtml,
      accountId: accountId != null ? String(accountId) : undefined,
    }, delay)

    // Schedule follow-up reminder if configured. Fire AFTER the undo-send
    // window so we don't create reminders for sends that the user cancels
    // or that fail before reaching the server.
    const effectiveFollowupDate = explicitFollowupDate !== undefined ? explicitFollowupDate : followupDate
    if (effectiveFollowupDate) {
      const reminderDate = effectiveFollowupDate.toISOString()
      const tryReminder = (attempt: number) => {
        apiClient.createReminder(sendId, subject.trim() || '(sans objet)', reminderDate)
          .catch((err) => {
            if (attempt < 3) {
              setTimeout(() => tryReminder(attempt + 1), attempt * 1500)
            } else {
              // BS2-002: loud-log + event so the final failure is visible in
              // DevTools/Sentry and any future toast layer can pick it up.
              console.warn('[NewMessageModal] createReminder failed after 3 retries:', err)
              window.dispatchEvent(new CustomEvent('reminder:create-failed', {
                detail: { sendId, reminderDate, error: String(err) },
              }))
            }
          })
      }
      setTimeout(() => tryReminder(1), Math.max(0, delay * 1000))
    }

    // Close modal with success animation. Cancel any pending debounced
    // autosave first, else it fires after this delete and resurrects the
    // just-sent email as a ghost draft.
    if (autosaveTimerRef.current) { clearTimeout(autosaveTimerRef.current); autosaveTimerRef.current = null }
    deleteSavedDraft(sessionIdRef.current)
    onDraftSaved?.()
    setIsSending(false)
    sendingRef.current = false  // F-10: release guard on success
    setIsSentAnim(true)
    setTimeout(() => {
      setIsSentAnim(false)
      resetForm()
      onClose()
    }, 2500)
  }

  const doScheduleSend = async (sendAtLocal: Date) => {
    const recipientRaw = to.trim()
    if (!recipientRaw) return
    const allHaveAtSign = recipientRaw
      .split(/[,;]/)
      .map((r) => r.trim())
      .filter(Boolean)
      .every((r) => r.includes('@'))
    if (!allHaveAtSign) {
      window.dispatchEvent(new CustomEvent('agentys:send-failed', {
        detail: {
          error: t('err_invalid_recipient'),
          to: recipientRaw,
          subject: subject.trim() || '(sans objet)',
          validation: true,
        },
      }))
      return
    }
    if (sendAtLocal.getTime() <= Date.now()) return

    // F-10 guard: same ref pattern as doSend so a held shortcut or
    // double-click on the "schedule send" affordance can't double-fire
    // the apiClient.scheduleEmail POST.
    if (sendingRef.current) return
    sendingRef.current = true
    setIsSending(true)

    try {
      const files = attachments.map(a => a.file)
      const resolvedTo = resolveGroupChips(to.trim())
      const resolvedCc = cc.trim() ? resolveGroupChips(cc.trim()) : ''
      const resolvedBcc = bcc.trim() ? resolveGroupChips(bcc.trim()) : ''
      const sigHtml = sigHtmlRef.current || ''

      let serializedAttachments: { filename: string; data: string; content_type: string }[] | undefined
      if (files.length > 0) {
        const fileToBase64 = (file: File): Promise<string> => new Promise((resolve, reject) => {
          const reader = new FileReader()
          reader.onload = () => resolve(((reader.result as string) || '').split(',')[1] || '')
          reader.onerror = () => reject(new Error(`Lecture du fichier "${file.name}" impossible`))
          reader.readAsDataURL(file)
        })
        serializedAttachments = await Promise.all(files.map(async (file) => ({
          filename: file.name,
          data: await fileToBase64(file),
          content_type: file.type || 'application/octet-stream',
        })))
      }

      // FIX UI-004 (audit P1): the body comes from DraftEditor (a rich-text
      // editor) so it almost always contains HTML markup. Hardcoding
      // is_html:false caused the backend to send Content-Type: text/plain
      // and recipients saw raw "<p><strong>...</strong></p>" markup instead
      // of formatted text. Detect dynamically with isHtmlContent.
      const trimmedBody = body.trim()
      await apiClient.scheduleEmail({
        to: resolvedTo,
        subject: subject.trim(),
        body: trimmedBody,
        cc: resolvedCc,
        bcc: resolvedBcc,
        send_at: sendAtLocal.toISOString(),
        is_html: isHtmlContent(trimmedBody),
        attachments: serializedAttachments,
        skip_signature: true,
        signature_html: sigHtml,
        ai_assisted: composeId !== null,
      })

      if (autosaveTimerRef.current) { clearTimeout(autosaveTimerRef.current); autosaveTimerRef.current = null }
      deleteSavedDraft(sessionIdRef.current)
      onDraftSaved?.()
      setIsSending(false)
      sendingRef.current = false  // F-10: release guard on schedule success
      setIsSentAnim(true)
      setTimeout(() => {
        setIsSentAnim(false)
        resetForm()
        onClose()
      }, 1800)
    } catch (err) {
      setIsSending(false)
      sendingRef.current = false  // F-10: release guard on schedule error
      const message = err instanceof Error ? err.message : "Erreur lors de la programmation de l'envoi"
      window.dispatchEvent(new CustomEvent('agentys:send-failed', {
        detail: {
          error: message,
          to: to.trim(),
          subject: subject.trim() || '(sans objet)',
          validation: false,
        },
      }))
    }
  }

  // Note: previously had a COMMITMENT_REGEX that intercepted Send to open the
  // schedule-a-reminder picker when the body contained a commitment phrase
  // without an explicit date, plus a detectDateFromBody auto-attach that
  // pre-set the follow-up date. Both interceptions were removed so Send always
  // sends — the bell icon (FollowupDatePicker) remains the single explicit,
  // opt-in entry point for scheduling a reminder. Mirrors ReplyComposer fix.

  const handleSend = async () => {
    // Silent-failure fix (issue #311) : validation minimale du destinataire —
    // avant, taper « notanemail » créait un chip et le bouton Envoyer partait
    // en 500 silencieux. On bloque côté client avant l'appel API.
    const recipientRaw = to.trim()
    if (!recipientRaw) return
    // Don't ship a half-streamed AI draft: while compose generation is in
    // flight the body is still filling in word-by-word. Block Send here (covers
    // the Ctrl+Enter path too); the button is also disabled while streaming.
    if (isStreaming || isGenerating) return
    // Split par virgule/point-virgule, chaque item doit contenir un @
    const allHaveAtSign = recipientRaw
      .split(/[,;]/)
      .map((r) => r.trim())
      .filter(Boolean)
      .every((r) => r.includes('@'))
    if (!allHaveAtSign) {
      window.dispatchEvent(new CustomEvent('agentys:send-failed', {
        detail: {
          error: t('err_invalid_recipient'),
          to: recipientRaw,
          subject: subject.trim() || '(sans objet)',
          validation: true,
        },
      }))
      return
    }

    // Audit 2026-05-20 BUG-Z003: empty-body guard. Mirrors the fix in ReplyComposer
    // — Ctrl+Enter shortcut shouldn't blast an empty message into the wild without
    // some signal. Strip HTML + zero-width whitespace before evaluating.
    const strippedBody = (body || '')
      .replace(/<br\s*\/?>/gi, ' ')
      .replace(/<[^>]*>/g, '')
      .replace(/ |\u200B/g, ' ')
      .trim()
    if (!strippedBody) {
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: {
          message: t('err_empty_body'),
          detail: t('err_empty_body_hint'),
          type: 'warning',
          duration: 4000,
        },
      }))
      return
    }

    // Check for forgotten attachment before sending
    const detection = detectForgottenAttachment(body.replace(/<[^>]*>/g, ' '), attachments.length > 0)
    if (detection.detected) {
      setAttachmentReminder(detection)
      return
    }

    // Send always sends. If a follow-up date was configured manually via the
    // bell icon, doSend will pick it up from state. We no longer auto-open the
    // schedule picker based on phrases in the body.
    doSend()
  }

  const resetForm = () => {
    setTo('')
    setCc('')
    setBcc('')
    setShowCc(false)
    setShowBcc(false)
    setSubject('')
    setBody('')
    setAttachments([])
    bodyInitializedRef.current = false
    sigHtmlRef.current = ''
    // A streaming generation that never received its WS completion event
    // (network blip, server restart, missed event) used to leave these
    // flags stuck `true`. The next compose open then disabled the mic
    // (`disabled={isTranscribing || isGenerating}`) and silently no-op'd
    // Ctrl+G via the `if (isGenerating || isStreamingRef.current) return`
    // guard. Reset them on every form reset so reopening the modal always
    // gives the user a usable surface.
    setIsGenerating(false)
    setIsStreaming(false)
    isStreamingRef.current = false
    setStreamStage(null)
  }

  const handleDiscard = () => {
    deleteSavedDraft(sessionIdRef.current)
    onDraftSaved?.()
    resetForm()
    onClose()
  }

  // Global keyboard shortcuts: Ctrl+Enter = send, Ctrl+Shift+, = discard draft
  const handleSendRef = useRef(handleSend);
  handleSendRef.current = handleSend;
  const handleDiscardRef = useRef(handleDiscard);
  handleDiscardRef.current = handleDiscard;
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Ctrl+Enter → send
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        handleSendRef.current();
        return;
      }
      // Ctrl+Shift+, → supprimer brouillon (détection robuste cross-layout, cf. utils/keyboard)
      if (isDeleteDraftShortcut(e)) {
        e.preventDefault();
        handleDiscardRef.current();
        return;
      }
    };
    window.addEventListener('keydown', handler, true);
    return () => window.removeEventListener('keydown', handler, true);
  }, []);

  // Silent-failure fix (issue #312) — autosave debounced chaque fois que
  // l'utilisateur tape. Couplé au auto-restore sur ouverture dans App.tsx,
  // ça rend le flow "je ferme puis je reviens plus tard" non-destructif.
  // 1s de debounce évite de hammer localStorage à chaque keystroke.
  useEffect(() => {
    if (!isOpen) return
    // Ne pas autosave tant que rien n'est tapé (évite d'écraser un brouillon
    // restauré avec un objet vide si l'effect fire juste après le mount).
    if (!hasContent({ to, subject, body })) return

    const timer = setTimeout(() => {
      try {
        saveComposeDraft({ id: sessionIdRef.current, to, cc, bcc, subject, body })
        onDraftSaved?.()
      } catch (err) {
        // Quota ou storage indisponible — draftStorage l'absorbe déjà,
        // mais si ça remonte jusqu'ici on évite un crash du composant.
        console.warn('[NewMessageModal] autosave failed', err)
      }
    }, 1000)
    autosaveTimerRef.current = timer

    return () => clearTimeout(timer)
  }, [isOpen, to, cc, bcc, subject, body, onDraftSaved])

  const doClose = () => {
    clearImageError()
    setIsClosing(true)
    setTimeout(() => {
      setIsClosing(false)
      resetForm()
      onClose()
    }, 150)
  }

  const handleClose = () => {
    if (hasContent({ to, subject, body })) {
      saveComposeDraft({ id: sessionIdRef.current, to, cc, bcc, subject, body })
      onDraftSaved?.()
      // Audit Cluster D (2026-05-11) toast site 3: previously fully silent.
      // The local saveComposeDraft above keeps the user's content; the
      // backend draft is a secondary sync. Log so failures show up in
      // DevTools / Sentry, but no user-facing toast (the local save is
      // the user-visible artifact).
      apiClient.saveNewDraft(to, subject, body, cc, bcc, sigHtmlRef.current || undefined)
        .catch(silentFailLog('save-new-draft-on-close'))
    }
    doClose()
  }

  const handleAttachClick = () => {
    fileInputRef.current?.click()
  }

  const addFiles = useCallback((files: File[] | FileList) => {
    const newAttachments: Attachment[] = Array.from(files).map(file => ({
      name: file.name,
      size: file.size,
      file
    }))
    setAttachments(prev => [...prev, ...newAttachments])
  }, [])

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files) addFiles(files)
    e.target.value = ''
  }

  const { isDragging: isFileDragging, dropZoneProps: fileDropZoneProps } = useFileDrop({
    onDrop: addFiles,
  })

  const removeAttachment = (index: number) => {
    setAttachments(prev => prev.filter((_, i) => i !== index))
  }

  const handleAiSubmit = async (
    promptOverride?: string,
    opts?: { useSpecialty?: boolean; surgical?: boolean }
  ) => {
    if (aiLocked) {
      showPaidAiBlocked()
      return
    }
    const activePrompt = promptOverride ?? ''
    // ↑ with empty prompt + body text → /expand by default
    const resolvedPrompt = activePrompt.trim() === '' && bodyPlainText.length > 0
      ? (SLASH_COMMANDS.find(c => c.expand)?.instruction ?? '')
      : activePrompt
    if (!resolvedPrompt.trim()) return
    const activePromptFinal = resolvedPrompt
    const useSpecialty = !!opts?.useSpecialty
    const surgical = !!opts?.surgical

    setIsGenerating(true)
    setIsLongWait(false)
    // Clear any prior specialty feedback; the current response will repopulate it.
    setSpecialtyInfo(null)
    setSpecialtyMessage(null)

    // Save original body for safety — never lose user text
    const savedBody = body

    // Timeouts were 30s/35s. Bumped to 90s/120s after audit 2026-05-19 found
    // production cold-start Ctrl+G round-trips at ~50–55s — the old 30s
    // timeout fired silently while the backend was still generating, the
    // body got replaced ~20s later, and users assumed the feature was broken.
    // Expert mode (Sonnet plan + Haiku draft = two sequential LLM calls)
    // gets the larger budget.
    const timeoutMs = useSpecialty ? 120_000 : 90_000
    const withTimeout = <T,>(promise: Promise<T>, ms = timeoutMs): Promise<T> => {
      const timeout = new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error(t('err_server_timeout', { seconds: Math.round(ms / 1000) }))), ms)
      )
      return Promise.race([promise, timeout])
    }
    // After 15s with no result, swap the "Réflexion..." indicator label to
    // a longer-form reassurance ("Toujours en cours…") so the user knows the
    // request is still in flight instead of assuming a silent failure. Cleared
    // in the finally{} block by setIsLongWait(false) below.
    const longWaitTimer = setTimeout(() => setIsLongWait(true), 15_000)

    try {
      // Extract plain text from HTML body for AI operations
      const bodyText = body.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()

      // Slash commands (/expand) opèrent sur du texte existant. Sans body, le
      // compose path les exécute comme une instruction et le LLM répond par
      // un meta-message
      // demandant le contenu source. On bail tôt avec un hint.
      const isRefineCommand = SLASH_COMMANDS.some(c => c.instruction === activePromptFinal.trim())
      if (!bodyText && isRefineCommand) {
        setSpecialtyMessage({
          type: 'warning',
          text: t('err_write_text_first'),
        })
        setIsGenerating(false)
        return
      }

      // Destinataire requis seulement en mode compose (body vide).
      // Surface via the inline specialty-message rail instead of a blocking
      // alert() (audit Ctrl+G MEDIUM "empty body alert after isGenerating").
      if (!bodyText && !to.trim()) {
        setSpecialtyMessage({
          type: 'warning',
          text: t('err_recipient_required'),
        })
        setIsGenerating(false)
        return
      }

      if (bodyText) {
        // REFINE mode — blocking /refine-text endpoint (no streaming needed, fast)
        // Pass `to` so the backend can load the recipient's ContactStyleProfile
        // and adapt tone/greeting/nickname when expanding notes into an email.
        // useSpecialty=true (Ctrl+Shift+G) triggers the two-call Sonnet plan
        // → Haiku draft flow and adds a mandatory "---\nSources : …" footnote.
        const _firstTo = (to.split(',')[0] || '').trim().toLowerCase()
        const _recipientName = _firstTo ? recipientNamesByEmail[_firstTo] : undefined
        const targetLanguage =
          threadLanguageHint === 'fr' || threadLanguageHint === 'en'
            ? threadLanguageHint
            : undefined
        const refineRes = await withTimeout(
          apiClient.refineText(
            bodyText,
            activePromptFinal.trim(),
            undefined,
            to.trim() || undefined,
            {
              useSpecialty,
              subject: subject.trim() || undefined,
              surgical,
              senderName: _recipientName,
              targetLanguage: surgical ? undefined : targetLanguage,
            }
          )
        )
        if (!refineRes.success || !refineRes.refined_text?.trim()) {
          console.warn('Refine returned empty — keeping original body')
          // Tell the user the request completed but produced nothing, instead of
          // the thinking indicator silently disappearing (looked like a broken AI).
          window.dispatchEvent(new CustomEvent('agentys:toast', {
            detail: { message: t('generation_no_changes'), type: 'warning', duration: 6000 },
          }))
          return
        }
        // Surface specialty_info: full match → badge state, warning-only →
        // inline message. Never downgrade silently — the user always sees
        // either the expertise badge or an explicit fallback notice.
        if (refineRes.specialty_info) {
          const info = refineRes.specialty_info
          if (isSpecialtyMatch(info)) {
            setSpecialtyInfo(info)
            if (info.warning === 'plan_empty_fallback' || info.warning === 'plan_failed_fallback') {
              setSpecialtyMessage({
                type: 'warning',
                text: t('err_specialty_degraded'),
              })
            }
          } else if (info.warning === 'no_active_specialty') {
            setSpecialtyMessage({
              type: 'warning',
              text: t('err_no_active_specialty'),
            })
          } else if (info.warning === 'specialty_unavailable') {
            setSpecialtyMessage({
              type: 'error',
              text: t('err_specialty_unavailable'),
            })
          } else if (info.warning === 'classification_error') {
            setSpecialtyMessage({
              type: 'error',
              text: t('err_classification_error'),
            })
          }
        }
        const generatedText = refineRes.refined_text.trim()

        // Show word-diff overlay on changes
        const parts = computeWordDiff(bodyText, generatedText)
        if (countChanges(parts) > 0) {
          if (diffTimerRef.current) clearTimeout(diffTimerRef.current)
          setDiffOverlay(parts)
          diffTimerRef.current = setTimeout(() => dismissDiff(), 2500)
        }

        setBody(preserveInlineImages(savedBody, generatedText))

        // Onboarding V2 — notify the tour overlay that refine (Ctrl+G) succeeded
        window.dispatchEvent(new CustomEvent('onboarding-v2:refine-success'))

        // Feature A — auto-fill subject if empty after notes → email generation
        // BS2-001: use functional setter so we don't clobber a subject the
        // user typed during the in-flight LLM round-trip (1-3s).
        // Treat "subject == project prefix only" as empty so Ctrl+G still
        // suggests a subject when the user picked a project tag but typed
        // nothing past it.
        const prefix = appliedPrefixRef.current
        const subjectIsPrefixOnly = (s: string) =>
          !s.trim() || (!!prefix && s.trim() === prefix.trim())
        if (subjectIsPrefixOnly(subject) && generatedText.trim()) {
          apiClient.suggestSubject(generatedText, to.trim() || undefined).then((res) => {
            if (res.success && res.subject?.trim()) {
              const suggested = res.subject.trim()
              setSubject(prev => (subjectIsPrefixOnly(prev) ? prefix + suggested : prev))
            }
          }).catch(silentFailLog('suggest-subject-refine'))
        }
        return
      }

      // COMPOSE mode — streaming via WebSocket
      const newComposeId = `compose-${Date.now()}`
      setComposeId(newComposeId)
      const composeId = newComposeId
      isStreamingRef.current = true
      setIsStreaming(true)
      clearDraftStreamState(composeId)

      // Subscribe to stream BEFORE API call
      const unsub = subscribeDraftStream((state) => {
        if (state.emailId !== composeId) return

        if (state.stageLabel) setStreamStage(state.stageLabel)

        if (state.accumulatedText) {
          setBody(state.accumulatedText)
        }

        if (state.isComplete) {
          unsub()
          setStreamStage(null)
          setIsStreaming(false)
          isStreamingRef.current = false
          setIsGenerating(false)

          // Feature A — auto-fill subject if empty
          // BS2-001: functional setter — don't overwrite if the user typed
          // a subject while the suggest-subject round-trip was in flight.
          // Treat "subject == project prefix only" as empty.
          const completedText = state.accumulatedText || ''
          const prefix = appliedPrefixRef.current
          const subjectIsPrefixOnly = (s: string) =>
            !s.trim() || (!!prefix && s.trim() === prefix.trim())
          if (subjectIsPrefixOnly(subject) && completedText.trim()) {
            apiClient.suggestSubject(completedText, to.trim() || undefined).then((res) => {
              if (res.success && res.subject?.trim()) {
                const raw = res.subject.trim()
                setSubject(prev => (subjectIsPrefixOnly(prev) ? prefix + raw : prev))
              }
            }).catch(silentFailLog('suggest-subject-compose'))
          }
        }
      })

      // Kick off generation (returns 202)
      const composeRes = await withTimeout(apiClient.composeEmail(
        to.trim(),
        // QA 2026-05-19 — Bug #4: don't persist 'Sans objet' as the
        // actual subject; send empty and let t('no_subject') render the
        // localized placeholder consistently in the inbox/sent lists.
        subject.trim(),
        activePromptFinal.trim(),
        true,
        undefined,
        composeId,
      ))

      if (!composeRes.success) {
        unsub()
        isStreamingRef.current = false
        setIsStreaming(false)
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const errorMsg = (composeRes as any)?.error || 'Error generating message'
        // Audit Cluster D (2026-05-11) toast site 2 / U-07: alert() blocks the
        // UI and is stylistically inconsistent with the rest of the app.
        // Surface via the toast layer instead.
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: {
            message: t('common:toasts.generation_failed', { detail: errorMsg }),
            type: 'error',
            duration: 8000,
          },
        }))
        setIsGenerating(false)
        return
      }
      // Streaming in progress — isGenerating stays true until stream completes
      return

    } catch (error: unknown) {
      console.error('AI generation error:', error)
      setBody(savedBody)
      setStreamStage(null)
      setIsStreaming(false)
      isStreamingRef.current = false
      const err = error as Record<string, unknown>
      const errorMessage = (err?.message as string) || (err?.error as string) || 'Connection error'
      // Expert-mode rate limit (3/60s) → inline message that points the user
      // to the non-blocking fallback (Ctrl+G standard). Avoids an alert()
      // for a condition the user will hit occasionally.
      if (useSpecialty && /rate limit/i.test(errorMessage)) {
        const retryHint = err?.retry_after as number | undefined
        setSpecialtyMessage({
          type: 'warning',
          text: retryHint
            ? t('common:toasts.expert_mode_rate_limited_retry', { seconds: retryHint })
            : t('common:toasts.expert_mode_rate_limited'),
        })
      } else {
        // Audit Cluster D (2026-05-11) toast site 2: alert() → toast error.
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: {
            message: t('common:toasts.generation_failed', { detail: errorMessage }),
            type: 'error',
            duration: 8000,
          },
        }))
      }
    } finally {
      clearTimeout(longWaitTimer)
      setIsLongWait(false)
      // Only reset generating if we're NOT in streaming mode
      if (!isStreamingRef.current) {
        setIsGenerating(false)
      }
    }
  }

  // ── AICommandMenu handlers ─────────────────────────────────────────────────
  // Use a ref to always call the latest handleAiSubmit (avoids stale closures)
  const handleAiSubmitRef = useRef(handleAiSubmit)
  useEffect(() => { handleAiSubmitRef.current = handleAiSubmit })

  const handleMagicGenerate = useCallback(() => {
    if (isGenerating || isStreamingRef.current) return
    const expandCmd = SLASH_COMMANDS.find(c => c.expand)
    if (expandCmd) handleAiSubmitRef.current(expandCmd.instruction)
  }, [isGenerating])

  const handleCommandFromMenu = useCallback((cmd: typeof SLASH_COMMANDS[number]) => {
    handleAiSubmitRef.current(cmd.instruction)
  }, [])

  const handleCustomPromptFromMenu = useCallback((prompt: string) => {
    // Le mode surgical n'est plus géré dans la popup — il a sa propre
    // SurgicalEditBar inline. La popup reste pour les commandes compose.
    handleAiSubmitRef.current(prompt)
  }, [])

  // Bullet list handler — track cursor via ref so click doesn't lose position
  const handleInsertBulletList = () => {
    editorRef.current?.toggleBulletList()
  }

  // ── Snippet insert helper ──────────────────────────────────────────────────
  const insertSnippetContent = useCallback((content: string) => {
    // Snippets are stored as RichTextEditor HTML; insert it as-is so we don't
    // double-wrap block structure in <p> (which TipTap re-parses into extra
    // empty paragraphs → doubled line spacing). Plain-text legacy snippets are
    // still converted. See snippetContentToInsertionHtml.
    const snippetHtml = snippetContentToInsertionHtml(content)
    setBody((prev) => snippetHtml + (prev || ''))
  }, [])

  const handlePlaceholderConfirm = useCallback(() => {
    if (!pendingPlaceholders) return
    const { processedContent, values, snippet, baseVariables } = pendingPlaceholders
    // Replace custom placeholders with user-provided values
    let finalContent = processedContent
    for (const [name, value] of Object.entries(values)) {
      finalContent = finalContent.replace(new RegExp(`\\{${name}\\}`, 'g'), value || `{${name}}`)
    }
    insertSnippetContent(finalContent)

    // Apply snippet's subject/recipients if present and fields are empty
    if (snippet.subject && !subject) {
      let finalSubject = replaceSnippetVariables(snippet.subject, baseVariables)
      for (const [name, value] of Object.entries(values)) {
        finalSubject = finalSubject.replace(new RegExp(`\\{${name}\\}`, 'g'), value || `{${name}}`)
      }
      setSubject(finalSubject)
    }

    setPendingPlaceholders(null)
  }, [pendingPlaceholders, insertSnippetContent, subject])

  const handlePlaceholderCancel = useCallback(() => {
    setPendingPlaceholders(null)
  }, [])

  // Snippet handlers
  const handleSnippetSelect = (snippet: Snippet) => {
    // Extract name parts from the FIRST recipient's bare email
    // (e.g. "alexandre.simon@..." → "Alexandre", "Simon"). Parse out a
    // single recipient and any "Name <email>" wrapper first, so a multi-recipient
    // field ("a@x.com, b@y.com") or a chip ("Bob Smith <bob@x.com>") doesn't
    // garble the derived name.
    const firstRecipient = (to.split(',')[0] || '').trim()
    const angleMatch = firstRecipient.match(/^.+?\s*<(.+?)>$/)
    const bareEmail = angleMatch ? angleMatch[1] : firstRecipient
    const emailPrefix = bareEmail.split('@')[0] || ''
    const nameParts = emailPrefix.split(/[._-]/).filter(Boolean)
    const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).toLowerCase()
    const firstName = nameParts.length > 0 ? capitalize(nameParts[0]) : ''
    const lastName = nameParts.length > 1 ? capitalize(nameParts[nameParts.length - 1]) : ''
    const fullName = nameParts.map(capitalize).join(' ')

    const variables: Record<string, string> = {
      first_name: firstName,
      last_name: lastName,
      full_name: fullName,
      sender_first_name: 'You',
      sender_last_name: '',
      sender_full_name: 'You',
      date: formatDayMonthYear(new Date(), i18n.language, 'long'),
      time: new Date().toLocaleTimeString(i18n.language, { hour: '2-digit', minute: '2-digit' }),
    }

    // Replace variables in content
    const processedContent = replaceSnippetVariables(snippet.content, variables)

    // Check for unreplaced custom placeholders
    const unreplaced = findUnreplacedVariables(processedContent)
    if (unreplaced.length > 0) {
      // Show modal so the user can fill in custom placeholders before insertion
      const initialValues: Record<string, string> = {}
      for (const v of unreplaced) {
        const name = v.replace(/^\{|\}$/g, '')
        initialValues[name] = ''
      }
      setPendingPlaceholders({
        variables: unreplaced,
        values: initialValues,
        processedContent,
        snippet,
        baseVariables: variables,
      })
      return // Wait for the user to fill in placeholders
    }

    insertSnippetContent(processedContent)

    // Apply snippet's subject/recipients if present and fields are empty
    if (snippet.subject && !subject) {
      setSubject(replaceSnippetVariables(snippet.subject, variables))
    }
    if (snippet.to?.length && !to) {
      setTo(snippet.to.join(', '))
    }
    if (snippet.cc?.length && !cc) {
      setCc(snippet.cc.join(', '))
      setShowCc(true)
    }
    if (snippet.bcc?.length && !bcc) {
      setBcc(snippet.bcc.join(', '))
      setShowBcc(true)
    }

    // Record usage
    trackSnippetUsage(snippet)
    setShowSnippetSelector(false)
  }

  const handleCreateSnippet = async (payload: CreateSnippetPayload) => {
    await createSnippet(payload)
  }

  if (!isOpen) return null

  const modKey = navigator.platform?.includes('Mac') ? '⌘' : 'Ctrl'

  return createPortal(
    <div className={`new-message-overlay fullscreen${isClosing ? ' closing' : ''}`} role="dialog" aria-modal="true" aria-label={subject.trim() || t('new_message')} ref={focusTrapRef} {...fileDropZoneProps}>
      <FileDropOverlay visible={isFileDragging} />
<div className={`new-message-modal gmail-style${isMaximized ? ' maximized' : ''}${isSentAnim ? ' nm-sent' : ''}${isFileDragging ? ' nm-file-dragging' : ''}`} data-testid="new-message-modal">
        {/* Success dispatch animation */}
        {isSentAnim && (
          <div className="nm-sent-overlay">
            <div className="nm-sent-stage">
              <div className="rc-ring-pulse" />
              <div className="rc-sparks">
                <span className="rc-spark" />
                <span className="rc-spark" />
                <span className="rc-spark" />
                <span className="rc-spark" />
                <span className="rc-spark" />
                <span className="rc-spark" />
              </div>
              <div className="rc-success-circle">
                <svg aria-hidden="true" className="rc-check-svg" viewBox="0 0 24 24">
                  <path className="rc-check-path" d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <span className="rc-sent-label">{t('sent_label')}</span>
            </div>
          </div>
        )}
        {/* Header */}
        <div className="gmail-header">
          <span
            className="gmail-title"
            role="heading"
            aria-level={2}
            title={subject.trim() || undefined}
          >
            {subject.trim() || t('new_message')}
          </span>
          <div className="gmail-header-actions">
            {/* Agrandir/réduire — branche les règles CSS .maximized (jusqu'ici
                orphelines). Simple toggle visuel : aucun handler Échap ici,
                le contrat escape-owner du modal est inchangé. */}
            <button
              className="gmail-header-btn"
              onClick={() => setIsMaximized(v => !v)}
              title={isMaximized ? t('restore_size', 'Réduire') : t('maximize', 'Agrandir')}
              aria-label={isMaximized ? t('restore_size', 'Réduire') : t('maximize', 'Agrandir')}
              aria-pressed={isMaximized}
              data-testid="nm-maximize"
            >
              {isMaximized ? (
                <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="4 14 10 14 10 20"/>
                  <polyline points="20 10 14 10 14 4"/>
                  <line x1="14" y1="10" x2="21" y2="3"/>
                  <line x1="3" y1="21" x2="10" y2="14"/>
                </svg>
              ) : (
                <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="15 3 21 3 21 9"/>
                  <polyline points="9 21 3 21 3 15"/>
                  <line x1="21" y1="3" x2="14" y2="10"/>
                  <line x1="3" y1="21" x2="10" y2="14"/>
                </svg>
              )}
            </button>
            <button className="gmail-header-btn" onClick={handleClose} title={t('close')} aria-label={t('close')}>
              <CloseIcon />
            </button>
          </div>
        </div>

        {/* To field */}
        {/* BUG-T003 (2026-05-16): the To row used to render as a bare input
            indistinguishable from the global search bar (`/`). Add a sticky
            label so the user can tell at a glance they're in compose, not
            search. The placeholder is dropped so it doesn't duplicate the
            label. */}
        <div
          ref={toFieldRef}
          className={`gmail-field gmail-field-to${dragOverField === 'to' ? ' drop-active' : ''}${toFieldMultiline ? ' to-field-multiline' : ''}`}
          onFocus={(e) => {
            if ((e.target as HTMLElement).tagName === 'INPUT') setLastFocusedField('to')
          }}
          onDragOver={dragState ? (e) => { e.preventDefault(); setDragOverField('to') } : undefined}
          onDragLeave={dragState ? () => setDragOverField(null) : undefined}
          onDrop={dragState ? (e) => handleFieldDrop(e, 'to') : undefined}
        >
          {/* Ponctuation localisée : « À : » garde l'espace typographique
              français, "To:"/"Para:" n'en prennent pas. */}
          <span className="gmail-field-label" aria-hidden="true">{t('to_field_label')}</span>
          <ContactAutocomplete
            value={to}
            onChange={setTo}
            accountId={currentAccountId}
            contactGroups={contactGroups}
            placeholder=""
            className="inline"
            inputRef={toInputRef}
            fieldId="to"
            multi
            onChipDragStart={handleChipDragStart}
            onChipDragEnd={handleChipDragEnd}
            isDragActive={!!dragState}
            onHideContact={handleHideContact}
            onContactSelect={(c) => {
              if (c.name && c.name !== c.email) {
                setRecipientNamesByEmail((prev) => ({ ...prev, [c.email.toLowerCase()]: c.name }))
              }
            }}
          />
          {/* Inline Cc/Bcc toggles — only when To: fits on a single line.
              When To: wraps, the toggles render in their own row below
              (see `.gmail-cc-bcc--row` below) so they don't visually
              orphan in the middle of the wrapped chip stack. */}
          {!toFieldMultiline && (!showCc || !showBcc || isStreaming) && (
            <div className="gmail-cc-bcc">
              {!showCc && (
                <button
                  type="button"
                  className="gmail-cc-link"
                  onClick={() => {
                    setShowCc(true)
                    setLastFocusedField('cc')
                    setTimeout(() => ccInputRef.current?.focus(), 50)
                  }}
                >
                  {t('cc_toggle')}
                </button>
              )}
              {!showBcc && (
                <button
                  type="button"
                  className="gmail-cc-link"
                  onClick={() => {
                    setShowBcc(true)
                    setLastFocusedField('bcc')
                    setTimeout(() => bccInputRef.current?.focus(), 50)
                  }}
                >
                  {t('bcc_toggle')}
                </button>
              )}
              {isStreaming && (
                <AIProcessButton
                  active={showPipeline}
                  disabled={isSending}
                  onClick={() => setShowPipeline((v) => !v)}
                />
              )}
            </div>
          )}
        </div>

        {/* Cc/Bcc toggle row — only when To: wraps to multiple lines. Keeps
            the toggles right-aligned beneath the wrapped chip stack instead
            of vertically centering them against the stack (which orphaned
            them in the middle of rows pre-fix). */}
        {toFieldMultiline && (!showCc || !showBcc || isStreaming) && (
          <div className="gmail-cc-bcc gmail-cc-bcc--row">
            {!showCc && (
              <button
                type="button"
                className="gmail-cc-link"
                onClick={() => {
                  // P3-22 (2026-05-17): close any open contact suggestion popover
                  // before showing Cc — without this, the To-field dropdown stays
                  // open over the (now shifted-down) Subject row for ~150 ms.
                  window.dispatchEvent(new Event('agentys:close-contact-suggestions'))
                  setShowCc(true)
                  setLastFocusedField('cc')
                  setTimeout(() => ccInputRef.current?.focus(), 50)
                }}
              >
                {t('cc_toggle')}
              </button>
            )}
            {!showBcc && (
              <button
                type="button"
                className="gmail-cc-link"
                onClick={() => {
                  // P3-22: same as above for Bcc.
                  window.dispatchEvent(new Event('agentys:close-contact-suggestions'))
                  setShowBcc(true)
                  setLastFocusedField('bcc')
                  setTimeout(() => bccInputRef.current?.focus(), 50)
                }}
              >
                {t('bcc_toggle')}
              </button>
            )}
            {isStreaming && (
              <AIProcessButton
                active={showPipeline}
                disabled={isSending}
                onClick={() => setShowPipeline((v) => !v)}
              />
            )}
          </div>
        )}

        {/* Cc field */}
        {showCc && (
          <div
            className={`gmail-field${dragOverField === 'cc' ? ' drop-active' : ''}`}
            onFocus={(e) => {
              if ((e.target as HTMLElement).tagName === 'INPUT') setLastFocusedField('cc')
            }}
            onDragOver={dragState ? (e) => { e.preventDefault(); setDragOverField('cc') } : undefined}
            onDragLeave={dragState ? () => setDragOverField(null) : undefined}
            onDrop={dragState ? (e) => handleFieldDrop(e, 'cc') : undefined}
          >
            <span className="gmail-field-label" aria-hidden="true">{t('cc_label')} :</span>
            <ContactAutocomplete
              value={cc}
              onChange={setCc}
              accountId={currentAccountId}
              contactGroups={contactGroups}
              placeholder={t('cc_label')}
              className="inline"
              inputRef={ccInputRef}
              fieldId="cc"
              multi
              onChipDragStart={handleChipDragStart}
              onChipDragEnd={handleChipDragEnd}
              isDragActive={!!dragState}
              onHideContact={handleHideContact}
            />
          </div>
        )}

        {/* Bcc field */}
        {showBcc && (
          <div
            className={`gmail-field${dragOverField === 'bcc' ? ' drop-active' : ''}`}
            onFocus={(e) => {
              if ((e.target as HTMLElement).tagName === 'INPUT') setLastFocusedField('bcc')
            }}
            onDragOver={dragState ? (e) => { e.preventDefault(); setDragOverField('bcc') } : undefined}
            onDragLeave={dragState ? () => setDragOverField(null) : undefined}
            onDrop={dragState ? (e) => handleFieldDrop(e, 'bcc') : undefined}
          >
            <span className="gmail-field-label" aria-hidden="true">{t('bcc_label')} :</span>
            <ContactAutocomplete
              value={bcc}
              onChange={setBcc}
              accountId={currentAccountId}
              contactGroups={contactGroups}
              placeholder={t('bcc_label')}
              className="inline"
              inputRef={bccInputRef}
              fieldId="bcc"
              multi
              onChipDragStart={handleChipDragStart}
              onChipDragEnd={handleChipDragEnd}
              isDragActive={!!dragState}
              onHideContact={handleHideContact}
            />
          </div>
        )}

        {/* Group suggestions — lives in the recipient zone (below the last
            visible recipient row, above the subject) so it visually anchors
            to "people", not "content". Chip body routes to the last-focused
            recipient row; chevron opens a To/Cc/Bcc override menu. */}
        {pendingSuggestedGroups.length > 0 && (
          <div className="nm-group-suggestions" ref={groupChipsRef}>
            {pendingSuggestedGroups.map(g => {
              const fieldLabel = lastFocusedField === 'to' ? t('to')
                : lastFocusedField === 'cc' ? t('cc_label')
                : t('bcc_label')
              const memberList = g.members.map(m => m.name || m.email).join(', ')
              return (
                <div className="nm-group-chip" key={g.id}>
                  <button
                    type="button"
                    className="nm-group-chip-body"
                    onClick={() => addGroupToField(g, lastFocusedField)}
                    title={`${t('group_chip_add_to')} ${fieldLabel} — ${memberList}`}
                  >
                    <span className="nm-group-chip-emoji">{g.emoji || '👥'}</span>
                    <span className="nm-group-chip-name">{g.name}</span>
                    <span className="nm-group-chip-count">{g.members.length}</span>
                  </button>
                  <button
                    type="button"
                    className="nm-group-chip-trigger"
                    onClick={() => setOpenGroupMenuId(prev => prev === g.id ? null : g.id)}
                    title={t('group_chip_choose_field')}
                    aria-label={t('group_chip_choose_field')}
                    aria-haspopup="menu"
                    aria-expanded={openGroupMenuId === g.id}
                  >
                    <ChevronDownIcon size={12} />
                  </button>
                  {openGroupMenuId === g.id && (
                    <div className="nm-group-chip-menu" role="menu">
                      <button
                        type="button"
                        role="menuitem"
                        className="nm-group-chip-menu-item"
                        onClick={() => addGroupToField(g, 'to')}
                      >
                        {t('to')}
                      </button>
                      <button
                        type="button"
                        role="menuitem"
                        className="nm-group-chip-menu-item"
                        onClick={() => addGroupToField(g, 'cc')}
                      >
                        {t('cc_label')}
                      </button>
                      <button
                        type="button"
                        role="menuitem"
                        className="nm-group-chip-menu-item"
                        onClick={() => addGroupToField(g, 'bcc')}
                      >
                        {t('bcc_label')}
                      </button>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {/* Subject field */}
        <div className="gmail-field">
          <input
            type="text"
            value={subject}
            onChange={(e) => {
              const v = e.target.value;
              // Auto-capitalize first letter of subject
              if (v && v[0] !== v[0].toUpperCase()) {
                setSubject(v[0].toUpperCase() + v.slice(1));
              } else {
                setSubject(v);
              }
            }}
            placeholder={t('subject_placeholder_upper')}
            className="gmail-input gmail-input-subject"
            spellCheck={false}
            aria-label={t('subject_aria')}
          />
          {projectsWithPrefix.length > 0 && (
            <div className="nm-project-picker" ref={projectPickerRef}>
              <button
                type="button"
                className={`nm-project-btn${appliedPrefix ? ' nm-project-btn--active' : ''}`}
                onClick={() => setProjectPickerOpen(o => !o)}
                title={appliedPrefix
                  ? (projectsWithPrefix.find(l => l.subject_prefix === appliedPrefix)?.name ?? appliedPrefix)
                  : t('pick_project')}
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/>
                  <circle cx="7" cy="7" r="1" fill="currentColor" stroke="none"/>
                </svg>
              </button>
              {projectPickerOpen && (
                <div className="nm-project-dropdown">
                  {appliedPrefix && (
                    <button type="button" className="nm-project-option nm-project-option--clear" onClick={clearProjectPrefix}>
                      {t('no_project')}
                    </button>
                  )}
                  {projectsWithPrefix.map(l => (
                    <button
                      key={l.name}
                      type="button"
                      className={`nm-project-option${l.subject_prefix === appliedPrefix ? ' nm-project-option--selected' : ''}`}
                      onClick={() => applyProjectPrefix(l.subject_prefix!)}
                      title={l.subject_prefix}
                    >
                      <span className="nm-project-option-dot" style={{ background: l.color }} aria-hidden="true" />
                      <span className="nm-project-option-name">{l.name}</span>
                      {l.is_favorite && (
                        <svg
                          aria-hidden="true"
                          className="nm-project-option-star"
                          width="11"
                          height="11"
                          viewBox="0 0 24 24"
                          fill="currentColor"
                          stroke="currentColor"
                          strokeWidth="1.5"
                          strokeLinejoin="round"
                        >
                          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                        </svg>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Image insert error */}
        {imageError && (
          <div className="rc-error" style={{ margin: '0 16px 4px' }} role="alert">
            <span className="rc-error-icon">!</span>
            <span>{imageError}</span>
          </div>
        )}

        {/* Body — always editable, subtle highlight overlay on corrections */}
        <div className="gmail-body">
          {/* Streaming stage indicator — visible only during compose generation.
              Swapped for the richer ThoughtStream narration when the user
              enabled the Processus IA disclosure. */}
          {isStreaming && !showPipeline && (
            <div className="nm-stream-indicator">
              <StageFlow activeStageName={null} isComplete={false} />
              {streamStage && <div className="nm-stream-stage">{streamStage}</div>}
            </div>
          )}
          {isStreaming && showPipeline && (
            <ThoughtStream
              stageName={streamView.stageName}
              versionIndex={streamView.versionIndex}
              accumulatedText={body}
              critique={streamView.critique || undefined}
              isComplete={false}
            />
          )}
          {/* BUG-Y008 (Session AA fix): refine mode (Ctrl+G plain, Haiku only)
              previously had ZERO pipeline visualization — the draft just
              appeared instantaneously, hiding the AI process from the user.
              Now we surface the same StageFlow indicator so the user sees
              CLASSIF → REDACT → CRITIQUE → FINITION even on the fast path.
              The stage stays at "redact" until the draft lands, then flips
              to isComplete on the streamView completion signal. */}
          {isGenerating && !isStreaming && (
            <div className="nm-stream-indicator nm-stream-indicator--refine">
              <StageFlow activeStageName="redact" isComplete={false} />
            </div>
          )}
          {/* Refine mode has no stream — show a shimmer label while the
              backend expands the user's note into a draft. After ~15s of
              waiting we swap to a longer reassurance label so the user
              knows the request is still in flight (cold-start LLM calls
              can run 50–55s in production). */}
          <ThinkingIndicator
            visible={isGenerating && !isStreaming}
            label={isLongWait ? t('thinking_long_wait') : t('thinking')}
          />
          {/* Whisper transcription — fires after the user stops recording and
              the audio is sent to the backend. Mic button is disabled in this
              state, so the two indicators are mutually exclusive. */}
          <ThinkingIndicator
            visible={isTranscribing}
            label={t('transcribing')}
          />
          {/* Body first — user writes here, AI improves here */}
          {/* `pointer-events: none` while recording or transcribing :
              prevents phantom click events from moving the caret during
              dictation. Concrete repro on HP Pavilion Gaming with sensitive
              ELAN trackpad — chassis vibrations from speech register as
              phantom taps → caret jumps mid-dictation. Generalises to any
              hardware where speech-induced clicks can leak through (sensitive
              touchpads, voice-controlled mice, accidental clicks). The mic
              button lives in the toolbar below, outside this wrapper, so it
              stays clickable to stop recording. */}
          <div
            className="nm-body-wrapper"
            style={{
              fontFamily: fontFamilyCss,
              fontSize: fontSizeCss,
              position: 'relative',
              pointerEvents: (isRecording || isTranscribing) ? 'none' : undefined,
            }}
          >
            {body.replace(/<[^>]*>/g, '').trim() === '' && !isGenerating && !isTranscribing && !isRecording && (
              <div className="nm-body-placeholder" aria-hidden="true">
                {/* Clé compose dédiée : `notes_placeholder` (partagée avec le
                    ReplyComposer) dit « générer une réponse » — faux ici. */}
                {t('compose_notes_placeholder', { platform: navigator.platform?.includes('Mac') ? '⌘' : 'Ctrl' })}
              </div>
            )}
            <DraftEditor
              ref={editorRef}
              content={body}
              onChange={(html) => { if (diffOverlay) dismissDiff(); setBody(html) }}
              // Stay editable while recording/transcribing so the dictation
              // block cursor marks the insertion point and the transcript can
              // land there. Phantom taps are already blocked by the wrapper's
              // `pointer-events: none`; only AI streaming locks the editor.
              readOnly={isStreaming}
              dictating={isRecording || isTranscribing}
              recording={isRecording}
              hideWordCount
              hideToolbar
              className="nm-editor-borderless"
            />
            {diffOverlay && (
              <div className="nm-diff-overlay" aria-hidden="true" style={{ fontFamily: fontFamilyCss, fontSize: fontSizeCss }}>
                {renderSubtleDiff(diffOverlay)}
              </div>
            )}
          </div>

          {/* SurgicalEditBar — barre inline pour modifier un détail du
              brouillon. Active via Ctrl+M ou click "Modifier" dans la popup
              AI. Voice transcripts y sont routés automatiquement quand elle
              est ouverte (cf. handleVoiceTranscript + surgicalEditOpenRef). */}
          <SurgicalEditBar
            isOpen={surgicalEditOpen}
            body={body}
            to={to}
            isRecording={isRecording}
            isTranscribing={isTranscribing}
            onMicToggle={handleMicClick}
            dictationEnabled={voiceDictationAllowed}
            instruction={surgicalInstruction}
            setInstruction={setSurgicalInstruction}
            onSubmit={(modifiedBody, fastPath) => {
              if (!fastPath) {
                const oldPlain = body.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
                const newPlain = modifiedBody.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
                const parts = computeWordDiff(oldPlain, newPlain)
                if (countChanges(parts) > 0) {
                  if (diffTimerRef.current) clearTimeout(diffTimerRef.current)
                  setDiffOverlay(parts)
                  diffTimerRef.current = setTimeout(() => dismissDiff(), 2500)
                }
              }
              setBody(modifiedBody)
              setSurgicalEditOpen(false)
              setSurgicalInstruction('')
            }}
            onClose={() => {
              setSurgicalEditOpen(false)
              setSurgicalInstruction('')
            }}
          />

          {/* Specialty expertise feedback (Ctrl+Shift+G) */}
          <SpecialtyBadge
            info={specialtyInfo}
            message={specialtyMessage}
            onDismiss={() => { setSpecialtyInfo(null); setSpecialtyMessage(null) }}
          />

          {/* Signature footer — outside TipTap, seamless with editor.
              Cliquer la signature ouvre l'éditeur (même UI que le ReplyComposer,
              portée message : rien n'est persisté). */}
          {(displaySignatureHtml || signatureEditorOpen) && (
            <div
              className={`nm-signature-footer${signatureClickable ? ' rc-signature-footer--clickable' : ''}`}
              style={{ fontSize: fontSizeCss, fontFamily: fontFamilyCss }}
              role={signatureClickable ? 'button' : undefined}
              tabIndex={signatureClickable ? 0 : undefined}
              onClick={signatureClickable ? handleSignatureClick : undefined}
              onKeyDown={signatureClickable ? handleSignatureKeyDown : undefined}
              title={signatureClickable ? t('switch_signature') : undefined}
              aria-label={signatureClickable ? t('switch_signature') : undefined}
            >
              {signatureEditorOpen ? (
                <div
                  className="rc-signature-editor"
                  // Tant que l'éditeur est ouvert, il possède Échap : les hôtes
                  // (NewMessageModal/useAppShortcuts) consultent hasEscapeOwner()
                  // et s'abstiennent — voir utils/escapeOwner.ts.
                  data-escape-owner=""
                  onKeyDown={(event) => {
                    if (event.key === 'Escape') {
                      event.stopPropagation()
                      setSignatureEditorOpen(false)
                    }
                  }}
                >
                  {signatureLibrary.length > 0 && (
                    <div className="rc-signature-chips" role="group" aria-label={t('signature_switch_aria')}>
                      {signatureLibrary.map(entry => (
                        <button
                          key={entry.id}
                          type="button"
                          className={`rc-signature-chip${(activeSignatureId ? activeSignatureId === entry.id : entry.is_default) ? ' rc-signature-chip--active' : ''}`}
                          data-testid="rc-signature-chip"
                          onClick={() => {
                            setSignatureDraft(entry.text || '')
                            setPendingEntry({ id: entry.id, html: entry.html || '', text: entry.text || '' })
                          }}
                        >
                          {entry.name}
                        </button>
                      ))}
                    </div>
                  )}
                  <textarea
                    className="rc-signature-textarea"
                    value={signatureDraft}
                    onChange={(event) => {
                      setSignatureDraft(event.target.value)
                      setPendingEntry(null)
                    }}
                    rows={2}
                    spellCheck={false}
                    aria-label={t('signature_for_message')}
                    // Focus à l'ouverture : sans lui, Échap part du body et
                    // n'atteint jamais le handler du conteneur (touche morte).
                    autoFocus
                  />
                  {/* Actions groupées en bas à droite : Annuler (fantôme) +
                      Appliquer (accent). Le ✓ applique la signature à CE message
                      (éphémère), d'où « Appliquer » plutôt que « Enregistrer ». */}
                  <div className="rc-signature-actions">
                    <button
                      type="button"
                      className="rc-signature-action-btn"
                      onClick={() => setSignatureEditorOpen(false)}
                    >
                      {tCommon('cancel')}
                    </button>
                    <button
                      type="button"
                      className="rc-signature-action-btn rc-signature-action-btn--primary"
                      onClick={applySignatureDraft}
                    >
                      {tCommon('apply')}
                    </button>
                  </div>
                </div>
              ) : displaySignatureHtml ? (
                <div dangerouslySetInnerHTML={{ __html: displaySignatureHtml }} />
              ) : null}
            </div>
          )}

        </div>

        {/* Attachments */}
        {attachments.length > 0 && (
          <div className="attachments-list">
            {attachments.map((attachment, index) => (
              <AttachmentCard
                key={index}
                file={attachment.file}
                name={attachment.name}
                size={attachment.size}
                onRemove={() => removeAttachment(index)}
                removeLabel={t('remove')}
              />
            ))}
          </div>
        )}

        {/* Hidden file input */}
        <input
          type="file"
          ref={fileInputRef}
          onChange={handleFileChange}
          style={{ display: 'none' }}
          multiple
          aria-label={t('attach_files')}
        />
        {/* Hidden image input */}
        <input
          type="file"
          ref={imageInputRef}
          onChange={handleImageInsert}
          style={{ display: 'none' }}
          accept="image/*"
          aria-label={t('insert_image')}
        />

        <RecordingWaveform isRecording={isRecording} audioLevels={audioLevels} />

        {/* Footer actions */}
        <div className="gmail-footer">
          {/* Envoyer (à gauche) — bouton split avec chevron pour planifier */}
          <SendButtonSplit
            onSend={handleSend}
            onSchedule={doScheduleSend}
            // Disable while a compose generation streams in — sending mid-stream
            // would ship a truncated, half-written AI draft.
            disabled={!to.trim() || isStreaming || isGenerating}
            loading={isSending || isSentAnim}
            label={isSentAnim ? t('sent_excl') : isSending ? t('sending') : t('send')}
            sendTestId="compose-send-button"
            pillClassName={isSentAnim ? 'rc-send-success' : ''}
          />


          {/* Sélecteur langue dictée — défaut = langue du destinataire (Settings → Training).
              Masqué en Free : la dictée est verrouillée, le picker n'a pas de sens. */}
          {!isRecording && !isTranscribing && !aiLocked && (
            <VoiceLanguageBadge
              language={voiceLanguage}
              onChange={setVoiceLanguage}
              disabled={isGenerating || !voiceDictationAllowed}
            />
          )}

          {/* Micro — la dictée (Whisper) est une fonctionnalité IA payante.
              En Free le bouton porte le même cadenas que la baguette IA et le
              clic ouvre le paywall au lieu de démarrer l'enregistrement. */}
          <button
            type="button"
            className={`rc-icon-btn nmm-mic-btn${isRecording ? ' nmm-mic-recording' : ''}`}
            onClick={handleMicClick}
            onMouseEnter={() => { if (voiceDictationAllowed) void prewarmMic() }}
            disabled={isTranscribing || isGenerating || (!voiceDictationAllowed && !isRecording)}
            title={
              !voiceDictationAllowed && !isRecording
                ? t('dictation_requires_trial_or_plan')
                : isRecording
                  ? t('ai_cmd_mic_stop_tooltip')
                  : `${t('ai_cmd_dictate')} (${voiceLanguage === 'auto' ? 'auto' : voiceLanguage.toUpperCase()})`
            }
            aria-label={
              !voiceDictationAllowed && !isRecording
                ? t('dictation_unavailable')
                : isRecording ? t('ai_cmd_mic_stop_tooltip') : t('ai_cmd_dictate')
            }
          >
            {isTranscribing ? (
              <span className="nmm-mic-spinner" />
            ) : isRecording ? (
              <svg width="18" height="18" viewBox="0 0 20 20" fill="var(--accent-primary, #0d9488)" aria-hidden="true">
                <rect className="ai-wf-1" x="1"  y="6" width="3" height="8"  rx="1.5"/>
                <rect className="ai-wf-2" x="6"  y="3" width="3" height="14" rx="1.5"/>
                <rect className="ai-wf-3" x="11" y="5" width="3" height="10" rx="1.5"/>
                <rect className="ai-wf-4" x="16" y="7" width="3" height="6"  rx="1.5"/>
              </svg>
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                <line x1="12" y1="19" x2="12" y2="22"/>
                <line x1="8" y1="22" x2="16" y2="22"/>
              </svg>
            )}
            {aiLocked && (
              <span className="ai-cmd-lock" data-testid="mic-lock" aria-hidden="true">
                <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
                  <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                </svg>
              </span>
            )}
          </button>

          {/* Logo Agentys — accès aux commandes. En Free le bouton reste
              cliquable (clic → toast paywall + upsell, cf. handleMagicGenerate)
              mais porte le même cadenas que la baguette IA. */}
          <button
            type="button"
            className="rc-icon-btn"
            onClick={handleMagicGenerate}
            disabled={isGenerating}
            title={aiLocked ? paidAiMessage : t('magic_generate_tooltip')}
            aria-label={aiLocked ? paidAiMessage : t('magic_generate_tooltip')}
          >
            <MagicDraftIcon size={16} />
            {aiLocked && (
              <span className="ai-cmd-lock" data-testid="magic-generate-lock" aria-hidden="true">
                <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
                  <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                </svg>
              </span>
            )}
          </button>
          <AICommandMenu
            ref={aiCmdMenuRef}
            commands={SLASH_COMMANDS}
            onCommandSelect={handleCommandFromMenu}
            onCustomSubmit={handleCustomPromptFromMenu}
            onDictate={handleMicClick}
            // Le mic du toolbar est partagé : isRecording/isTranscribing
            // reflètent le SEUL useWhisperRecording du compose. Le mic inline
            // dans la popup et le mic du toolbar pilotent la même session.
            isRecording={isRecording}
            isTranscribing={isTranscribing}
            onStopRecording={handleMicClick}
            showDictateOption={false}
            dictationEnabled={voiceDictationAllowed}
            transcriptionError={transcriptionError}
            disabled={isGenerating || aiLocked}
            disabledReason={aiLocked ? paidAiMessage : undefined}
            bodyHasContent={bodyPlainText.length > 0}
            onOpenChange={(open) => { aiPopupOpenRef.current = open }}
            // Click sur le preset "Modifier" → ouvre la SurgicalEditBar inline
            // dans la zone teal sous le body (UX moins invasive qu'une popup).
            onEnterSurgicalMode={() => {
              setSurgicalInstruction('')
              setSurgicalEditOpen(true)
            }}
          />

          {/* Pièce jointe */}
          <button className="rc-icon-btn" onClick={handleAttachClick} title={t('attach_files')} aria-label={t('attach_files')}>
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/>
            </svg>
          </button>

          {/* Snippet */}
          <div className="rc-snippet-wrapper">
            <button
              ref={snippetBtnRef}
              className="rc-icon-btn"
              onClick={() => setShowSnippetSelector(!showSnippetSelector)}
              title={t('insert_snippet')}
              aria-label={t('insert_snippet')}
            >
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 4H7a2 2 0 0 0-2 2v3a2 2 0 0 1-2 2 2 2 0 0 1 2 2v3a2 2 0 0 0 2 2h2" />
                <path d="M15 4h2a2 2 0 0 1 2 2v3a2 2 0 0 0 2 2 2 2 0 0 0-2 2v3a2 2 0 0 1-2 2h-2" />
              </svg>
            </button>
            <SnippetSelector
              isOpen={showSnippetSelector}
              onClose={() => setShowSnippetSelector(false)}
              snippets={snippets}
              sharedSnippets={sharedSnippets}
              onSelect={handleSnippetSelect}
              onCreateNew={() => {
                setShowSnippetSelector(false)
                setShowSnippetEditor(true)
              }}
              anchorRef={snippetBtnRef as React.RefObject<HTMLElement>}
              loading={snippetsLoading}
            />
          </div>

          {/* Insert availability — calendar picker + booking link, à la Superhuman.
              `language` = threadLanguageHint (pin du picker sinon hint
              destinataire ; un choix explicite « Auto » retombe volontairement
              sur le hint — assumé). Le STT reste en auto-détection. */}
          <InsertAvailabilityButton
            accountId={accountId}
            disabled={isGenerating || isTranscribing || isStreaming}
            onInsert={(text) => {
              // Inserting availability slots is an explicit signal that
              // the dates in the body are PROPOSED to the recipient, not
              // commitments we owe ourselves. Take manual control of the
              // follow-up reminder: lock auto-detect off and clear any
              // pre-existing detected date. The user can still set a
              // reminder explicitly via the bell button.
              followupOverrideRef.current = true
              setFollowupDate(null)
              editorRef.current?.insertText(text)
            }}
            language={threadLanguageHint ?? 'auto'}
          />

          {/* Rappel (bell) */}
          <button
            ref={followupBtnRef}
            type="button"
            className={followupDate ? 'followup-date-chip' : 'rc-icon-btn'}
            title={followupDate ? t('cancel_reminder') : t('reminder_activate')}
            aria-label={t('auto_reminder')}
            onClick={(e) => {
              if (followupDate) {
                followupOverrideRef.current = true
                setFollowupDate(null)
              } else {
                const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
                setFollowupPickerPos({ x: rect.left, y: rect.bottom + 4, buttonTop: rect.top })
              }
            }}
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
              <path d="M13.73 21a2 2 0 0 1-3.46 0" />
            </svg>
            {followupDate && <span>{formatFollowupDate(followupDate)}</span>}
          </button>
          {followupPickerPos && (
            <FollowupDatePicker
              position={followupPickerPos}
              emailBody={body}
              forceCalendar={followupPickerPos.forceCalendar}
              onSelect={(date) => {
                followupOverrideRef.current = true
                setFollowupDate(date)
                setFollowupPickerPos(null)
              }}
              onClose={() => {
                setFollowupPickerPos(null)
              }}
            />
          )}

          {/* Liste à puces */}
          <button className="rc-icon-btn" onMouseDown={(e) => e.preventDefault()} onClick={handleInsertBulletList} title={t('bullet_list')} aria-label={t('insert_bullet_list')}>
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="9" y1="6" x2="20" y2="6"/>
              <line x1="9" y1="12" x2="20" y2="12"/>
              <line x1="9" y1="18" x2="20" y2="18"/>
              <circle cx="4" cy="6" r="1.5" fill="currentColor" stroke="none"/>
              <circle cx="4" cy="12" r="1.5" fill="currentColor" stroke="none"/>
              <circle cx="4" cy="18" r="1.5" fill="currentColor" stroke="none"/>
            </svg>
          </button>


          {/* Poubelle (extrême droite) */}
          <div className="gmail-footer-right">
            <button className="rc-delete-btn icon-btn--delete" onClick={handleDiscard} title={t('delete_draft')} aria-label={t('delete_draft')}>
              <TrashIcon size={16} />
            </button>
          </div>
        </div>

        {/* Hints clavier — l'ancien ruban global s'affichait sur le backdrop,
            ~250px sous le modal, visuellement déconnecté du composeur. Il est
            masqué quand ce modal est ouvert (App.tsx) ; les raccourcis vivent
            ici, dans le pied du modal. NB : les chips .shortcut-key sont
            stylées dans EmailList.css (chargé en eager par App), pas App.css.
            Pas d'aria-hidden : le ruban remplacé était exposé aux lecteurs
            d'écran, cette rangée l'est donc aussi. */}
        <div className="nm-shortcut-hints">
          <span className="nm-hint"><span className="shortcut-key">{modKey}</span><span className="shortcut-key">Enter</span><span className="nm-hint-label">{tCommon('send')}</span></span>
          <span className="nm-hint"><span className="shortcut-key">{modKey}</span><span className="shortcut-key">G</span><span className="nm-hint-label">{t('action_compose')}</span></span>
          <span className="nm-hint"><span className="shortcut-key">{modKey}</span><span className="shortcut-key">Shift</span><span className="shortcut-key">,</span><span className="nm-hint-label">{t('delete_draft')}</span></span>
          <span className="nm-hint"><span className="shortcut-key">Esc</span><span className="nm-hint-label">{tCommon('close')}</span></span>
        </div>
      </div>

      {/* Snippet Editor Modal */}
      <SnippetEditor
        isOpen={showSnippetEditor}
        onClose={() => setShowSnippetEditor(false)}
        onSave={handleCreateSnippet}
      />

      {/* Custom placeholder fill modal */}
      {pendingPlaceholders && createPortal(
        <div className="nmm-placeholder-overlay" onClick={handlePlaceholderCancel}>
          <div className="nmm-placeholder-modal" onClick={(e) => e.stopPropagation()}>
            <h3>{t('fill_placeholders', 'Remplir les champs personnalisés')}</h3>
            <p className="nmm-placeholder-hint">
              {t('fill_placeholders_hint', 'Ce snippet contient des champs à remplir avant insertion.')}
            </p>
            <div className="nmm-placeholder-fields">
              {pendingPlaceholders.variables.map((v) => {
                const name = v.replace(/^\{|\}$/g, '')
                return (
                  <label key={name} className="nmm-placeholder-field">
                    <span className="nmm-placeholder-label">{name.replace(/_/g, ' ')}</span>
                    <input
                      type="text"
                      autoFocus={pendingPlaceholders.variables[0] === v}
                      value={pendingPlaceholders.values[name] || ''}
                      placeholder={v}
                      onChange={(e) =>
                        setPendingPlaceholders((prev) =>
                          prev ? { ...prev, values: { ...prev.values, [name]: e.target.value } } : null
                        )
                      }
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handlePlaceholderConfirm()
                        if (e.key === 'Escape') handlePlaceholderCancel()
                      }}
                    />
                  </label>
                )
              })}
            </div>
            <div className="nmm-placeholder-actions">
              <button className="nmm-placeholder-btn-cancel" onClick={handlePlaceholderCancel}>
                {t('cancel', 'Annuler')}
              </button>
              <button className="nmm-placeholder-btn-confirm" onClick={handlePlaceholderConfirm}>
                {t('insert', 'Insérer')}
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}

      {/* Forgotten attachment reminder */}
      {attachmentReminder && (
        <Suspense fallback={null}>
          <AttachmentReminderModal
            keyword={attachmentReminder.keyword}
            matchedText={attachmentReminder.matchedText}
            onAttach={() => {
              setAttachmentReminder(null)
              fileInputRef.current?.click()
              apiClient.recordFeature('attachment_reminder')
            }}
            onSendAnyway={() => {
              setAttachmentReminder(null)
              doSend()
            }}
            onClose={() => setAttachmentReminder(null)}
          />
        </Suspense>
      )}

      <MicPermissionDialog
        open={softAskOpen}
        onConfirm={confirmSoftAsk}
        onCancel={dismissSoftAsk}
      />

    </div>,
    document.body
  )
}
