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

import { useState, useCallback, useRef, useEffect } from 'react'
import { apiClient, type PendingDraft, type Email } from '../services/api'
import { markEmailRead, invalidateEmailCache } from '../api/emails'
import i18n from '../i18n'

export interface EmailDetailController {
  selectedEmail: Email | null
  setSelectedEmail: React.Dispatch<React.SetStateAction<Email | null>>
  emailDraft: PendingDraft | null
  setEmailDraft: React.Dispatch<React.SetStateAction<PendingDraft | null>>
  isLoadingEmailDraft: boolean
  setIsLoadingEmailDraft: React.Dispatch<React.SetStateAction<boolean>>
  selectedEmailIdRef: React.MutableRefObject<string | null>
  detailReady: boolean
  isEmailExpanded: boolean
  setIsEmailExpanded: React.Dispatch<React.SetStateAction<boolean>>
  replyTriggerType: 'reply' | 'reply_all' | 'forward' | null
  setReplyTriggerType: React.Dispatch<React.SetStateAction<'reply' | 'reply_all' | 'forward' | null>>
  replyComposerOpen: boolean
  setReplyComposerOpen: React.Dispatch<React.SetStateAction<boolean>>
  handleEmailSelect: (email: Email, prefetchedDraft?: PendingDraft | null) => Promise<void>
  handleCloseEmailDetail: () => void
}

export function useEmailDetailController(): EmailDetailController {
  const [selectedEmail, setSelectedEmail] = useState<Email | null>(null)
  const [emailDraft, setEmailDraft] = useState<PendingDraft | null>(null)
  const [isLoadingEmailDraft, setIsLoadingEmailDraft] = useState(false)
  const selectedEmailIdRef = useRef<string | null>(null)
  const [detailReady, setDetailReady] = useState(false)
  const [isEmailExpanded, setIsEmailExpanded] = useState(false)
  const [replyTriggerType, setReplyTriggerType] = useState<'reply' | 'reply_all' | 'forward' | null>(null)
  const [replyComposerOpen, setReplyComposerOpen] = useState(false)

  // Trigger detail-ready class after detail panel mounts
  useEffect(() => {
    if (selectedEmail) {
      setDetailReady(false)
      requestAnimationFrame(() => {
        requestAnimationFrame(() => setDetailReady(true))
      })
    }
  }, [selectedEmail?.id])

  // Handle email selection - fetch pending draft if available
  // prefetchedDraft: if the caller already has the draft (e.g. Deep Focus hero card), skip the API call
  const handleEmailSelect = useCallback(async (email: Email, prefetchedDraft?: PendingDraft | null) => {
    selectedEmailIdRef.current = email.id
    setSelectedEmail(email)

    // Mark as read on every selection — including keyboard prev/next nav.
    // EmailList.handleEmailClick used to be the only path that fired this;
    // the prev/next arrow buttons (and J/K keyboard shortcuts) route
    // through here without going through that handler, so historically
    // they left emails unread + skipped the backend auto-trigger reeval.
    // The backend audit-log dedup prevents double-execution if a rule
    // already fired for this (step, email).
    // Skipped for sent emails (no "unread" semantics there).
    if (email && email.id && !email.id.startsWith('sent:')) {
      void markEmailRead(email.id)
        .then(() => invalidateEmailCache())
        .catch(err => console.warn('[useEmailDetailController] markEmailRead failed:', err))
    }

    // If a pre-fetched draft was provided, use it directly (no API call needed)
    if (prefetchedDraft) {
      setEmailDraft(prefetchedDraft)
      setIsLoadingEmailDraft(false)
      return
    }

    setEmailDraft(null)

    // If email has a pending draft, fetch it
    if (email.has_pending_draft) {
      setIsLoadingEmailDraft(true)
      try {
        const draft = await apiClient.getPendingDraftByEmailId(email.id, email.subject)
        // Guard against race condition: only apply if this email is still selected
        if (draft && selectedEmailIdRef.current === email.id) {
          // Verify draft belongs to this email (IMAP UIDs can be reassigned)
          const subjectMatch = !draft.email_subject || !email.subject ||
            draft.email_subject.replace(/^Re:\s*/i, '') === email.subject.replace(/^Re:\s*/i, '')
          if (subjectMatch) {
            setEmailDraft(draft)
          } else {
            console.warn('[App] Stale draft detected: draft subject', JSON.stringify(draft.email_subject), 'does not match email subject', JSON.stringify(email.subject))
          }
        }
      } catch (err) {
        // F-06 (audit 2026-06-11) : l'email porte le badge has_pending_draft
        // mais la vue s'ouvrait sans le brouillon ni aucun signal — l'utilisateur
        // croyait le brouillon disparu.
        console.error('Failed to load email draft:', err)
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: { message: i18n.t('common:toasts.pending_draft_load_failed'), type: 'error' },
        }))
      } finally {
        if (selectedEmailIdRef.current === email.id) {
          setIsLoadingEmailDraft(false)
        }
      }
    }
  }, [])

  // Close email detail/draft modal
  const handleCloseEmailDetail = useCallback(() => {
    selectedEmailIdRef.current = null
    setSelectedEmail(null)
    setEmailDraft(null)
    setIsEmailExpanded(false)
    setReplyComposerOpen(false)
  }, [])

  return {
    selectedEmail, setSelectedEmail,
    emailDraft, setEmailDraft,
    isLoadingEmailDraft, setIsLoadingEmailDraft,
    selectedEmailIdRef,
    detailReady,
    isEmailExpanded, setIsEmailExpanded,
    replyTriggerType, setReplyTriggerType,
    replyComposerOpen, setReplyComposerOpen,
    handleEmailSelect,
    handleCloseEmailDetail,
  }
}
