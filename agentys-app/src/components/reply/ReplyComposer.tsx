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

/* eslint-disable react-refresh/only-export-components */
import React, { useState, useEffect, useCallback, useRef, Suspense, useMemo } from 'react';
import DOMPurify from 'dompurify';
import { createPortal } from 'react-dom';
import { lazyWithRetry as lazy } from '../../utils/lazyWithRetry';
import { useTranslation } from 'react-i18next';
import i18n from '../../i18n';
import { formatFullDateLong, formatLongDateFromDate, formatDayMonthYear } from '../../utils/dateFormat';
import { isHtmlContent } from '../../utils/emailContent';
import { DraftEditor } from '../DraftEditor';
import type { DraftEditorHandle } from '../DraftEditor';
import { InsertAvailabilityButton } from '../availability/InsertAvailabilityButton';
import { useInlineImage } from '../../hooks/useInlineImage';
import { generateDraft } from '../../api/emails';
import type { GenerateDraftResponse } from '../../api/emails';
import { apiClient, hideContact } from '../../services/api';
import { silentFailWithToast } from '../../utils/silentFail';
import type { OutgoingAttachment } from '../../services/api';
import type { EmailDetail } from '../../types/email';
import { getReplyDraftForEmail, saveReplyDraft, deleteReplyDraftForEmail, hasContent } from '../../services/draftStorage';
import { isDeleteDraftShortcut } from '../../utils/keyboard';
import { getDraftStreamState, clearDraftStreamState, subscribeDraftStream } from '../../hooks/useWebSocketSync';
import type { EmailIntent } from '../SmartReply';
import { SnippetSelector, SnippetEditor } from '../snippets';
import { useSnippets } from '../../hooks/useSnippets';
import { replaceSnippetVariables } from '../../api/snippets';
import { snippetContentToInsertionHtml } from '../../utils/snippetInsertion';
import { preserveInlineImages } from '../../utils/preserveInlineImages';
import type { Snippet, CreateSnippetPayload } from '../../types/snippets';
import type { SpecialtyInfo } from '../../types/specialty';
import { isSpecialtyMatch } from '../../types/specialty';
import { SpecialtyBadge } from '../specialty/SpecialtyBadge';
import { ThoughtStream } from '../pipeline/ThoughtStream';
import { AIProcessButton } from '../pipeline/AIProcessButton';
import { PipelineDisclosure } from '../pipeline/PipelineDisclosure';
import { type PipelineInfo, buildPipelineInfo } from '../pipeline/pipelineInfo';
import { useDraftStream } from '../../hooks/useDraftStream';
import { useComposeFontPrefs } from '../../hooks/useComposeFontPrefs';
import { ContactAutocomplete } from '../compose/ContactAutocomplete';
import { SendButtonSplit } from '../compose/SendButtonSplit';
import { RecordingWaveform } from '../compose/RecordingWaveform';
import { MicPermissionDialog } from '../compose/MicPermissionDialog';
import '../compose/SchedulePicker.css';
import { detectForgottenAttachment, type AttachmentDetectionResult } from '../../utils/attachmentDetector';
const AttachmentReminderModal = lazy(() => import('../AttachmentReminderModal').then(m => ({ default: m.AttachmentReminderModal })));
import { FollowupDatePicker, detectDateFromBody } from '../FollowupDatePicker';
import { useFileDrop } from '../../hooks/useFileDrop';
import { FileDropOverlay } from '../FileDropOverlay';
import { AttachmentCard } from '../compose/AttachmentCard';
import { ChevronDownIcon, MagicDraftIcon, TrashIcon } from '../icons/ActionIcons';
import { ThinkingIndicator } from '../ThinkingIndicator';

import { writeSnoozeEntry } from '../../hooks/useSnooze';
import { useAccountSignature } from '../../hooks/useAccountSignature';
import { useSignatureLibrary } from '../../hooks/useSignatureLibrary';
import { useAutoReminderOnCommitment } from '../../hooks/useAutoReminderOnCommitment';
import './ReplyComposer.css';
import { SLASH_COMMANDS } from '../../utils/slash-commands';
import { useWhisperRecording } from '../../hooks/useWhisperRecording';
import { useLabels } from '../../hooks/useLabels';
import { useVoiceLanguage } from '../../hooks/useVoiceLanguage';
import { useVoiceDictationAccess } from '../../hooks/useVoiceDictationAccess';
import { useContactLanguages, extractEmails } from '../../hooks/useContactLanguages';
import { VoiceLanguageBadge } from '../compose/VoiceLanguageBadge';
import { AICommandMenu } from '../compose/AICommandMenu';
import {
  DRAFT_READY_POLL_INITIAL_DELAY_MS,
  getNextDraftReadyPollDelay,
  getRemainingDraftReadyPollWait,
} from './draftPolling';
import { buildReplyAllRecipients, pickReplyRecipient, withSenderDisplayName } from './replyRecipient';
import { getJwtEmail } from '../../services/authToken';
import { buildCachedDraftEmailContext } from '../../api/emailBodyCache';

interface ReplyComposerProps {
  email: EmailDetail;
  replyType: 'reply' | 'reply_all' | 'forward';
  accountEmail?: string;
  onSend: (draftId: string, body: string) => void;
  onCancel: () => void;
  onDraftSaved?: () => void;
  onDraftDiscarded?: () => void;
  onDraftGenerated?: () => void;
  /** Pre-fill the editor body directly (e.g. from SmartReply chips) */
  prefillBody?: string;
  /** Auto-trigger AI generation on mount with this instruction (e.g. from SmartReply prompt) */
  autoGeneratePrompt?: string;
  aiEnabled?: boolean;
  onUpgradeRequired?: () => void;
}

type ComposerState = 'idle' | 'generating' | 'editing' | 'sending' | 'sent';


// ── Default auto-gen instruction per intent (constrains LLM, avoids hallucination) ──
const AUTO_GEN_INSTRUCTIONS: Record<EmailIntent, string> = {
  meeting: 'Reply to this meeting invitation. Only mention what is in the email.',
  availability: 'Reply to the availability request. Only mention what is in the email.',
  urgent: 'Reply to this urgent request. Only mention what is in the email.',
  document: 'Reply to the document request. Only mention what is in the email.',
  confirmation: 'Confirm or reply to the request. Only mention what is in the email.',
  question: 'Reply to the question asked. Only mention what is in the email.',
  social: 'Reply in a friendly way with a few words. It is just a greeting between friends, no need to invent details about your life.',
  issue: 'Reply to the issue report. Only mention what is in the email.',
  followup: 'Reply to this follow-up. Only mention what is in the email.',
  introduction: 'Reply to this introduction. Only mention what is in the email.',
  thanks: 'Reply courteously to the thank-you.',
  action: 'Reply appropriately. Only mention what is in the email.',
};

export function _getAutoGenInstruction(intent: EmailIntent | null, bodyLength: number): string {
  const base = AUTO_GEN_INSTRUCTIONS[intent || 'action'];
  if (bodyLength < 80) {
    return base + ' Reply in MAXIMUM 2 short sentences.';
  }
  if (bodyLength < 150) {
    return base + ' Reply briefly, 3 sentences maximum.';
  }
  return base;
}

// ── Level 1: Template responses for trivial emails (no LLM needed) ──────────

export function _extractFirstName(sender: string, senderName: string | null): string {
  // Use sender_name if available: "Alexandre Simon" → "Alexandre"
  if (senderName) {
    return senderName.split(/\s+/)[0] || '';
  }
  // Fallback: parse email "alexandre.simon@hotmail.com" → "Alexandre"
  const local = sender.split('@')[0] || '';
  const parts = local.split(/[._-]/);
  if (parts.length > 0 && parts[0].length >= 2) {
    return parts[0].charAt(0).toUpperCase() + parts[0].slice(1).toLowerCase();
  }
  return '';
}

function _detectLanguage(text: string): 'fr' | 'en' {
  // Simple heuristic: French accent chars + common French words
  if (/[àâéèêëïîôùûüç]/.test(text)) return 'fr';
  if (/\b(salut|bonjour|merci|comment|oui|non|bien|quoi|c'est)\b/i.test(text)) return 'fr';
  return 'en';
}

function _isCasual(text: string): boolean {
  return /\b(salut|hey|yo|mec|pote|dude|bro|coucou|wesh)\b/i.test(text);
}

/**
 * For trivially simple emails, return a pre-built response (no LLM call).
 * Returns null if the email is too complex for a template.
 */
export function getTemplateResponse(
  intent: EmailIntent | null,
  senderName: string,
  body: string,
  subject: string,
): string | null {
  // Only template very short emails
  if (body.length > 200) return null;

  const fullText = `${subject} ${body}`;
  const lang = _detectLanguage(fullText);
  const casual = _isCasual(fullText);
  const name = senderName;

  // Social greeting: "salut, comment ça va?"
  if (intent === 'social') {
    if (lang === 'fr') {
      if (casual || !name) {
        return name
          ? `Salut ${name},\n\nDoing well, thanks! And you?`
          : `Hey,\n\nDoing well, thanks! And you?`;
      }
      return `Hi ${name},\n\nDoing well, thanks! And you?`;
    }
    return name
      ? `Hey ${name},\n\nDoing well, thanks! How about you?`
      : `Hey,\n\nDoing well, thanks! How about you?`;
  }

  // Thanks: "merci pour X"
  if (intent === 'thanks') {
    if (lang === 'fr') {
      return name
        ? `Hi ${name},\n\nYou're welcome!`
        : `You're welcome!`;
    }
    return `${name ? `Hi ${name},\n\n` : ''}You're welcome!`;
  }

  // Simple receipt confirmation: "as-tu reçu mon email?"
  if (/\b(as-tu re[cç]u|re[cç]u mon|did you (get|receive)|got my (email|message))\b/i.test(fullText)) {
    if (lang === 'fr') {
      return name
        ? `Hi ${name},\n\nYes, received. Thanks!`
        : `Yes, received. Thanks!`;
    }
    return `${name ? `Hi ${name},\n\n` : ''}Yes, received. Thanks!`;
  }

  const bodyShort = body.trim().length < 60;
  const greeting = name ? `Hi ${name},` : 'Hi,';

  // OK/ack: "ok", "d'accord", "entendu", "got it", "sounds good"
  if (bodyShort && /^(?:ok|okay|d['\u2019]accord|c['\u2019]est bon|parfait|entendu|not[eé]|got it|alright|sounds good|all good)\s*[.!]?\s*$/i.test(body.trim())) {
    return `${greeting}\n\nGot it, thanks!`;
  }

  // FYI/notification ack: "pour info", "fyi", "heads up"
  if (/\b(pour (?:ta|ton|votre )?info|fyi|heads? up|note\s*:)\b/i.test(fullText)) {
    return `${greeting}\n\nNoted, thanks for the heads up.`;
  }

  // Confirmation received: "c'est confirmé", "confirmed"
  if (/\b(c['\u2019]est confirm[eé]|on confirme|confirmed|it['\u2019]s confirmed)\b/i.test(fullText)) {
    return `${greeting}\n\nPerfect, thanks for confirming.`;
  }

  // Simple agreement: "ça marche", "deal", "works for me", "agreed"
  if (bodyShort && /^(?:[çc]a marche|deal|[çc]a me va|works? for me|agreed)\s*[.!]?\s*$/i.test(body.trim())) {
    return `${greeting}\n\nGreat!`;
  }

  return null; // Not trivial → use LLM
}


/** Strip embedded agentys-signature div to avoid double signature (useAccountSignature adds it separately) */
function stripEmbeddedSignature(html: string): string {
  // The naive non-greedy regex stops at the first </div>, leaving orphan tags when the
  // signature itself contains nested <div>s. Walk the string manually to find the matching
  // closing tag and remove the whole block.
  const start = html.search(/<div[^>]*class="agentys-signature"[^>]*>/i);
  if (start === -1) return html;
  let depth = 0;
  let i = start;
  while (i < html.length) {
    if (html[i] === '<') {
      if (/^<\/div/i.test(html.slice(i))) {
        depth--;
        if (depth === 0) {
          const end = html.indexOf('>', i) + 1;
          return (html.slice(0, start) + html.slice(end)).trim();
        }
      } else if (/^<div/i.test(html.slice(i))) {
        depth++;
      }
    }
    i++;
  }
  // No closing tag found — remove from start to end
  return html.slice(0, start).trim();
}


export const ReplyComposer = React.memo(function ReplyComposer({ email, replyType, accountEmail, onSend, onCancel, onDraftSaved, onDraftDiscarded, onDraftGenerated, prefillBody, autoGeneratePrompt, aiEnabled = true, onUpgradeRequired }: ReplyComposerProps) {
  const { t } = useTranslation('compose');
  const { t: tInbox } = useTranslation('inbox');
  const { t: tCommon } = useTranslation('common');
  const { fontFamilyCss, fontSizeCss } = useComposeFontPrefs();
  const [state, setState] = useState<ComposerState>('idle');
  const [draftBody, setDraftBody] = useState('');
  const [draftId, setDraftId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const aiLocked = aiEnabled === false;
  const paidAiMessage = t('ai_paid_required', { defaultValue: 'Les brouillons IA sont réservés aux abonnements payants.' });
  const showPaidAiBlocked = useCallback(() => {
    setError(paidAiMessage);
    onUpgradeRequired?.();
  }, [onUpgradeRequired, paidAiMessage]);
  // Specialty expertise state — populated on Ctrl+Shift+G match, cleared
  // every new generation. Warnings (no match, no active, rate limit) land in
  // specialtyMessage so the user sees a visible fallback path.
  const [specialtyInfo, setSpecialtyInfo] = useState<SpecialtyInfo | null>(null);
  const [specialtyMessage, setSpecialtyMessage] = useState<{ type: 'info' | 'warning' | 'error'; text: string } | null>(null);
  const cachedDraftEmailContext = useMemo(
    () => buildCachedDraftEmailContext(email.id, email),
    [email],
  );
  const editorRef = useRef<DraftEditorHandle>(null);
  // Voice dictation: insert the transcript at the caret so the user sees the
  // words land where the cursor is and can dictate several times back-to-back
  // with the text flowing on ("que le texte se suivent"). The editor's onChange
  // syncs `draftBody`. If the ref is somehow unavailable we fall back to a
  // plain append, guarding the empty "<p></p>" TipTap normalises to.
  const handleVoiceTranscript = useCallback((html: string) => {
    if (editorRef.current) {
      editorRef.current.insertDictation(html)
      return
    }
    const isBlank = (s: string) =>
      !s
        .replace(/<[^>]*>/g, '')
        .replace(/&nbsp;|&#160;/gi, '')
        .replace(/\u00A0/g, '')
        .replace(/ /g, '')
        .trim()
    setDraftBody(prev => (isBlank(prev) ? html : prev + html))
  }, []);
  const [forwardTo, setForwardTo] = useState('');
  const [currentReplyType, setCurrentReplyType] = useState<'reply' | 'reply_all' | 'forward'>(replyType);
  const ownEmail = accountEmail || getJwtEmail();
  // Voice dictation language : default to the recipient's preferred language
  // (Settings → Training contact data). Reply context = original sender ;
  // forward context = forwardTo field.
  const { aggregate: aggregateContactLanguages } = useContactLanguages()
  const recipientEmails = useMemo(() => {
    if (currentReplyType === 'forward') return extractEmails(forwardTo)
    const emails: string[] = []
    if (email.sender) emails.push(email.sender)
    if (currentReplyType === 'reply_all') {
      for (const addr of email.to ?? []) emails.push(addr)
      for (const addr of email.cc ?? []) emails.push(addr)
    }
    return extractEmails(emails.join(' '))
  }, [currentReplyType, email.sender, email.to, email.cc, forwardTo])
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
  const refineTargetLanguage: 'fr' | 'en' | undefined =
    threadLanguageHint === 'fr' || threadLanguageHint === 'en' ? threadLanguageHint : undefined
  const voiceDictationAllowed = useVoiceDictationAccess()
  const { projectLabels } = useLabels()
  const voiceVocabulary = useMemo(
    () => projectLabels.map(label => label.name).filter(Boolean),
    [projectLabels],
  )

  const { isRecording, isTranscribing, transcriptionError, showMicButton: _showMicButton, handleMicClick, formattedTime: _formattedTime, silenceDetected: _silenceDetected, silenceCountdown: _silenceCountdown, audioLevels, prewarmMic, softAskOpen, confirmSoftAsk, dismissSoftAsk } = useWhisperRecording(
    !draftBody.replace(/<[^>]*>/g, '').trim(),
    true,
    handleVoiceTranscript,
    { language: voiceLanguageParam, promptVocabulary: voiceVocabulary, surfaceSelector: '.reply-composer', enabled: voiceDictationAllowed },
  );

  // When dictation starts, surface the editor caret so the user sees where the
  // spoken words will be inserted. Skip if already focused so push-to-talk keeps
  // the caret where the user left it.
  useEffect(() => {
    if (isRecording) editorRef.current?.focusForDictation();
  }, [isRecording]);
  // Streaming narration state (stageName, versionIndex, critique, crossfade key)
  // is owned by the shared `useDraftStream` hook — the subscribe effect below
  // only keeps the side-effects specific to the reply flow (mirror text into
  // draftBody, fetch pipelineInfo on completion, polling fallback, error bus).
  const streamView = useDraftStream(email.id, state === 'generating');
  const [showSnippetSelector, setShowSnippetSelector] = useState(false);
  const [showSnippetEditor, setShowSnippetEditor] = useState(false);
  const [attachments, setAttachments] = useState<{name: string; size: number; file: File}[]>([]);
  const [pipelineInfo, setPipelineInfo] = useState<PipelineInfo | null>(null);
  const [showPipeline, setShowPipeline] = useState(false);
  const [attachError, setAttachError] = useState<string | null>(null);
  const [to, setTo] = useState('');
  const [cc, setCc] = useState('');
  const [bcc, setBcc] = useState('');
  const [showCc, setShowCc] = useState(false);
  const [showBcc, setShowBcc] = useState(false);
  const [subject, setSubject] = useState('');
  const [dragState, setDragState] = useState<{ email: string; sourceField: 'to' | 'cc' | 'bcc' } | null>(null)
  const [dragOverField, setDragOverField] = useState<'to' | 'cc' | 'bcc' | null>(null)
  const [showSendMenu, setShowSendMenu] = useState(false);
  const sendMenuRef = useRef<HTMLDivElement>(null);
  const sendChevronRef = useRef<HTMLButtonElement>(null);
  const [showModeDropdown, setShowModeDropdown] = useState(false);
  const modeDropdownRef = useRef<HTMLDivElement>(null);
  const modePillRef = useRef<HTMLButtonElement>(null);
  const modeDropdownPortalRef = useRef<HTMLDivElement>(null);
  const [modeDropdownPos, setModeDropdownPos] = useState<{ top: number; left: number } | null>(null);
  // Sujet masqué par défaut : il est toujours pré-rempli ("Re: …"), l'utilisateur
  // l'affiche via le lien "Objet" ou Ctrl+Shift+S s'il veut le modifier.
  const [showSubject, setShowSubject] = useState(false);
  const subjectInputRef = useRef<HTMLInputElement>(null);
  const snippetBtnRef = useRef<HTMLButtonElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { clearImageError } = useInlineImage(editorRef);
  const [followupDate, setFollowupDate] = useState<Date | null>(null);
  const [followupPickerPos, setFollowupPickerPos] = useState<{ x: number; y: number; buttonTop?: number; forceCalendar?: boolean } | null>(null);
  const followupBtnRef = useRef<HTMLButtonElement>(null);
  // Toggle « Auto-reminder when commitment detected » (Settings > Inbox)
  const { autoReminderOnCommitment } = useAutoReminderOnCommitment();
  // True dès que l'utilisateur a manuellement choisi/effacé la date dans CE brouillon :
  // l'auto-sync en arrête de toucher l'état pour ne pas écraser son choix.
  const followupOverrideRef = useRef(false);

  // Reset reminder when switching to a different email
  useEffect(() => {
    setFollowupDate(null);
    setFollowupPickerPos(null);
    followupOverrideRef.current = false;
  }, [email.id]);

  // Auto-sync followupDate avec une date détectée dans le brouillon — tant que
  // (a) le toggle est ON, (b) l'utilisateur n'a pas manuellement choisi/effacé.
  // Le filtre vacances/OOO est géré DANS detectDateFromBody (FollowupDatePicker.tsx).
  useEffect(() => {
    if (!autoReminderOnCommitment) return;
    if (followupOverrideRef.current) return;
    const detected = detectDateFromBody(draftBody);
    setFollowupDate(prev => {
      const nextTime = detected?.date.getTime() ?? null;
      const prevTime = prev?.getTime() ?? null;
      if (prevTime === nextTime) return prev;
      return detected?.date ?? null;
    });
  }, [draftBody, autoReminderOnCommitment]);

  // Snippets
  const {
    snippets,
    sharedSnippets,
    loading: snippetsLoading,
    createSnippet,
    trackSnippetUsage,
  } = useSnippets();
  const { html: rawAccountSignatureHtml, text: rawAccountSignatureText } = useAccountSignature(ownEmail);
  // BUG-P3-002 : la signature vient de l'API backend sans sanitisation côté frontend.
  // DOMPurify élimine tout vecteur XSS potentiel avant le rendu via dangerouslySetInnerHTML.
  const accountSignatureHtml = useMemo(() => {
    if (!rawAccountSignatureHtml) return null;
    const clean = DOMPurify.sanitize(rawAccountSignatureHtml, { USE_PROFILES: { html: true } });
    // Strip any border-top/padding-top inline styles that render a divider line above the signature
    return clean
      .replace(/border-top\s*:[^;"]*/gi, 'border-top:none')
      .replace(/padding-top\s*:\s*[^;"]*/gi, 'padding-top:0');
  }, [rawAccountSignatureHtml]);
  const signatureContactEmail = currentReplyType === 'forward' ? '' : (email.sender || '').trim().toLowerCase();
  const [contactSignatureText, setContactSignatureText] = useState<string | null>(null);
  const [signatureEditorOpen, setSignatureEditorOpen] = useState(false);
  const [signatureDraft, setSignatureDraft] = useState('');
  const [signatureSaving, setSignatureSaving] = useState(false);
  const contactSignatureDisplay = (contactSignatureText || '').trim();
  const hasContactSignatureOverride = contactSignatureDisplay.length > 0;

  useEffect(() => {
    let cancelled = false;
    setContactSignatureText(null);
    setSignatureEditorOpen(false);
    setSignatureDraft('');

    if (!signatureContactEmail) return () => { cancelled = true; };

    apiClient.getContactStyle(signatureContactEmail)
      .then((style) => {
        if (cancelled) return;
        setContactSignatureText((style.preferred_signature || '').trim() || null);
      })
      .catch(() => {
        if (!cancelled) setContactSignatureText(null);
      });

    return () => { cancelled = true; };
  }, [signatureContactEmail]);

  const openSignatureEditor = useCallback(() => {
    setSignatureDraft(contactSignatureDisplay || rawAccountSignatureText || '');
    setSignatureEditorOpen(true);
  }, [contactSignatureDisplay, rawAccountSignatureText]);

  const signatureClickable = !signatureEditorOpen && Boolean(signatureContactEmail);

  const handleSignatureClick = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
    // Laisser vivre les liens contenus dans la signature et la sélection de texte.
    if ((event.target as HTMLElement).closest('a')) return;
    if (window.getSelection()?.toString()) return;
    openSignatureEditor();
  }, [openSignatureEditor]);

  const handleSignatureKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      openSignatureEditor();
    }
  }, [openSignatureEditor]);

  // Chips de bascule — bibliothèque de signatures du compte d'envoi,
  // chargée seulement à l'ouverture de l'éditeur inline.
  const signatureLibrary = useSignatureLibrary(signatureEditorOpen, ownEmail);

  const saveContactSignature = useCallback(async () => {
    if (!signatureContactEmail) return;
    const next = signatureDraft.trim();
    setSignatureSaving(true);
    try {
      await apiClient.updateContactSignature(signatureContactEmail, next || null);
      setContactSignatureText(next || null);
      setSignatureEditorOpen(false);
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: {
          message: next
            ? t('contact_signature_saved')
            : t('contact_signature_reset'),
          type: 'success',
          duration: 3500,
        },
      }));
    } catch {
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: {
          message: t('contact_signature_save_error'),
          type: 'error',
          duration: 5000,
        },
      }));
    } finally {
      setSignatureSaving(false);
    }
  }, [signatureContactEmail, signatureDraft, t]);
  // Track latest draft body in a ref so the unmount cleanup always has the current value
  const draftBodyRef = useRef(draftBody);
  draftBodyRef.current = draftBody;
  const generationSourceBodyRef = useRef('');
  // Audit 2026-05-11 F-09: snapshot draftId in a ref so the Ctrl+G recovery
  // path (which clears draftId optimistically) can restore it on AI failure
  // without re-registering the keydown listener.
  const draftIdRef = useRef(draftId);
  draftIdRef.current = draftId;
  const onDraftGeneratedRef = useRef(onDraftGenerated);
  onDraftGeneratedRef.current = onDraftGenerated;
  const sentRef = useRef(false);
  const generationStartedRef = useRef(false);

  useEffect(() => {
    generationStartedRef.current = false;
  }, [email.id]);

  // Auto-save draft on unmount (covers: X button, backdrop click, Escape, navigation)
  useEffect(() => {
    return () => {
      if (sentRef.current) return; // Don't save if we just sent
      if (draftIdRef.current) {
        deleteReplyDraftForEmail(email.id);
        return;
      }
      const body = draftBodyRef.current;
      if (hasContent({ body })) {
        saveReplyDraft({
          emailId: email.id,
          emailSubject: email.subject,
          emailSender: email.sender,
          body,
        });
      }
    };
  }, [email.id, email.subject, email.sender]);

  const isForward = currentReplyType === 'forward';
  const subjectPrefix = isForward ? 'Fwd' : 'Re';
  // Strip existing Re:/Fwd: prefixes to avoid "Fwd: Re: Re: ..."
  const cleanSubject = email.subject?.replace(/^(?:Re|Fwd|Fw|Tr)\s*:\s*/gi, '').trim() || '';

  // Restore saved reply draft on mount, or pre-fill forwarded content,
  // or show pre-generated AI draft (speculative prefetch).
  // Skip when caller provides prefillBody or autoGeneratePrompt — those take priority.
  useEffect(() => {
    if (prefillBody || autoGeneratePrompt) return;

    if (isForward) {
      const fwdDate = email.received_at
        ? formatFullDateLong(email.received_at, i18n.language)
        : '';
      const fromDisplay = email.sender_name
        ? `${email.sender_name} &lt;${email.sender}&gt;`
        : (email.sender || '');
      const fwdHeader =
        `<p><br></p><p><br></p>` +
        `<p>---------- Forwarded message ----------</p>` +
        `<p><b>From:</b> ${fromDisplay}</p>` +
        `<p><b>Date:</b> ${fwdDate}</p>` +
        `<p><b>Subject:</b> ${email.subject || ''}</p>` +
        `<p><br></p>`;

      let bodyHtml: string;
      if (isHtmlContent(email.body || '')) {
        bodyHtml = (email.body || '')
          .replace(/<head[^>]*>[\s\S]*?<\/head>/gi, '')
          .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, '')
          .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '')
          .replace(/<html[^>]*>/gi, '')
          .replace(/<\/html>/gi, '')
          .replace(/<body[^>]*>/gi, '')
          .replace(/<\/body>/gi, '')
          .trim();
      } else {
        bodyHtml = (email.body || '')
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/\n/g, '<br>');
      }

      setDraftBody(fwdHeader + DOMPurify.sanitize(bodyHtml));
      setState('editing');
      return;
    }

    // 1. Check local saved draft
    const savedDraft = getReplyDraftForEmail(email.id);
    if (savedDraft && savedDraft.body) {
      // Strip all embedded signatures — the injection effect will add one clean copy
      setDraftBody(stripEmbeddedSignature(savedDraft.body));
      setState('editing');
      return;
    }

    // 2. Check for an existing contextual AI draft.
    // Load an existing contextual draft if one was already generated for this email.
    let cancelled = false;
    apiClient.getPendingDraftByEmailId(email.id).then((existing) => {
      if (cancelled || generationStartedRef.current) return;
      if (existing && existing.draft_body) {
        setDraftBody(stripEmbeddedSignature(existing.draft_body));
        const existingDraftId = existing.id || null;
        draftIdRef.current = existingDraftId;
        setDraftId(existingDraftId);
        setState('editing');
      } else {
        // No saved draft, no speculative draft → let user write or use AI prompt
        setState('editing');
      }
    }).catch(err => {
      if (cancelled || generationStartedRef.current) return;
      // Audit Cluster D (2026-05-11) toast site 10: previously console.error
      // only. If the fetch fails on a real network outage, the user gets
      // an empty editor and can double-write a draft that already exists
      // server-side. Warn them so they know to verify before re-typing.
      console.error('[ReplyComposer] fetch existing draft failed:', err);
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: {
          message: tCommon('toasts.draft_load_failed'),
          type: 'warning',
          duration: 7000,
        },
      }));
      // API error → let user write or use AI prompt
      setState('editing');
    });

    return () => { cancelled = true; };
  }, [email.id, isForward, prefillBody, autoGeneratePrompt]);

  // Handle prefillBody (from SmartReply chips) — set editor content directly
  useEffect(() => {
    if (prefillBody && !isForward) {
      setDraftBody(prefillBody);
      setState('editing');
    }
  }, [prefillBody, isForward]);

  // Initialize To field with default recipient + subject
  useEffect(() => {
    if (!isForward) {
      if (currentReplyType === 'reply_all') {
        setTo(buildReplyAllRecipients(email, ownEmail).to.join(', '));
      } else {
        const picked = pickReplyRecipient(email.sender, email.to, ownEmail);
        setTo(withSenderDisplayName(picked, email.sender, email.sender_name));
      }
    }
    setSubject(`${subjectPrefix}: ${cleanSubject}`);
  }, [email.sender, email.sender_name, email.to, email.cc, currentReplyType, isForward, ownEmail, subjectPrefix, cleanSubject]);

  const getRecipients = useCallback(() => {
    if (isForward) {
      return forwardTo.trim() ? forwardTo.split(',').map(s => s.trim()).filter(Boolean) : [];
    }
    // Parse from the editable To field
    return to.trim() ? to.split(',').map(s => s.trim()).filter(Boolean) : [];
  }, [to, isForward, forwardTo]);

  const getCcRecipients = useCallback(() => {
    if (currentReplyType === 'reply_all') {
      return buildReplyAllRecipients(email, ownEmail).cc;
    }
    return [];
  }, [email.sender, email.to, email.cc, ownEmail, currentReplyType]);

  // Pre-populate CC for reply_all from original email
  useEffect(() => {
    const initialCc = getCcRecipients();
    if (initialCc.length > 0) {
      setCc(initialCc.join(', '));
      setShowCc(true);
    }
  }, [getCcRecipients]);

  // Subscribe to streaming draft chunks for progressive display
  useEffect(() => {
    if (state !== 'generating') return;

    const unsub = subscribeDraftStream((streamState) => {
      if (streamState.emailId !== email.id) return;
      // Narration state (stage, versionIndex, critique, crossfade) is handled
      // by `useDraftStream` — this listener only owns the reply-specific
      // side-effects: mirror accumulated text into draftBody, then on
      // completion fetch the full pipeline info for the disclosure panel.
      if (streamState.accumulatedText) {
        setDraftBody(preserveInlineImages(generationSourceBodyRef.current, stripEmbeddedSignature(streamState.accumulatedText)));
      } else if (streamState.expectsNewVersion) {
        // Critic rejected V1 → clear the editor so the V1 text does not linger
        // while the V2 is being re-drafted (fixes the flash V1 → V2 replacement).
        setDraftBody('');
      }
      if (streamState.isComplete) {
        // Snapshot critique info now — read directly from the stream rather
        // than from `streamView` to avoid a one-render lag during completion.
        const liveCritique = streamState.critique
          ? {
              score: streamState.critique.score,
              initialScore: streamState.initialCritiqueScore,
              motive: streamState.critique.motive,
            }
          : null;
        // Fetch pipeline info for the "AI Process" disclosure panel
        apiClient.getPendingDraftByEmailId(email.id).then((fullDraft) => {
          if (fullDraft) {
            draftIdRef.current = fullDraft.id || null;
            setDraftId(fullDraft.id || null);
            setPipelineInfo(buildPipelineInfo(fullDraft, liveCritique));
            onDraftGeneratedRef.current?.();
          }
        }).catch(() => { /* pipeline info is optional */ });
        setState('editing');
      }
    });

    // Polling fallback: if WebSocket events are missed, poll pending-drafts API.
    // Poll at 5s, 10s, 20s, 40s intervals (exponential backoff).
    // Uses a cancelled flag to avoid acting after the effect is cleaned up.
    let cancelled = false;

    const pollStartedAt = Date.now();

    const schedulePoll = (delayMs: number) => {
      return setTimeout(async () => {
        if (cancelled) return;
        try {
          const pending = await apiClient.getPendingDraftByEmailId(email.id);
          if (cancelled) return;
          if (pending?.draft_body) {
            draftIdRef.current = pending.id || null;
            setDraftId(pending.id || null);
            setDraftBody(preserveInlineImages(generationSourceBodyRef.current, stripEmbeddedSignature(pending.draft_body)));
            try {
              const liveSnap = getDraftStreamState(email.id);
              setPipelineInfo(buildPipelineInfo(pending, liveSnap?.critique
                ? { score: liveSnap.critique.score, initialScore: liveSnap.initialCritiqueScore, motive: liveSnap.critique.motive }
                : null));
            } catch { /* optional */ }
            setState('editing');
            onDraftGeneratedRef.current?.();
            return; // Done — no more polling
          }
        } catch { /* draft not ready yet */ }
        const remainingWaitMs = getRemainingDraftReadyPollWait(pollStartedAt, Date.now());
        const nextDelayMs = Math.min(getNextDraftReadyPollDelay(delayMs), remainingWaitMs);
        if (!cancelled && nextDelayMs > 0) {
          timers.push(schedulePoll(nextDelayMs));
        } else if (!cancelled) {
          // Maximum wait exceeded — backend did not produce a draft.
          // Reset the UI instead of staying stuck on "generating" indefinitely.
          setError(t('err_generation_timeout'));
          setState(draftBody ? 'editing' : 'idle');
        }
      }, delayMs);
    };

    const timers: ReturnType<typeof setTimeout>[] = [];
    timers.push(schedulePoll(DRAFT_READY_POLL_INITIAL_DELAY_MS));

    // Listen for processing_error events dispatched via WebSocket
    const handleLLMError = (e: Event) => {
      if (cancelled) return;
      const detail = (e as CustomEvent).detail;
      const errorMsg = detail?.error || 'Unknown error';
      // Model/auth/config errors are backend-side in our managed setup — there's
      // nothing for the user to configure, so show a plain retry message rather
      // than pointing them at a settings section to "configure their API key".
      const isModelError = /api.key|model|anthropic|unauthorized|401|config/i.test(errorMsg);
      setError(isModelError
        ? t('err_ai_unavailable')
        : `AI Error: ${errorMsg}`);
      setState(draftBody ? 'editing' : 'idle');
    };
    window.addEventListener('llm:error', handleLLMError);

    return () => {
      cancelled = true;
      unsub();
      timers.forEach(t => clearTimeout(t));
      window.removeEventListener('llm:error', handleLLMError);
    };
  }, [state, email.id, draftBody]);

  const handleAIGenerate = useCallback(
    async (text?: string) => {
      if (aiLocked) {
        showPaidAiBlocked();
        return;
      }
      const defaultPrompt = isForward
        ? 'Write a short introduction message to forward this email (e.g. for your information, I am forwarding this email...)'
        : 'Reply appropriately to this email. Only mention what is in the email. If dates, times, availability, or commitments are missing, do not invent them; say you will check and come back.';
      const prompt = (text || '').trim() || defaultPrompt;

      generationSourceBodyRef.current = draftBodyRef.current;
      generationStartedRef.current = true;
      setState('generating');
      clearDraftStreamState(email.id); // Clear stale stream cache from any previous generation
      setError(null);
      // Narration state reset (stage/versionIndex/critique/crossfade) is
      // handled by `useDraftStream` — it re-initializes on each active cycle
      // because `state === 'generating'` toggles false→true here.

      try {
        // Start generation — streaming chunks arrive via WebSocket
        const response: GenerateDraftResponse = await generateDraft(email.id, {
          instructions: prompt,
          reply_type: currentReplyType === 'forward' ? undefined : currentReplyType,
          cached_email: cachedDraftEmailContext ?? undefined,
        });

        if (!isMountedRef.current) return;

        if (response.success && response.draft_id) {
          draftIdRef.current = response.draft_id;
          setDraftId(response.draft_id);

          // Check if streaming already delivered the draft
          const streamState = getDraftStreamState(email.id);
          if (streamState?.isComplete && streamState.accumulatedText) {
            setDraftBody(preserveInlineImages(generationSourceBodyRef.current, stripEmbeddedSignature(streamState.accumulatedText)));
          } else {
            // Fallback: fetch full draft from API (streaming may still be in flight).
            // Guard against an empty `draft_body` — backend post-LLM cleanup can
            // occasionally strip a draft down to nothing, and overwriting the
            // editor with "" right after streaming already displayed valid text
            // erases the user-visible draft (user-reported 2026-05-13).
            try {
              const fullDraft = await apiClient.getPendingDraft(response.draft_id);
              if (!isMountedRef.current) return;
              if (fullDraft.draft_body) {
                setDraftBody(preserveInlineImages(generationSourceBodyRef.current, stripEmbeddedSignature(fullDraft.draft_body)));
              }
            } catch { /* streaming already set the body, or draft not yet persisted — ignore */ }
          }

          // Store pipeline details for the disclosure panel (merge live critique snapshot)
          try {
            const fullDraft = await apiClient.getPendingDraft(response.draft_id);
            if (!isMountedRef.current) return;
            const liveSnap = getDraftStreamState(email.id);
            setPipelineInfo(buildPipelineInfo(fullDraft, liveSnap?.critique
              ? { score: liveSnap.critique.score, initialScore: liveSnap.initialCritiqueScore, motive: liveSnap.critique.motive }
              : null));
          } catch { /* pipeline info is optional */ }

          setState('editing');
          onDraftGeneratedRef.current?.();
        } else if (response.success) {
          // 202 Accepted — async generation, WebSocket will deliver the result
          // Stay in 'generating' state; the WebSocket listener will set 'editing'.
          // Also perform a quick fallback check: local/dev backends often persist
          // the draft before the first 5s polling tick, and missing WS delivery
          // would otherwise leave the composer looking stuck.
          window.setTimeout(() => {
            apiClient.getPendingDraftByEmailId(email.id).then((pending) => {
              if (!isMountedRef.current || !pending?.draft_body) return;
              draftIdRef.current = pending.id || null;
              setDraftId(pending.id || null);
              setDraftBody(preserveInlineImages(generationSourceBodyRef.current, stripEmbeddedSignature(pending.draft_body)));
              try {
                const liveSnap = getDraftStreamState(email.id);
                setPipelineInfo(buildPipelineInfo(pending, liveSnap?.critique
                  ? { score: liveSnap.critique.score, initialScore: liveSnap.initialCritiqueScore, motive: liveSnap.critique.motive }
                  : null));
              } catch { /* optional */ }
              setState('editing');
              onDraftGeneratedRef.current?.();
            }).catch(() => { /* regular polling continues */ });
          }, 1500);
        } else {
          throw new Error('Failed to generate draft');
        }
      } catch (err) {
        const raw = err instanceof Error ? err.message : 'Error during generation';
        const message =
          raw === 'Failed to fetch'
            ? 'Backend unreachable — make sure the server is running (python run_api.py)'
            : raw === 'EMAIL_NOT_FOUND'
              ? t('email_not_found')
              : raw;
        setError(message);
        setState(draftBody ? 'editing' : 'idle');
      }
    },
    [email.id, currentReplyType, cachedDraftEmailContext, draftBody, aiLocked, showPaidAiBlocked]
  );

  // Refine an existing draft via the backend critique pipeline
  const handleRefine = useCallback(
    async (instruction: string) => {
      if (!instruction.trim()) {
        handleAIGenerate();
        return;
      }

      // Expand mode (/idees): embed body as notes, generate from scratch
      const expandCmd = SLASH_COMMANDS.find(c => c.expand && c.instruction === instruction.trim());
      if (expandCmd && draftBody.trim()) {
        const notes = draftBody.trim();
        draftIdRef.current = null;
        setDraftId(null);
        handleAIGenerate(`Write a complete and professional reply by expanding these notes:\n\n${notes}`);
        return;
      }

      if (draftId) {
        // Use refineDraft API (real refinement with Critique pipeline)
        setState('generating');
        setError(null);
        try {
          const result = await apiClient.refineDraft(draftId, instruction.trim());
          if (result.refined_body) {
            setDraftBody(preserveInlineImages(draftBody, stripEmbeddedSignature(result.refined_body)));
          }
          setState('editing');
        } catch (err) {
          const raw = err instanceof Error ? err.message : 'Error during refinement';
          setError(raw === 'Failed to fetch' ? 'Backend unreachable — make sure the server is running (python run_api.py)' : raw);
          setState('editing');
        }
      } else if (draftBody.replace(/<[^>]*>/g, '').trim()) {
        // User wrote text manually — refine it via lightweight LLM call.
        // Strip TipTap HTML to plain text first (mirror NewMessageModal and the
        // specialty-expand path): feeding '<p>…</p>' to the model and to the
        // backend language/formality/closing detectors echoes tags and
        // mis-detects locale, producing a garbled or wrong-language draft.
        setState('generating');
        setError(null);
        try {
          const plain = draftBody.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
          const result = await apiClient.refineText(plain, instruction.trim(), email.id, email.sender, {
            senderName: email.sender_name ?? undefined,
            targetLanguage: refineTargetLanguage,
          });
          if (result.refined_text) {
            setDraftBody(preserveInlineImages(draftBody, result.refined_text));
          }
          setState('editing');
        } catch (err) {
          const raw = err instanceof Error ? err.message : 'Error during refinement';
          setError(raw === 'Failed to fetch' ? 'Backend unreachable — make sure the server is running (python run_api.py)' : raw);
          setState('editing');
        }
      } else {
        // No text at all — generate from scratch with the instruction
        handleAIGenerate(instruction);
      }
    },
    [draftId, draftBody, email.id, email.sender, email.sender_name, handleAIGenerate, refineTargetLanguage]
  );

  // Expand notes → email using the specialty-aware two-call flow.
  // Triggered by Ctrl+Shift+G. Calls /refine-text directly with use_specialty=true
  // and the parent email's subject so the backend can classify against active
  // specialties and inject the matching expert context into a Sonnet plan →
  // Haiku draft flow with a mandatory "---\nSources : …" footnote.
  const handleExpandWithSpecialty = useCallback(async () => {
    if (aiLocked) {
      showPaidAiBlocked();
      return;
    }
    const originalBody = draftBodyRef.current;
    const notes = originalBody.replace(/<[^>]*>/g, '').trim();
    if (!notes) {
      setSpecialtyMessage({
        type: 'info',
        text: t('err_notes_first'),
      });
      return;
    }
    setState('generating');
    setError(null);
    setSpecialtyInfo(null);
    setSpecialtyMessage(null);
    const instruction = `Write a complete and professional reply by expanding these notes:\n\n${notes}`;
    try {
      const result = await apiClient.refineText(
        notes,
        instruction,
        email.id,
        email.sender,
        {
          useSpecialty: true,
          subject: email.subject || undefined,
          senderName: email.sender_name ?? undefined,
          targetLanguage: refineTargetLanguage,
        }
      );
      if (result.refined_text?.trim()) {
        setDraftBody(preserveInlineImages(originalBody, result.refined_text.trim()));
      }
      if (result.specialty_info) {
        const info = result.specialty_info;
        if (isSpecialtyMatch(info)) {
          setSpecialtyInfo(info);
          if (info.warning === 'plan_empty_fallback' || info.warning === 'plan_failed_fallback') {
            setSpecialtyMessage({
              type: 'warning',
              text: t('err_specialty_degraded'),
            });
          }
        } else if (info.warning === 'no_active_specialty') {
          setSpecialtyMessage({
            type: 'warning',
            text: t('err_no_active_specialty'),
          });
        } else if (info.warning === 'specialty_unavailable') {
          setSpecialtyMessage({
            type: 'error',
            text: t('err_specialty_unavailable'),
          });
        } else if (info.warning === 'classification_error') {
          setSpecialtyMessage({
            type: 'error',
            text: t('err_classification_error'),
          });
        }
      }
      setState('editing');
    } catch (err) {
      const raw = err instanceof Error ? err.message : 'Error during expert refinement';
      if (/rate limit/i.test(raw)) {
        setSpecialtyMessage({
          type: 'warning',
          text: tCommon('toasts.expert_mode_rate_limited'),
        });
      } else {
        setError(raw === 'Failed to fetch'
          ? 'Backend unreachable — make sure the server is running (python run_api.py)'
          : raw);
      }
      setState('editing');
    }
  }, [email.id, email.sender, email.sender_name, email.subject, refineTargetLanguage, aiLocked, showPaidAiBlocked, t, tCommon]);

  // Handle autoGeneratePrompt (from SmartReply custom input) — trigger AI generation on mount
  const autoGenerateRef = useRef(false);
  useEffect(() => {
    if (autoGeneratePrompt && !autoGenerateRef.current) {
      autoGenerateRef.current = true;
      const timer = setTimeout(() => {
        handleAIGenerate(autoGeneratePrompt);
      }, 150);
      return () => clearTimeout(timer);
    }
  }, [autoGeneratePrompt, handleAIGenerate]);

  // ── AICommandMenu handlers ─────────────────────────────────────────────────
  const handleCommandFromMenu = useCallback((cmd: typeof SLASH_COMMANDS[number]) => {
    if (cmd.expand && draftBody.trim()) {
      const notes = draftBody.trim();
      draftIdRef.current = null;
      setDraftId(null);
      handleAIGenerate(`Write a complete and professional reply by expanding these notes:\n\n${notes}`);
      return;
    }
    if (cmd.group === 'Reply') {
      setDraftBody('');
      draftIdRef.current = null;
      setDraftId(null);
      handleAIGenerate(cmd.instruction);
      return;
    }
    handleRefine(cmd.instruction);
  }, [draftBody, handleAIGenerate, handleRefine]);

  const handleCustomPromptFromMenu = useCallback((prompt: string) => {
    const hasBody = !!draftBody.replace(/<[^>]*>/g, '').trim();
    if (hasBody) {
      handleRefine(prompt);
    } else {
      handleAIGenerate(prompt);
    }
  }, [draftBody, handleRefine, handleAIGenerate]);

  const handleMagicGenerate = useCallback(() => {
    const notes = draftBodyRef.current.replace(/<[^>]*>/g, '').trim();
    const snapshot = draftBodyRef.current;
    const prevDraftId = draftIdRef.current;
    if (notes) {
      draftIdRef.current = null;
      setDraftId(null);
      Promise.resolve(
        handleAIGenerate(`Write a complete and professional reply by expanding these notes:\n\n${notes}`),
      ).catch(() => {
        setDraftBody(snapshot);
        draftIdRef.current = prevDraftId;
        setDraftId(prevDraftId);
      });
    } else {
      handleAIGenerate();
    }
  }, [handleAIGenerate]);

  const [attachmentReminder, setAttachmentReminder] = useState<AttachmentDetectionResult | null>(null);

  const sendingRef = useRef(false);
  const isMountedRef = useRef(true);
  // Audit F-05 (2026-05-13 deep-audit pass): the post-send archive toast
  // is scheduled via setTimeout 1500ms after `doSend` runs. Without a
  // cancellable ref the timer survived component unmount, so a user
  // chaining `Esc + j + r` within 1.5s would see the previous email's
  // toast surface on top of the new composer. Track the handle and
  // clear it on unmount so the dispatch never fires post-teardown.
  const postSendToastTimerRef = useRef<number | null>(null);
  useEffect(() => {
    return () => {
      isMountedRef.current = false;
      if (postSendToastTimerRef.current !== null) {
        clearTimeout(postSendToastTimerRef.current);
        postSendToastTimerRef.current = null;
      }
    };
  }, []);

  const doSend = useCallback(async (explicitFollowupDate?: Date | null) => {
    if (!draftBody.replace(/<[^>]*>/g, '').trim()) return;
    if (sendingRef.current) return; // Guard against double-click race condition
    sendingRef.current = true;

    setState('sending');
    setError(null);

    try {
      // Convert attachments to base64
      let outgoingAttachments: OutgoingAttachment[] | undefined;
      if (attachments.length > 0) {
        outgoingAttachments = await Promise.all(
          attachments.map(async (a) => ({
            filename: a.name,
            data_base64: await fileToBase64(a.file),
            content_type: a.file.type || 'application/octet-stream',
          }))
        );
      }

      let finalDraftId = draftId;

      // Parse CC/BCC from comma-separated strings
      const ccList = cc.split(',').map(s => s.trim()).filter(Boolean);
      const bccList = bcc.split(',').map(s => s.trim()).filter(Boolean);

      if (!finalDraftId) {
        const toList = getRecipients();
        // Create draft + send in a single request (same provider instance)
        const response = await apiClient.createDraft(
          email.id,
          subject,
          draftBody,
          toList.length > 0 ? toList : undefined,
          ccList.length > 0 ? ccList : undefined,
          bccList.length > 0 ? bccList : undefined,
          outgoingAttachments,
          true, // send immediately
          true, // always archive after manual send
        );
        finalDraftId = response?.draft_id ?? '';
      } else {
        await apiClient.updatePendingDraft(finalDraftId, undefined, draftBody);
        await apiClient.validatePendingDraft(
          finalDraftId, true, undefined,
          ccList.length > 0 ? ccList : undefined,
          bccList.length > 0 ? bccList : undefined,
        );
      }

      sentRef.current = true;
      deleteReplyDraftForEmail(email.id);
      onDraftSaved?.();

      // Schedule follow-up reminder if configured
      const effectiveFollowupDate = explicitFollowupDate !== undefined ? explicitFollowupDate : followupDate;
      if (effectiveFollowupDate) {
        writeSnoozeEntry(email.id, effectiveFollowupDate, email.subject, 'followup', email.labels, email.sender, email.sender_name ?? undefined);
        const reminderDate = effectiveFollowupDate.toISOString();
        const tryReminder = (attempt: number) => {
          apiClient.createReminder(email.id, email.subject, reminderDate)
            .catch((err) => {
              if (attempt < 3) {
                setTimeout(() => tryReminder(attempt + 1), attempt * 1500);
              } else {
                console.warn('[ReplyComposer] createReminder failed after 3 retries:', err);
                window.dispatchEvent(new CustomEvent('reminder:create-failed', {
                  detail: { emailId: email.id, reminderDate, error: String(err) },
                }));
              }
            });
        };
        tryReminder(1);
      }

      // Trigger fly-away animation before closing
      setState('sent');

      // Audit 2026-05-13 (follow-up to 4e470354 "envoi immédiat"): the in-
      // composer checkmark already covers "Sent". The bottom-right toast is
      // reserved for the auto-archive — the composer animation can't signal
      // it because the archive happens after the composer closes. Format
      // mirrors the quickstep_fired toast (verb: subject + detail line) so
      // both auto-action sources read identically.
      const archivedEmailId = email.id;
      const subjectForToast = (email.subject || '').trim() || tInbox('qs_no_subject');
      if (postSendToastTimerRef.current !== null) {
        clearTimeout(postSendToastTimerRef.current);
      }
      postSendToastTimerRef.current = window.setTimeout(() => {
        postSendToastTimerRef.current = null;
        if (!isMountedRef.current) return;
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: {
            message: `${tInbox('qs_archived')}: ${subjectForToast}`,
            detail: tInbox('qs_detail_auto_after_reply'),
            type: 'success',
            duration: 5000,
            action: {
              label: tCommon('undo_label'),
              onClick: () => {
                apiClient.unarchiveEmail(archivedEmailId).catch((err) => {
                  console.warn('[ReplyComposer] undo archive failed:', err);
                });
              },
            },
          },
        }));
      }, 1500);

      setTimeout(() => {
        sendingRef.current = false;
        onSend(finalDraftId, draftBody);
      }, 1200);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Error while sending';
      setError(message);
      setState('editing');
      sendingRef.current = false;
    }
  }, [draftBody, draftId, email.id, email.subject, subject, onSend, onDraftSaved, getRecipients, cc, bcc, attachments, followupDate, tInbox, tCommon]);

  const doScheduleSend = useCallback(async (sendAtLocal: Date) => {
    const bodyHtml = (draftBody || '').trim();
    if (!bodyHtml || sendAtLocal.getTime() <= Date.now()) return;
    if (sendingRef.current) return;
    sendingRef.current = true;
    setState('sending');
    setError(null);

    try {
      let outgoingAttachments: OutgoingAttachment[] | undefined;
      if (attachments.length > 0) {
        outgoingAttachments = await Promise.all(
          attachments.map(async (a) => ({
            filename: a.name,
            data_base64: await fileToBase64(a.file),
            content_type: a.file.type || 'application/octet-stream',
          }))
        );
      }
      const ccList = cc.split(',').map(s => s.trim()).filter(Boolean);
      const bccList = bcc.split(',').map(s => s.trim()).filter(Boolean);
      const toList = getRecipients();

      await apiClient.scheduleEmail({
        to: toList.join(', '),
        cc: ccList.join(', '),
        bcc: bccList.join(', '),
        subject,
        body: bodyHtml,
        send_at: sendAtLocal.toISOString(),
        is_html: true,
        reply_to_id: email.id,
        thread_id: (email as { thread_id?: string }).thread_id,
        attachments: outgoingAttachments?.map(a => ({
          filename: a.filename,
          data: a.data_base64,
          content_type: a.content_type,
        })),
      });

      sentRef.current = true;
      deleteReplyDraftForEmail(email.id);
      onDraftSaved?.();
      setState('sent');
      setTimeout(() => {
        sendingRef.current = false;
        onSend(draftId || '', bodyHtml);
      }, 1200);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Erreur lors de la programmation de l'envoi";
      setError(message);
      setState('editing');
      sendingRef.current = false;
    }
  }, [draftBody, attachments, cc, bcc, subject, email, draftId, getRecipients, onDraftSaved, onSend]);

  // Audit 2026-05-11 LIVE-CTRL-ENTER-NOUNDO: 5s undo grace period before
  // the actual send fires. Ctrl+Enter is destructive (real email out, with
  // auto-archive). The grace banner gives the user a Gmail-style undo.
  // 2026-05-13: user requested immediate send. The 5s "Envoi dans 5 s…" grace
  // banner that used to cover this composer has been removed; handleSend now
  // calls doSend() synchronously. The forgotten-attachment check still gates
  // the call before it fires.

  const handleSend = useCallback(() => {
    // Audit 2026-05-20 BUG-Z003: Ctrl+Enter on an empty composer (after Ctrl+A/Delete)
    // used to fire silently — doSend() short-circuits on empty body but the user got
    // NO feedback (no toast, no validation). The email "send shortcut" also bypasses
    // the SendConfirmationModal entirely. Strip HTML + invisible whitespace BEFORE
    // doing anything destructive, and surface a toast so the user knows what happened.
    const stripped = (draftBody || '')
      .replace(/<br\s*\/?>/gi, ' ')
      .replace(/<[^>]*>/g, '')
      .replace(/\u00A0|\u200B/g, ' ')
      .trim();
    if (!stripped) {
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: {
          message: t('err_empty_body'),
          detail: t('err_empty_body_hint'),
          type: 'warning',
          duration: 4000,
        },
      }));
      return;
    }

    // Check for forgotten attachment before sending
    const detection = detectForgottenAttachment(draftBody, attachments.length > 0);
    if (detection.detected) {
      setAttachmentReminder(detection);
      return;
    }

    // Send always sends. A follow-up date already synced into state by the
    // explicit bell picker or the auto-reminder effect is picked up by doSend.
    // We do not open the date picker from Send itself: that made Send feel stuck.
    void doSend();
  }, [draftBody, attachments, doSend, t]);

  // handleCancelWithSave removed — draft auto-save handled elsewhere

  // Discard draft completely (trash button)
  const handleDiscard = useCallback(() => {
    sentRef.current = true; // Prevent auto-save on unmount
    setState('idle'); // Annule toute génération en cours
    clearImageError();
    deleteReplyDraftForEmail(email.id);
    onCancel(); // Fermeture immédiate pour UX instantanée

    const doDelete = async () => {
      let id = draftId;
      if (!id) {
        try {
          const d = await apiClient.getPendingDraftByEmailId(email.id);
          id = d?.id ?? null;
        } catch (err) {
          // Normal si le brouillon n'existe pas encore — 404 silencieux OK.
          console.debug('[ReplyComposer] lookup pending draft by email failed:', err);
        }
      }
      if (id) {
        try {
          await apiClient.deletePendingDraft(id);
        } catch (err) {
          // Le UI a déjà fermé le composer (optimiste). Si la DELETE prod échoue
          // le brouillon réapparaîtra au prochain refresh — on loggue pour le debug
          // mais on ne spam pas un toast d'erreur sur une action de "cancel".
          console.warn('[ReplyComposer] deletePendingDraft failed:', err);
        }
      }
      onDraftDiscarded?.(); // APRÈS le DELETE — pas de race condition
    };
    doDelete();
  }, [email.id, draftId, onCancel, onDraftDiscarded, clearImageError]);

  // Global keyboard shortcuts: Ctrl+Enter = send (same as NewMessageModal), W = AI generate, Ctrl+G = expand notes
  // NOTE: draftBody est lu via draftBodyRef (toujours à jour, ligne 331) et NON dans les deps.
  // Mettre draftBody dans les deps ré-enregistrerait le listener à chaque frappe → TipTap perd
  // le focus pendant la micro-pause cleanup/re-attach → Ctrl+G s'échappe vers le handler global.
  // handleSend lu via ref (handleSendRef) pour la même raison — deps de handleSend changent souvent.
  const handleSendRef = useRef(handleSend);
  handleSendRef.current = handleSend;
  useEffect(() => {
    // Audit 2026-05-11 F-03: Ctrl+Enter / Ctrl+G fired from ANY focused
    // input on the page (search bar, NewMessageModal, calendar popover…)
    // because the listener is on `window` capture-phase with no target
    // check. Scope the modifier shortcuts to the reply composer subtree.
    const isInsideReplyComposer = (target: EventTarget | null): boolean => {
      const el = target as HTMLElement | null;
      if (!el || typeof el.closest !== 'function') return false;
      return !!el.closest('[data-testid="reply-composer"], .reply-composer');
    };
    const handler = (e: KeyboardEvent) => {
      // Ctrl+Enter → envoyer le mail (cohérent avec NewMessageModal).
      // L'utilisateur a explicitement demandé que ce shortcut envoie au lieu de
      // re-déclencher le pipeline IA (qui reste accessible via W, Ctrl+G, ou le bouton).
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        if (!isInsideReplyComposer(e.target)) return;
        e.preventDefault();
        e.stopPropagation();
        handleSendRef.current();
        return;
      }
      // Ctrl+Shift+G → Rédiger AVEC expertise active (mode expert).
      // Doit être testé AVANT Ctrl+G plain, sinon Shift est ignoré.
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'g') {
        if (!isInsideReplyComposer(e.target)) return;
        e.preventDefault();
        e.stopPropagation();
        handleExpandWithSpecialty();
        return;
      }
      // Ctrl+G → rédiger / développer les notes
      // stopPropagation: évite que l'event remonte vers d'autres handlers globaux
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'g') {
        if (!isInsideReplyComposer(e.target)) return;
        e.preventDefault();
        e.stopPropagation();
        handleMagicGenerate();
        return;
      }
      // Ctrl+Shift+, → supprimer brouillon. Le ruban (App.tsx) annonce Ctrl+Shift+,
      // — l'ancien handler écoutait Ctrl+Shift+D, qui ne correspondait à rien.
      if (isDeleteDraftShortcut(e)) {
        e.preventDefault();
        handleDiscard();
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) return;
      const key = e.key.toLowerCase();
      if (key === 'w') {
        e.preventDefault();
        handleAIGenerate();
      }
    };
    window.addEventListener('keydown', handler, true);
    return () => window.removeEventListener('keydown', handler, true);
  // draftBody intentionnellement absent des deps — lu via draftBodyRef pour éviter le re-enregistrement

  }, [handleDiscard, handleAIGenerate, handleExpandWithSpecialty, handleMagicGenerate]);

  // ── Reply mode change handler (split button) ──────────────────────────
  const handleReplyModeChange = useCallback((mode: 'reply' | 'reply_all' | 'forward') => {
    const prevMode = currentReplyType;
    setCurrentReplyType(mode);
    setShowSendMenu(false);

    if (mode === 'reply_all') {
      const recipients = buildReplyAllRecipients(email, ownEmail);
      setTo(recipients.to.join(', '));
      setCc(recipients.cc.join(', '));
      setShowCc(recipients.cc.length > 0);
      if (prevMode === 'forward') {
        setForwardTo('');
      }
    } else if (mode === 'forward') {
      if (prevMode === 'reply_all') {
        setCc('');
        setShowCc(false);
      }
      setForwardTo('');
    } else {
      // Back to reply
      if (prevMode === 'reply_all') {
        setCc('');
        setShowCc(false);
      }
      if (prevMode === 'forward') {
        setForwardTo('');
      }
      setTo(withSenderDisplayName(
        pickReplyRecipient(email.sender, email.to, ownEmail),
        email.sender,
        email.sender_name,
      ));
    }
  }, [currentReplyType, email, ownEmail]);

  // Click-outside handler for send dropdown
  useEffect(() => {
    if (!showSendMenu) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (
        sendMenuRef.current && !sendMenuRef.current.contains(e.target as Node) &&
        sendChevronRef.current && !sendChevronRef.current.contains(e.target as Node)
      ) {
        setShowSendMenu(false);
      }
    };
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowSendMenu(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [showSendMenu]);

  // Position + click-outside handler for mode dropdown (portal)
  useEffect(() => {
    if (!showModeDropdown) return;
    const updatePos = () => {
      if (!modePillRef.current) return;
      const rect = modePillRef.current.getBoundingClientRect();
      setModeDropdownPos({ top: rect.bottom + 4, left: rect.left });
    };
    updatePos();
    window.addEventListener('scroll', updatePos, true);
    window.addEventListener('resize', updatePos);
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as Node;
      if (modeDropdownRef.current?.contains(target)) return;
      if (modeDropdownPortalRef.current?.contains(target)) return;
      setShowModeDropdown(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      window.removeEventListener('scroll', updatePos, true);
      window.removeEventListener('resize', updatePos);
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showModeDropdown]);

  // Composer field shortcuts via custom event from useAppShortcuts
  useEffect(() => {
    const handler = (e: Event) => {
      const { key } = (e as CustomEvent<{ key: string }>).detail;
      if (key === 's') {
        setShowSubject(v => { if (!v) setTimeout(() => subjectInputRef.current?.focus(), 50); return !v; });
      } else if (key === 'c') {
        setShowCc(true);
      } else if (key === 'b') {
        setShowBcc(true);
      } else if (key === 'o') {
        // Focus the To input
        const toInput = document.querySelector<HTMLInputElement>('.rc-recipient-row input');
        toInput?.focus();
      }
    };
    window.addEventListener('agentys:composer-field', handler);
    return () => window.removeEventListener('agentys:composer-field', handler);
  }, []);

  // R/A/F keyboard shortcuts for reply mode
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement;
      if (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable) return;
      const key = e.key.toLowerCase();
      if (key === 'r') {
        handleReplyModeChange('reply');
      } else if (key === 'a') {
        handleReplyModeChange('reply_all');
      } else if (key === 'f') {
        handleReplyModeChange('forward');
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [handleReplyModeChange]);

  // Drag handlers for recipient chips
  const handleChipDragStart = (email: string, sourceField: string) => {
    setDragState({ email, sourceField: sourceField as 'to' | 'cc' | 'bcc' })
    setShowCc(true)
    setShowBcc(true)
  }
  const handleChipDragEnd = () => {
    setDragState(null)
    setDragOverField(null)
    setShowCc(v => v && !cc.trim() ? false : v)
    setShowBcc(v => v && !bcc.trim() ? false : v)
  }
  const handleHideContact = useCallback((email: string) => {
    // Audit Cluster D (2026-05-11) toast site 5: log-only meant the contact
    // reappeared at the next refresh with no explanation.
    hideContact(email).catch(silentFailWithToast('hide-contact', {
      message: tCommon('toasts.contact_hide_failed'),
    }))
  }, [tCommon])
  const handleFieldDrop = (e: React.DragEvent, targetField: 'to' | 'cc' | 'bcc') => {
    e.preventDefault()
    if (!dragState || dragState.sourceField === targetField) { setDragOverField(null); return }
    const { email: dragEmail, sourceField } = dragState
    const removeEmail = (val: string) => val.split(',').map(s => s.trim()).filter(s => s && s.toLowerCase() !== dragEmail.toLowerCase()).join(', ')
    const addEmail = (val: string) => {
      const existing = val.split(',').map(s => s.trim()).filter(Boolean)
      if (existing.some(e => e.toLowerCase() === dragEmail.toLowerCase())) return val
      return [...existing, dragEmail].join(', ')
    }
    if (sourceField === 'to')  setTo(prev => removeEmail(prev))
    if (sourceField === 'cc')  setCc(prev => removeEmail(prev))
    if (sourceField === 'bcc') setBcc(prev => removeEmail(prev))
    if (targetField === 'to')  setTo(prev => addEmail(prev))
    if (targetField === 'cc')  setCc(prev => addEmail(prev))
    if (targetField === 'bcc') setBcc(prev => addEmail(prev))
    setDragState(null)
    setDragOverField(null)
  }

  // Snippet handlers
  const handleSnippetSelect = useCallback((snippet: Snippet) => {
    const senderEmail = email.sender || '';
    const emailPrefix = senderEmail.split('@')[0] || '';
    const nameParts = emailPrefix.split(/[._-]/).filter(Boolean);
    const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
    const firstName = nameParts.length > 0 ? capitalize(nameParts[0]) : '';
    const lastName = nameParts.length > 1 ? capitalize(nameParts[nameParts.length - 1]) : '';
    const fullName = nameParts.map(capitalize).join(' ');

    const variables: Record<string, string> = {
      first_name: firstName,
      last_name: lastName,
      full_name: fullName,
      date: formatDayMonthYear(new Date(), i18n.language, 'long'),
      time: new Date().toLocaleTimeString(i18n.language, { hour: '2-digit', minute: '2-digit' }),
    };

    const processedContent = replaceSnippetVariables(snippet.content, variables);
    const snippetHtml = snippetContentToInsertionHtml(processedContent);
    setDraftBody((prev) => {
      if (!prev || prev === '<p></p>') return snippetHtml;
      return snippetHtml + prev;
    });
    setState('editing');
    trackSnippetUsage(snippet);
    setShowSnippetSelector(false);
  }, [email.sender, trackSnippetUsage]);

  const handleCreateSnippet = useCallback(async (payload: CreateSnippetPayload) => {
    await createSnippet(payload);
  }, [createSnippet]);

  // Attachment handlers
  const MAX_TOTAL_SIZE = 25 * 1024 * 1024; // 25 MB

  const handleAttachClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const addFiles = useCallback((files: File[] | FileList) => {
    setAttachError(null);
    const newFiles = Array.from(files).map(f => ({ name: f.name, size: f.size, file: f }));
    setAttachments(prev => {
      const combined = [...prev, ...newFiles];
      const totalSize = combined.reduce((sum, a) => sum + a.size, 0);
      if (totalSize > MAX_TOTAL_SIZE) {
        setAttachError('The total size of attachments exceeds 25 MB');
        return prev;
      }
      return combined;
    });
  }, []);

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files) addFiles(files);
    e.target.value = '';
  }, [addFiles]);

  const { isDragging: isFileDragging, dropZoneProps: fileDropZoneProps } = useFileDrop({
    onDrop: addFiles,
  });

  const removeAttachment = useCallback((index: number) => {
    setAttachments(prev => prev.filter((_, i) => i !== index));
    setAttachError(null);
  }, []);

  const fileToBase64 = (file: File): Promise<string> =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result as string;
        // Strip "data:...;base64," prefix
        resolve(result.split(',')[1]);
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });

  const isGenerating = state === 'generating';
  const isSending = state === 'sending';
  const isSent = state === 'sent';

  // Strip HTML tags to check if the draft has real text content (TipTap wraps empty content in <p></p>)
  const isDraftEmpty = !draftBody.replace(/<[^>]*>/g, '').trim();


  return (
    <div className={`reply-composer${isSent ? ' rc-sent-flyaway' : ''}${isFileDragging ? ' rc-file-dragging' : ''}`} data-testid="reply-composer" {...fileDropZoneProps}>
      <FileDropOverlay visible={isFileDragging} />
      {/* First-time mic soft-ask: without this the reply mic button was a silent
          dead no-op (recording never started, no permission prompt). Mirrors
          NewMessageModal / PendingDraftDetail. */}
      <MicPermissionDialog open={softAskOpen} onConfirm={confirmSoftAsk} onCancel={dismissSoftAsk} />
      {/* 2026-05-13: removed the 5s "Envoi dans 5 s…" undo banner — user
          requested immediate send. handleSend now calls doSend() directly. */}
      {/* Success dispatch animation on send */}
      {isSent && (
        <div className="rc-sent-overlay">
          <div className="rc-sent-stage">
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
      {/* Draft meridian — thin gradient line separating thread from draft */}
      <div
        className={`rc-draft-label rc-draft-label--minimal agentys-meridian${isGenerating ? ' agentys-meridian--breathing' : ''}`}
        aria-hidden="true"
      />

      {/* Draft Card: recipients + subject */}
      <div className="rc-draft-card">
        <div
          className={`rc-recipient-row${dragOverField === 'to' ? ' drop-active' : ''}`}
          onDragOver={dragState ? (e) => { e.preventDefault(); setDragOverField('to') } : undefined}
          onDragLeave={dragState ? () => setDragOverField(null) : undefined}
          onDrop={dragState ? (e) => handleFieldDrop(e, 'to') : undefined}
        >
          <div className="draft-to-left">
            <div className="draft-mode-pill-wrapper" ref={modeDropdownRef}>
              <button
                ref={modePillRef}
                type="button"
                className={`draft-mode-pill ${currentReplyType === 'forward' ? 'forward' : currentReplyType === 'reply_all' ? 'reply-all' : 'reply'}`}
                onClick={() => setShowModeDropdown(v => !v)}
                aria-haspopup="menu"
                aria-expanded={showModeDropdown}
              >
                {currentReplyType === 'reply' && <svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" width="14" height="14"><path d="M6.5 3L2.5 7L6.5 11"/><path d="M2.5 7H10.5C12.1569 7 13.5 8.3431 13.5 10V13"/></svg>}
                {currentReplyType === 'reply_all' && <svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" width="14" height="14"><path d="M6.5 3L2.5 7L6.5 11"/><path d="M9.5 3L5.5 7L9.5 11"/><path d="M5.5 7H10.5C12.1569 7 13.5 8.3431 13.5 10V13"/></svg>}
                {currentReplyType === 'forward' && <svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" width="14" height="14"><path d="M9.5 3L13.5 7L9.5 11"/><path d="M13.5 7H5.5C3.8431 7 2.5 8.3431 2.5 10V13"/></svg>}
                <ChevronDownIcon className="draft-mode-pill-chevron" />
              </button>
              {showModeDropdown && modeDropdownPos && createPortal(
                <div ref={modeDropdownPortalRef} className="rc-send-dropdown draft-mode-dropdown draft-mode-dropdown--portal" role="menu"
                  style={{ position: 'fixed', top: modeDropdownPos.top, left: modeDropdownPos.left, bottom: 'auto', zIndex: 1100 }}>
                  <button type="button" className={`rc-send-dropdown-item${currentReplyType === 'reply' ? ' active' : ''}`} role="menuitem"
                    data-testid="reply-mode-reply"
                    onClick={() => { handleReplyModeChange('reply'); setShowModeDropdown(false); }}>
                    <span className="rc-send-dropdown-icon"><svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M6.5 3L2.5 7L6.5 11"/><path d="M2.5 7H10.5C12.1569 7 13.5 8.3431 13.5 10V13"/></svg></span>
                    <span className="rc-send-dropdown-text"><span className="rc-send-dropdown-label">{t('reply')}</span></span>
                    <span className="rc-send-dropdown-shortcut">R</span>
                    {currentReplyType === 'reply' && <span className="rc-send-dropdown-check" />}
                  </button>
                  <button type="button" className={`rc-send-dropdown-item${currentReplyType === 'reply_all' ? ' active' : ''}`} role="menuitem"
                    data-testid="reply-all-button"
                    onClick={() => { handleReplyModeChange('reply_all'); setShowModeDropdown(false); }}>
                    <span className="rc-send-dropdown-icon"><svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M6.5 3L2.5 7L6.5 11"/><path d="M9.5 3L5.5 7L9.5 11"/><path d="M5.5 7H10.5C12.1569 7 13.5 8.3431 13.5 10V13"/></svg></span>
                    <span className="rc-send-dropdown-text"><span className="rc-send-dropdown-label">{t('reply_all')}</span></span>
                    <span className="rc-send-dropdown-shortcut">A</span>
                    {currentReplyType === 'reply_all' && <span className="rc-send-dropdown-check" />}
                  </button>
                  <button type="button" className={`rc-send-dropdown-item${currentReplyType === 'forward' ? ' active' : ''}`} role="menuitem"
                    data-testid="reply-mode-forward"
                    onClick={() => { handleReplyModeChange('forward'); setShowModeDropdown(false); }}>
                    <span className="rc-send-dropdown-icon"><svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M9.5 3L13.5 7L9.5 11"/><path d="M13.5 7H5.5C3.8431 7 2.5 8.3431 2.5 10V13"/></svg></span>
                    <span className="rc-send-dropdown-text"><span className="rc-send-dropdown-label">{t('forward')}</span></span>
                    <span className="rc-send-dropdown-shortcut">F</span>
                    {currentReplyType === 'forward' && <span className="rc-send-dropdown-check" />}
                  </button>
                </div>,
                document.body
              )}
              {/* Hover tooltip with composer field shortcuts */}
              <div className="rc-shortcut-tooltip" role="tooltip" aria-hidden="true">
                <div className="rc-shortcut-tooltip-row"><span className="rc-shortcut-tooltip-label">{t('to')}</span><span className="rc-shortcut-tooltip-keys"><kbd>{navigator.platform?.includes('Mac') ? '⌘' : 'ctrl'}</kbd><kbd>shift</kbd><kbd>O</kbd></span></div>
                <div className="rc-shortcut-tooltip-row"><span className="rc-shortcut-tooltip-label">{t('cc_label')}</span><span className="rc-shortcut-tooltip-keys"><kbd>{navigator.platform?.includes('Mac') ? '⌘' : 'ctrl'}</kbd><kbd>shift</kbd><kbd>C</kbd></span></div>
                <div className="rc-shortcut-tooltip-row"><span className="rc-shortcut-tooltip-label">{t('bcc_label', 'Bcc')}</span><span className="rc-shortcut-tooltip-keys"><kbd>{navigator.platform?.includes('Mac') ? '⌘' : 'ctrl'}</kbd><kbd>shift</kbd><kbd>B</kbd></span></div>
                <div className="rc-shortcut-tooltip-row"><span className="rc-shortcut-tooltip-label">{t('subject', 'Objet')}</span><span className="rc-shortcut-tooltip-keys"><kbd>{navigator.platform?.includes('Mac') ? '⌘' : 'ctrl'}</kbd><kbd>shift</kbd><kbd>S</kbd></span></div>
              </div>
            </div>
          </div>
          <ContactAutocomplete
            value={currentReplyType === 'forward' ? forwardTo : to}
            onChange={currentReplyType === 'forward' ? setForwardTo : setTo}
            placeholder={t('to')}
            className="draft-to-input inline"
            fieldId="to"
            onChipDragStart={handleChipDragStart}
            onChipDragEnd={handleChipDragEnd}
            isDragActive={!!dragState}
            onHideContact={handleHideContact}
          />
          <div className="rc-cc-toggles">
            {!showCc && <button className="rc-cc-toggle-btn" onClick={() => setShowCc(true)} type="button">{t('cc_toggle')}</button>}
            {!showBcc && <button className="rc-cc-toggle-btn" onClick={() => setShowBcc(true)} type="button">{t('bcc_toggle')}</button>}
            {!showSubject && <button className="rc-cc-toggle-btn" onClick={() => { setShowSubject(true); setTimeout(() => subjectInputRef.current?.focus(), 50); }} type="button">{t('object_toggle')}</button>}
            {(pipelineInfo || isGenerating) && (
              <AIProcessButton
                active={showPipeline}
                disabled={isSending}
                onClick={() => setShowPipeline((v) => !v)}
              />
            )}
          </div>
        </div>
        {showCc && (
          <div
            className={`rc-cc-row${dragOverField === 'cc' ? ' drop-active' : ''}`}
            onDragOver={dragState ? (e) => { e.preventDefault(); setDragOverField('cc') } : undefined}
            onDragLeave={dragState ? () => setDragOverField(null) : undefined}
            onDrop={dragState ? (e) => handleFieldDrop(e, 'cc') : undefined}
          >
            <span className="rc-label">{t('cc_label')}</span>
            <ContactAutocomplete
              value={cc}
              onChange={setCc}
              placeholder={t('cc_placeholder')}
              fieldId="cc"
              onChipDragStart={handleChipDragStart}
              onChipDragEnd={handleChipDragEnd}
              isDragActive={!!dragState}
              onHideContact={handleHideContact}
            />
          </div>
        )}
        {showBcc && (
          <div
            className={`rc-cc-row${dragOverField === 'bcc' ? ' drop-active' : ''}`}
            onDragOver={dragState ? (e) => { e.preventDefault(); setDragOverField('bcc') } : undefined}
            onDragLeave={dragState ? () => setDragOverField(null) : undefined}
            onDrop={dragState ? (e) => handleFieldDrop(e, 'bcc') : undefined}
          >
            <span className="rc-label">{t('bcc_label')}</span>
            <ContactAutocomplete
              value={bcc}
              onChange={setBcc}
              placeholder={t('bcc_placeholder')}
              fieldId="bcc"
              onChipDragStart={handleChipDragStart}
              onChipDragEnd={handleChipDragEnd}
              isDragActive={!!dragState}
              onHideContact={handleHideContact}
            />
          </div>
        )}
        {showSubject && (
          <div className="rc-subject-row">
            <input
              ref={subjectInputRef}
              type="text"
              className="rc-subject-input"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder={t('subject_placeholder')}
              aria-label={t('subject_aria')}
              spellCheck={false}
            />
          </div>
        )}
      </div>

      {/* Editor Area */}
      <div className="rc-editor-area reply-composer-editor">
        {/* Whisper transcription — mic button is disabled while this runs,
            so a separate visual status above the editor is the clearest cue. */}
        <ThinkingIndicator
          visible={isTranscribing}
          label={t('transcribing')}
        />
        {isGenerating && (
          <ThoughtStream
            stageName={streamView.stageName}
            versionIndex={streamView.versionIndex}
            accumulatedText={draftBody}
            critique={streamView.critique || undefined}
            waitingForEmailBody={!cachedDraftEmailContext}
            isComplete={false}
          />
        )}
        {isGenerating ? (
          <div className="rc-editor-wrapper rc-editor-wrapper--streaming" key={`gen-${streamView.crossfadeKey}`}>
            <DraftEditor
              content={draftBody}
              onChange={() => {}}
              placeholder={t('generating_placeholder')}
              readOnly={true}
              hideWordCount
              hideToolbar
            />
          </div>
        ) : (
          /* `pointer-events: none` while recording or transcribing : prevents
             phantom click events (sensitive trackpads, voice-controlled mice,
             accidental clicks) from moving the caret mid-dictation. The mic
             button is in the toolbar below, outside this wrapper, so it stays
             clickable to stop recording. See NewMessageModal for the full
             rationale. */
          <div
            className="rc-editor-wrapper"
            style={{
              position: 'relative',
              pointerEvents: (isRecording || isTranscribing) ? 'none' : undefined,
            }}
          >
            {isDraftEmpty && !isSending && !isTranscribing && !isRecording && (
              <div className="rc-body-placeholder" aria-hidden="true">
                {t('notes_placeholder', { platform: navigator.platform?.includes('Mac') ? '⌘' : 'Ctrl' })}
              </div>
            )}
            <DraftEditor
              ref={editorRef}
              content={draftBody}
              onChange={setDraftBody}
              placeholder=""
              autoFocus={currentReplyType !== 'forward'}
              // Stay editable while recording/transcribing so the dictation
              // block cursor marks the insertion point and the transcript can
              // land there. Phantom taps are already blocked by the wrapper's
              // `pointer-events: none` above.
              readOnly={isSending}
              dictating={isRecording || isTranscribing}
              recording={isRecording}
              hideWordCount
              hideToolbar
            />
          </div>
        )}

        {/* Specialty expertise feedback (Ctrl+Shift+G) */}
        <SpecialtyBadge
          info={specialtyInfo}
          message={specialtyMessage}
          onDismiss={() => { setSpecialtyInfo(null); setSpecialtyMessage(null); }}
        />

        {/* Signature footer — outside TipTap, seamless with editor.
            Cliquer la signature ouvre l'éditeur per-contact (plus de bouton dédié). */}
        {(accountSignatureHtml || hasContactSignatureOverride || signatureEditorOpen) && state === 'editing' && (
          <div
            className={`rc-signature-footer${hasContactSignatureOverride ? ' rc-signature-footer--contact' : ''}${signatureClickable ? ' rc-signature-footer--clickable' : ''}`}
            style={{ fontFamily: fontFamilyCss, fontSize: fontSizeCss }}
            role={signatureClickable ? 'button' : undefined}
            tabIndex={signatureClickable ? 0 : undefined}
            onClick={signatureClickable ? handleSignatureClick : undefined}
            onKeyDown={signatureClickable ? handleSignatureKeyDown : undefined}
            title={signatureClickable ? t('edit_contact_signature') : undefined}
            aria-label={signatureClickable ? t('edit_contact_signature') : undefined}
          >
            {signatureEditorOpen ? (
              <div
                className="rc-signature-editor"
                // Tant que l'éditeur est ouvert, il possède Échap : les hôtes
                // (useAppShortcuts/EmailDetailModal, listeners capture) consultent
                // hasEscapeOwner() et s'abstiennent — voir utils/escapeOwner.ts.
                data-escape-owner=""
                onKeyDown={(event) => {
                  if (event.key === 'Escape' && !signatureSaving) {
                    event.stopPropagation();
                    setSignatureEditorOpen(false);
                  }
                }}
              >
                {signatureLibrary.length > 0 && (
                  <div className="rc-signature-chips" role="group" aria-label={t('signature_switch_aria')}>
                    {signatureLibrary.map(entry => (
                      <button
                        key={entry.id}
                        type="button"
                        className="rc-signature-chip"
                        data-testid="rc-signature-chip"
                        disabled={signatureSaving}
                        onClick={() => setSignatureDraft(entry.text || '')}
                      >
                        {entry.name}
                      </button>
                    ))}
                  </div>
                )}
                <textarea
                  className="rc-signature-textarea"
                  value={signatureDraft}
                  onChange={(event) => setSignatureDraft(event.target.value)}
                  rows={2}
                  spellCheck={false}
                  disabled={signatureSaving}
                  aria-label={t('signature_for_contact')}
                  // Focus à l'ouverture : sans lui, Échap part du body et
                  // n'atteint jamais le handler du conteneur (touche morte).
                  autoFocus
                />
                {/* Actions groupées en bas à droite : Annuler (fantôme) +
                    Enregistrer (accent). Ici le ✓ PERSISTE la signature pour ce
                    contact, d'où « Enregistrer » (et non « Appliquer »). */}
                <div className="rc-signature-actions">
                  <button
                    type="button"
                    className="rc-signature-action-btn"
                    onClick={() => setSignatureEditorOpen(false)}
                    disabled={signatureSaving}
                  >
                    {tCommon('cancel')}
                  </button>
                  <button
                    type="button"
                    className="rc-signature-action-btn rc-signature-action-btn--primary"
                    onClick={saveContactSignature}
                    disabled={signatureSaving}
                    aria-label={t('save_contact_signature')}
                  >
                    {signatureSaving ? tCommon('saving', 'Saving…') : tCommon('save')}
                  </button>
                </div>
              </div>
            ) : (
              <>
                {hasContactSignatureOverride ? (
                  <div className="rc-signature-text">{contactSignatureDisplay}</div>
                ) : accountSignatureHtml ? (
                  <div className="rc-signature-html" dangerouslySetInnerHTML={{ __html: accountSignatureHtml }} />
                ) : null}
              </>
            )}
          </div>
        )}
      </div>

      {/* Attachment cards */}
      {attachments.length > 0 && (
        <div className="rc-attachments">
          {attachments.map((att, index) => (
            <AttachmentCard
              key={`${att.name}-${index}`}
              file={att.file}
              name={att.name}
              size={att.size}
              onRemove={() => removeAttachment(index)}
              removeLabel={t('remove')}
            />
          ))}
        </div>
      )}
      {attachError && (
        <div className="rc-error" style={{ margin: '0 24px 8px' }} role="alert">
          <span className="rc-error-icon">!</span>
          <span>{attachError}</span>
        </div>
      )}


      {/* Pipeline Disclosure — Accordion cards of AI agent process */}
      {pipelineInfo && !isGenerating && showPipeline && (
        <PipelineDisclosure pipelineInfo={pipelineInfo} draftId={draftId || ''} />
      )}

      {/* Error */}
      {error && (
        <div id="rc-error-message" className="rc-error" role="alert" style={{ margin: '0 24px 8px' }}>
          <span className="rc-error-icon">!</span>
          <span>{error}</span>
        </div>
      )}

      {/* Action Bar */}
      <div className="rc-action-bar">
        <RecordingWaveform isRecording={isRecording} audioLevels={audioLevels} />
        <div className="rc-action-buttons">
          <SendButtonSplit
            onSend={handleSend}
            onSchedule={doScheduleSend}
            disabled={isDraftEmpty || (isForward && !forwardTo.trim()) || isGenerating}
            loading={isSending}
            label={isSent ? t('sent_excl') : isSending ? t('sending') : t('send')}
            sendTestId="reply-send-button"
            pillClassName={isSent ? 'rc-send-success' : ''}
          />
          {/* Sélecteur langue dictée — défaut = langue du destinataire (Settings → Training).
              Masqué en Free : la dictée est verrouillée, le picker n'a pas de sens. */}
          {!isRecording && !isTranscribing && !aiLocked && (
            <VoiceLanguageBadge
              language={voiceLanguage}
              onChange={setVoiceLanguage}
              disabled={isGenerating || isSending || !voiceDictationAllowed}
            />
          )}

          {/* Micro — la dictée (Whisper) est une fonctionnalité IA payante.
              En Free le bouton porte le cadenas et le clic ouvre le paywall. */}
          <button
            type="button"
            className={`rc-icon-btn nmm-mic-btn${isRecording ? ' nmm-mic-recording' : ''}`}
            onClick={handleMicClick}
            onMouseEnter={() => { if (voiceDictationAllowed) void prewarmMic() }}
            disabled={isTranscribing || isGenerating || isSending || (!voiceDictationAllowed && !isRecording)}
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
          {/* En Free le bouton reste cliquable (clic → message paywall +
              upsell, cf. handleAIGenerate) mais porte le même cadenas que la
              baguette IA. */}
          <button
            type="button"
            className="rc-icon-btn"
            onClick={handleMagicGenerate}
            disabled={isGenerating || isSending}
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
            commands={SLASH_COMMANDS}
            onCommandSelect={handleCommandFromMenu}
            onCustomSubmit={handleCustomPromptFromMenu}
            onDictate={handleMicClick}
            isRecording={false}
            isTranscribing={false}
            onStopRecording={handleMicClick}
            showDictateOption={false}
            dictationEnabled={voiceDictationAllowed}
            transcriptionError={transcriptionError}
            disabled={isGenerating || isSending || aiLocked}
            disabledReason={aiLocked ? paidAiMessage : undefined}
          />
          <button
            type="button"
            className="rc-icon-btn"
            title={t('attach_file')}
            aria-label={t('add_attachment_aria')}
            onClick={handleAttachClick}
            disabled={isSending || isGenerating}
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
            </svg>
          </button>
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            style={{ display: 'none' }}
            multiple
            aria-label={t('attach_files')}
          />

          <div className="rc-snippet-wrapper">
            <button
              ref={snippetBtnRef}
              type="button"
              className="rc-icon-btn"
              title={t('snippets')}
              aria-label={t('insert_snippet_aria')}
              onClick={() => setShowSnippetSelector(!showSnippetSelector)}
              disabled={isSending || isGenerating}
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
                setShowSnippetSelector(false);
                setShowSnippetEditor(true);
              }}
              anchorRef={snippetBtnRef as React.RefObject<HTMLElement>}
              loading={snippetsLoading}
            />
          </div>
          {/* Insert availability — same Superhuman-style picker as in NewMessageModal.
              `language` = threadLanguageHint (pin du picker sinon hint
              destinataire ; un choix explicite « Auto » du picker retombe
              volontairement sur le hint — assumé). Le STT, lui, reste en
              auto-détection (2026-06-11). */}
          <InsertAvailabilityButton
            disabled={isGenerating || isTranscribing || isSending}
            onInsert={(text) => {
              followupOverrideRef.current = true;
              setFollowupDate(null);
              editorRef.current?.insertText(text);
            }}
            language={threadLanguageHint ?? 'auto'}
          />

          {/* Follow-up bell — shows date inline when configured */}
          <button
            type="button"
            className={followupDate ? 'followup-date-chip' : 'rc-icon-btn'}
            title={followupDate ? t('cancel_reminder') : t('schedule_reminder')}
            aria-label={t('auto_reminder')}
            ref={followupBtnRef}
            disabled={isSending || isGenerating}
            onClick={(e) => {
              if (followupDate) {
                followupOverrideRef.current = true;
                setFollowupDate(null);
              } else {
                const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                setFollowupPickerPos({ x: rect.left, y: rect.bottom + 4, buttonTop: rect.top });
              }
            }}
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
              <path d="M13.73 21a2 2 0 0 1-3.46 0" />
            </svg>
            {followupDate && <span>{formatLongDateFromDate(followupDate, i18n.language)}</span>}
          </button>
          {followupPickerPos && (
            <FollowupDatePicker
              position={followupPickerPos}
              emailBody={(draftBody ?? email.body) ?? undefined}
              forceCalendar={followupPickerPos.forceCalendar}
              onSelect={(date) => {
                followupOverrideRef.current = true;
                setFollowupDate(date);
                setFollowupPickerPos(null);
              }}
              onClose={() => {
                setFollowupPickerPos(null);
              }}
            />
          )}
          <button
            type="button"
            className="rc-icon-btn"
            title={t('bullet_list')}
            aria-label={t('insert_bullet_list')}
            onMouseDown={(e) => { e.preventDefault(); editorRef.current?.toggleBulletList(); }}
            disabled={isSending || isGenerating}
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="9" y1="6" x2="20" y2="6" />
              <line x1="9" y1="12" x2="20" y2="12" />
              <line x1="9" y1="18" x2="20" y2="18" />
              <circle cx="4" cy="6" r="1.5" fill="currentColor" stroke="none" />
              <circle cx="4" cy="12" r="1.5" fill="currentColor" stroke="none" />
              <circle cx="4" cy="18" r="1.5" fill="currentColor" stroke="none" />
            </svg>
          </button>
        <div className="gmail-footer-right">
          <button
            type="button"
            className="rc-delete-btn icon-btn--delete"
            onClick={handleDiscard}
            disabled={isSending}
            title={t('delete_draft')}
            aria-label={t('delete_draft')}
          >
            <TrashIcon size={16} />
          </button>
        </div>
        </div>
      </div>

      {/* Snippet Editor Modal */}
      <SnippetEditor
        isOpen={showSnippetEditor}
        onClose={() => setShowSnippetEditor(false)}
        onSave={handleCreateSnippet}
      />

      {/* Forgotten attachment reminder */}
      {attachmentReminder && (
        <Suspense fallback={null}>
          <AttachmentReminderModal
            keyword={attachmentReminder.keyword}
            matchedText={attachmentReminder.matchedText}
            onAttach={() => {
              setAttachmentReminder(null);
              fileInputRef.current?.click();
              apiClient.recordFeature('attachment_reminder');
            }}
            onSendAnyway={() => {
              setAttachmentReminder(null);
              sendingRef.current = false; // Reset guard so doSend() can proceed
              doSend();
            }}
            onClose={() => setAttachmentReminder(null)}
          />
        </Suspense>
      )}
    </div>
  );
});
