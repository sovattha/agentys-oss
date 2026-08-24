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

import React, { Suspense, useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { lazyWithRetry as lazy } from '../utils/lazyWithRetry';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import i18n from '../i18n';
import { formatShortDate, formatFullDateWithTime, formatLongDateFromDate, formatDayMonthYear } from '../utils/dateFormat';
import { createPortal } from 'react-dom';
import { apiClient, type PendingDraft, type DraftVersion, type OutgoingAttachment } from '../services/api';
import { useAutoSave, type SaveStatus } from '../hooks/useAutoSave';
import { useComposeFontPrefs } from '../hooks/useComposeFontPrefs';
const EmailDetailModal = lazy(() => import('./EmailDetailModal').then(m => ({ default: m.EmailDetailModal })));
import { RegenerateModal } from './RegenerateModal';
import { DraftVersionHistory } from './DraftVersionHistory';
import { DraftComparisonView } from './DraftComparisonView';
import { SendConfirmationModal, shouldSkipSendConfirmation } from './SendConfirmationModal';
import { addApprovalAuditEntry, type ApprovalState } from '../types/approval';
import { usageLimitsService } from '../services/subscription';
import { useIsLimitReached } from './LimitReachedBanner';
import { EmailBodyContent } from './EmailDetailModal';
import { fetchEmailDetail } from '../api/emails';
import { cleanDraftBody } from '../utils/draftBody';
import { isDeleteDraftShortcut } from '../utils/keyboard';
import { playUISound } from '../services/uiSounds';
import { FollowupSuggestions } from './FollowupSuggestions';
import { FollowupDatePicker } from './FollowupDatePicker';
import { PipelineCard, PipelineConnector } from './pipeline/PipelineCards';
import { MemoryTracePanel } from './pipeline/MemoryTracePanel';
import { PipelineSummary } from './pipeline/PipelineSummary';
import { AIProcessButton } from './pipeline/AIProcessButton';
import type { MemoryTrace } from '../types/training';
import { LabelBadge } from './labels/LabelBadge';
import { CloseIcon, CheckIcon, TrashIcon, ChevronDownIcon, ChevronUpIcon, MagicDraftIcon } from './icons/ActionIcons';
import { ContactAutocomplete } from './compose/ContactAutocomplete';
import { SnippetSelector, SnippetEditor } from './snippets';
import { useSnippets } from '../hooks/useSnippets';
import { replaceSnippetVariables } from '../api/snippets';
import { AICommandMenu } from './compose/AICommandMenu';
import { SendButtonSplit } from './compose/SendButtonSplit';
import { RecordingWaveform } from './compose/RecordingWaveform';
import { MicPermissionDialog } from './compose/MicPermissionDialog';
import { useWhisperRecording } from '../hooks/useWhisperRecording';
import { useVoiceLanguage } from '../hooks/useVoiceLanguage';
import { useVoiceDictationAccess } from '../hooks/useVoiceDictationAccess';
import { useContactLanguages, extractEmails } from '../hooks/useContactLanguages';
import { VoiceLanguageBadge } from './compose/VoiceLanguageBadge';
import type { Snippet, CreateSnippetPayload } from '../types/snippets';
import { useAccountSignature } from '../hooks/useAccountSignature';
import { useSignatureLibrary } from '../hooks/useSignatureLibrary';
import { writeSnoozeEntry } from '../hooks/useSnooze';
import { AccountApprovalCard } from './AccountApprovalCard';
import './PendingDraftDetail.css';
import './reply/ReplyComposer.css'; // For rc-slash-menu + rc-action-bar styles
import './compose/NewMessageModal.css'; // For gmail-field + gmail-input styles
import { SLASH_COMMANDS, isBinaryQuestion } from '../utils/slash-commands';
import { ReceivedAttachments } from './attachments/ReceivedAttachments';
import { DraftEditor } from './DraftEditor';
import type { DraftEditorHandle } from './DraftEditor';

/** Fallback auto-reply instruction (overridden by i18n at runtime) */
const AUTO_REPLY_INSTRUCTION_FALLBACK = 'Reply appropriately to this email';

// Parité compose (2026-06-09) : helpers de normalisation du body partagés
// dans utils/draftBodyFormat (testés unitairement).
import {
  looksLikeHtmlBody,
  htmlBodyToPlainText,
  isBodyBlank,
  toHtmlEmailBody,
} from '../utils/draftBodyFormat';

// Identité d'avatar unifiée (2026-06-09) : initiales 2 lettres + couleur depuis
// LE canon Avatar.tsx — l'ancien hash local divergeait du chip destinataire
// (« A » vert dans l'en-tête vs « AS » rouge dans le chip pour le même contact).
import { getInitials as getAvatarInitials, generateColorFromString } from './Avatar';


// ─── Typing Reveal Hook ───────────────────────────────────────────────────
function useTypingReveal(text: string, enabled: boolean) {
  const [revealedCount, setRevealedCount] = useState(0);
  const [isComplete, setIsComplete] = useState(false);
  const hasPlayedRef = useRef<string | null>(null);
  const WORDS_PER_FRAME = 3; // ~167 renders instead of 1000 for 500-word draft

  const words = useMemo(() => {
    if (!text) return [];
    return text.split(/(\s+)/);
  }, [text]);

  useEffect(() => {
    if (!enabled || !text || hasPlayedRef.current === text) {
      if (hasPlayedRef.current === text || !text) {
        setRevealedCount(words.length);
        setIsComplete(true);
      }
      return;
    }
    hasPlayedRef.current = text;
    setRevealedCount(0);
    setIsComplete(false);
    let i = 0;
    let rafId: number;
    const step = () => {
      i = Math.min(i + WORDS_PER_FRAME, words.length);
      setRevealedCount(i);
      if (i >= words.length) {
        setIsComplete(true);
      } else {
        rafId = requestAnimationFrame(step);
      }
    };
    rafId = requestAnimationFrame(step);
    return () => cancelAnimationFrame(rafId);
  }, [text, enabled, words.length]);

  return { words, revealedCount, isComplete };
}

// ─── Diff Highlight: compute changed words between old and new text ──────
function computeDiffIndices(oldText: string, newText: string): Set<number> {
  const oldWords = oldText.split(/(\s+)/);
  const newWords = newText.split(/(\s+)/);
  const changed = new Set<number>();
  const maxLen = Math.max(oldWords.length, newWords.length);
  for (let i = 0; i < maxLen; i++) {
    if (oldWords[i] !== newWords[i]) {
      changed.add(i);
    }
  }
  return changed;
}

// ─── Send Success: particle spawner ──────────────────────────────────────
function spawnParticles(container: HTMLDivElement) {
  const colors = ['#0d9488', '#2dd4bf', '#5eead4', '#14b8a6', '#99f6e4'];
  for (let i = 0; i < 14; i++) {
    const p = document.createElement('div');
    p.className = 'send-particle';
    const angle = (Math.PI * 2 * i) / 14;
    const dist = 50 + Math.random() * 70;
    p.style.cssText = `
      left: 50%; top: 45%;
      width: ${4 + Math.random() * 4}px;
      height: ${4 + Math.random() * 4}px;
      background: ${colors[i % colors.length]};
      --tx: ${Math.cos(angle) * dist}px;
      --ty: ${Math.sin(angle) * dist}px;
    `;
    container.appendChild(p);
    setTimeout(() => p.classList.add('burst'), 30 + i * 15);
  }
}

// cleanDraftBody / stripHtmlTags moved to ../utils/draftBody (imported above)
// so the leading-only header strip can be unit-tested without loading this
// 2400-line component module.

// ─── Thread Context List (expandable conversation history) ────────────────
function ThreadContextList({ items, senderName }: { items: Array<{ sender: string; subject: string; date: string; body_preview?: string; body?: string }>; senderName?: string }) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  return (
    <div className="thread-context-list">
      {items.map((item, idx) => {
        const isExpanded = expandedIdx === idx;
        const bodyText = item.body_preview || item.body || '';
        const senderEmail = item.sender || '';
        const displayName = senderName || senderEmail.split('@')[0] || '';
        return (
          <div
            key={idx}
            className={`thread-context-item${isExpanded ? ' expanded' : ''}`}
            style={{ animationDelay: `${idx * 0.04}s` }}
            onClick={() => setExpandedIdx(isExpanded ? null : idx)}
          >
            <div className="thread-context-avatar">{getAvatarInitials(senderName || null, senderEmail)}</div>
            <div className="thread-context-item-content">
              <div className="thread-context-item-header">
                <div className="thread-context-sender-group">
                  <span className="thread-context-sender">{displayName}</span>
                  {senderEmail && <span className="thread-context-email">{senderEmail}</span>}
                </div>
                {item.date && (
                  <span className="thread-context-date" title={formatFullDateWithTime(item.date, i18n.language)}>
                    {formatShortDate(item.date, i18n.language)}
                  </span>
                )}
              </div>
              {item.subject && (
                <div className="thread-context-subject-line">{item.subject}</div>
              )}
              {!isExpanded && bodyText && (
                <div className="thread-context-preview">{bodyText}</div>
              )}
              {isExpanded && bodyText && (
                <div className="thread-context-body">{bodyText}</div>
              )}
            </div>
            <span className={`thread-context-chevron${isExpanded ? ' open' : ''}`}>
              <ChevronDownIcon size={12} />
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ─── Memoized Sub-Components ──────────────────────────────────────────────

// ── 1. DraftEmailZone: original email display (sender, body, nav arrows) ──

interface DraftEmailZoneProps {
  emailSubject: string;
  emailLabels: Array<{ name: string; color: string }>;
  emailDate: string | undefined;
  senderName: string | undefined;
  senderEmail: string;
  originalCc: string[];
  emailBodyHtml: string;
  emailId: string;
  emailAttachments: Array<{ id: string; filename: string; size: number; content_type: string }>;
  navInfo: { current: number; total: number; hasPrev: boolean; hasNext: boolean } | null;
  onNavigatePrev?: () => void;
  onNavigateNext?: () => void;
  onClose?: () => void;
  tCommon: (key: string, options?: Record<string, unknown>) => string;
}

const DraftEmailZone = React.memo(function DraftEmailZone({
  emailSubject,
  emailDate,
  senderName,
  senderEmail,
  originalCc,
  emailBodyHtml,
  emailId,
  emailAttachments,
  navInfo,
  onNavigatePrev,
  onNavigateNext,
  onClose,
  tCommon,
}: DraftEmailZoneProps) {
  return (
    <div className="pdd-email-zone">
      {/* 1. Collapsed Original Email + Nav Arrows */}
      <div
        className="original-email-collapsed expanded"
      >
        <div className="original-email-collapsed-info">
          <span className="original-email-collapsed-subject">
            {emailSubject}
          </span>
        </div>
        <div className="pdd-email-header-right" onClick={e => e.stopPropagation()}>
          {navInfo && (
            <div className="email-nav-arrows">
              <button
                className="email-nav-btn"
                onClick={onNavigatePrev}
                disabled={!navInfo.hasPrev}
                aria-label={tCommon('previous')}
                title={tCommon('previous')}
              >
                <ChevronUpIcon size={14} />
              </button>
              <button
                className="email-nav-btn"
                onClick={onNavigateNext}
                disabled={!navInfo.hasNext}
                aria-label={tCommon('next')}
                title={tCommon('next')}
              >
                <ChevronDownIcon size={14} />
              </button>
            </div>
          )}
          {/* Fermer — DANS la rangée, après les flèches (parité avec l'en-tête
              inbox). L'ancien bouton absolu chevauchait la flèche « Suivant »
              dès que la container query ≤600px réduisait le padding-right
              réservé (bug 2026-06-09). */}
          {onClose && (
            <button
              className="email-nav-btn pdd-header-close"
              onClick={onClose}
              aria-label={tCommon('close')}
              title={`${tCommon('close')} (Esc)`}
            >
              <CloseIcon size={16} />
            </button>
          )}
        </div>
      </div>

      {/* Original email body — always visible */}
      <div className="original-email-section">
          <div className="original-card-sender">
            <div className="thread-card-avatar" style={{ backgroundColor: generateColorFromString(senderEmail || senderName || ''), color: '#fff' }}>
              {getAvatarInitials(senderName || null, senderEmail || '')}
            </div>
            <span className="draft-card-recipient-name">{senderName || senderEmail}</span>
            {senderName && <span className="draft-card-recipient-email">&lt;{senderEmail}&gt;</span>}
            {emailDate && <span className="original-card-date">{formatFullDateWithTime(emailDate, i18n.language)}</span>}
          </div>

          {originalCc.length > 0 && (
            <div className="original-card-cc">
              <span className="draft-card-label">Cc</span>
              <span className="original-card-cc-list">{originalCc.join(', ')}</span>
            </div>
          )}
          {emailAttachments.length > 0 && (
            <ReceivedAttachments attachments={emailAttachments} emailId={emailId} />
          )}
          <div className="email-original-body-container">
            <EmailBodyContent body={emailBodyHtml} />
          </div>
        </div>

    </div>
  );
});

// ── 2. DraftPipelineCards: AI pipeline visualization (classification, drafter, critique) ──

interface DraftPipelineCardsProps {
  draft: PendingDraft;
  onDraftUpdated?: (draft: PendingDraft) => void;
  tDrafts: TFunction;
  tCompose: TFunction;
}

const DraftPipelineCards = React.memo(function DraftPipelineCards({
  draft,
  onDraftUpdated,
  tDrafts,
  tCompose,
}: DraftPipelineCardsProps) {
  // Classification color lookup (case-insensitive)
  const CLASSIFICATION_COLORS: Record<string, string> = {
    action: '#dc2626', fyi: '#3b82f6',
    noise: '#6b7280', unlabeled: '#9ca3af',
    urgent: '#dc2626', important: '#dc2626', normal: '#3b82f6',
    newsletter: '#6b7280', promo: '#6b7280', cc_only: '#9ca3af', spam: '#6b7280',
  };
  const classRaw = draft.classification || 'Unlabeled';
  const classColor = CLASSIFICATION_COLORS[classRaw.toLowerCase()] || '#9ca3af';
  const classDisplay = classRaw.charAt(0).toUpperCase() + classRaw.slice(1).toLowerCase();
  // BUG-G003 fix: normalize routing_tier — strip "TIER_" prefix, lowercase, map special values
  const rawTierValue = draft.routing_tier ? draft.routing_tier.toLowerCase().replace(/^tier_/, '') : '';
  const tierValue = (['simple', 'standard', 'complex'].includes(rawTierValue) && rawTierValue !== 'skip')
    ? rawTierValue
    : rawTierValue && rawTierValue !== 'skip' ? 'complex' : 'standard';
  const historyCount = draft.conversation_history?.length || draft.conversation_history_count || 0;
  const hasCritique = !!draft.critique;
  const wasRevised = draft.draft_v1 && draft.draft_body !== draft.draft_v1;

  return (
    <div className="pipeline-cards-section">
      {/* Card 1: Classification + Knowledge Inputs */}
      <PipelineCard stageKey="classification" title={tCompose('pipeline_classification')} index={0} defaultOpen agentId="classifier">
        <div className="pipe-overview">
          <div className="pipe-overview-row">
            <LabelBadge
              name={classDisplay}
              color={classColor}
              size="small"
            />
            <span className={`pipe-tier-badge tier-${tierValue}`}>
              {tierValue === 'simple' ? tCompose('tier_simple') : tierValue === 'standard' ? tCompose('tier_standard') : tCompose('tier_complex')}
            </span>
            {draft.specialty_info && (
              <span className="pipe-specialty-badge">
                <svg aria-hidden="true" width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" /></svg>
                {draft.specialty_info.specialty_name}
              </span>
            )}
          </div>
          {draft.classification_reason && (
            <p className="pipe-classification-reason">
              {draft.classification_reason}
            </p>
          )}
          <div className="pipe-inputs">
            {historyCount > 0 && (
              <span className="pipe-input-chip">
                <svg aria-hidden="true" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
                {historyCount} messages
              </span>
            )}
            <span className="pipe-input-chip">
              <svg aria-hidden="true" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>
              {tCompose('profile_chip')}
            </span>
            <span className="pipe-input-chip">
              <svg aria-hidden="true" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" /><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" /></svg>
              {tCompose('rules_chip')}
            </span>
            <span className="pipe-input-chip">
              <svg aria-hidden="true" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 1 1 7.072 0l-.548.547A3.374 3.374 0 0 0 14 18.469V19a2 2 0 1 1-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" /></svg>
              {tCompose('knowledge_chip')}
            </span>
          </div>
        </div>
      </PipelineCard>

      {/* Specialty card (Expert Mode) */}
      {draft.specialty_info && (
        <>
          <PipelineConnector />
          <PipelineCard stageKey="classification" title={tCompose('pipeline_expertise')} index={0}>
            <div className="pipe-overview">
              <div className="pipe-overview-row">
                <span className="pipe-specialty-name">{draft.specialty_info.specialty_name}</span>
                <span className="pipe-specialty-category">{draft.specialty_info.category?.replace(/_/g, ' ')}</span>
              </div>
              {draft.specialty_info.expert_names && draft.specialty_info.expert_names.length > 0 && (
                <div className="pipe-inputs">
                  {draft.specialty_info.expert_names.map((name: string, i: number) => (
                    <span key={i} className="pipe-input-chip pipe-input-chip--specialty">
                      <svg aria-hidden="true" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" /></svg>
                      {name}
                    </span>
                  ))}
                </div>
              )}
              {draft.specialty_info.risk_level === 'medium' && (
                <div className="pipe-specialty-warning pipe-specialty-warning--medium">
                  <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
                  </svg>
                  {tCompose('risk_medium')}
                </div>
              )}
              {draft.specialty_info.risk_level === 'high' && (
                <div className="pipe-specialty-warning pipe-specialty-warning--high">
                  <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
                  </svg>
                  {tCompose('risk_high')}
                </div>
              )}
            </div>
          </PipelineCard>
        </>
      )}

      {/* Account Approval Gate */}
      {draft.account_info && draft.account_info.status !== 'not_found' && (
        <>
          <PipelineConnector />
          <AccountApprovalCard
            draftId={draft.id}
            accountInfo={draft.account_info}
            onConfirmed={(updated, newDraftBody) => onDraftUpdated?.({ ...draft, account_info: updated, ...(newDraftBody ? { draft_body: newDraftBody } : {}) })}
            onRejected={(updated) => onDraftUpdated?.({ ...draft, account_info: updated })}
          />
        </>
      )}

      {/* Conversation Context (expandable, between Classification and Rédaction) */}
      {historyCount > 0 && (
        <>
          <PipelineConnector />
          <div className="thread-context-standalone">
            <div className="thread-context-header">
              <span className="thread-context-icon">
                <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
              </span>
              <span className="thread-context-title">{tCompose('conversation_context')}</span>
              <span className="thread-context-count-text">
                {historyCount} messages
              </span>
            </div>
            <div className="thread-context-body-area">
              {draft.conversation_history && draft.conversation_history.length > 0 ? (
                <ThreadContextList items={draft.conversation_history} senderName={draft.email_sender_name} />
              ) : (
                <span className="thread-context-empty">{tCompose('conversation_context_empty')}</span>
              )}
            </div>
          </div>
        </>
      )}

      {/* Card 2: Drafter v1 */}
      {draft.draft_v1 && (
        <>
          <PipelineConnector />
          <PipelineCard stageKey="redaction" title={tCompose('pipeline_drafting')} index={1} agentId="drafter">
            <pre>{draft.draft_v1}</pre>
          </PipelineCard>
        </>
      )}

      {/* Card 3: Critic */}
      {hasCritique && (
        <>
          <PipelineConnector />
          <PipelineCard
            stageKey="optimisation"
            title={tCompose('pipeline_critique')}
            badge={{
              label: (draft.critique ?? '').toLowerCase().includes('rejet') ? tDrafts('rejected') : tDrafts('approved'),
              variant: (draft.critique ?? '').toLowerCase().includes('rejet') ? 'rejected' : 'approved',
            }}
            index={2}
            agentId="critic"
          >
            <pre>{draft.critique}</pre>
          </PipelineCard>
        </>
      )}

      {/* Card 4: Post-treatment */}
      {(() => {
        const corrDetails = draft.correction_details;
        const corrCount = corrDetails?.length || (wasRevised ? 1 : 0);
        if (!corrCount) return null;
        return (
          <>
            <PipelineConnector />
            <PipelineCard
              stageKey="finalisation"
              title={tCompose('pipeline_post_processing')}
              badge={{
                label: tCompose(corrCount > 1 ? 'pipeline_corrections_other' : 'pipeline_corrections_one', { count: corrCount }),
                variant: 'corrected',
              }}
              index={3}
              agentId="postprocessor"
            >
              {corrDetails && corrDetails.length > 0 ? (
                <ul className="pipe-correction-list">
                  {corrDetails.map((c, i) => (
                    <li key={i} className="pipe-correction-item">
                      <CheckIcon size={10} />
                      {tCompose(`correction_${c}`, c)}
                    </li>
                  ))}
                </ul>
              ) : (
                <span className="pipe-card-corrections">
                  <CheckIcon size={12} />
                  {tCompose('applied_correction')}
                </span>
              )}
            </PipelineCard>
          </>
        );
      })()}
    </div>
  );
});

// ─── End Memoized Sub-Components ─────────────────────────────────────────

interface PendingDraftDetailProps {
  draft: PendingDraft;
  accountId?: number;
  onDraftUpdated?: (draft: PendingDraft) => void;
  onDraftValidated?: (draft: PendingDraft, gmailDraftId: string) => void;
  onDraftScheduled?: (draft: PendingDraft, scheduledId: string) => void;
  onDraftRejected?: (draft: PendingDraft) => void;
  onEmailClick?: (emailId: string) => void;
  onKnowledgeSuggestion?: (s: { question: string; answer: string; context: string }) => void;
  onClose?: () => void;
  navInfo?: { current: number; total: number; hasPrev: boolean; hasNext: boolean } | null;
  onNavigatePrev?: () => void;
  onNavigateNext?: () => void;
  /** Start with original email collapsed (used in Deep Focus) */
  initialEmailCollapsed?: boolean;
  /** Keyboard shortcut trigger for reply mode (R / A / F) */
  triggerReplyType?: 'reply' | 'reply_all' | 'forward' | null;
  onTriggerReplyHandled?: () => void;
  aiEnabled?: boolean;
  onUpgradeRequired?: () => void;
}


export const PendingDraftDetail = React.memo(function PendingDraftDetail({ draft, accountId: _accountId = 1, onDraftUpdated, onDraftValidated, onDraftScheduled, onDraftRejected, onEmailClick: _onEmailClick, onKnowledgeSuggestion, onClose, navInfo, onNavigatePrev, onNavigateNext, initialEmailCollapsed, triggerReplyType, onTriggerReplyHandled, aiEnabled = true, onUpgradeRequired, onComposerStateChange: _onComposerStateChange }: PendingDraftDetailProps & { onComposerStateChange?: (open: boolean) => void }) {
  const { t: tDrafts } = useTranslation('drafts');
  const { t: tCompose } = useTranslation('compose');
  const { t: tCommon, i18n } = useTranslation('common');
  const { t: tErrors } = useTranslation('errors');
  const AUTO_REPLY_INSTRUCTION = tCompose('default_instruction') || AUTO_REPLY_INSTRUCTION_FALLBACK;
  const [isEditing, setIsEditing] = useState(false);
  const [editedSubject, setEditedSubject] = useState(draft.draft_subject);
  // Skip pre-generated draft body for binary-question emails
  const _hasBinaryChips = useMemo(() => {
    const plain = (draft.email_body ?? '').replace(/<[^>]*>/g, '')
    return isBinaryQuestion(plain)
  }, [])
  const [editedBody, setEditedBody] = useState(_hasBinaryChips ? '' : (draft.draft_body ?? ''));
  // isSaving state removed (unused — auto-save handles saving)
  const [error, setError] = useState<string | null>(null);
  const aiLocked = aiEnabled === false;
  const paidAiMessage = tCompose('ai_paid_required', { defaultValue: 'Les brouillons IA sont réservés aux abonnements payants.' });
  const showPaidAiBlocked = useCallback(() => {
    setError(paidAiMessage);
    onUpgradeRequired?.();
  }, [onUpgradeRequired, paidAiMessage]);
  const [showPipeline, setShowPipeline] = useState(false);
  const [selectedEmailId, setSelectedEmailId] = useState<string | null>(null);
  const [isRefining, setIsRefining] = useState(false);
  // Parité compose : le body est édité dans le DraftEditor TipTap partagé.
  const editorRef = useRef<DraftEditorHandle>(null);
  const bodyEditorWrapRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const draftZoneRef = useRef<HTMLDivElement>(null);
  const [showJumpPill, setShowJumpPill] = useState(false);

  const [autoSaveStatus, setAutoSaveStatus] = useState<SaveStatus>('idle');
  // `id` inclus : le guard anti-écho de l'effet de sync ne doit JAMAIS matcher
  // un AUTRE draft (deux drouillons vides identiques se contamineraient).
  const lastSavedRef = useRef({ id: draft.id, subject: draft.draft_subject, body: draft.draft_body });

  // Attachments
  const [attachments, setAttachments] = useState<{name: string; size: number; file: File}[]>([]);
  const [attachError, setAttachError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const MAX_TOTAL_SIZE = 25 * 1024 * 1024; // 25 MB

  // Snippets
  const [showSnippetSelector, setShowSnippetSelector] = useState(false);
  const [showSnippetEditor, setShowSnippetEditor] = useState(false);
  const snippetBtnRef = useRef<HTMLButtonElement>(null);
  const {
    snippets,
    sharedSnippets,
    loading: snippetsLoading,
    createSnippet,
    trackSnippetUsage,
  } = useSnippets();
  const { text: signatureText } = useAccountSignature();
  const signatureContactEmail = (draft.email_sender || '').trim().toLowerCase();
  const [contactSignatureText, setContactSignatureText] = useState<string | null>(null);
  const [signatureEditorOpen, setSignatureEditorOpen] = useState(false);
  const [signatureDraft, setSignatureDraft] = useState('');
  const [signatureSaving, setSignatureSaving] = useState(false);
  const contactSignatureDisplay = (contactSignatureText || '').trim();
  const effectiveSignatureText = contactSignatureDisplay || signatureText;

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
    setSignatureDraft(contactSignatureDisplay || signatureText || '');
    setSignatureEditorOpen(true);
  }, [contactSignatureDisplay, signatureText]);

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

  // Chips de bascule — bibliothèque de signatures du compte courant,
  // chargée seulement à l'ouverture de l'éditeur inline.
  const signatureLibrary = useSignatureLibrary(signatureEditorOpen);

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
            ? tCompose('contact_signature_saved')
            : tCompose('contact_signature_reset'),
          type: 'success',
          duration: 3500,
        },
      }));
    } catch {
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: {
          message: tCompose('contact_signature_save_error'),
          type: 'error',
          duration: 5000,
        },
      }));
    } finally {
      setSignatureSaving(false);
    }
  }, [signatureContactEmail, signatureDraft, tCompose]);
  const signatureInjectedRef = useRef(false);
  // CC/BCC state
  const [originalCc, setOriginalCc] = useState<string[]>([]);
  const [originalTo, setOriginalTo] = useState<string[]>([]);
  const [emailAttachments, setEmailAttachments] = useState<Array<{ id: string; filename: string; size: number; content_type: string }>>([]);
  const [cc, setCc] = useState('');
  const [bcc, setBcc] = useState('');
  const [showCc, setShowCc] = useState(false);
  const [showBcc, setShowBcc] = useState(false);
  const [showSubject, setShowSubject] = useState(true);
  const subjectInputRef = useRef<HTMLInputElement>(null);
  const [dragState, setDragState] = useState<{ email: string; sourceField: 'to' | 'cc' | 'bcc' } | null>(null)
  const [dragOverField, setDragOverField] = useState<'to' | 'cc' | 'bcc' | null>(null)

  // Prefs de police compose : le DraftEditor les applique en INLINE sur son
  // contenu (DraftEditor.tsx), donc les vues sœurs (typing reveal, diff,
  // signature) doivent porter le même style — sinon elles rendent à
  // var(--font-size-base) 14px à côté d'un body 16px (rapport utilisateur
  // 2026-06-09 « my signature seems smaller »).
  const { fontFamilyCss, fontSizeCss } = useComposeFontPrefs();
  const bodyFontStyle = useMemo(
    () => ({ fontFamily: fontFamilyCss, fontSize: fontSizeCss }),
    [fontFamilyCss, fontSizeCss],
  );

  // Voice dictation (Whisper) — shared hook.
  // Parité compose : insérer la transcription AU CARET du DraftEditor (le texte
  // tombe là où le bloc de dictée est affiché, les dictées enchaînées coulent).
  // Fallback append si la ref n'est pas montée (mode diff/typing).
  const handleWhisperTranscript = useCallback((html: string) => {
    if (editorRef.current) {
      editorRef.current.insertDictation(html);
      setIsEditing(true);
      return;
    }
    const text = html.replace(/<[^>]*>/g, '').trim();
    if (text) {
      setEditedBody(prev => (isBodyBlank(prev) ? text : prev + '\n' + text));
      setIsEditing(true);
    }
  }, []);
  // Langue de dictée : défaut = langue préférée du destinataire du brouillon
  // (la personne à qui on répond → draft.email_sender), issue de Settings →
  // Entraînement. Le badge VoiceLanguageBadge (barre d'outils) permet d'en
  // changer — il manquait sur cette page (2026-06-23). Un pin erroné qui
  // renverrait un transcript VIDE est rejoué en auto-détection par
  // useWhisperRecording (résidu 2026-06-11 neutralisé — voir useVoiceLanguage).
  const { aggregate: aggregateContactLanguages } = useContactLanguages();
  const recipientDefaultLang = useMemo(
    () => aggregateContactLanguages(extractEmails(draft.email_sender || '')),
    [aggregateContactLanguages, draft.email_sender],
  );
  const {
    language: voiceLanguage,
    languageParam: voiceLanguageParam,
    setLanguage: setVoiceLanguage,
  } = useVoiceLanguage(recipientDefaultLang);
  // Gating dictée (essai 7j / plan) conservé du modèle billing actuel.
  const voiceDictationAllowed = useVoiceDictationAccess();
  const { isRecording, isTranscribing, transcriptionError, handleMicClick, audioLevels, softAskOpen, confirmSoftAsk, dismissSoftAsk } = useWhisperRecording(
    isBodyBlank(editedBody),
    true,
    handleWhisperTranscript,
    { language: voiceLanguageParam, surfaceSelector: '.pending-draft-detail', enabled: voiceDictationAllowed },
  );

  // Au départ de la dictée, faire apparaître le caret de l'éditeur pour que
  // l'utilisateur voie où les mots vont tomber (même comportement que
  // ReplyComposer). Skip si déjà focus — push-to-talk garde le caret en place.
  useEffect(() => {
    if (isRecording) editorRef.current?.focusForDictation();
  }, [isRecording]);

  // Reply mode state (reply / reply_all / forward)
  const [replyMode, setReplyMode] = useState<'reply' | 'reply_all' | 'forward'>('reply');
  const [showSendMenu, setShowSendMenu] = useState(false);
  const [forwardTo, setForwardTo] = useState('');
  const [to, setTo] = useState('');
  const sendMenuRef = useRef<HTMLDivElement>(null);
  const sendChevronRef = useRef<HTMLButtonElement>(null);
  const [showModeDropdown, setShowModeDropdown] = useState(false);
  const modeDropdownRef = useRef<HTMLDivElement>(null);
  const modePillRef = useRef<HTMLButtonElement>(null);
  const [modeDropdownPos, setModeDropdownPos] = useState<{top: number, left: number} | null>(null);

  // Labels from original email
  const [emailLabels, setEmailLabels] = useState<Array<{ name: string; color: string }>>([]);

  // Original email expanded by default (Superhuman-style thread scroll), collapsed in Deep Focus
  const [, setOriginalExpanded] = useState(!initialEmailCollapsed);

  // Reset expanded state when navigating to a different draft. Keyed
  // on draft.id only: initialEmailCollapsed is a prop that defines the
  // INITIAL state; we re-read it intentionally each time the draft
  // changes (not when the prop itself changes mid-flight, which would
  // be a footgun).
  useEffect(() => {
    setOriginalExpanded(!initialEmailCollapsed);
    // Reset reply-recipient overrides on draft change. Without this, a "To"
    // (or forward address / reply mode) typed for the previous draft persisted
    // into the next one and could be SENT to the wrong recipient.
    setTo('');
    setForwardTo('');
    setReplyMode('reply');
  }, [draft.id]);

  // Fetch real email HTML body if draft.email_body is CSS junk or missing + fetch CC, labels, summary
  const [realEmailBody, setRealEmailBody] = useState<string | null>(null);
  useEffect(() => {
    // Reset all email-derived state immediately on draft change
    setRealEmailBody(null);
    setEmailAttachments([]);
    setEmailLabels([]);
    setOriginalCc([]);
    setOriginalTo([]);

    const body = draft.email_body || '';
    const looksLikeCSS = /@media\b|!important|\{[^}]*display\s*:/i.test(body.slice(0, 500));
    const bodyMissing = body.trim().length < 20;
    const needsBetterBody = looksLikeCSS || bodyMissing;

    if (draft.email_id) {
      let cancelled = false;
      fetchEmailDetail(draft.email_id).then(detail => {
        if (cancelled || !detail) return;
        // Toujours préférer body_html (contient les images inline de la signature)
        // Fallback: texte brut uniquement si corps original est CSS junk ou vide
        const htmlBody = detail.body_html || (needsBetterBody ? detail.body : null);
        if (htmlBody) setRealEmailBody(htmlBody);
        // Capture To and CC from original email
        if (detail.to && detail.to.length > 0) {
          setOriginalTo(detail.to);
        }
        if (detail.cc && detail.cc.length > 0) {
          setOriginalCc(detail.cc);
        }
        // Capture labels from original email
        if (detail.labels && detail.labels.length > 0) {
          setEmailLabels(detail.labels);
        }
        // Capture attachments from original email
        if (detail.attachments && detail.attachments.length > 0) {
          setEmailAttachments(detail.attachments);
        }
      }).catch(err => {
        if (cancelled) return;
        // 404 = email archivé ou supprimé entre-temps — ignorer silencieusement
        const msg = err instanceof Error ? err.message : String(err);
        if (msg.includes('404')) {
          console.warn('[PendingDraftDetail] Email source introuvable (archivé ou supprimé)', draft.email_id);
        } else {
          console.error('[PendingDraftDetail] fetch email detail failed:', err);
        }
      });
      return () => { cancelled = true; };
    }
  }, [draft.email_id, draft.email_body]);

  // Follow-up reminder state
  const [followupDate, setFollowupDate] = useState<Date | null>(null);
  const [followupPickerPos, setFollowupPickerPos] = useState<{ x: number; y: number; buttonTop?: number } | null>(null);


  // Story 6-4: Regenerate with new instructions state
  const [showRegenerateModal, setShowRegenerateModal] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [lastInstructions, setLastInstructions] = useState('');
  const [versionHistory, setVersionHistory] = useState<DraftVersion[]>([]);
  const [showVersionHistory, setShowVersionHistory] = useState(false);
  const [comparisonVersions, setComparisonVersions] = useState<{ a: DraftVersion; b: DraftVersion } | null>(null);
  const versionIdCounter = useRef(0);

  // Story 6-5: Explicit approval state
  const [, setApprovalState] = useState<ApprovalState>({
    isApproved: false,
    approvedAt: null,
    approvalAuditId: null,
  });
  const [isSending, setIsSending] = useState(false);

  // Story 6-6: Send confirmation modal state
  const [showSendConfirmation, setShowSendConfirmation] = useState(false);

  const [, setSelectedSuggestion] = useState<string | null>(null);
  const [, setSuggestionsHidden] = useState(false);

  // Story 9-5: Track usage limits for draft generation
  void useIsLimitReached();

  const isPending = draft.status === 'pending' || draft.status === 'modified';

  // ─── Premium: Typing reveal ──────────────────────────────────────────
  const [typingDone, setTypingDone] = useState(false);
  // Reveal sur TEXTE LISIBLE : un draft sauvegardé depuis le DraftEditor est du
  // HTML — sans strip, l'animation taperait les balises (<p>…) à l'écran.
  const cleanedBody = useMemo(() => htmlBodyToPlainText(cleanDraftBody(draft.draft_body)), [draft.draft_body]);
  const typingReveal = useTypingReveal(cleanedBody, !typingDone);
  useEffect(() => {
    if (typingReveal.isComplete) setTypingDone(true);
  }, [typingReveal.isComplete]);

  // ─── Premium: Diff highlight after refinement ────────────────────────
  const [diffIndices, setDiffIndices] = useState<Set<number>>(new Set());
  const [diffFlash, setDiffFlash] = useState(false);
  const [diffToastVisible, setDiffToastVisible] = useState(false);
  const [diffCount, setDiffCount] = useState(0);
  // prevBodyRef removed (unused)

  // ─── Premium: Send success animation ─────────────────────────────────
  const [showSendSuccess, setShowSendSuccess] = useState(false);
  const [sendCheckPop, setSendCheckPop] = useState(false);
  const [sendTextVisible, setSendTextVisible] = useState(false);
  const particlesRef = useRef<HTMLDivElement>(null);

  // ─── Undo Send: countdown timer ──────────────────────────────────────

  // Stable ref for onDraftValidated to avoid stale closure in setTimeout
  const onDraftValidatedRef = useRef(onDraftValidated);
  onDraftValidatedRef.current = onDraftValidated;
  const onDraftScheduledRef = useRef(onDraftScheduled);
  onDraftScheduledRef.current = onDraftScheduled;
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // ─── Premium: Draft glow state ───────────────────────────────────────
  const draftGlowClass = isRefining || isRegenerating ? 'glow-generating' : (typingDone ? 'glow-ready' : '');

  // Corps HTML normalisé pour les envois (schedule / forward / reply-all).
  // La signature est apposée EXCLUSIVEMENT côté serveur par append_signature,
  // qui estampille class="agentys-signature" pour éviter les doublons.
  // N'inclure JAMAIS la signature ici — le guard backend ne détecterait pas
  // la version frontend (signatureToHtml → <p> sans classe CSS).
  const bodyHtmlForSend = useMemo(
    () => toHtmlEmailBody(editedBody),
    [editedBody],
  );

  // Auto-save handler
  const handleAutoSave = useCallback(async (data: { subject: string; body: string }) => {
    if (!isPending) return;

    if (data.subject === lastSavedRef.current.subject && data.body === lastSavedRef.current.body) {
      return;
    }

    await apiClient.updatePendingDraft(draft.id, data.subject, data.body);
    lastSavedRef.current = { id: draft.id, subject: data.subject, body: data.body };
    onDraftUpdated?.({ ...draft, draft_subject: data.subject, draft_body: data.body });
    // `draft` is intentionally not in deps — we want the callback identity
    // pinned to draft.id (so the auto-save hook doesn't reset its debounce
    // every render). The spread reads the latest draft via closure, which
    // is the desired behaviour for the optimistic `onDraftUpdated` payload.

  }, [draft.id, isPending, onDraftUpdated]);

  // FIX UI-003 (audit P1): when draft.id changes (ArrowDown navigation), the
  // editor's editedSubject/editedBody state lags by one render before the
  // useEffect below resets them. During that lag, the auto-save debounce
  // could fire with the PREVIOUS draft's data targeting the NEW draft's id —
  // silently overwriting the new draft. Pause auto-save for ~100ms across
  // every draft.id change to flush the pending timer and let state settle.
  const [autoSavePaused, setAutoSavePaused] = useState(false);
  useEffect(() => {
    setAutoSavePaused(true);
    const t = setTimeout(() => setAutoSavePaused(false), 100);
    return () => clearTimeout(t);
  }, [draft.id]);

  // Use auto-save hook.
  // Sauvegarde le body SANS signature (le serveur l'appose à l'envoi).
  const { status: saveStatus, error: saveError } = useAutoSave({
    data: { subject: editedSubject, body: editedBody },
    onSave: handleAutoSave,
    debounceMs: 2000,
    enabled: isEditing && isPending && !autoSavePaused,
  });

  // Update auto-save status for UI
  useEffect(() => {
    setAutoSaveStatus(saveStatus);
    if (saveError) {
      setError(saveError);
    }
  }, [saveStatus, saveError]);

  // Sync edited values when draft changes
  useEffect(() => {
    // Écho de notre propre auto-save : `onDraftUpdated` reboucle le draft mis à
    // jour avec EXACTEMENT ce qu'on vient de sauvegarder. Sans ce guard, chaque
    // sauvegarde (2 s après une frappe) rejouait l'animation typing et
    // démontait le DraftEditor sous le curseur de l'utilisateur. Le guard est
    // verrouillé sur draft.id : naviguer vers un autre draft (même au contenu
    // identique) doit toujours resynchroniser.
    if (
      draft.id === lastSavedRef.current.id &&
      draft.draft_subject === lastSavedRef.current.subject &&
      draft.draft_body === lastSavedRef.current.body
    ) {
      return;
    }
    setTypingDone(false);
    setEditedSubject(draft.draft_subject);
    setEditedBody(cleanDraftBody(draft.draft_body));
    signatureInjectedRef.current = false;
    lastSavedRef.current = { id: draft.id, subject: draft.draft_subject, body: draft.draft_body };
    setSelectedSuggestion(null);
    setSuggestionsHidden(false);
    // Reset reply mode and send menu when navigating to a new draft
    setReplyMode('reply');
    setShowSendMenu(false);
    setForwardTo('');
    // Reset send success animation when navigating to a new draft
    setShowSendSuccess(false);
    setSendCheckPop(false);
    setSendTextVisible(false);
  }, [draft.id, draft.draft_subject, draft.draft_body]);

  // BUG-F005 : si le statut du brouillon revient à un état non-envoyé (ex: backend annule),
  // masquer l'overlay de succès pour éviter l'affichage résiduel "Envoyé ✓" sur un brouillon actif.
  useEffect(() => {
    if (draft.status !== 'sent') {
      setShowSendSuccess(false);
      setSendCheckPop(false);
      setSendTextVisible(false);
    }
  }, [draft.status]);

  // Strip signature from editedBody if present (show it separately in .pdd-signature-preview)
  //
  // Only strip when the signature is actually at the TAIL of the body
  // (followed by at most whitespace) — not anywhere it happens to appear.
  // Bug avoided: follow-up templates like "Hi {{recipient_name}}, just
  // following up on…" embed the recipient's name (= signature first line)
  // at the START of the body. Using indexOf without an end-anchor check
  // would truncate the body to just "Hi".
  useEffect(() => {
    if (effectiveSignatureText && !signatureInjectedRef.current) {
      setEditedBody(prev => {
        const sigFirstLine = effectiveSignatureText.split('\n')[0].trim();
        if (sigFirstLine) {
          const idx = prev.lastIndexOf(sigFirstLine);
          if (idx !== -1) {
            const tailAfterSig = prev.slice(idx + sigFirstLine.length).trim();
            // Tail must be empty OR contain only subsequent signature
            // lines for this to be the real signature block. Anything
            // else (".", ", just following up…", etc.) means we hit a
            // mid-body false positive — leave the body intact.
            const sigRest = effectiveSignatureText.split('\n').slice(1).join('\n').trim();
            if (tailAfterSig === '' || tailAfterSig === sigRest) {
              return prev.substring(0, idx).trimEnd();
            }
          }
        }
        return prev;
      });
      signatureInjectedRef.current = true;
    }
  }, [effectiveSignatureText, draft.id, draft.draft_body]);

  // (L'auto-grow du <textarea> legacy a disparu : le DraftEditor TipTap
  // grandit naturellement avec son contenu.)

  const handleReject = () => {
    // Optimistic: close immediately, then delete in background (matches ReplyComposer.handleDiscard)
    playUISound('delete');
    onDraftRejected?.(draft);
    const draftId = draft.id;
    (async () => {
      try {
        await apiClient.deletePendingDraft(draftId);
      } catch (err) {
        // Audit U-06 / Toast Site 3 / #329 (2026-05-12): the optimistic
        // close runs before the DELETE — if the backend rejects, the draft
        // reappears next refresh with no explanation. Surface a warning
        // toast so the user knows the rejection is not durable yet.
        console.error('[PendingDraftDetail] Delete failed (background):', err);
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('agentys:toast', {
            detail: {
              message: tCommon('toasts.draft_delete_failed'),
              type: 'warning',
              duration: 7000,
            },
          }));
        }
      }
    })();
  };

  // handleSave and handleCancelEdit removed (unused — auto-save handles saving)

  // Story 6-6: Handle click on "Envoyer" - confirm unless user opted out
  const handleApproveAndSend = async () => {
    if (shouldSkipSendConfirmation()) {
      await performActualSend();
      return;
    }
    setShowSendConfirmation(true);
  };

  // Story 6-6: Cancel send confirmation
  const handleCancelSendConfirmation = useCallback(() => {
    setShowSendConfirmation(false);
  }, []);

  const handleScheduleSend = async (sendAtLocal: Date) => {
    if (sendAtLocal.getTime() <= Date.now()) return;

    setIsSending(true);
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

      const ccList = cc.trim() ? cc.split(',').map(s => s.trim()).filter(Boolean) : [];
      const bccList = bcc.trim() ? bcc.split(',').map(s => s.trim()).filter(Boolean) : [];
      const toList = replyMode === 'forward'
        ? forwardTo.trim().split(',').map(s => s.trim()).filter(Boolean)
        : to.trim().split(',').map(s => s.trim()).filter(Boolean);

      const scheduled = await apiClient.scheduleEmail({
        to: toList.join(', '),
        cc: ccList.join(', '),
        bcc: bccList.join(', '),
        subject: editedSubject,
        body: bodyHtmlForSend,
        send_at: sendAtLocal.toISOString(),
        is_html: true,
        reply_to_id: draft.email_id,
        attachments: outgoingAttachments?.map(a => ({
          filename: a.filename,
          data: a.data_base64,
          content_type: a.content_type,
        })),
        ai_assisted: true,
      });

      try {
        await apiClient.deletePendingDraft(draft.id);
      } catch {
        // The scheduled email already exists. If cleanup fails, parent refresh
        // will surface the stale draft instead of losing the scheduled send.
      }

      onDraftScheduledRef.current?.(draft, scheduled.scheduled_id);
      onCloseRef.current?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur lors de la programmation de l'envoi");
    } finally {
      setIsSending(false);
    }
  };

  // Execute the actual API send call (used both directly and after undo countdown)
  const executeSendAPI = async () => {
    setIsSending(true);
    setError(null);
    try {
      // Convert attachments to base64 for API
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

      // Parse CC/BCC into arrays
      const ccList = cc.trim() ? cc.split(',').map(s => s.trim()).filter(Boolean) : undefined;
      const bccList = bcc.trim() ? bcc.split(',').map(s => s.trim()).filter(Boolean) : undefined;

      let result: { success: boolean; gmail_draft_id?: string; draft_id?: string; sent?: boolean; knowledge_suggestions?: Array<{ question: string; answer: string; context: string }> };

      const toList = replyMode === 'forward'
        ? forwardTo.trim().split(',').map(s => s.trim()).filter(Boolean)
        : to.trim().split(',').map(s => s.trim()).filter(Boolean);

      const defaultTo = [recipientEmail];
      const toChanged = toList.length !== defaultTo.length || toList.some((t, i) => !t.includes(defaultTo[i] ?? ''));

      if (replyMode === 'forward' || toChanged) {
        // Forward or custom To: use createDraft with explicit recipients
        const fwdResult = await apiClient.createDraft(
          draft.email_id,
          editedSubject,
          bodyHtmlForSend,
          toList,
          ccList,
          bccList,
          outgoingAttachments,
          true, // send immediately
          true, // archive original
        );
        result = { success: fwdResult.success, gmail_draft_id: fwdResult.draft_id, sent: fwdResult.sent };
      } else {
        // Reply / Reply All: use validatePendingDraft (CC handles reply_all).
        // The follow-up reminder/snooze is created client-side below (the backend
        // never consumed a delay), so we only pass the archive flag: keep the
        // email (archive=false) when a reminder is set so it can resurface.
        result = await apiClient.validatePendingDraft(
          draft.id,
          !followupDate, // false si rappel programmé → email reste pour ressurgir en snooze
          outgoingAttachments,
          ccList,
          bccList,
        );
      }

      if (result.success && result.sent) {
        if (followupDate) {
          writeSnoozeEntry(draft.email_id, followupDate, draft.email_subject, 'followup', undefined, draft.email_sender, draft.email_sender_name ?? undefined);
          // Retry 3× avec délai croissant si le backend vient de démarrer
          const _reminderDate = followupDate.toISOString();
          const _tryReminder = (attempt: number) => {
            apiClient.createReminder(draft.email_id, draft.email_subject, _reminderDate)
              .catch((err) => {
                if (attempt < 3) {
                  setTimeout(() => _tryReminder(attempt + 1), attempt * 1500);
                } else {
                  console.warn('[PendingDraftDetail] createReminder failed after 3 retries:', err);
                  window.dispatchEvent(new CustomEvent('reminder:create-failed', {
                    detail: { emailId: draft.email_id, reminderDate: _reminderDate, error: String(err) },
                  }));
                }
              });
          };
          _tryReminder(1);
        }
        const draftId = result.gmail_draft_id ?? result.draft_id ?? '';
        playUISound('send');
        addApprovalAuditEntry({
          draftId: draft.id,
          action: 'sent',
          userAction: `Email sent successfully. Gmail Draft ID: ${draftId}`,
        });
        // Forward knowledge suggestions if any
        if (result.knowledge_suggestions?.length) {
          onKnowledgeSuggestion?.(result.knowledge_suggestions[0]);
        }
        // Premium: Show success animation before closing
        setIsSending(false);
        setShowSendSuccess(true);
        setTimeout(() => {
          setSendCheckPop(true);
          if (particlesRef.current) spawnParticles(particlesRef.current);
        }, 150);
        setTimeout(() => setSendTextVisible(true), 350);
        // Guard against double-fire (audit Reply-MEDIUM-8): both timers below
        // would otherwise call onDraftValidated twice in 1.7s, causing
        // duplicate parent state mutations.
        const _firedRef = { fired: false };
        const _fireOnce = () => {
          if (_firedRef.fired) return;
          _firedRef.fired = true;
          onDraftValidatedRef.current?.(draft, draftId);
        };
        setTimeout(_fireOnce, 1800);
        // Safety fallback: force close if still mounted after 3.5s
        setTimeout(() => {
          _fireOnce();
          onCloseRef.current?.();
        }, 3500);
        return;
      } else if (result.success && (result.gmail_draft_id || result.draft_id)) {
        // success=true but sent=false: draft was created but not sent
        const draftId = result.gmail_draft_id ?? result.draft_id ?? '';
        addApprovalAuditEntry({
          draftId: draft.id,
          action: 'sent',
          userAction: `Draft created. Gmail Draft ID: ${draftId}`,
        });
        // FE-02: the draft was saved (Gmail/Exchange Drafts) but NOT dispatched.
        // Without feedback the user believes the email was sent; it actually sits
        // unsent in their Drafts. Warn them before removing it from the queue.
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: { message: tCommon('toasts.draft_saved_not_sent'), type: 'warning', duration: 7000 },
        }));
        onDraftValidated?.(draft, draftId);
      } else if (!result.success) {
        setError(tErrors('send_server_refused'));
      }
    } catch (err) {
      addApprovalAuditEntry({
        draftId: draft.id,
        action: 'cancelled',
        userAction: `Send failed: ${err instanceof Error ? err.message : tCommon('unknown_error')}`,
      });
      setApprovalState({
        isApproved: false,
        approvedAt: null,
        approvalAuditId: null,
      });
      setShowSendSuccess(false);
      setError(err instanceof Error ? err.message : 'Error sending email');
    } finally {
      setIsSending(false);
    }
  };


  // Perform the actual send after confirmation
  const performActualSend = async () => {
    setShowSendConfirmation(false);

    const auditEntry = addApprovalAuditEntry({
      draftId: draft.id,
      action: 'approved',
      userAction: 'User clicked Send button',
    });

    setApprovalState({
      isApproved: true,
      approvedAt: auditEntry.timestamp,
      approvalAuditId: auditEntry.id,
    });

    // Send immediately (no countdown)
    void executeSendAPI();
  };

  // handleKeyDown and approvalHistory removed (unused)

  // Intentionally not wrapped in useCallback — reads a wide closure
  // (editedBody, draft, tCompose, conversation history, …). Wrapping
  // would require maintaining a long deps array prone to drift; the
  // function is only called imperatively from user-clicked menu items,
  // so the per-render identity is fine in practice. The consumer
  // useCallbacks below ack the dep via eslint-disable so this stays
  // out of the warning channel without forcing a refactor.

  const handleRefine = async (instructionOverride?: string) => {
    if (aiLocked) {
      showPaidAiBlocked();
      return;
    }
    const raw = (instructionOverride ?? '').trim();
    const isAutoReply = !raw;

    // Detect expand mode (/idees): embed body as notes in the instruction.
    // Le body peut être du HTML (DraftEditor) — toujours stripper avant de
    // nourrir le LLM, sinon les balises sont recopiées dans le brouillon
    // (même règle que ReplyComposer).
    const expandCmd = SLASH_COMMANDS.find(c => c.expand && c.instruction === raw);
    const notes = htmlBodyToPlainText(editedBody) || htmlBodyToPlainText(draft.draft_body ?? '');
    const instruction = expandCmd && notes
      ? tCompose('expand_notes_instruction', { notes })
      : (raw || AUTO_REPLY_INSTRUCTION);

    setIsRefining(true);
    setError(null);
    const oldBody = editedBody;
    if (expandCmd) setEditedBody('');

    // Determine base text for refineText path (plain text for the LLM)
    const baseText = htmlBodyToPlainText(oldBody) || htmlBodyToPlainText(draft.draft_body ?? '');

    // Use refineDraft (full pipeline) for:
    // - Auto-reply (no user instruction, needs email context to generate from scratch)
    // - When there's no existing text to work with
    // - Expand mode (/idees): needs full pipeline with email context
    const needsFullPipeline = isAutoReply || !baseText || !!expandCmd;

    try {
      if (needsFullPipeline) {
        // Full pipeline: Drafter → Critique → V2 (has email context via draft ID)
        const result = await apiClient.refineDraft(draft.id, instruction);
        if (result.success) {
          const updatedDraft = {
            ...draft,
            draft_v1: result.pipeline_details.draft_v1,
            critique: result.pipeline_details.critique.feedback,
            draft_body: result.refined_body,
            status: 'modified' as const,
          } satisfies PendingDraft;
          setEditedBody(result.refined_body);
          setIsEditing(true);
          onDraftUpdated?.(updatedDraft);
        }
      } else {
        // Lightweight refineText (single LLM call, no critique).
        // Pass draft.email_sender so the backend loads the ContactStyleProfile
        // of the recipient and adapts tone/nickname/greeting.
        const res = await apiClient.refineText(baseText, instruction, draft.email_id, draft.email_sender);
        if (res.success) {
          setEditedBody(res.refined_text);
          setIsEditing(true);

          // Premium: Trigger diff highlight (diff sur texte brut — oldBody peut être du HTML)
          const indices = computeDiffIndices(htmlBodyToPlainText(oldBody), res.refined_text);
          if (indices.size > 0) {
            setDiffIndices(indices);
            setDiffCount(indices.size);
            setDiffFlash(true);
            setDiffToastVisible(true);
            setTimeout(() => setDiffFlash(false), 300);
            setTimeout(() => setDiffToastVisible(false), 3000);
            setTimeout(() => setDiffIndices(new Set()), 4000);
          }
        }
      }
    } catch (err) {
      // Map 410 (draft disappeared during edit) to an actionable message and
      // notify the parent so the list refreshes (audit Reply-HIGH-3 "410 not
      // surfaced as actionable toast"). The parent listens to this event in
      // App.tsx and triggers setRefreshKey.
      const msg = err instanceof Error ? err.message : 'Error while refining';
      const looksLike410 = /\b410\b|Quick Reply|disappeared|Pending draft not found/i.test(msg);
      if (looksLike410) {
        setError(tDrafts('draft_stale_refreshing', 'Brouillon supprimé pendant l\'édition. Actualisation…'));
        try {
          window.dispatchEvent(new CustomEvent('agentys:pending-draft-stale', {
            detail: { draftId: draft.id },
          }));
        } catch { /* unmounted */ }
        // Auto-close after 2s so the user sees the message
        setTimeout(() => onCloseRef.current?.(), 2000);
      } else {
        setError(msg);
      }
    } finally {
      setIsRefining(false);
    }
  };

  // AICommandMenu callbacks (triggered from action bar). handleRefine
  // is intentionally not useCallback-wrapped (see its definition above
  // for the rationale); the dep is included so React's checker stays
  // happy with the closure capture.
  const handleCommandFromMenu = useCallback((cmd: typeof SLASH_COMMANDS[number]) => {
    if (cmd.group === 'Reply') setEditedBody('');
    handleRefine(cmd.instruction);
  }, [handleRefine]);

  const handleCustomPromptFromMenu = useCallback((prompt: string) => {
    handleRefine(prompt);
  }, [handleRefine]);

  // Parité Nouveau message : bouton « générer à partir des notes » — déclenche
  // la commande slash expand (le chemin handleRefine détecte l'instruction
  // expand et embarque le corps comme notes).
  const handleMagicGenerate = useCallback(() => {
    const expandCmd = SLASH_COMMANDS.find(c => c.expand);
    if (expandCmd) handleRefine(expandCmd.instruction);
  }, [handleRefine]);

  // ── Attachment handlers ──────────────────────────────────────────────────
  const handleAttachClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    setAttachError(null);
    const newFiles = Array.from(files).map(f => ({ name: f.name, size: f.size, file: f }));
    setAttachments(prev => {
      const combined = [...prev, ...newFiles];
      const totalSize = combined.reduce((sum, a) => sum + a.size, 0);
      if (totalSize > MAX_TOTAL_SIZE) {
        setAttachError(tErrors('attachments_too_large'));
        return prev;
      }
      return combined;
    });
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, [MAX_TOTAL_SIZE, tErrors]);

  const removeAttachment = useCallback((index: number) => {
    setAttachments(prev => prev.filter((_, i) => i !== index));
    setAttachError(null);
  }, []);

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  };

  const fileToBase64 = (file: File): Promise<string> =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result as string;
        resolve(result.split(',')[1] || result);
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });

  // ── Snippet handlers ───────────────────────────────────────────────────
  const handleSnippetSelect = useCallback((snippet: Snippet) => {
    const senderEmail = draft.email_sender || '';
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
    setEditedBody(prev => {
      if (isBodyBlank(prev)) return processedContent;
      // Body HTML (DraftEditor) ou snippet HTML : concaténer en HTML pour ne
      // pas mélanger \n bruts et balises. Deux drafts legacy plain restent en plain.
      if (looksLikeHtmlBody(prev) || looksLikeHtmlBody(processedContent)) {
        return toHtmlEmailBody(prev) + '<p></p>' + toHtmlEmailBody(processedContent);
      }
      return prev + '\n\n' + processedContent;
    });
    setIsEditing(true);
    trackSnippetUsage(snippet);
    setShowSnippetSelector(false);
  }, [draft.email_sender, trackSnippetUsage]);

  const handleCreateSnippet = useCallback(async (payload: CreateSnippetPayload) => {
    await createSnippet(payload);
  }, [createSnippet]);

  const handleJumpToComposer = useCallback(() => {
    const el = bodyEditorWrapRef.current;
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const zone = el.closest('.pdd-draft-zone') as HTMLElement | null;
    if (zone) {
      zone.classList.add('composer-jump-highlight');
      setTimeout(() => zone.classList.remove('composer-jump-highlight'), 800);
    }
    setTimeout(() => editorRef.current?.focusEnd(), 200);
  }, []);

  // ── Keyboard shortcuts: Ctrl+Enter = send, Ctrl+Shift+, = delete draft ────
  // Refs pattern: handleReject/performActualSend/handleRefine/handleJumpToComposer
  // are closures over many state values and get rebuilt every render. Listing
  // them as effect deps caused the keydown listener to tear down + re-add on
  // every keystroke in the body textarea. Under throttled CPU, Ctrl+Enter
  // could land in the gap between unsub and re-sub → silent lost send. The
  // ref pattern subscribes ONCE per isPending/isSending/isRegenerating change
  // and reads the latest handlers on each event.
  const shortcutHandlersRef = useRef({
    handleReject,
    handleRefine,
    performActualSend,
    handleJumpToComposer,
  });
  useEffect(() => {
    shortcutHandlersRef.current = {
      handleReject,
      handleRefine,
      performActualSend,
      handleJumpToComposer,
    };
  });
  useEffect(() => {
    if (!isPending) return;
    const handleShortcutKeys = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || (e.target as HTMLElement).isContentEditable) return;
      const h = shortcutHandlersRef.current;
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        if (!isSending && !isRegenerating) h.performActualSend();
        return;
      }
      if (isDeleteDraftShortcut(e)) {
        e.preventDefault();
        h.handleReject();
        return;
      }
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === 'w' || e.key === 'W') {
        e.preventDefault();
        h.handleRefine();
      } else if (e.key === 'g' || e.key === 'G') {
        e.preventDefault();
        h.handleJumpToComposer();
      }
    };
    window.addEventListener('keydown', handleShortcutKeys);
    return () => window.removeEventListener('keydown', handleShortcutKeys);
  }, [isPending, isSending, isRegenerating]);

  // Show jump pill when draft zone scrolls out of view
  useEffect(() => {
    const zone = draftZoneRef.current;
    const container = containerRef.current;
    if (!zone || !container) return;
    const observer = new IntersectionObserver(
      ([entry]) => setShowJumpPill(!entry.isIntersecting),
      { root: container, threshold: 0.6 }
    );
    observer.observe(zone);
    return () => observer.disconnect();
  }, []);

  // BUG-N002 fix v3: scrollIntoView({behavior:'smooth'}) is unreliable in Tauri's
  // WebView — it silently no-ops when called during the 400ms slideIn animation.
  // Direct scrollTop assignment is deterministic. We use three passes:
  //   • rAF ×2 (≈16ms) for fast machines where Tiptap initialises immediately.
  //   • 450ms fallback after the slideIn animation (400ms) finishes.
  //   • 800ms safety net for rich drafts where Tiptap lazy-initialises async
  //     (BUG-P003 fix capped pdd-email-zone at 480px so offsetTop ≤ 480px now,
  //     making scrollTop assignment always reachable regardless of email length).
  // .pending-draft-detail has position:relative so zone.offsetTop is relative to it.
  useEffect(() => {
    const scrollToZone = () => {
      const zone = draftZoneRef.current;
      if (!zone) return;
      const scrollParent = zone.closest('.pending-draft-detail') as HTMLElement | null;
      if (scrollParent) {
        scrollParent.scrollTop = zone.offsetTop;
      } else {
        zone.scrollIntoView({ behavior: 'instant', block: 'start' });
      }
    };

    // First pass: two animation frames after mount (layout computed, no animation yet)
    const rafId = requestAnimationFrame(() => requestAnimationFrame(scrollToZone));
    // Second pass: after the 400ms slideIn animation finishes
    const timerId1 = setTimeout(scrollToZone, 450);
    // Third pass: safety net for slow Tiptap init on rich drafts
    const timerId2 = setTimeout(scrollToZone, 800);

    return () => {
      cancelAnimationFrame(rafId);
      clearTimeout(timerId1);
      clearTimeout(timerId2);
    };
  }, []);

  // handleBodyChange and formatEmailBody removed (unused)

  // i18n comes from the common-namespace hook above (same global instance).
  const formatFollowupDate = (date: Date): string => {
    return formatLongDateFromDate(date, i18n.language);
  };

  // ── Drag handlers for recipient chips ─────────────────────────────────
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
    if (sourceField === 'to')  setForwardTo(prev => removeEmail(prev))
    if (sourceField === 'cc')  setCc(prev => removeEmail(prev))
    if (sourceField === 'bcc') setBcc(prev => removeEmail(prev))
    if (targetField === 'to')  setForwardTo(prev => addEmail(prev))
    if (targetField === 'cc')  setCc(prev => addEmail(prev))
    if (targetField === 'bcc') setBcc(prev => addEmail(prev))
    setDragState(null)
    setDragOverField(null)
  }

  // ── Reply mode change handler ──────────────────────────────────────────
  const handleReplyModeChange = useCallback((mode: 'reply' | 'reply_all' | 'forward') => {
    const prevMode = replyMode;
    setReplyMode(mode);
    setShowSendMenu(false);

    if (mode === 'reply_all') {
      // Auto-fill CC with original To (excluding the sender) + original CC
      const allCc = [
        ...originalTo.filter(addr => addr.toLowerCase() !== (draft.email_sender || '').toLowerCase()),
        ...originalCc,
      ];
      const uniqueCc = [...new Set(allCc.map(a => a.toLowerCase()))].map(lower =>
        allCc.find(a => a.toLowerCase() === lower) || lower
      );
      if (uniqueCc.length > 0) {
        setCc(uniqueCc.join(', '));
        setShowCc(true);
      }
      // Restore subject to Re: if coming from forward
      if (prevMode === 'forward') {
        setEditedSubject(sub => sub.replace(/^Fwd:\s*/i, '').replace(/^(Re:\s*)?/i, 'Re: '));
        setForwardTo('');
      }
    } else if (mode === 'forward') {
      // Clear auto CC from reply_all
      if (prevMode === 'reply_all') {
        setCc('');
      }
      setForwardTo('');
      // Prefix subject with Fwd:
      setEditedSubject(sub => {
        const cleaned = sub.replace(/^(Re|Fwd):\s*/i, '');
        return `Fwd: ${cleaned}`;
      });
    } else {
      // Back to reply mode
      if (prevMode === 'reply_all') {
        setCc('');
      }
      if (prevMode === 'forward') {
        setForwardTo('');
        setEditedSubject(sub => sub.replace(/^Fwd:\s*/i, '').replace(/^(Re:\s*)?/i, 'Re: '));
      }
    }
  }, [replyMode, originalTo, originalCc, draft.email_sender]);

  // ── Trigger reply mode from parent (keyboard shortcuts R/A/F) ──
  useEffect(() => {
    if (triggerReplyType) {
      handleReplyModeChange(triggerReplyType);
      onTriggerReplyHandled?.();
    }
  }, [triggerReplyType, handleReplyModeChange, onTriggerReplyHandled]);

  // (position is now computed inline in the onClick handler)

  // Click-outside handler for mode dropdown
  useEffect(() => {
    if (!showModeDropdown) return;
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as Node;
      // Close if click is outside the pill wrapper AND outside the portal dropdown
      const isInsidePill = modeDropdownRef.current?.contains(target);
      const isInsidePortal = (target as Element)?.closest?.('.draft-mode-dropdown');
      if (!isInsidePill && !isInsidePortal) {
        setShowModeDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showModeDropdown]);

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
      if (e.key === 'Escape') {
        // Dismiss only the send dropdown — stop Escape before it reaches a host
        // (the original-email EmailDetailModal viewer, or SnoozedView's detail)
        // whose own document/window Escape would otherwise close the whole
        // panel. Capture phase + stopImmediatePropagation beats those host
        // listeners regardless of their phase. See utils/escapeOwner.ts for the
        // structural variant used elsewhere; here a self-contained stop is
        // simplest because the dropdown has no single rendered root to tag.
        e.preventDefault();
        e.stopImmediatePropagation();
        setShowSendMenu(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape, true);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape, true);
    };
  }, [showSendMenu]);

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
      }
    };
    window.addEventListener('agentys:composer-field', handler);
    return () => window.removeEventListener('agentys:composer-field', handler);
  }, []);

  // ── Reply mode shortcuts (R / A / F) — direct handler ──────────────
  useEffect(() => {
    const handleReplyShortcut = (e: KeyboardEvent) => {
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
    window.addEventListener('keydown', handleReplyShortcut);
    return () => window.removeEventListener('keydown', handleReplyShortcut);
  }, [handleReplyModeChange]);



  // Story 6-4: Handle regenerate with new instructions
  const handleRegenerate = useCallback(async (instructions: string) => {
    if (aiLocked) {
      showPaidAiBlocked();
      return;
    }
    if (!instructions.trim()) {
      setShowRegenerateModal(true);
      return;
    }
    if (!usageLimitsService.canGenerateDraft()) {
      setError(tErrors('daily_limit_reached'));
      return;
    }

    setIsRegenerating(true);
    setError(null);
    try {
      const result = await apiClient.regenerateDraft(draft.id, instructions);
      if (result.success) {
        const currentVersion: DraftVersion = {
          id: `v-${versionIdCounter.current++}`,
          body: draft.draft_body,
          instructions: lastInstructions || 'Initial version',
          timestamp: new Date(),
          pipelineDetails: draft.draft_v1 ? {
            draft_v1: draft.draft_v1,
            critique: {
              is_valid: !draft.critique?.toLowerCase().includes('rejet'),
              feedback: draft.critique || '',
            },
            was_corrected: draft.draft_body !== draft.draft_v1,
          } : undefined,
        };

        setVersionHistory(prev => [currentVersion, ...prev].slice(0, 10));

        const updatedDraft: PendingDraft = {
          ...draft,
          draft_v1: result.pipeline_details.draft_v1,
          critique: result.pipeline_details.critique.feedback,
          draft_body: result.regenerated_body,
          status: 'modified',
        };
        setEditedBody(result.regenerated_body);
        setLastInstructions(instructions);
        onDraftUpdated?.(updatedDraft);
        setShowRegenerateModal(false);

        usageLimitsService.incrementDraftCount();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error while regenerating');
    } finally {
      setIsRegenerating(false);
    }
  }, [draft, lastInstructions, onDraftUpdated, tErrors, aiLocked, showPaidAiBlocked]);

  // Story 6-4: Handle version selection
  const handleVersionSelect = useCallback((version: DraftVersion) => {
    setEditedBody(version.body);
    const updatedDraft: PendingDraft = {
      ...draft,
      draft_body: version.body,
      draft_v1: version.pipelineDetails?.draft_v1 || draft.draft_v1,
      critique: version.pipelineDetails?.critique.feedback || draft.critique,
      status: 'modified',
    };
    onDraftUpdated?.(updatedDraft);
  }, [draft, onDraftUpdated]);

  // Story 6-4: Handle comparison
  const handleCompare = useCallback((versionA: DraftVersion, versionB: DraftVersion) => {
    setComparisonVersions({ a: versionA, b: versionB });
    setShowVersionHistory(false);
  }, []);

  // Story 6-4: Handle version change in comparison
  const handleComparisonVersionChange = useCallback((side: 'left' | 'right', version: DraftVersion) => {
    if (!comparisonVersions) return;
    setComparisonVersions(prev => prev ? {
      a: side === 'left' ? version : prev.a,
      b: side === 'right' ? version : prev.b,
    } : null);
  }, [comparisonVersions]);

  // Get current version for history display
  const currentVersion: DraftVersion | undefined = versionHistory.length > 0 ? {
    id: 'current',
    body: draft.draft_body,
    instructions: lastInstructions || 'Current version',
    timestamp: new Date(),
    pipelineDetails: draft.draft_v1 ? {
      draft_v1: draft.draft_v1,
      critique: {
        is_valid: !draft.critique?.toLowerCase().includes('rejet'),
        feedback: draft.critique || '',
      },
      was_corrected: draft.draft_body !== draft.draft_v1,
    } : undefined,
  } : undefined;

  const allVersions = currentVersion ? [currentVersion, ...versionHistory] : versionHistory;

  // Get recipient from the original email (reply-to address)
  const recipientEmail = draft.email_sender;
  const recipientName = draft.email_sender_name;

  // Initialize `to` from recipientEmail when navigating to a new draft.
  // Keyed on draft.id only: re-running this when `to` changes would
  // overwrite the user's edit; re-running when recipientEmail/Name
  // changes mid-draft is a no-op (they're derived from `draft`). Both
  // exclusions are intentional.
  useEffect(() => {
    if (recipientEmail && !to) {
      setTo(recipientName ? `${recipientName} <${recipientEmail}>` : recipientEmail);
    }

  }, [draft.id]);

  return (
    <div className="pending-draft-detail" ref={containerRef} data-testid="pending-draft-detail">
      {/* Le bouton Fermer vit désormais DANS l'en-tête de DraftEmailZone (après
          les flèches de navigation) — l'ancien bouton absolu ici chevauchait la
          flèche « Suivant » sur les panneaux ≤600px (bug 2026-06-09). */}
      {/* ── Email zone (left column in Deep Focus 2-col layout) ── */}
      <DraftEmailZone
        emailSubject={draft.email_subject}
        emailLabels={emailLabels}
        emailDate={draft.email_received_at || draft.created_at}
        senderName={draft.email_sender_name}
        senderEmail={draft.email_sender}
        originalCc={originalCc}
        emailBodyHtml={realEmailBody || draft.email_body}
        emailId={draft.email_id}
        emailAttachments={emailAttachments}
        navInfo={navInfo ?? null}
        onNavigatePrev={onNavigatePrev}
        onNavigateNext={onNavigateNext}
        onClose={onClose}
        tCommon={tCommon}
      />

      {/* ── Floating jump-to-draft arrow ── */}
      {showJumpPill && (
        <button
          className="pdd-jump-to-draft"
          onClick={handleJumpToComposer}
          aria-label="Go to draft"
        >
          <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24" aria-hidden="true">
            <line x1="12" y1="5" x2="12" y2="19"/><polyline points="19,12 12,19 5,12"/>
          </svg>
        </button>
      )}

      {/* ── Draft zone (right column in Deep Focus 2-col layout) ── */}
      <div className="pdd-draft-zone" ref={draftZoneRef}>
      {/* Draft meridian — thin gradient line separating thread from draft.
          Mirrors ReplyComposer's lean pattern: all draft actions (save status,
          version history, AI pipeline toggle) now live inline in the Cc/Bcc
          toggles row below, instead of a dedicated DRAFT header bar. */}
      <div
        className={`rc-draft-label rc-draft-label--minimal agentys-meridian${(isRefining || isRegenerating) ? ' agentys-meridian--breathing' : ''}`}
        aria-hidden="true"
      />

      {showPipeline && (
        <>
          <DraftPipelineCards
            draft={draft}
            onDraftUpdated={onDraftUpdated}
            tDrafts={tDrafts}
            tCompose={tCompose}
          />
          <MemoryTracePanel trace={draft.memory_trace as MemoryTrace | null | undefined} />
          <PipelineSummary
            draftId={draft.id}
            cachedSummary={draft.pipeline_summary}
          />
        </>
      )}

      {/* 4. Draft Card with Glow + Typing Reveal + Diff Highlight */}
      <div className={`draft-card ${draftGlowClass}`} style={{ position: 'relative' }} aria-live="polite" aria-busy={isRefining || isRegenerating}>
        {/* Send Success Overlay (countdown mode or completed mode) */}
        <div className={`send-success-overlay ${showSendSuccess ? 'visible' : ''}`}>
          <div className={`send-success-check-circle ${sendCheckPop ? 'pop' : ''}`}>
            <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 12 10 16 18 8" /></svg>
          </div>
          <div className={`send-success-text ${sendTextVisible ? 'visible' : ''}`}>{tDrafts('sent_successfully')}</div>
          <div className="send-particles-container" ref={particlesRef} />
        </div>

        {/* Diff toast */}
        <div className={`diff-toast ${diffToastVisible ? 'visible' : ''}`}>
          &#10003; {tDrafts(diffCount > 1 ? 'diff_toast_other' : 'diff_toast_one', { count: diffCount })}
        </div>

        {/* Recipient + CC/BCC toggles + inline mode pill */}
        <div className={`gmail-field draft-card-recipient${dragOverField === 'to' ? ' drop-active' : ''}`}
          data-testid="recipient-to"
          onDragOver={dragState ? (e) => { e.preventDefault(); setDragOverField('to') } : undefined}
          onDragLeave={dragState ? () => setDragOverField(null) : undefined}
          onDrop={dragState ? (e) => handleFieldDrop(e, 'to') : undefined}
        >
          <div className="draft-to-left">
          <div className="draft-mode-pill-wrapper" ref={modeDropdownRef}>
            <button
              ref={modePillRef}
              type="button"
              className={`draft-mode-pill ${replyMode === 'forward' ? 'forward' : replyMode === 'reply_all' ? 'reply-all' : 'reply'}`}
              onClick={() => {
                if (modePillRef.current) {
                  const r = modePillRef.current.getBoundingClientRect();
                  setModeDropdownPos({ top: r.bottom + 4, left: r.left });
                }
                setShowModeDropdown(v => !v);
              }}
              aria-haspopup="menu"
              aria-expanded={showModeDropdown}
              aria-label={replyMode === 'forward' ? tCompose('forward') : replyMode === 'reply_all' ? tCompose('reply_all') : tCompose('reply')}
            >
              {replyMode === 'reply' && (
                <svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" width="14" height="14"><path d="M6.5 3L2.5 7L6.5 11"/><path d="M2.5 7H10.5C12.1569 7 13.5 8.3431 13.5 10V13"/></svg>
              )}
              {replyMode === 'reply_all' && (
                <svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" width="14" height="14"><path d="M6.5 3L2.5 7L6.5 11"/><path d="M9.5 3L5.5 7L9.5 11"/><path d="M5.5 7H10.5C12.1569 7 13.5 8.3431 13.5 10V13"/></svg>
              )}
              {replyMode === 'forward' && (
                <svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" width="14" height="14"><path d="M9.5 3L13.5 7L9.5 11"/><path d="M13.5 7H5.5C3.8431 7 2.5 8.3431 2.5 10V13"/></svg>
              )}
              <ChevronDownIcon className="draft-mode-pill-chevron" size={10} />
            </button>
            {showModeDropdown && modeDropdownPos && createPortal(
              <div className="rc-send-dropdown draft-mode-dropdown" role="menu"
                style={{ position: 'fixed', top: modeDropdownPos.top, left: modeDropdownPos.left, bottom: 'auto', zIndex: 9999 }}
              >
                <button
                  type="button"
                  className={`rc-send-dropdown-item${replyMode === 'reply' ? ' active' : ''}`}
                  role="menuitem"
                  onClick={() => { handleReplyModeChange('reply'); setShowModeDropdown(false); }}
                >
                  <span className="rc-send-dropdown-icon">
                    <svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M6.5 3L2.5 7L6.5 11"/><path d="M2.5 7H10.5C12.1569 7 13.5 8.3431 13.5 10V13"/></svg>
                  </span>
                  <span className="rc-send-dropdown-text">
                    <span className="rc-send-dropdown-label">Reply</span>
                  </span>
                  <span className="rc-send-dropdown-shortcut">R</span>
                  {replyMode === 'reply' && <span className="rc-send-dropdown-check" />}
                </button>
                <button
                  type="button"
                  className={`rc-send-dropdown-item${replyMode === 'reply_all' ? ' active' : ''}`}
                  role="menuitem"
                  onClick={() => { handleReplyModeChange('reply_all'); setShowModeDropdown(false); }}
                >
                  <span className="rc-send-dropdown-icon">
                    <svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M6.5 3L2.5 7L6.5 11"/><path d="M9.5 3L5.5 7L9.5 11"/><path d="M5.5 7H10.5C12.1569 7 13.5 8.3431 13.5 10V13"/></svg>
                  </span>
                  <span className="rc-send-dropdown-text">
                    <span className="rc-send-dropdown-label">Reply all</span>
                  </span>
                  <span className="rc-send-dropdown-shortcut">A</span>
                  {replyMode === 'reply_all' && <span className="rc-send-dropdown-check" />}
                </button>
                <button
                  type="button"
                  className={`rc-send-dropdown-item${replyMode === 'forward' ? ' active' : ''}`}
                  role="menuitem"
                  onClick={() => { handleReplyModeChange('forward'); setShowModeDropdown(false); }}
                >
                  <span className="rc-send-dropdown-icon">
                    <svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M9.5 3L13.5 7L9.5 11"/><path d="M13.5 7H5.5C3.8431 7 2.5 8.3431 2.5 10V13"/></svg>
                  </span>
                  <span className="rc-send-dropdown-text">
                    <span className="rc-send-dropdown-label">Forward</span>
                  </span>
                  <span className="rc-send-dropdown-shortcut">F</span>
                  {replyMode === 'forward' && <span className="rc-send-dropdown-check" />}
                </button>
              </div>,
              document.body
            )}
          </div>
          </div>
          <ContactAutocomplete
            value={replyMode === 'forward' ? forwardTo : to}
            onChange={replyMode === 'forward' ? setForwardTo : setTo}
            placeholder={tCompose('to')}
            className="draft-to-input inline"
            fieldId="to"
            onChipDragStart={handleChipDragStart}
            onChipDragEnd={handleChipDragEnd}
            isDragActive={!!dragState}
          />
          <div className="draft-cc-toggles">
            {!showCc && <button className="draft-cc-toggle-btn" onClick={() => setShowCc(true)} type="button">{tCompose('cc_toggle')}</button>}
            {!showBcc && <button className="draft-cc-toggle-btn" onClick={() => setShowBcc(true)} type="button">{tCompose('bcc_toggle')}</button>}
            {!showSubject && <button className="draft-cc-toggle-btn" onClick={() => { setShowSubject(true); setTimeout(() => subjectInputRef.current?.focus(), 50); }} type="button">{tCompose('object_toggle')}</button>}
            {(isEditing || autoSaveStatus !== 'idle') && (
              <span className={`save-status save-status-${autoSaveStatus}`} data-testid="save-status" aria-live="polite" role="status">
                {autoSaveStatus === 'saving' && tCommon('saving')}
                {autoSaveStatus === 'saved' && tCommon('saved')}
                {autoSaveStatus === 'error' && tCommon('error')}
              </span>
            )}
            {versionHistory.length > 0 && (
              <button
                className="history-toggle"
                onClick={() => setShowVersionHistory(!showVersionHistory)}
                data-testid="version-history-toggle"
              >
                {showVersionHistory
                  ? tCompose('history_hide', { count: versionHistory.length })
                  : tCompose('history_show', { count: versionHistory.length })}
              </button>
            )}
            <AIProcessButton
              active={showPipeline}
              onClick={() => setShowPipeline(!showPipeline)}
            />
          </div>
        </div>

        {/* CC input */}
        {showCc && (
          <div
            className={`gmail-field${dragOverField === 'cc' ? ' drop-active' : ''}`}
            onDragOver={dragState ? (e) => { e.preventDefault(); setDragOverField('cc') } : undefined}
            onDragLeave={dragState ? () => setDragOverField(null) : undefined}
            onDrop={dragState ? (e) => handleFieldDrop(e, 'cc') : undefined}
          >
            <ContactAutocomplete
              value={cc}
              onChange={setCc}
              placeholder={tCompose('cc_label')}
              className="inline"
              fieldId="cc"
              onChipDragStart={handleChipDragStart}
              onChipDragEnd={handleChipDragEnd}
              isDragActive={!!dragState}
            />
          </div>
        )}

        {/* BCC input */}
        {showBcc && (
          <div
            className={`gmail-field${dragOverField === 'bcc' ? ' drop-active' : ''}`}
            onDragOver={dragState ? (e) => { e.preventDefault(); setDragOverField('bcc') } : undefined}
            onDragLeave={dragState ? () => setDragOverField(null) : undefined}
            onDrop={dragState ? (e) => handleFieldDrop(e, 'bcc') : undefined}
          >
            <ContactAutocomplete
              value={bcc}
              onChange={setBcc}
              placeholder={tCompose('bcc_label')}
              className="inline"
              fieldId="bcc"
              onChipDragStart={handleChipDragStart}
              onChipDragEnd={handleChipDragEnd}
              isDragActive={!!dragState}
            />
          </div>
        )}

        {/* Editable subject */}
        {showSubject && (
          <div className="gmail-field draft-card-subject">
            <input
              ref={subjectInputRef}
              type="text"
              className="gmail-input"
              value={editedSubject}
              onChange={(e) => {
                setEditedSubject(e.target.value);
                setIsEditing(true);
              }}
              placeholder={tCompose('subject')}
              spellCheck={false}
            />
          </div>
        )}

        {/* Draft body */}
        <div className="draft-card-body-wrapper" style={bodyFontStyle} aria-live="polite" aria-busy={isRefining || isRegenerating}>
          {/* Body: typing OR diff OR textarea */}
          {!typingDone ? (
            <div className="typing-reveal-container" style={{ cursor: 'text' }} onClick={() => setTypingDone(true)}>
              {typingReveal.words.map((word, i) => (
                <span
                  key={i}
                  className={`typing-word ${i < typingReveal.revealedCount ? 'revealed' : ''}`}
                >{word}</span>
              ))}
              {!typingReveal.isComplete && <span className="typing-cursor" />}
            </div>
          ) : diffIndices.size > 0 ? (
            <div className="typing-reveal-container" onClick={() => { setDiffIndices(new Set()); }}>
              {editedBody.split(/(\s+)/).map((word, i) => (
                <span
                  key={i}
                  className={diffIndices.has(i) ? `diff-highlight-word ${diffFlash ? 'flash' : ''}` : ''}
                >{word}</span>
              ))}
            </div>
          ) : (
            // Brouillon vide (effacé à la main, ou draft IA revenu vide) → on rend
            // directement le DraftEditor éditable (avec placeholder) au lieu de
            // l'ancien prompt bloquant « Le brouillon est vide / Régénérer », qui
            // remplaçait l'éditeur et empêchait d'écrire, forçant la modale de
            // régénération (bug signalé 2026-06-23). La régénération reste
            // accessible via la barre d'outils (✨ générer-depuis-les-notes +
            // menu IA + chips de suggestions affichées plus bas quand c'est vide).
            // Parité compose (2026-06-09) : DraftEditor TipTap partagé avec
            // Reply/Nouveau message — gras/italique/couleur via la bubble de
            // sélection, dictée insérée au caret avec le bloc-curseur, images.
            // `pointer-events: none` pendant la dictée : bloque les clics
            // fantômes qui déplaceraient le caret (cf. NewMessageModal).
            <div
              ref={bodyEditorWrapRef}
              className="rc-editor-wrapper pdd-body-editor"
              data-testid="draft-body"
              style={{
                position: 'relative',
                pointerEvents: (isRecording || isTranscribing) ? 'none' : undefined,
              }}
              onKeyDown={(e) => {
                // The window-level shortcut skips contenteditable targets, so
                // wire the same send behavior here for focused draft edits.
                if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  if (!isSending && !isRegenerating) void handleApproveAndSend();
                }
              }}
            >
              <DraftEditor
                ref={editorRef}
                content={editedBody}
                onChange={(html) => {
                  // Le sync de montage (plain → HTML TipTap) repasse par
                  // onChange : ne marquer "édité" (→ auto-save) que si le TEXTE
                  // a changé, pas seulement la forme. Sinon, ouvrir un draft
                  // suffirait à le réécrire côté serveur en HTML.
                  if (htmlBodyToPlainText(html) !== htmlBodyToPlainText(editedBody)) {
                    setIsEditing(true);
                  }
                  setEditedBody(html);
                }}
                placeholder={tCompose('body_placeholder')}
                // Reste éditable pendant la dictée pour que le bloc-curseur
                // marque le point d'insertion (les clics fantômes sont déjà
                // bloqués par le wrapper).
                readOnly={isSending}
                dictating={isRecording || isTranscribing}
                recording={isRecording}
                hideWordCount
                hideToolbar
              />
            </div>
          )}
        </div>

        {/* Signature preview — editable per contact.
            Cliquer la signature ouvre l'éditeur (plus de bouton dédié). */}
        {(effectiveSignatureText || signatureEditorOpen) && (
          <div
            className={`pdd-signature-preview pdd-signature-preview--editable${signatureClickable ? ' rc-signature-footer--clickable' : ''}`}
            style={bodyFontStyle}
            role={signatureClickable ? 'button' : undefined}
            tabIndex={signatureClickable ? 0 : undefined}
            onClick={signatureClickable ? handleSignatureClick : undefined}
            onKeyDown={signatureClickable ? handleSignatureKeyDown : undefined}
            title={signatureClickable ? tCompose('edit_contact_signature') : undefined}
            aria-label={signatureClickable ? tCompose('edit_contact_signature') : undefined}
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
                  <div className="rc-signature-chips" role="group" aria-label={tCompose('signature_switch_aria')}>
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
                  aria-label={tCompose('signature_for_contact')}
                  // Focus à l'ouverture : sans lui, Échap part du body et
                  // n'atteint jamais le handler du conteneur (touche morte).
                  autoFocus
                />
                {/* Actions groupées en bas à droite : Annuler (fantôme) +
                    Enregistrer (accent). Le ✓ PERSISTE la signature pour ce
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
                    aria-label={tCompose('save_contact_signature')}
                  >
                    {signatureSaving ? tCommon('saving', 'Saving…') : tCommon('save')}
                  </button>
                </div>
              </div>
            ) : (
              <>
                {effectiveSignatureText && (
                  <div className="pdd-signature-text">{effectiveSignatureText}</div>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {/* Smart Suggestions — clickable chips that fill the draft body */}
      {draft.smart_suggestions && draft.smart_suggestions.length > 0 && isBodyBlank(editedBody) && (
        <div className="smart-suggestions-row">
          {draft.smart_suggestions.map((suggestion, i) => (
            <button
              key={i}
              type="button"
              className="smart-suggestion-chip"
              onClick={() => {
                setEditedBody(suggestion)
                setIsEditing(true)
                setTypingDone(true)
              }}
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}

      {/* 6. Attachment Chips */}
      {attachments.length > 0 && (
        <div className="rc-attachments" style={{ padding: '0 24px 8px' }}>
          {attachments.map((att, index) => (
            <div key={`${att.name}-${index}`} className="rc-attachment-chip">
              <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
              </svg>
              <span className="rc-attachment-name">{att.name}</span>
              <span className="rc-attachment-size">({formatFileSize(att.size)})</span>
              <button
                type="button"
                className="rc-attachment-remove icon-btn--delete"
                onClick={() => removeAttachment(index)}
                title={tCommon('delete')}
                aria-label={tCompose('remove_attachment', { name: att.name })}
              >
                <CloseIcon size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
      {attachError && (
        <div className="rc-error" style={{ margin: '0 24px 8px' }} role="alert">
          <span className="rc-error-icon">!</span>
          <span>{attachError}</span>
        </div>
      )}

      {/* 6b. Error Message */}
      {error && (
        <div className="rc-error" style={{ margin: '0 24px 8px' }} role="alert">
          <span className="rc-error-icon">!</span>
          <span>{error}</span>
        </div>
      )}

      {/* 7b. AI Commitment Suggestions (Issue #26) */}
      <FollowupSuggestions emailId={draft.email_id} />

      <RecordingWaveform isRecording={isRecording} audioLevels={audioLevels} />

      {/* 8. Action Bar: Send + AI + Attach + Snippets + Bell + Bullets + Delete */}
      {isPending && (
        <div className="rc-action-bar">
          <SendButtonSplit
            onSend={handleApproveAndSend}
            onSchedule={handleScheduleSend}
            disabled={isSending || isRegenerating || (replyMode === 'forward' && !forwardTo.trim())}
            loading={isSending}
            label={isSending ? tCompose('sending') : tCompose('send')}
            sendTestId="send-button"
          />
          {/* Sélecteur langue dictée — défaut = langue du destinataire (Settings → Entraînement).
              Masqué en Free : la dictée est verrouillée, le picker n'a pas de sens. */}
          {!isRecording && !isTranscribing && !aiLocked && (
            <VoiceLanguageBadge
              language={voiceLanguage}
              onChange={setVoiceLanguage}
              disabled={isSending || isRegenerating}
            />
          )}
          {/* Micro — la dictée (Whisper) est une fonctionnalité IA payante.
              En Free le bouton porte le cadenas et le clic ouvre le paywall. */}
          <button
            type="button"
            className={`rc-icon-btn nmm-mic-btn${isRecording ? ' nmm-mic-recording' : ''}`}
            onClick={handleMicClick}
            disabled={isTranscribing || isRegenerating || isSending || (!voiceDictationAllowed && !isRecording)}
            title={
              !voiceDictationAllowed && !isRecording
                ? tCompose('dictation_requires_trial_or_plan')
                : isRecording ? tCompose('ai_cmd_mic_stop_tooltip') : tCompose('ai_cmd_dictate')
            }
            aria-label={
              !voiceDictationAllowed && !isRecording
                ? tCompose('dictation_unavailable')
                : isRecording ? tCompose('ai_cmd_mic_stop_tooltip') : tCompose('ai_cmd_dictate')
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
          {/* Générer à partir des notes — parité Nouveau message */}
          <button
            type="button"
            className="rc-icon-btn"
            data-testid="pdd-magic-generate"
            onClick={handleMagicGenerate}
            disabled={isRefining || isRegenerating || isSending}
            title={tCompose('magic_generate_tooltip')}
            aria-label={tCompose('magic_generate_tooltip')}
          >
            <MagicDraftIcon size={16} />
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
            disabled={isRegenerating || isSending || aiLocked}
            disabledReason={aiLocked ? paidAiMessage : undefined}
            busy={isRefining}
          />
          <button
            type="button"
            className="rc-icon-btn"
            title={tCompose('attach_file')}
            aria-label={tCompose('add_attachment_aria')}
            onClick={handleAttachClick}
            disabled={isSending || isRegenerating}
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
          />
          <div className="rc-snippet-wrapper">
            <button
              ref={snippetBtnRef}
              type="button"
              className="rc-icon-btn"
              title={tCompose('snippets')}
              aria-label={tCompose('insert_snippet_aria')}
              onClick={() => setShowSnippetSelector(!showSnippetSelector)}
              disabled={isSending || isRegenerating}
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
          {/* Follow-up bell — shows date inline when configured */}
          <button
            type="button"
            className={followupDate ? 'followup-date-chip' : 'rc-icon-btn'}
            title={followupDate ? tCompose('cancel_reminder') : tCompose('reminder_activate')}
            aria-label={tCompose('auto_reminder')}
            disabled={isSending || isRegenerating}
            onClick={(e) => {
              if (followupDate) {
                setFollowupDate(null);
              } else {
                const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                setFollowupPickerPos({ x: rect.left, y: rect.bottom + 4 });
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
              emailBody={realEmailBody ?? undefined}
              onSelect={(date) => { setFollowupDate(date); setFollowupPickerPos(null); }}
              onClose={() => setFollowupPickerPos(null)}
            />
          )}
          <button
            type="button"
            className="rc-icon-btn"
            title={tCompose('bullet_list')}
            aria-label={tCompose('insert_bullet_list')}
            disabled={isSending || isRegenerating}
            onMouseDown={(e) => {
              // Vraie liste à puces TipTap (parité compose) — remplace
              // l'ancienne insertion de "• " texte dans le <textarea>.
              e.preventDefault();
              editorRef.current?.toggleBulletList();
              setIsEditing(true);
            }}
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
              onClick={handleReject}
              disabled={isSending || isRegenerating}
              data-testid="reject-button"
              title={tCompose('delete_draft')}
              aria-label={tCompose('delete_draft')}
            >
              <TrashIcon size={16} />
            </button>
          </div>
        </div>
      )}

      </div>

      {/* 9. All existing modals unchanged */}

      {/* Email Detail Modal */}
      {selectedEmailId && (
        <Suspense fallback={null}>
          <EmailDetailModal
            emailId={selectedEmailId}
            isOpen={!!selectedEmailId}
            onClose={() => setSelectedEmailId(null)}
          />
        </Suspense>
      )}

      {/* Regenerate Modal */}
      <RegenerateModal
        isOpen={showRegenerateModal}
        onClose={() => setShowRegenerateModal(false)}
        onRegenerate={handleRegenerate}
        isLoading={isRegenerating}
        previousInstructions={lastInstructions}
      />

      {/* Version History Panel */}
      <DraftVersionHistory
        versions={allVersions}
        currentVersionId={currentVersion?.id}
        isOpen={showVersionHistory}
        onClose={() => setShowVersionHistory(false)}
        onVersionSelect={handleVersionSelect}
        onCompare={handleCompare}
      />

      {/* Comparison View */}
      {comparisonVersions && (
        <DraftComparisonView
          versionA={comparisonVersions.a}
          versionB={comparisonVersions.b}
          allVersions={allVersions}
          onClose={() => setComparisonVersions(null)}
          onVersionChange={handleComparisonVersionChange}
        />
      )}

      {/* Send Confirmation Modal */}
      <SendConfirmationModal
        isOpen={showSendConfirmation}
        recipient={recipientEmail}
        recipientName={recipientName || undefined}
        subject={draft.draft_subject}
        onConfirm={performActualSend}
        onCancel={handleCancelSendConfirmation}
        isLoading={isSending}
      />

      {/* Snippet Editor Modal */}
      <SnippetEditor
        isOpen={showSnippetEditor}
        onClose={() => setShowSnippetEditor(false)}
        onSave={handleCreateSnippet}
      />

      <MicPermissionDialog
        open={softAskOpen}
        onConfirm={confirmSoftAsk}
        onCancel={dismissSoftAsk}
      />

    </div>
  );
});
