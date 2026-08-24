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

import React, { useState, useEffect, useLayoutEffect, useCallback, useMemo, useRef } from 'react';
import { flushSync } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { List } from 'react-window';
import type { Email, EmailLabel, EmailLoadingState, EmailStatus, SearchResult } from '../types/email';
import { fetchEmails, searchEmails, markEmailRead, markEmailUnread, markEmailsBulk, createEmailFetchController, invalidateEmailCache, prefetchEmailDetails, prefetchSingleEmail, type EmailFolder } from '../api/emails';
import { emailActionFailureToastKey, emitEmailProviderAuthExpired, handleEmailActionFailure, isEmailProviderAuthFailure } from '../lib/handleEmailPatchFailure';
import { SwipeableEmailItem, setMultiSelectActive, setKeyboardNavMode, markDeletePending, unmarkDeletePending, setLastPendingDeleteId, clearLastPendingDeleteId, lockHoverForAnimation } from './SwipeableEmailItem';
import { SmartSearchBar } from './search/SmartSearchBar';
import { EmailListHeader } from './EmailListHeader';
import { EmailListEmpty } from './EmailListEmpty';
import { ToastContainer, useToast, type ToastType } from './Toast';
import { apiClient, blockSender } from '../services/api';

import { useSharedLabels } from '../contexts/LabelsContext';
import { useHideNoiseSetting } from '../hooks/useHideNoiseSetting';
import { useAutoDeleteNoiseSetting } from '../hooks/useAutoDeleteNoiseSetting';
import { useAutoEmptySpamSetting } from '../hooks/useAutoEmptySpamSetting';
import { useAutoEmptyTrashSetting } from '../hooks/useAutoEmptyTrashSetting';
import { useEmailViewMode, type EmailViewMode } from '../hooks/useEmailViewMode';
import { getLabelDisplayName } from '../types/labels';
import { useSnooze, writeSnoozeEntry } from '../hooks/useSnooze';
import { SnoozeDropdown } from './SnoozeDropdown';
import { usePinned } from '../hooks/usePinned';
import { useFollowupNudgeCount } from '../hooks/useFollowupNudgeCount';
import ConfirmationDialog from './ConfirmationDialog';
import { useBulkActionCount } from '../hooks/useBulkActionCount';
import { QuickStepsListHotkeys } from './QuickStepsListHotkeys';
import { useAutoBadges } from '../hooks/useAutoBadges';
import { CheckIcon, TrashIcon } from './icons/ActionIcons';
import i18n from '../i18n';
import { getEmailSyncInProgressDecision } from '../utils/emailSyncInProgress';
import { formatHourMinute } from '../utils/dateFormat';
import { syncUnreadLabelCountsAfterReadStateChange, invalidateLabelCounts } from '../lib/labelCounts';
import { getUnreadThreadEmailsOnOpen, markEmailThreadReadInList } from '../lib/emailThreads';
import './EmailList.css';


const EMAIL_ITEM_HEIGHT_COMPACT = 36;
const EMAIL_ITEM_HEIGHT_BALANCED = 52;
const EMAIL_ITEM_HEIGHT_COMFORTABLE = 94;
const SECTION_HEADER_HEIGHT = 28;
const PAGE_SIZE = 50;
const INFINITE_SCROLL_THRESHOLD = 10;
// Prefetch désactivé par défaut : en metadata-only, chaque détail peut déclencher
// un fetch provider live. Le cache body se remplit à l'ouverture explicite d'un
// email; le hover ne doit pas consommer de quota Gmail/Outlook.
const BLIND_PREFETCH_ENABLED = false;
const HOVER_PREFETCH_ENABLED = false;

interface EmailListProps {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onEmailSelect?: (email: Email, prefetchedDraft?: any) => void | Promise<void>;
  selectedEmailId?: string | null;
  onEmailsLoaded?: (emails: Email[]) => void;
  onSwipeArchive?: (email: Email) => void | Promise<void>;
  onSwipeDelete?: (email: Email) => void | Promise<void>;
  onToast?: (message: string, type: 'success' | 'error' | 'info') => void;
  folder?: EmailFolder;
  activeLabel?: string | null;
  onLabelChange?: (label: string | null) => void;
  /** Increment to trigger a silent refresh without remounting */
  refreshTrigger?: number;
  /** Callback to start Deep Focus mode */
  /** Called when the displayed (filtered) email list changes — used for J/K navigation */
  onDisplayedEmailsChange?: (emails: Email[]) => void;
  /** Ribbon action callbacks (from App-level shortcuts) */
  onNavigateUp?: () => void;
  onNavigateDown?: () => void;
  onReply?: () => void;
  onForward?: () => void;
  onArchive?: () => void;
  onDelete?: () => void;
  onToggleRead?: () => void;
  onSearch?: () => void;
  onNewMessage?: () => void;
  onReplyAll?: () => void;
  /** Ref for search trigger (so App can invoke search focus) */
  onSearchRef?: React.MutableRefObject<(() => void) | null>;
  /** Open settings/accounts panel when no account is configured */
  onOpenAccounts?: () => void;
  /** Native provider folder/label ID for server-side filtering */
  providerLabel?: string | null;
  /** Set of email IDs that have local reply drafts in localStorage */
  localDraftEmailIds?: Set<string>;
  /** Current account email — used to display "Moi" instead of own name */
  accountEmail?: string;
  /** Refs for bulk actions — allows App to delegate archive/delete to bulk handlers */
  bulkArchiveRef?: React.MutableRefObject<(() => void) | null>;
  bulkDeleteRef?: React.MutableRefObject<(() => void) | null>;
  /** Refs for spam/trash folder bulk actions */
  bulkNotSpamRef?: React.MutableRefObject<(() => void) | null>;
  bulkRestoreRef?: React.MutableRefObject<(() => void) | null>;
  /** Ref for optimistic (animated) single-email delete — allows App to call EmailList's internal handler */
  deleteEmailOptimisticRef?: React.MutableRefObject<((email: Email) => void) | null>;
  /** Ref for optimistic (animated) single-email archive — allows App to call EmailList's internal handler */
  archiveEmailOptimisticRef?: React.MutableRefObject<((email: Email) => void) | null>;
  /** Ref for deselect all — allows App to exit bulk selection mode via Escape */
  deselectAllRef?: React.MutableRefObject<(() => void) | null>;
  /** Ref for select all — allows App to trigger select all via keyboard shortcut */
  selectAllRef?: React.MutableRefObject<(() => void) | null>;
  /** Ref for select all from here — allows App to trigger select from current position */
  selectAllFromHereRef?: React.MutableRefObject<(() => void) | null>;
  /** Called when user deletes the pending draft from the email list row */
  onDeleteDraft?: (email: Email) => void;
  /** Current account ID — used for per-account settings isolation */
  accountId?: number;
}

const _dateFormatCache = new Map<string, string>();
let _dateFormatCacheDay = '';

/** Parse date string, fixing malformed formats like "+00:00Z" (both offset and Z). */
function parseDate(s: string): Date {
  if (s && s.endsWith('+00:00Z')) {
    return new Date(s.slice(0, -6) + 'Z');
  }
  return new Date(s);
}

/** Sort emails by received_at descending (most recent first). */
const _isHexEmailId = (id: string) => /[a-f]/i.test(id) && id.length > 8;

function sortByDateDesc(emails: Email[]): Email[] {
  // Single-pass sort + dedup: build a Map keyed by content key (subject+minute+sender).
  // This merges IMAP/Gmail duplicates AND deduplicates by ID in one pass over the
  // already-sorted input, avoiding intermediate array allocations.
  // Pre-compute timestamps to avoid repeated Date parsing in sort comparator (O(n log n) → O(n))
  const tsCache = new Map<string, number>();
  for (const e of emails) {
    if (!tsCache.has(e.id)) tsCache.set(e.id, parseDate(e.received_at).getTime());
  }
  const sorted = [...emails].sort((a, b) =>
    (tsCache.get(b.id) || 0) - (tsCache.get(a.id) || 0)
  );

  const seenIds = new Set<string>();
  const contentSeen = new Map<string, Email>();
  for (const email of sorted) {
    // Pass 1: skip exact ID duplicates
    if (seenIds.has(email.id)) continue;
    seenIds.add(email.id);

    // Pass 2: merge Gmail hex ID / IMAP int ID pairs
    const key = `${email.subject}___${email.received_at.slice(0, 16)}___${email.sender}`;
    const existing = contentSeen.get(key);
    if (!existing) {
      contentSeen.set(key, email);
    } else {
      const mergedAttachments = email.has_attachments || existing.has_attachments;
      const mergedDraft = email.has_pending_draft || existing.has_pending_draft;
      const keepHex = _isHexEmailId(email.id) && !_isHexEmailId(existing.id);
      if (keepHex) {
        contentSeen.set(key, { ...email, has_attachments: mergedAttachments, has_pending_draft: mergedDraft });
      } else if (!_isHexEmailId(email.id) && _isHexEmailId(existing.id)) {
        contentSeen.set(key, { ...existing, has_attachments: mergedAttachments, has_pending_draft: mergedDraft });
      }
    }
  }
  return Array.from(contentSeen.values());
}

function mergeFreshRowsIntoVisibleSearch(visibleEmails: Email[], freshEmails: Email[]): Email[] {
  const freshById = new Map(freshEmails.map(email => [email.id, email]));
  return visibleEmails.map(email => {
    const fresh = freshById.get(email.id);
    return fresh ? { ...email, ...fresh } : email;
  });
}

function formatEmailTime(dateString: string): string {
  // Invalidate cache at day boundary
  const today = new Date().toDateString();
  if (today !== _dateFormatCacheDay) {
    _dateFormatCache.clear();
    _dateFormatCacheDay = today;
  }
  const cacheKey = `${dateString}__${i18n.language}`;
  const cached = _dateFormatCache.get(cacheKey);
  if (cached) return cached;

  const date = parseDate(dateString);
  const now = new Date();

  const isToday = date.toDateString() === now.toDateString();
  let result: string;

  if (isToday) {
    // QA 2026-05-19 — Bug #5: was hardcoded "${hours}h${minutes}", which
    // produced French-style "13h53" in an English UI that otherwise renders
    // dates like "May 14th". Route through the locale-aware helper so EN/ES
    // get "13:53" while FR keeps "13h53".
    result = formatHourMinute(date, i18n.language);
  } else {
    const day = date.getDate();
    const monthName = date.toLocaleString(i18n.language, { month: 'short' });
    result = i18n.language.startsWith('en')
      ? `${monthName} ${getOrdinalSuffix(day)}`
      : `${day} ${monthName}`;
  }

  _dateFormatCache.set(cacheKey, result);
  return result;
}

function getOrdinalSuffix(n: number): string {
  const v = n % 100;
  if (v >= 11 && v <= 13) return `${n}th`;
  switch (n % 10) {
    case 1: return `${n}st`;
    case 2: return `${n}nd`;
    case 3: return `${n}rd`;
    default: return `${n}th`;
  }
}

function getDateSectionKey(dateString: string): string {
  const date = parseDate(dateString);
  const now = new Date();

  const isToday = date.toDateString() === now.toDateString();
  if (isToday) return 'today';

  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return 'yesterday';

  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfEmailDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const diffDays = Math.floor((startOfToday.getTime() - startOfEmailDay.getTime()) / (1000 * 60 * 60 * 24));

  if (diffDays <= 7) {
    // Use local date components (not toISOString which returns UTC and can shift the day)
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const d = String(date.getDate()).padStart(2, '0');
    return `day-${y}-${m}-${d}`;
  }

  return `month-${date.getFullYear()}-${date.getMonth()}`;
}

function getSectionLabel(sectionKey: string, yesterdayLabel: string, todayLabel?: string): string {
  if (sectionKey === 'today') return todayLabel || '';
  if (sectionKey === 'yesterday') return yesterdayLabel;

  if (sectionKey.startsWith('day-')) {
    const dateStr = sectionKey.replace('day-', '');
    const date = new Date(dateStr + 'T00:00:00');
    const day = date.getDate();
    const monthName = date.toLocaleString(i18n.language, { month: 'long' });
    if (i18n.language.startsWith('en')) {
      return `${monthName} ${getOrdinalSuffix(day)}`;
    }
    return `${day} ${monthName}`;
  }

  if (sectionKey.startsWith('month-')) {
    const parts = sectionKey.replace('month-', '').split('-');
    const year = parseInt(parts[0]);
    const month = parseInt(parts[1]);
    const date = new Date(year, month, 1);
    const monthName = date.toLocaleString(i18n.language, { month: 'long' });

    // QA 2026-05-19 — Bug #8: when an inbox contains both day-headers like
    // "May 12th" (for emails ≤7 days old) and a month-year header like
    // "May 2026" (for older emails in the same month), the timeline reads
    // as nonsense — a "May 2026" group appearing AFTER "May 12th" but
    // containing earlier dates in May. Special-case the current month/year
    // ("Earlier this month") and drop the year for other months in the
    // current year so the headers form a clean descending timeline.
    const now = new Date();
    if (year === now.getFullYear() && month === now.getMonth()) {
      return i18n.t('inbox:earlier_this_month', 'Earlier this month');
    }
    if (year === now.getFullYear()) {
      return monthName;
    }
    return `${monthName} ${year}`;
  }

  return sectionKey;
}

/**
 * P3-23 (2026-05-17): normalize a display name across Inbox / Sent rows.
 *
 * Previously Inbox showed the IMAP `sender_name` header verbatim (usually
 * already titlecased — "Alexandre Simon") while Sent showed the raw
 * local-part of the recipient address ("alexandre.simon"). Two rows
 * for the same human looked like two different people. This helper
 * titlecases a `local.part` fallback when no display-name is available
 * so Inbox and Sent render the same string for the same contact.
 *
 * Rules:
 *   - If `displayName` is present and isn't itself an email, use it.
 *   - If `displayName` is an email, strip the domain and titlecase the
 *     local part.
 *   - Otherwise titlecase the supplied `localPart` (splitting on `.`, `_`,
 *     `-`, `+`).
 */
function formatDisplayName(displayName: string | null | undefined, localPart: string): string {
  const titleCase = (raw: string) =>
    raw
      .split(/[._\-+]/)
      .filter(Boolean)
      .map((p) => p.charAt(0).toUpperCase() + p.slice(1).toLowerCase())
      .join(' ');
  if (displayName && displayName.trim()) {
    const dn = displayName.trim();
    if (dn.includes('@')) {
      return titleCase(dn.substring(0, dn.indexOf('@')));
    }
    return dn;
  }
  return titleCase(localPart);
}

/** Bare, comparable email address from a raw sender string ("Name <a@b.com>" or "a@b.com"). */
function senderAddress(sender: string): string {
  if (!sender) return '';
  const m = sender.match(/<([^>]+)>/);
  return (m ? m[1] : sender).trim().toLowerCase();
}

function getSenderDisplay(email: Email): string {
  const sender = email.sender ?? '';
  const atIndex = sender.indexOf('@');
  const localPart = atIndex > 0 ? sender.substring(0, atIndex) : sender;
  return formatDisplayName(email.sender_name, localPart);
}

/** For sent folder: show first recipient instead of sender (which is always the user). */
function getRecipientDisplay(email: Email, noRecipientLabel: string): string {
  if (email.to && email.to.length > 0) {
    const first = email.to[0];
    // Extract "Name <email>" → name; otherwise titlecase the local part.
    const match = first.match(/^(.+?)\s*<(.+)>$/);
    if (match) {
      const candidateName = match[1].trim().replace(/^"|"$/g, '');
      const candidateEmail = match[2].trim();
      const atIndex = candidateEmail.indexOf('@');
      const localPart = atIndex > 0 ? candidateEmail.substring(0, atIndex) : candidateEmail;
      return formatDisplayName(candidateName, localPart);
    }
    const atIndex = first.indexOf('@');
    const localPart = atIndex > 0 ? first.substring(0, atIndex) : first;
    return formatDisplayName(null, localPart);
  }
  // No parsed recipient: a sent email with no `to` would otherwise fall back to
  // the sender — i.e. the user — reading as if they emailed themselves. Show a
  // neutral placeholder instead.
  return noRecipientLabel;
}

function searchResultToEmail(result: SearchResult): Email {
  return {
    id: result.email_id,
    sender: result.sender,
    sender_name: null,
    subject: result.subject,
    received_at: result.date,
    has_attachments: (result as unknown as Record<string, unknown>).has_attachments as boolean || false,
    conversation_id: null,
    is_read: result.is_read,
    body_preview: result.snippet,
  };
}

function filterByStatus(emails: Email[], status: EmailStatus): Email[] {
  switch (status) {
    case 'unread':
      return emails.filter((e) => !e.is_read);
    case 'read':
      return emails.filter((e) => e.is_read);
    case 'draft_ready':
    case 'sent':
      return emails;
    case 'all':
    default:
      return emails;
  }
}

// ============================================================================
// FLATTENED ROW MODEL (used by virtualized list)
// ============================================================================

type FlatRow =
  | { type: 'header'; label: string; key: string }
  | { type: 'snooze-woken-header'; key: string }
  | { type: 'pinned-header'; key: string }
  | { type: 'email'; email: Email; snoozedUntil?: string; isWoken?: boolean; isFollowup?: boolean; isPinned?: boolean; key: string }
  | { type: 'loading'; key: string };

function flattenEmailsWithHeaders(
  emails: Email[],
  hasMore: boolean,
  wokeIds?: Set<string>,
  snoozedMap?: Map<string, { date: string; type?: 'snooze' | 'followup' }>,
  sleepingIds?: Set<string>,
  pinnedIds?: Set<string>,
  wokeFollowupIds?: Set<string>,
  yesterdayLabel?: string,
  todayLabel?: string,
): FlatRow[] {
  const rows: FlatRow[] = [];

  const seenIds = new Set<string>();

  // 0. Manually pinned emails at top
  if (pinnedIds && pinnedIds.size > 0) {
    const pinnedEmails = emails.filter(e => pinnedIds.has(e.id) && !seenIds.has(e.id));
    if (pinnedEmails.length > 0) {
      rows.push({ type: 'pinned-header', key: 'pinned-header' });
      for (const email of pinnedEmails) {
        seenIds.add(email.id);
        const isWoken = wokeIds?.has(email.id) ?? false;
        const isFollowup = isWoken && (wokeFollowupIds?.has(email.id) || snoozedMap?.get(email.id)?.type === 'followup');
        rows.push({ type: 'email', email, isPinned: true, isWoken: isWoken || undefined, isFollowup: isFollowup || undefined, key: `pinned-${email.id}` });
      }
    }
  }

  // 1. Pinned woken emails at top
  if (wokeIds && wokeIds.size > 0) {
    const wokeEmails = emails.filter(e => wokeIds.has(e.id) && !seenIds.has(e.id));
    if (wokeEmails.length > 0) {
      // Sort by snooze date most recent first
      wokeEmails.sort((a, b) => {
        const da = snoozedMap?.get(a.id)?.date ?? '';
        const db = snoozedMap?.get(b.id)?.date ?? '';
        return db.localeCompare(da);
      });
      rows.push({ type: 'snooze-woken-header', key: 'snooze-woken-header' });
      for (const email of wokeEmails) {
        seenIds.add(email.id);
        const isFollowup = wokeFollowupIds?.has(email.id) || snoozedMap?.get(email.id)?.type === 'followup';
        rows.push({ type: 'email', email, isWoken: true, isFollowup, key: `woken-${email.id}` });
      }
    }
  }

  // 2. Normal date-sorted emails (sleeping ones carry snoozedUntil metadata)
  let currentSection = '';
  for (const email of emails) {
    if (seenIds.has(email.id)) continue;
    // Sleeping emails are hidden from the list — they reappear pinned at top when they wake
    if (sleepingIds?.has(email.id)) continue;
    seenIds.add(email.id);

    const sectionKey = getDateSectionKey(email.received_at);
    if (sectionKey !== currentSection) {
      currentSection = sectionKey;
      const label = getSectionLabel(sectionKey, yesterdayLabel ?? 'Hier', todayLabel);
      if (label) {
        rows.push({ type: 'header', label, key: `header-${sectionKey}` });
      }
    }
    rows.push({ type: 'email', email, key: email.id });
  }

  if (hasMore) {
    rows.push({ type: 'loading', key: 'loading-sentinel' });
  }

  return rows;
}

// ============================================================================
// VIRTUALIZED ROW COMPONENT (react-window v2 API)
// ============================================================================

interface VirtualRowProps {
  flatRows: FlatRow[];
  selectedEmailId?: string | null;
  handleEmailClick: (email: Email) => void;
  onSwipeArchive?: (email: Email) => void | Promise<void>;
  onSwipeDelete?: (email: Email) => void | Promise<void>;
  handleMarkReadToggle: (email: Email, isRead: boolean) => void;
  handleLabelUpdate: (email: Email, newLabels: EmailLabel[], silent?: boolean) => void;
  showToast: (message: string, type: ToastType) => void;
  multiSelectMode: boolean;
  selectedIds: Set<string>;
  handleCheckChange: (email: Email, checked: boolean) => void;
  handleShiftClick: (email: Email) => void;
  animatingEmailId: string | null;
  animationType: 'archive' | 'delete' | null;
  shiftBelowIndex?: number | null;
  shiftAmount?: number;
  onEmailHover: (emailId: string) => void;
  onEmailHoverEnd: () => void;
  /** Immediate hover tracking — used by QuickStepsListHotkeys to know
   *  which row a global shortcut should target. Distinct from
   *  ``onEmailHover`` which is debounced for prefetch. */
  onSetHoveredImmediate?: (emailId: string | null) => void;
  localDraftEmailIds?: Set<string>;
  getSenderDisplayFn?: (email: Email) => string;
  folder?: string;
  onNotSpam?: (email: Email) => void;
  onRestore?: (email: Email) => void;
  onMoveToSpam?: (email: Email) => void;
  onBlockSender?: (email: Email) => void;
  onUnarchive?: (email: Email) => void;
  onDeleteDraft?: (email: Email) => void;
  viewMode?: EmailViewMode;
  threadCounts?: Map<string, number>;
  dismissSnoozed?: (emailId: string) => void;
  pinnedIds?: Set<string>;
  onPinToggle?: (email: Email) => void;
  userLabelNames?: ReadonlySet<string>;
  onOpenSnooze?: (email: Email, pos: { x: number; y: number }) => void;
  followupPendingKeys?: ReadonlySet<string>;
  triagePendingIds?: ReadonlySet<string>;
}

const VirtualRow = React.memo(function VirtualRow({
  index,
  style,
  flatRows,
  selectedEmailId,
  handleEmailClick,
  onSwipeArchive,
  onSwipeDelete,
  handleMarkReadToggle,
  handleLabelUpdate,
  showToast,
  multiSelectMode,
  selectedIds,
  handleCheckChange,
  handleShiftClick,
  animatingEmailId,

  animationType: _animationType,
  shiftBelowIndex,
  shiftAmount = EMAIL_ITEM_HEIGHT_COMPACT,
  onEmailHover,
  onEmailHoverEnd,
  onSetHoveredImmediate,
  localDraftEmailIds,
  getSenderDisplayFn,
  folder,
  onNotSpam,
  onRestore,
  onMoveToSpam,
  onBlockSender,
  onUnarchive,
  onDeleteDraft,
  viewMode,
  threadCounts,
  dismissSnoozed,
  pinnedIds,
  onPinToggle,
  userLabelNames,
  onOpenSnooze,
  followupPendingKeys,
  triagePendingIds,
}: VirtualRowProps & { index: number; style: React.CSSProperties; ariaAttributes: Record<string, unknown> }) {
  const { t: tCommonRow } = useTranslation('common');
  const row = flatRows[index];

  if (!row || row.type === 'loading') {
    return (
      <div style={style} className="email-list-loading-more">
        <div className="loading-spinner-small" />
        <span>{tCommonRow('loading')}</span>
      </div>
    );
  }

  if (row.type === 'pinned-header') {
    return (
      <div style={style} className="email-date-separator">
        <span className="email-date-label">{tCommonRow('pinned_section', 'Pinned')}</span>
      </div>
    );
  }

  if (row.type === 'snooze-woken-header') {
    return (
      <div style={style} className="email-date-separator">
        <span className="email-date-label">{tCommonRow('woken_section', 'Back in inbox')}</span>
      </div>
    );
  }

  if (row.type === 'header') {
    const isHeaderShifting = shiftBelowIndex != null && shiftBelowIndex >= 0 && index > shiftBelowIndex;
    const headerShiftStyle = isHeaderShifting
      ? { '--shift-amount': `-${shiftAmount}px` } as React.CSSProperties
      : {};
    return (
      <div
        style={{ ...style, ...headerShiftStyle }}
        className={['email-date-separator', isHeaderShifting ? 'email-item-shift-up' : ''].filter(Boolean).join(' ')}
      >
        <span className="email-date-label">{row.label}</span>
      </div>
    );
  }

  const email = row.email;
  const isAnimating = animatingEmailId === email.id;
  const animationClass = isAnimating ? 'email-item-slide-left' : '';
  const isShiftingUp = shiftBelowIndex != null && shiftBelowIndex >= 0 && index > shiftBelowIndex;
  const shiftStyle = isShiftingUp
    ? { '--shift-amount': `-${shiftAmount}px` } as React.CSSProperties
    : {};

  const handleSelectWithDismiss = (e: Email) => {
    if (row.isWoken && dismissSnoozed) {
      dismissSnoozed(e.id);
    }
    handleEmailClick(e);
  };

  return (
    <div
      style={{ ...style, ...shiftStyle }}
      className={[
        isShiftingUp ? 'email-item-shift-up' : '',
        isAnimating ? 'email-item-animating-row' : '',
      ].filter(Boolean).join(' ')}
      onMouseEnter={() => { onSetHoveredImmediate?.(email.id); onEmailHover(email.id); }}
      onMouseLeave={() => { onSetHoveredImmediate?.(null); onEmailHoverEnd(); }}
    >
      <div className={animationClass} style={{ width: '100%', height: '100%' }}>
      <SwipeableEmailItem
        email={email}
        selected={selectedEmailId === email.id}
        onSelect={handleSelectWithDismiss}
        onSwipeArchive={onSwipeArchive}
        onSwipeDelete={onSwipeDelete}
        onMarkReadToggle={handleMarkReadToggle}
        onLabelUpdate={handleLabelUpdate}
        onToast={showToast}
        formatTime={formatEmailTime}
        getSenderDisplay={getSenderDisplayFn || getSenderDisplay}
        multiSelectMode={multiSelectMode}
        isChecked={selectedIds.has(email.id)}
        selectedIds={selectedIds}
        onCheckChange={handleCheckChange}
        onShiftClick={handleShiftClick}
        hasLocalDraft={localDraftEmailIds?.has(email.id) ?? false}
        folder={folder}
        onNotSpam={onNotSpam}
        onRestore={onRestore}
        onMoveToSpam={onMoveToSpam}
        onBlockSender={onBlockSender}
        onUnarchive={onUnarchive}
        onDeleteDraft={onDeleteDraft}
        viewMode={viewMode}
        threadCount={email.thread_count ?? threadCounts?.get(email.conversation_id || '') ?? 0}
        snoozedUntil={row.snoozedUntil}
        isWoken={row.isWoken}
        isFollowup={row.type === 'email' ? row.isFollowup : undefined}
        isPinned={row.type === 'email' ? (row.isPinned ?? pinnedIds?.has(email.id)) : undefined}
        onPinToggle={onPinToggle}
        userLabelNames={userLabelNames}
        /* Follow-up nudge chip suppressed in the Sent tab (2026-06-01): the
           `recipient::subject` key only ever matches there, so this gate
           removes the 🔁 Follow-up pill from Sent rows per user request. */
        hasPendingFollowup={folder !== 'sent' && (followupPendingKeys?.has(`${email.to?.[0]}::${email.subject}`.toLowerCase()) ?? false)}
        onOpenSnooze={onOpenSnooze}
        isTriagePending={triagePendingIds?.has(email.id) ?? false}
      />
      </div>
    </div>
  );
});

// ============================================================================
// VIRTUALIZED EMAIL LIST CONTENT
// ============================================================================

interface EmailListContentProps {
  filteredEmails: Email[];
  selectedEmailId?: string | null;
  handleEmailClick: (email: Email) => void;
  onSwipeArchive?: (email: Email) => void | Promise<void>;
  onSwipeDelete?: (email: Email) => void | Promise<void>;
  handleMarkReadToggle: (email: Email, isRead: boolean) => void;
  handleLabelUpdate: (email: Email, newLabels: EmailLabel[], silent?: boolean) => void;
  showToast: (message: string, type: ToastType) => void;
  multiSelectMode: boolean;
  selectedIds: Set<string>;
  handleCheckChange: (email: Email, checked: boolean) => void;
  handleShiftClick: (email: Email) => void;
  animatingEmailId: string | null;
  animationType: 'archive' | 'delete' | null;
  shiftBelowIndex?: number | null;
  shiftAmount?: number;
  flatRowsRef?: React.MutableRefObject<FlatRow[]>;
  onLoadMore?: () => void;
  hasMore?: boolean;
  isLoadingMore?: boolean;
  localDraftEmailIds?: Set<string>;
  getSenderDisplayFn?: (email: Email) => string;
  folder?: string;
  onNotSpam?: (email: Email) => void;
  onRestore?: (email: Email) => void;
  onMoveToSpam?: (email: Email) => void;
  onBlockSender?: (email: Email) => void;
  onUnarchive?: (email: Email) => void;
  onDeleteDraft?: (email: Email) => void;
  viewMode?: EmailViewMode;
  threadCounts?: Map<string, number>;
  wokeIds?: Set<string>;
  wokeFollowupIds?: Set<string>;
  sleepingIds?: Set<string>;
  snoozedMap?: Map<string, { date: string }>;
  dismissSnoozed?: (emailId: string) => void;
  pinnedIds?: Set<string>;
  onPinToggle?: (email: Email) => void;
  userLabelNames?: ReadonlySet<string>;
  onOpenSnooze?: (email: Email, pos: { x: number; y: number }) => void;
  triagePendingIds?: ReadonlySet<string>;
}

const EmailListContent = React.memo(function EmailListContent({
  filteredEmails,
  selectedEmailId,
  handleEmailClick,
  onSwipeArchive,
  onSwipeDelete,
  handleMarkReadToggle,
  handleLabelUpdate,
  showToast,
  multiSelectMode,
  selectedIds,
  handleCheckChange,
  handleShiftClick,
  animatingEmailId,
  animationType,
  shiftBelowIndex,
  shiftAmount = EMAIL_ITEM_HEIGHT_COMPACT,
  flatRowsRef,
  onLoadMore,
  hasMore = false,
  isLoadingMore = false,
  localDraftEmailIds,
  getSenderDisplayFn,
  folder,
  onNotSpam,
  onRestore,
  onMoveToSpam,
  onBlockSender,
  onUnarchive,
  onDeleteDraft,
  viewMode = 'compact',
  threadCounts,
  wokeIds,
  wokeFollowupIds,
  snoozedMap,
  sleepingIds,
  dismissSnoozed,
  pinnedIds,
  onPinToggle,
  userLabelNames,
  onOpenSnooze,
  triagePendingIds,
}: EmailListContentProps) {
  const { t: tCommonContent } = useTranslation('common');
  const sortedFilteredEmails = useMemo(() => sortByDateDesc(filteredEmails), [filteredEmails]);

  // ⚡ Auto badges — decorate inbox rows the user's Quick Step rules
  // auto-actioned (only rules with `showAutoBadge=true`). Best-effort
  // single GET per debounced id-slice ; failures degrade to no badge.
  // Important : the spread only fires when a badge exists for the row,
  // so existing email object references are preserved unchanged
  // otherwise — keeps React.memo'd children stable across re-renders.
  const autoBadgeIds = useMemo(
    () => sortedFilteredEmails.map(e => e.id),
    [sortedFilteredEmails],
  );
  const autoBadges = useAutoBadges(autoBadgeIds);
  const decoratedEmails = useMemo(
    () => sortedFilteredEmails.map(e =>
      autoBadges[e.id] ? { ...e, auto_badge: autoBadges[e.id] } : e
    ),
    [sortedFilteredEmails, autoBadges]
  );

  const flatRows = useMemo(
    () => flattenEmailsWithHeaders(decoratedEmails, hasMore, wokeIds, snoozedMap, sleepingIds, pinnedIds, wokeFollowupIds, tCommonContent('yesterday'), tCommonContent('today', "Aujourd'hui")),
    [decoratedEmails, hasMore, wokeIds, snoozedMap, sleepingIds, pinnedIds, wokeFollowupIds, tCommonContent]
  );

  // Keep flatRowsRef in sync so parent handlers can find email indices
  useEffect(() => {
    if (flatRowsRef) flatRowsRef.current = flatRows;
  }, [flatRows, flatRowsRef]);

  const emailItemHeight = viewMode === 'comfortable'
    ? EMAIL_ITEM_HEIGHT_COMFORTABLE
    : viewMode === 'balanced'
    ? EMAIL_ITEM_HEIGHT_BALANCED
    : EMAIL_ITEM_HEIGHT_COMPACT;

  const getRowHeight = useCallback(
    (index: number) => {
      const row = flatRows[index];
      if (!row || row.type === 'loading') return 48;
      if (row.type === 'header') return SECTION_HEADER_HEIGHT;
      // QA 2026-06-12: these were 0px, so pinned/woken rows (often weeks old)
      // rendered flush against the tab bar with no separator — the first row
      // looked clipped/broken and its out-of-order date had no explanation.
      // Render them like regular date separators, with a label.
      if (row.type === 'snooze-woken-header') return SECTION_HEADER_HEIGHT;
      if (row.type === 'pinned-header') return SECTION_HEADER_HEIGHT;
      return emailItemHeight;
    },
    [flatRows, emailItemHeight]
  );

  // Infinite scroll trigger via onRowsRendered
  const handleRowsRendered = useCallback(
    (_visibleRows: { startIndex: number; stopIndex: number }, allRows: { startIndex: number; stopIndex: number }) => {
      if (
        hasMore &&
        !isLoadingMore &&
        onLoadMore &&
        allRows.stopIndex >= flatRows.length - INFINITE_SCROLL_THRESHOLD
      ) {
        onLoadMore();
      }
    },
    [hasMore, isLoadingMore, onLoadMore, flatRows.length]
  );

  // Prefetch email detail on hover (200ms delay)
  const hoverTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleEmailHover = useCallback((emailId: string) => {
    if (!HOVER_PREFETCH_ENABLED) return;
    if (hoverTimeoutRef.current) clearTimeout(hoverTimeoutRef.current);
    hoverTimeoutRef.current = setTimeout(() => {
      prefetchSingleEmail(emailId);
    }, 200);
  }, []);
  const handleEmailHoverEnd = useCallback(() => {
    if (hoverTimeoutRef.current) {
      clearTimeout(hoverTimeoutRef.current);
      hoverTimeoutRef.current = null;
    }
  }, []);

  // Quick Actions plumbing — hovered row id (immediate, for keyboard shortcut
  // targeting) and right-click context-menu state. Both live at the list
  // level so the row component stays memoized.
  const [hoveredEmailIdNow, setHoveredEmailIdNow] = useState<string | null>(null);
  const lastHoverIdRef = useRef<string | null>(null);
  const handleSetHoveredImmediate = useCallback((emailId: string | null) => {
    if (emailId === null) {
      // Only clear if the most recent enter was for this row — avoids
      // races between adjacent rows whose enter/leave events fire
      // out of order during fast cursor sweeps.
      setHoveredEmailIdNow(prev => (prev === lastHoverIdRef.current ? null : prev));
      lastHoverIdRef.current = null;
    } else {
      lastHoverIdRef.current = emailId;
      setHoveredEmailIdNow(emailId);
    }
  }, []);

  const { pendingKeys: followupPendingKeys } = useFollowupNudgeCount();

  // Memoized rowProps passed to every row via react-window v2
  const rowProps = useMemo(() => ({
    flatRows,
    selectedEmailId,
    handleEmailClick,
    onSwipeArchive,
    onSwipeDelete,
    handleMarkReadToggle,
    handleLabelUpdate,
    showToast,
    multiSelectMode,
    selectedIds,
    handleCheckChange,
    handleShiftClick,
    animatingEmailId,
    animationType,
    shiftBelowIndex,
    shiftAmount,
    onEmailHover: handleEmailHover,
    onEmailHoverEnd: handleEmailHoverEnd,
    onSetHoveredImmediate: handleSetHoveredImmediate,
    localDraftEmailIds,
    getSenderDisplayFn,
    folder,
    onNotSpam,
    onRestore,
    onMoveToSpam,
    onBlockSender,
    onUnarchive,
    onDeleteDraft,
    viewMode,
    threadCounts,
    dismissSnoozed,
    pinnedIds,
    onPinToggle,
    userLabelNames,
    onOpenSnooze,
    followupPendingKeys,
    triagePendingIds,
  }), [
    flatRows,
    selectedEmailId,
    handleEmailClick,
    onSwipeArchive,
    onSwipeDelete,
    handleMarkReadToggle,
    handleLabelUpdate,
    showToast,
    multiSelectMode,
    selectedIds,
    handleCheckChange,
    handleShiftClick,
    animatingEmailId,
    animationType,
    shiftBelowIndex,
    shiftAmount,
    handleEmailHover,
    handleEmailHoverEnd,
    handleSetHoveredImmediate,
    localDraftEmailIds,
    getSenderDisplayFn,
    folder,
    onNotSpam,
    onRestore,
    onMoveToSpam,
    onBlockSender,
    onUnarchive,
    onDeleteDraft,
    viewMode,
    threadCounts,
    dismissSnoozed,
    pinnedIds,
    onPinToggle,
    userLabelNames,
    onOpenSnooze,
    followupPendingKeys,
    triagePendingIds,
  ]);

  return (
    <div className="email-list-virtualized" data-testid="email-list" role="listbox" aria-label="Liste des emails">
      <List<VirtualRowProps>
        rowComponent={VirtualRow as unknown as (props: { ariaAttributes: { "aria-posinset": number; "aria-setsize": number; role: "listitem" }; index: number; style: React.CSSProperties } & VirtualRowProps) => React.ReactElement | null}
        rowCount={flatRows.length}
        rowHeight={getRowHeight}
        rowProps={rowProps as VirtualRowProps}
        onRowsRendered={handleRowsRendered}
        overscanCount={3}
        defaultHeight={600}
      />
      <div aria-live="polite" className="sr-only">
        {filteredEmails.length} emails
      </div>
      <QuickStepsListHotkeys
        hoveredEmailId={hoveredEmailIdNow}
        selectedEmailId={selectedEmailId ?? null}
      />
    </div>
  );
});

/**
 * Skeleton loading placeholder for email list items
 */
function EmailSkeletonItem() {
  return (
    <div className="email-skeleton-item">
      <div className="skeleton-row">
        <div className="skeleton-avatar" />
        <div className="skeleton-text sender" />
        <div className="skeleton-text date" />
      </div>
      <div className="skeleton-text subject" />
      <div className="skeleton-text preview" />
    </div>
  );
}

function EmailSkeletonList({ count = 8 }: { count?: number }) {
  return (
    <div className="email-skeleton-list" data-testid="email-skeleton-list" aria-live="polite" aria-busy="true" role="status">
      {Array.from({ length: count }).map((_, i) => (
        <EmailSkeletonItem key={i} />
      ))}
    </div>
  );
}


export const EmailList = React.memo(function EmailList({ onEmailSelect, selectedEmailId, onEmailsLoaded, onSwipeArchive: _onSwipeArchive, onSwipeDelete: _onSwipeDelete, onToast, folder = 'inbox', activeLabel, onLabelChange, refreshTrigger, onDisplayedEmailsChange, onNavigateUp: _onNavigateUp, onNavigateDown: _onNavigateDown, onReply: _onReply, onForward: _onForward, onArchive: _onArchive, onDelete: _onDelete, onToggleRead: _onToggleRead, onSearch: _onSearch, onNewMessage: _onNewMessage, onReplyAll: _onReplyAll, onSearchRef, onOpenAccounts, providerLabel, localDraftEmailIds, accountEmail, bulkArchiveRef, bulkDeleteRef, bulkNotSpamRef, bulkRestoreRef, deselectAllRef, selectAllRef, selectAllFromHereRef, deleteEmailOptimisticRef, archiveEmailOptimisticRef, onDeleteDraft, accountId }: EmailListProps) {
  const { t } = useTranslation('inbox');
  const { t: tErrors } = useTranslation('errors');
  const folderTitles: Record<EmailFolder, string> = {
    inbox: t('title'),
    sent: t('sent'),
    archived: t('archive'),
    spam: t('spam'),
    trash: t('trash'),
  };
  const folderTitle = folderTitles[folder];
  const { labels: allLabels, favoriteLabels, labelCounts, refreshCounts } = useSharedLabels();
  const userLabelNames = useMemo(() => new Set(allLabels.map(l => l.name)), [allLabels]);

  const { hideNoise, toggleHideNoise } = useHideNoiseSetting(accountId);
  const { autoDeleteNoise } = useAutoDeleteNoiseSetting(accountId);
  const { autoEmptySpam } = useAutoEmptySpamSetting(accountId);
  const { autoEmptyTrash } = useAutoEmptyTrashSetting(accountId);
  const { viewMode } = useEmailViewMode();
  const snooze = useSnooze();
  const { pinnedIds, togglePin, addPin } = usePinned();
  const [snoozeTarget, setSnoozeTarget] = useState<{ email: Email; pos: { x: number; y: number } } | null>(null);
  const handleOpenSnooze = useCallback((email: Email, pos: { x: number; y: number }) => {
    setSnoozeTarget({ email, pos });
  }, []);

  // Auto-pin woken reminders
  useEffect(() => {
    for (const emailId of snooze.wokeIds) {
      addPin(emailId);
    }
  }, [snooze.wokeIds, addPin]);
  const [emails, setEmails] = useState<Email[]>([]);
  const [loadingState, setLoadingState] = useState<EmailLoadingState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [noAccount, setNoAccount] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  const [statusFilter, _setStatusFilter] = useState<EmailStatus>('all');
  const [isSearching, setIsSearching] = useState(false);
  const [showSearchBar, setShowSearchBar] = useState(false);
  // Multi-select state
  const [multiSelectMode, setMultiSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [, setIsBulkLoading] = useState(false);
  const isBulkLoadingRef = useRef(false);
  // Always-fresh refs so bulk handlers never capture stale closures
  const selectedIdsRef = useRef<Set<string>>(selectedIds);
  selectedIdsRef.current = selectedIds;
  const multiSelectModeRef = useRef(multiSelectMode);
  multiSelectModeRef.current = multiSelectMode;

  // Sync multi-select state to module-level flag so hover shortcuts don't interfere
  useEffect(() => {
    setMultiSelectActive(multiSelectMode);
    return () => setMultiSelectActive(false);
  }, [multiSelectMode]);

  const [animatingEmailId, setAnimatingEmailId] = useState<string | null>(null);
  const [animationType, setAnimationType] = useState<'archive' | 'delete' | null>(null);
  const [triagePendingIds, setTriagePendingIds] = useState<Set<string>>(() => new Set());
  const [shiftBelowIndex, _setShiftBelowIndex] = useState<number | null>(null);
  const [shiftAmount, _setShiftAmount] = useState<number>(EMAIL_ITEM_HEIGHT_COMPACT);
  const flatRowsRef = useRef<FlatRow[]>([]);
  const { toasts, addToast, dismissToast } = useToast();
  // Infinite scroll state
  const [hasMore, setHasMore] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const currentOffsetRef = useRef(0);
  // Deduplication: track email IDs with pending archive/delete to prevent double-calls
  const pendingOpsRef = useRef<Set<string>>(new Set());
  const locallyHiddenEmailKeysRef = useRef<Map<string, number>>(new Map());
  const hiddenKeyFor = useCallback((emailFolder: string, emailId: string) => `${emailFolder}:${emailId}`, []);
  const pruneLocallyHiddenEmails = useCallback(() => {
    const now = Date.now();
    for (const [key, expiresAt] of locallyHiddenEmailKeysRef.current.entries()) {
      if (expiresAt <= now) {
        locallyHiddenEmailKeysRef.current.delete(key);
      }
    }
  }, []);
  const hideEmailInCurrentFolder = useCallback((emailId: string) => {
    pruneLocallyHiddenEmails();
    locallyHiddenEmailKeysRef.current.set(hiddenKeyFor(folder, emailId), Date.now() + 60000);
  }, [folder, hiddenKeyFor, pruneLocallyHiddenEmails]);
  const markTriagePending = useCallback((emailId: string) => {
    setTriagePendingIds(prev => {
      if (prev.has(emailId)) return prev;
      const next = new Set(prev);
      next.add(emailId);
      return next;
    });
  }, []);
  const clearTriagePending = useCallback((emailId: string) => {
    setTriagePendingIds(prev => {
      if (!prev.has(emailId)) return prev;
      const next = new Set(prev);
      next.delete(emailId);
      return next;
    });
  }, []);
  const markBulkTriagePending = useCallback((emailIds: string[]) => {
    if (emailIds.length === 0) return;
    setTriagePendingIds(prev => {
      const next = new Set(prev);
      for (const emailId of emailIds) next.add(emailId);
      return next.size === prev.size ? prev : next;
    });
  }, []);
  const clearBulkTriagePending = useCallback((emailIds: string[]) => {
    if (emailIds.length === 0) return;
    setTriagePendingIds(prev => {
      let changed = false;
      const next = new Set(prev);
      for (const emailId of emailIds) {
        changed = next.delete(emailId) || changed;
      }
      return changed ? next : prev;
    });
  }, []);
  const clearEmailHiddenInFolder = useCallback((emailFolder: string, emailId: string) => {
    locallyHiddenEmailKeysRef.current.delete(hiddenKeyFor(emailFolder, emailId));
  }, [hiddenKeyFor]);
  const filterHiddenFromCurrentFolder = useCallback((emailList: Email[]) => {
    pruneLocallyHiddenEmails();
    return emailList.filter(email => {
      return !locallyHiddenEmailKeysRef.current.has(hiddenKeyFor(folder, email.id));
    });
  }, [folder, hiddenKeyFor, pruneLocallyHiddenEmails]);
  const showToast = useCallback((message: string, type: ToastType) => {
    if (onToast) {
      onToast(message, type as 'error' | 'success' | 'info');
    } else {
      addToast(message, type);
    }
  }, [onToast, addToast]);

  const removeEmailAfterSuccessfulTriage = useCallback((
    email: Email,
    targetFolder: string,
    type: 'archive' | 'delete',
    afterRemove?: () => void,
  ) => {
    hideEmailInCurrentFolder(email.id);
    clearEmailHiddenInFolder(targetFolder, email.id);
    setAnimatingEmailId(email.id);
    setAnimationType(type);
    setTimeout(() => {
      setEmails(prev => prev.filter(e => e.id !== email.id));
      allEmailsRef.current = allEmailsRef.current.filter(e => e.id !== email.id);
      setAnimatingEmailId(null);
      setAnimationType(null);
      clearTriagePending(email.id);
      afterRemove?.();
      invalidateEmailCache();
    }, 260);
  }, [clearEmailHiddenInFolder, clearTriagePending, hideEmailInCurrentFolder]);

  const handleOptimisticDelete = useCallback((email: Email) => {
    if (pendingOpsRef.current.has(email.id)) return;
    pendingOpsRef.current.add(email.id);
    markTriagePending(email.id);
    markDeletePending(email.id);
    lockHoverForAnimation();
    setLastPendingDeleteId(email.id);
    apiClient.deleteEmail(email.id).then(() => {
      removeEmailAfterSuccessfulTriage(email, 'trash', 'delete', () => {
        showToast(t('email_deleted'), 'success');
        pendingOpsRef.current.delete(email.id);
        unmarkDeletePending(email.id);
        clearLastPendingDeleteId();
      });
    }).catch((err) => {
      console.error('[DELETE] Failed to delete email', email.id, err);
      const reason = err instanceof Error ? err.message : String(err ?? '');
      if (isEmailProviderAuthFailure(reason)) {
        emitEmailProviderAuthExpired(reason);
      }
      showToast(i18n.t(emailActionFailureToastKey('delete', reason)), 'error');
      clearTriagePending(email.id);
      pendingOpsRef.current.delete(email.id);
      unmarkDeletePending(email.id);
      clearLastPendingDeleteId();
    });
  }, [clearTriagePending, markTriagePending, removeEmailAfterSuccessfulTriage, showToast, t]);

  const handleOptimisticArchive = useCallback((email: Email) => {
    if (pendingOpsRef.current.has(email.id)) return;
    pendingOpsRef.current.add(email.id);
    markTriagePending(email.id);
    // Pending-removal tracking, shared with delete (the `*DeletePending` helpers
    // really mean "row whose removal is in flight", not delete-specific): mark
    // this row so getEmailIdUnderCursor() skips it during the 260ms slide-out,
    // and record it as the last removal so a rapid 2nd `E` press resolves the
    // NEXT row instead of re-targeting this still-animating one (which pendingOps
    // would dedupe to a no-op). Without this, rapid successive E presses archived
    // only the first email — the delete shortcut already did this; archive didn't.
    markDeletePending(email.id);
    lockHoverForAnimation();
    setLastPendingDeleteId(email.id);
    apiClient.archiveEmail(email.id).then(() => {
      removeEmailAfterSuccessfulTriage(email, 'archived', 'archive', () => {
        window.dispatchEvent(new CustomEvent('agentys:archived'));
        showToast(t('email_archived'), 'success');
        pendingOpsRef.current.delete(email.id);
        unmarkDeletePending(email.id);
        clearLastPendingDeleteId();
      });
    }).catch((err) => {
      console.error('[ARCHIVE] Failed to archive email', email.id, err);
      const reason = err instanceof Error ? err.message : String(err ?? '');
      if (isEmailProviderAuthFailure(reason)) {
        emitEmailProviderAuthExpired(reason);
      }
      showToast(i18n.t(emailActionFailureToastKey('archive', reason)), 'error');
      clearTriagePending(email.id);
      pendingOpsRef.current.delete(email.id);
      unmarkDeletePending(email.id);
      clearLastPendingDeleteId();
    });
  }, [clearTriagePending, markTriagePending, removeEmailAfterSuccessfulTriage, showToast, t]);

  // Expose search toggle to parent via ref (for keyboard shortcut `/`)
  const toggleSearchFromShortcut = useCallback(() => {
    if (!showSearchBar) {
      // Barre cachée → l'afficher et focus.
      // BUG-#13 (2026-05-17): a single requestAnimationFrame fired before
      // React committed the SmartSearchBar render, so querySelector returned
      // null and the first `/` press was silently swallowed.
      //
      // QA 2026-06-12: the rAF retry ladder that replaced it had the same
      // failure mode in disguise — rAF callbacks do not fire AT ALL while
      // Chrome throttles rendering (occluded/background window), so `/`
      // opened the bar but focus never landed and the user's next
      // keystrokes went to the void. Commit the render synchronously with
      // flushSync, then focus in the same task: no frames needed, no race.
      flushSync(() => setShowSearchBar(true));
      const input = document.querySelector<HTMLInputElement>('.smart-search-input');
      if (input) {
        input.focus();
      } else {
        // Fallback (e.g. skeleton state delays the bar's mount): retry on
        // timers, which keep firing even when frame production is throttled.
        const tryFocus = (retries: number) => {
          const el = document.querySelector<HTMLInputElement>('.smart-search-input');
          if (el) { el.focus(); return; }
          if (retries > 0) setTimeout(() => tryFocus(retries - 1), 50);
        };
        setTimeout(() => tryFocus(5), 50);
      }
    } else {
      const input = document.querySelector<HTMLInputElement>('.smart-search-input');
      if (input && document.activeElement !== input) {
        // Barre visible mais pas focus → focus l'input (ne pas fermer)
        input.focus();
      } else {
        // Barre visible et déjà focus → fermer la barre
        setShowSearchBar(false);
        setSearchQuery('');
        setIsSearching(false);
      }
    }
  }, [showSearchBar]);

  useEffect(() => {
    if (onSearchRef) {
      onSearchRef.current = toggleSearchFromShortcut;
    }
  }, [onSearchRef, toggleSearchFromShortcut]);

  // NEW-C fix: also listen for the custom event dispatched by App as a fallback
  // when the ref hasn't been set yet (timing race on mount).
  useEffect(() => {
    const handleSearchEvent = () => toggleSearchFromShortcut();
    window.addEventListener('agentys:toggle-search', handleSearchEvent);
    return () => window.removeEventListener('agentys:toggle-search', handleSearchEvent);
  }, [toggleSearchFromShortcut]);

  const allEmailsRef = useRef<Email[]>([]);
  const abortControllerRef = useRef<AbortController | null>(null);
  const searchAbortRef = useRef<AbortController | null>(null);
  const isSearchingRef = useRef(false);
  const noAccountRetryCountRef = useRef(0);
  const syncInProgressRetryCountRef = useRef(0);
  const syncInProgressRetryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // forceRefresh: bypass frontend IndexedDB cache and enqueue provider sync in background.
  // softRefresh: bypass frontend IndexedDB cache + backend memory cache, but still uses SQLite (fast)
  const loadEmails = useCallback(async (forceRefresh = false, softRefresh = false) => {
    if (syncInProgressRetryTimerRef.current) {
      clearTimeout(syncInProgressRetryTimerRef.current);
      syncInProgressRetryTimerRef.current = null;
    }
    if (forceRefresh) {
      syncInProgressRetryCountRef.current = 0;
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    const controller = createEmailFetchController();
    abortControllerRef.current = controller;

    // On soft refresh (post-send, WebSocket event), keep current UI visible
    // instead of flashing a loading spinner over existing emails
    const hasExistingEmails = allEmailsRef.current.length > 0;
    if (!softRefresh || !hasExistingEmails) {
      setLoadingState('loading');
    }
    setError(null);
    setNoAccount(false);

    const skipFrontendCache = forceRefresh || softRefresh;

    try {
      if (skipFrontendCache) {
        invalidateEmailCache();
      }

      const response = await fetchEmails({
        limit: PAGE_SIZE,
        offset: 0,
        filter: 'all',
        signal: controller.signal,
        folder,
        forceRefresh: forceRefresh,  // Hard refresh asks backend to enqueue a sync job
        skipCache: softRefresh,      // Soft refresh: skip frontend cache
        skipBackendCache: softRefresh,  // Also skip backend memory cache (serve from SQLite)
        label: activeLabel || undefined,
        providerLabel: providerLabel || undefined,
        excludeLabel: (hideNoise && folder === 'inbox' && activeLabel !== 'Noise') ? 'Noise' : undefined,
      });

      if (!controller.signal.aborted) {
        if (response.no_account) {
          setNoAccount(true);
          setLoadingState('success');
          return;
        }
        // Cold-start / DB-miss: the backend returned immediately and queued
        // provider work. Keep waiting on DB reads while sync is active instead
        // of turning repeated `{ emails: [], sync_in_progress: true }` into an
        // empty inbox. Existing rows stay visible during a refresh.
        const syncDecision = getEmailSyncInProgressDecision({
          syncInProgress: response.sync_in_progress === true,
          syncFailed: response.sync_failed === true,
          responseEmailCount: response.emails.length,
          visibleEmailCount: allEmailsRef.current.length,
          retryCount: syncInProgressRetryCountRef.current,
        });
        if (syncDecision.action === 'error') {
          syncInProgressRetryCountRef.current = 0;
          setError(tErrors('folder_sync_failed'));
          setLoadingState('error');
          return;
        }
        if (syncDecision.action === 'wait') {
          syncInProgressRetryCountRef.current += 1;
          setLoadingState(syncDecision.preserveExisting ? 'success' : 'loading');
          syncInProgressRetryTimerRef.current = setTimeout(() => {
            syncInProgressRetryTimerRef.current = null;
            if (!controller.signal.aborted) {
              loadEmails(false, true);
            }
          }, syncDecision.delayMs);
          return;
        }
        if (syncDecision.action === 'preserve_existing') {
          setLoadingState('success');
          return;
        }
        syncInProgressRetryCountRef.current = 0;
        // Compte détecté — retirer l'écran de bienvenue et reset retry counter
        if (noAccount) {
          setNoAccount(false);
          noAccountRetryCountRef.current = 0;
        }
        // Filter out emails that already left this folder optimistically.
        // A pagination request started before the click can resolve after the
        // action and otherwise re-add the row for a few seconds.
        const filtered = filterHiddenFromCurrentFolder(response.emails);
        // sortByDateDesc handles dedup (by ID + by Gmail/IMAP pairs)
        const sorted = sortByDateDesc(filtered);
        if (isSearchingRef.current) {
          setEmails(prev => mergeFreshRowsIntoVisibleSearch(prev, sorted));
        } else {
          setEmails(sorted);
        }
        allEmailsRef.current = sorted;
        onEmailsLoaded?.(sorted);
        setLoadingState('success');
        currentOffsetRef.current = sorted.length;
        // Stop when the page is empty OR the backend authoritatively reports no
        // more. We can't use `< PAGE_SIZE` as the end signal because the backend
        // filters blocked/spammed senders AFTER the limit+1 fetch, so a page can
        // be short yet more pages remain. `has_more !== false` keeps the old
        // "stop only on empty" robustness when has_more is missing/undefined
        // (legacy cache), while letting an explicit has_more=false suppress the
        // spurious sentinel + extra fetch on a small inbox.
        setHasMore(response.emails.length > 0 && response.has_more !== false);

        // If served from frontend IndexedDB cache, schedule a background revalidation
        // to pick up any newer emails from the backend SQLite / provider.
        // Only trigger on actual IndexedDB hits (fromCache), NOT on backend source:'cache'
        // responses — those already went through the network and are fresh enough.
        // Single background revalidation when served from IndexedDB cache.
        // Only skip the frontend cache — let the backend serve from SQLite/memory
        // instead of bypassing all caches and hitting the slow IMAP provider.
        if (response.fromCache && !forceRefresh) {
          // QA 2026-05-19 — Bug #11 (Spam skeleton flash):
          // Original BUG-Q006 fix re-entered the 'loading' state when the
          // cache returned 0 rows, so the empty state wouldn't "flash" if
          // fresh data was about to arrive. In practice this produced the
          // opposite UX flaw: opening the Spam folder showed three skeleton
          // rows for a beat *before* resolving to "No spam", which felt
          // like the empty state was unreliable. We already have a fresh-
          // enough answer (revalidation will mutate state if anything new
          // arrives), so render the empty state immediately and let the
          // background revalidation update silently. The 4-second
          // skeletonGuard below is kept as a safety net for the non-empty
          // path.
          const revalidateTimer = setTimeout(() => {
            if (controller.signal.aborted) return;
            // Hard safety net: if for any reason the revalidation never
            // settles within 4s, force the skeleton to clear. The user will
            // see whatever the cache had (possibly the empty state), which is
            // strictly better than a skeleton that never resolves.
            const skeletonGuard = setTimeout(() => {
              if (controller.signal.aborted) return;
              setLoadingState('success');
            }, 4000);
            fetchEmails({
              limit: PAGE_SIZE,
              offset: 0,
              filter: 'all',
              folder,
              label: activeLabel || undefined,
              providerLabel: providerLabel || undefined,
              excludeLabel: (hideNoise && folder === 'inbox' && activeLabel !== 'Noise') ? 'Noise' : undefined,
              skipCache: true,
              // Don't bypass backend cache — let SQLite respond quickly.
              // The backend's stale-while-revalidate triggers provider sync in background.
            }).then(freshResponse => {
              clearTimeout(skeletonGuard);
              if (controller.signal.aborted) return;
              if (!freshResponse.fromCache) {
                const freshSorted = sortByDateDesc(filterHiddenFromCurrentFolder(freshResponse.emails));
                allEmailsRef.current = freshSorted;
                onEmailsLoaded?.(freshSorted);
                currentOffsetRef.current = freshSorted.length;
                setHasMore(freshResponse.emails.length > 0);
                if (!isSearchingRef.current) {
                  setEmails(freshSorted);
                }
              }
              // Always clear the skeleton, whether the revalidation produced
              // fresh data or hit the cache again. An empty list IS a valid
              // resolved state for folders like Spam/Trash when truly empty.
              setLoadingState('success');
            }).catch(err => {
              clearTimeout(skeletonGuard);
              console.error('[EmailList] background revalidation failed:', err);
              if (controller.signal.aborted) return;
              // Don't strand the user on the skeleton if the network call
              // fails — show whatever we have (likely the empty state).
              setLoadingState('success');
            });
          }, 100);
          // Make the outer timer cancellable on abort too (covered by
          // controller.signal.aborted guards inside, plus this reference is
          // kept for clarity in case future code wants to cancel it).
          void revalidateTimer;
        }

        // Prefetch aveugle des 10 premiers emails retiré suite à #233.
        // Les snippets de la liste suffisent; réactiver après mesure du bénéfice réel.
        if (BLIND_PREFETCH_ENABLED) {
          const emailIds = response.emails.slice(0, 10).map(e => e.id);
          prefetchEmailDetails(emailIds, 3);
        }
      }
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        return;
      }
      const rawMessage = err instanceof Error ? err.message : '';
      // For secondary folders (spam, trash, archived) that have no frontend cache,
      // a network failure should show an empty list rather than an error banner.
      // The inbox is the only folder where "Failed to fetch" warrants a visible error.
      if (rawMessage === 'Failed to fetch' && folder !== 'inbox') {
        setEmails([]);
        allEmailsRef.current = [];
        setLoadingState('success');
        setHasMore(false);
        return;
      }
      // On soft refresh with existing data, swallow transient errors silently.
      // The user already sees their email list — don't wipe it with an error banner.
      // Next automatic refresh (WebSocket event, tab refocus) will pick up changes.
      if (softRefresh && allEmailsRef.current.length > 0) {
        console.warn('[EmailList] soft refresh failed, keeping existing data:', rawMessage);
        setLoadingState('success');
        return;
      }
      // BUG-H005: When backend is unreachable and we switch label filters,
      // keep already-loaded emails so the client-side label filter (filteredEmails
      // useMemo below) can still show the right subset. Avoids "No Action email"
      // when emails were visible moments before in the All tab.
      if (rawMessage === 'Failed to fetch' && allEmailsRef.current.length > 0) {
        console.warn('[EmailList] label fetch failed (backend down), using cached emails for client-side filter:', activeLabel);
        setLoadingState('success');
        return;
      }
      const message = rawMessage === 'Failed to fetch' ? tErrors('network_error') : (rawMessage || tErrors('generic'));
      setError(message);
      setLoadingState('error');
    }
  }, [onEmailsLoaded, folder, activeLabel, providerLabel, hideNoise, noAccount, filterHiddenFromCurrentFolder, tErrors]);

  // Infinite scroll — load next page
  const loadMore = useCallback(async () => {
    if (isLoadingMore || !hasMore) return;
    if (isSearchingRef.current) return;

    setIsLoadingMore(true);
    try {
      const response = await fetchEmails({
        limit: PAGE_SIZE,
        offset: currentOffsetRef.current,
        filter: 'all',
        folder,
        label: activeLabel || undefined,
        providerLabel: providerLabel || undefined,
        excludeLabel: (hideNoise && folder === 'inbox' && activeLabel !== 'Noise') ? 'Noise' : undefined,
      });
      if (isSearchingRef.current) return;

      const visibleNewPage = filterHiddenFromCurrentFolder(response.emails);
      if (visibleNewPage.length > 0) {
        setEmails(prev => {
          const existingIds = new Set(prev.map(e => e.id));
          const newEmails = visibleNewPage.filter(e => !existingIds.has(e.id));
          return newEmails.length > 0 ? sortByDateDesc([...prev, ...newEmails]) : prev;
        });
        const existingIds = new Set(allEmailsRef.current.map(e => e.id));
        const newEmails = visibleNewPage.filter(e => !existingIds.has(e.id));
        if (newEmails.length > 0) {
          allEmailsRef.current = sortByDateDesc([...allEmailsRef.current, ...newEmails]);
        }
        currentOffsetRef.current += response.emails.length;
      }
      // See the load() path: combine empty-page with the authoritative has_more
      // so a spam-shrunk short page still paginates, but an explicit end stops.
      setHasMore(response.emails.length > 0 && response.has_more !== false);
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') return;
      // Audit F-01/F-11 (2026-05-12): non-Abort errors used to be swallowed,
      // so the spinner disappeared and the user thought they had reached the
      // end of their inbox. Surface the error and stop pagination so a retry
      // button can render in the footer instead of a silent infinite scroll.
      console.error('[EmailList] loadMore failed:', err);
      setHasMore(false);
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: {
            message: tErrors('error_load', { defaultValue: 'Chargement des emails suivants impossible — réessayez' }),
            type: 'error',
            duration: 6000,
          },
        }));
      }
    } finally {
      setIsLoadingMore(false);
    }
  }, [isLoadingMore, hasMore, folder, activeLabel, providerLabel, hideNoise, filterHiddenFromCurrentFolder, tErrors]);

  const filterEmailsLocally = useCallback((emailList: Email[], query: string): Email[] => {
    // Parse all filters from the query (supports multi-filter: "from:X subject:Y text")
    const filters: { type: string; value: string }[] = [];
    const freeTerms: string[] = [];

    // Tokenize: split by spaces but respect quoted strings
    const tokens: string[] = [];
    let i = 0;
    while (i < query.length) {
      if (query[i] === '"') {
        const end = query.indexOf('"', i + 1);
        if (end !== -1) {
          tokens.push(query.slice(i, end + 1));
          i = end + 1;
        } else {
          tokens.push(query.slice(i));
          break;
        }
      } else if (query[i] === ' ') {
        i++;
      } else {
        let j = i;
        while (j < query.length && query[j] !== ' ') j++;
        tokens.push(query.slice(i, j));
        i = j;
      }
    }

    for (const token of tokens) {
      const lower = token.toLowerCase();
      if (lower.startsWith('from:') || lower.startsWith('de:')) {
        const val = lower.startsWith('from:') ? token.slice(5) : token.slice(3);
        if (val) filters.push({ type: 'from', value: val.toLowerCase() });
      } else if (lower.startsWith('to:') || lower.startsWith('a:')) {
        const val = lower.startsWith('to:') ? token.slice(3) : token.slice(2);
        if (val) filters.push({ type: 'to', value: val.toLowerCase() });
      } else if (lower.startsWith('subject:') || lower.startsWith('objet:')) {
        const val = lower.startsWith('subject:') ? token.slice(8) : token.slice(6);
        if (val) filters.push({ type: 'subject', value: val.toLowerCase().replace(/^"|"$/g, '') });
      } else if (lower.startsWith('label:')) {
        const val = token.slice(6);
        if (val) filters.push({ type: 'label', value: val.toLowerCase() });
      } else if (lower.startsWith('body:') || lower.startsWith('contenu:')) {
        const val = lower.startsWith('body:') ? token.slice(5) : token.slice(8);
        if (val) filters.push({ type: 'body', value: val.toLowerCase() });
      } else if (lower.startsWith('has:')) {
        const val = token.slice(4).toLowerCase();
        if (val) filters.push({ type: 'has', value: val });
      } else if (lower.startsWith('in:') || lower.startsWith('dossier:') || lower.startsWith('folder:')) {
        // 'in:' scoping is handled server-side; skip locally to avoid false negatives
      } else if (lower.startsWith('after:') || lower.startsWith('before:')) {
        // date filters handled server-side only
      } else if (token.startsWith('-') && token.length > 1) {
        filters.push({ type: 'exclude', value: token.slice(1).toLowerCase() });
      } else {
        freeTerms.push(token.toLowerCase().replace(/^"|"$/g, ''));
      }
    }

    return emailList.filter((email) => {
      const sender = (email.sender || '').toLowerCase();
      const senderName = (email.sender_name || '').toLowerCase();
      const subject = (email.subject || '').toLowerCase();
      const bodyPreview = (email.body_preview || '').toLowerCase();

      // All filters must match (AND logic)
      for (const f of filters) {
        switch (f.type) {
          case 'from':
            if (!sender.includes(f.value) && !senderName.includes(f.value)) return false;
            break;
          case 'to':
            if (!(email.to || []).join(', ').toLowerCase().includes(f.value)) return false;
            break;
          case 'subject':
            if (!subject.includes(f.value)) return false;
            break;
          case 'label':
            if (!email.labels?.some((l) => l.name.toLowerCase() === f.value)) return false;
            break;
          case 'body':
            if (!bodyPreview.includes(f.value)) return false;
            break;
          case 'has':
            if (f.value === 'attachment' || f.value === 'attachments') {
              if (!email.has_attachments) return false;
            }
            break;
          case 'exclude':
            if (sender.includes(f.value) || subject.includes(f.value) || bodyPreview.includes(f.value)) return false;
            break;
        }
      }

      // All free terms must match somewhere
      for (const term of freeTerms) {
        if (!sender.includes(term) && !senderName.includes(term) && !subject.includes(term) && !bodyPreview.includes(term)) {
          return false;
        }
      }

      return true;
    });
  }, []);

  const handleSearch = useCallback(async (query: string) => {
    setSearchQuery(query);

    if (!query.trim()) {
      isSearchingRef.current = false;
      setIsSearching(false);
      setEmails(allEmailsRef.current);
      setLoadingState('success');
      // Cancel any in-flight search request
      searchAbortRef.current?.abort();
      return;
    }

    // Cancel previous search request before starting a new one
    searchAbortRef.current?.abort();
    const searchController = new AbortController();
    searchAbortRef.current = searchController;

    // Show local results instantly so the UI stays responsive
    const localResults = sortByDateDesc(filterEmailsLocally(allEmailsRef.current, query));
    setEmails(localResults);
    isSearchingRef.current = true;
    setIsSearching(true);
    setLoadingState('success');
    setError(null);

    // Fire backend search in the background — only replace if it finds more results
    try {
      const response = await searchEmails({
        query,
        limit: 50,
        signal: searchController.signal,
      });

      if (searchController.signal.aborted) return;

      if (response.success && response.results.length > 0) {
        const emailResults = sortByDateDesc(response.results.map(searchResultToEmail));
        // Merge: use backend results if they're richer than local
        if (emailResults.length >= localResults.length) {
          setEmails(emailResults);
        }
      }
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        return;
      }
      // Local results already displayed — nothing to do
    }
  }, [filterEmailsLocally]);



  const toggleSearchBar = useCallback(() => {
    setShowSearchBar((prev) => {
      if (prev && searchQuery) {
        setSearchQuery('');
        isSearchingRef.current = false;
        setIsSearching(false);
        searchAbortRef.current?.abort();
        setEmails(allEmailsRef.current);
      }
      const next = !prev;
      // BUG-I002 fix companion: SmartSearchBar no longer autofocuses on
      // mount (it stole focus on every label-tab remount). When the user
      // explicitly opens the bar via the header icon, focus the input on
      // the next frame so the cursor lands where they expect.
      if (next) {
        requestAnimationFrame(() => {
          document
            .querySelector<HTMLInputElement>('.smart-search-input')
            ?.focus();
        });
      }
      return next;
    });
  }, [searchQuery]);

  // Detect a freshly-completed onboarding — App.tsx sets this on wizard close.
  // We consume the flag once per mount so a later remount (e.g. folder switch)
  // doesn't re-trigger the post-onboarding behaviour.
  const justOnboardedRef = useRef<number>(0);
  if (justOnboardedRef.current === 0) {
    try {
      const raw = sessionStorage.getItem('agentys_just_onboarded_at');
      const ts = raw ? parseInt(raw, 10) : 0;
      if (ts > 0 && (Date.now() - ts) < 5 * 60 * 1000) {
        justOnboardedRef.current = ts;
        sessionStorage.removeItem('agentys_just_onboarded_at');
      } else {
        justOnboardedRef.current = -1;
      }
    } catch {
      justOnboardedRef.current = -1;
    }
  }

  useEffect(() => {
    // Post-onboarding: bypass the cache-first path and hit the provider so a
    // freshly OAuth'd user does not stare at "Inbox Zero" while the background
    // sync catches up. Otherwise use the standard cache-first load.
    loadEmails(justOnboardedRef.current > 0);
    // NOTE: No abort in cleanup — React 18 ignores state updates on unmounted components.
    // Aborting here breaks StrictMode (double-mount aborts the real fetch).
    // Duplicate-request cancellation is handled inside loadEmails() itself.

  }, []);

  useEffect(() => {
    syncInProgressRetryCountRef.current = 0;
    if (syncInProgressRetryTimerRef.current) {
      clearTimeout(syncInProgressRetryTimerRef.current);
      syncInProgressRetryTimerRef.current = null;
    }
  }, [folder, activeLabel, providerLabel, accountId]);

  useEffect(() => {
    return () => {
      if (syncInProgressRetryTimerRef.current) {
        clearTimeout(syncInProgressRetryTimerRef.current);
        syncInProgressRetryTimerRef.current = null;
      }
    };
  }, []);

  // Post-onboarding poll: when the inbox is empty right after onboarding,
  // keep checking SQLite for up to 90s. The provider-side sync that ran
  // during onboarding may still be writing rows — we want them to appear
  // without forcing the user to refresh. Gated on the just-onboarded flag
  // so it never hammers the backend for users with a legitimately empty
  // inbox. The last attempt escalates to a hard provider refresh in case
  // the initial sync stalled silently.
  const postOnboardPollRef = useRef<{ done: boolean; startedAt: number; attempts: number }>({ done: false, startedAt: 0, attempts: 0 });
  useEffect(() => {
    if (justOnboardedRef.current <= 0) return;
    if (folder !== 'inbox') return;
    if (postOnboardPollRef.current.done) return;
    if (loadingState !== 'success') return;
    if (allEmailsRef.current.length > 0) {
      postOnboardPollRef.current.done = true;
      return;
    }
    if (postOnboardPollRef.current.startedAt === 0) {
      postOnboardPollRef.current.startedAt = Date.now();
    }
    const elapsed = Date.now() - postOnboardPollRef.current.startedAt;
    if (elapsed > 90000) {
      postOnboardPollRef.current.done = true;
      return;
    }
    const timer = setTimeout(() => {
      if (allEmailsRef.current.length === 0) {
        postOnboardPollRef.current.attempts += 1;
        // After 30s of empty results, escalate to a hard provider refresh —
        // the silent-sync may have stalled on a transient Gmail error.
        const escalate = elapsed >= 30000;
        loadEmails(escalate, true);
      }
    }, 3000);
    return () => clearTimeout(timer);
  }, [folder, loadingState, loadEmails]);

  // Auto-retry quand noAccount est true (l'utilisateur est en train de connecter un compte)
  // Uses a ref counter so the limit survives effect re-runs caused by noAccount state flips
  // (loadEmails sets noAccount=false, then response sets it back to true → effect re-creates)
  useEffect(() => {
    if (!noAccount) return;
    const MAX_NO_ACCOUNT_RETRIES = 20;
    if (noAccountRetryCountRef.current >= MAX_NO_ACCOUNT_RETRIES) return;
    const interval = setInterval(() => {
      if (noAccountRetryCountRef.current >= MAX_NO_ACCOUNT_RETRIES) {
        clearInterval(interval);
        return;
      }
      noAccountRetryCountRef.current++;
      loadEmails(false, true);
    }, 5000);
    return () => clearInterval(interval);
  }, [noAccount, loadEmails]);

  // Silent refresh when refreshTrigger changes (new email via WebSocket/polling)
  const prevTriggerRef = useRef(refreshTrigger);
  useEffect(() => {
    if (refreshTrigger !== undefined && refreshTrigger !== prevTriggerRef.current) {
      prevTriggerRef.current = refreshTrigger;
      loadEmails(false, true);  // soft refresh: skip frontend cache, don't force backend re-fetch
    }
  }, [refreshTrigger, loadEmails]);

  // Re-fetch archives when an email is archived from another tab (inbox → archived)
  useEffect(() => {
    if (folder !== 'archived') return;
    const handler = () => loadEmails(false, true);
    window.addEventListener('agentys:archived', handler);
    return () => window.removeEventListener('agentys:archived', handler);
  }, [folder, loadEmails]);

  // Hard refresh quand un compte est ajouté/supprimé (AccountManager)
  useEffect(() => {
    const handler = () => loadEmails(true);
    window.addEventListener('agentys:account-changed', handler);
    return () => window.removeEventListener('agentys:account-changed', handler);
  }, [loadEmails]);

  // Incremental WS sync — patch list state without full refetch.
  // Emitted by useWebSocketSync on email_archived / email_deleted / email_updated.
  useEffect(() => {
    const onUpsert = (evt: Event) => {
      const custom = evt as CustomEvent<{ email?: Email }>;
      const incoming = custom.detail?.email;
      if (!incoming?.id) return;
      if (folder !== 'inbox') return;
      if (activeLabel || providerLabel) return;
      if (pendingOpsRef.current.has(incoming.id)) return;
      if (hideNoise && incoming.labels?.some(l => l.name.toLowerCase() === 'noise')) return;

      const next = sortByDateDesc([
        incoming,
        ...allEmailsRef.current.filter(e => e.id !== incoming.id),
      ]);
      allEmailsRef.current = next;
      currentOffsetRef.current = next.length;
      onEmailsLoaded?.(next);
      setLoadingState('success');
      setNoAccount(false);
      if (!isSearchingRef.current) {
        setEmails(next);
      }
      custom.preventDefault();
    };
    const onRemove = (evt: Event) => {
      const { email_id } = (evt as CustomEvent<{ email_id: string }>).detail || { email_id: '' };
      if (!email_id) return;
      setEmails(prev => prev.filter(e => e.id !== email_id));
    };
    const onPatch = (evt: Event) => {
      const detail = (evt as CustomEvent<{ email_id: string; updates: Partial<Email> & { delete_failed?: boolean; archive_failed?: boolean; reason?: string } }>).detail
        || { email_id: '', updates: {} };
      const { email_id, updates } = detail;
      if (!email_id || !updates) return;

      // F-01 (audit regressions 2026-05-17 batch4): delegate failure-flag
      // handling to `handleEmailActionFailure` so the dispatch contract is
      // unit-tested in isolation (see `lib/handleEmailPatchFailure.test.ts`)
      // instead of relying on a heavyweight EmailList integration test.
      if (handleEmailActionFailure(email_id, updates)) return;

      setEmails(prev => prev.map(e => (e.id === email_id ? { ...e, ...updates } : e)));
    };
    window.addEventListener('agentys:email-upsert', onUpsert);
    window.addEventListener('agentys:email-remove', onRemove);
    window.addEventListener('agentys:email-patch', onPatch);
    return () => {
      window.removeEventListener('agentys:email-upsert', onUpsert);
      window.removeEventListener('agentys:email-remove', onRemove);
      window.removeEventListener('agentys:email-patch', onPatch);
    };
  }, [activeLabel, folder, hideNoise, onEmailsLoaded, providerLabel]);

  // WebSocket noise_cleanup_complete triggers a list refresh via useWebSocketSync.
  // The toast is shown by handleCleanNoise — no separate listener needed here.

  const handleEmailClick = useCallback((email: Email) => {
    // Selecting via click should use global keyboard handler (not per-item hover handler)
    // so that Del/E shortcuts properly update App selection state
    setKeyboardNavMode(true);
    // Mark as read on open. We always hit the route (even when the email
    // is already marked as read locally) so the backend's auto-trigger
    // re-evaluation gets a chance to fire on historical emails that
    // arrived already-read from the provider — without the call, a Quick
    // Step gated on ``is_read AND has_label`` would never trip for older
    // messages because no state-change event happens at open time. The
    // audit-log dedup in ``run_auto_triggers`` prevents the rule from
    // double-executing.
    if (folder !== 'sent') {
      const selectedEmailExists = emails.some(e => e.id === email.id);
      const unreadThreadEmails = getUnreadThreadEmailsOnOpen(emails, email);
      const unreadEmailsToPatch = selectedEmailExists
        ? unreadThreadEmails
        : (email.is_read === false ? [email, ...unreadThreadEmails] : unreadThreadEmails);

      if (unreadEmailsToPatch.length > 0) {
        for (const unreadEmail of unreadEmailsToPatch) {
          syncUnreadLabelCountsAfterReadStateChange(unreadEmail, true);
        }
        setEmails(prev => markEmailThreadReadInList(prev, email));
        allEmailsRef.current = markEmailThreadReadInList(allEmailsRef.current, email);
      }

      const idsToSync = Array.from(new Set([email.id, ...unreadEmailsToPatch.map(e => e.id)]));
      const markReadPromise = idsToSync.length > 1
        ? markEmailsBulk(idsToSync, true)
        : markEmailRead(email.id);
      // Reconcile the unread badge counts AFTER the server write lands.
      // syncUnreadLabelCountsAfterReadStateChange only patches the cache
      // optimistically; invalidating before the write completed would refetch
      // the pre-change count and revert the optimistic update.
      markReadPromise
        .then(() => { invalidateEmailCache(); invalidateLabelCounts(); })
        .catch(err => {
          // F-12 / Site 6 (audit 2026-06-11) : le patch optimiste ci-dessus
          // ment si l'écriture serveur a échoué — réconcilier les caches pour
          // resynchroniser badges/état lu au prochain fetch. Pas de toast :
          // l'action principale (ouvrir l'email) a réussi.
          console.error('[EmailList] mark read failed:', err);
          invalidateEmailCache();
          invalidateLabelCounts();
        });
    }
    onEmailSelect?.(email);
  }, [onEmailSelect, folder, emails]);

  // Re-fetch emails when label changes (server-side filtering)
  // Use value comparison instead of mount ref to survive StrictMode double-mount
  const prevActiveLabelRef = useRef(activeLabel);
  useEffect(() => {
    if (prevActiveLabelRef.current === activeLabel) return; // No actual change
    prevActiveLabelRef.current = activeLabel;
    setSelectedIds(new Set());
    setMultiSelectMode(false);
    loadEmails();

  }, [activeLabel]);


  // Re-fetch emails when provider folder/label changes (server-side filtering)
  const prevProviderLabelRef = useRef(providerLabel);
  useEffect(() => {
    if (prevProviderLabelRef.current === providerLabel) return; // No actual change
    prevProviderLabelRef.current = providerLabel;
    setSelectedIds(new Set());
    setMultiSelectMode(false);
    loadEmails();

  }, [providerLabel]);

  const { filteredEmails } = useMemo(() => {
    let result = filterByStatus(emails, statusFilter);

    // Client-side label filter (safety net if server-side filter fails)
    // Skip when search is active — search overrides the label tab view
    if (activeLabel && !searchQuery) {
      result = result.filter(email =>
        email.labels?.some(l => l.name.toLowerCase() === activeLabel.toLowerCase())
      );
    }

    // Hide Noise emails from inbox (unless actively viewing the Noise label)
    // Count hidden noise in the same pass to avoid a second filter traversal
    let noiseCount = 0;
    if (hideNoise && folder === 'inbox' && activeLabel !== 'Noise') {
      const visible: Email[] = [];
      for (const email of result) {
        if (email.labels?.some(l => l.name.toLowerCase() === 'noise')) {
          noiseCount++;
        } else {
          visible.push(email);
        }
      }
      result = visible;
    }

    return { filteredEmails: result, hiddenNoiseCount: noiseCount };
  }, [emails, statusFilter, hideNoise, folder, activeLabel, searchQuery]);

  // Compute thread counts from conversation_id grouping (9.3)
  const threadCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const email of filteredEmails) {
      const cid = email.conversation_id;
      if (cid) counts.set(cid, (counts.get(cid) || 0) + 1);
    }
    return counts;
  }, [filteredEmails]);

  // Gmail-style thread collapsing: keep only the latest email per conversation_id
  // Single-pass: collect latest email, unread & draft flags per thread simultaneously
  const collapsedEmails = useMemo(() => {
    const threadInfo = new Map<string, { latest: Email; latestTs: number; hasUnread: boolean; hasDraft: boolean }>();
    const standalone: Email[] = [];
    for (const email of filteredEmails) {
      const cid = email.conversation_id;
      if (!cid) { standalone.push(email); continue; }
      const ts = parseDate(email.received_at).getTime();
      const existing = threadInfo.get(cid);
      if (!existing) {
        threadInfo.set(cid, { latest: email, latestTs: ts, hasUnread: !email.is_read, hasDraft: !!email.has_pending_draft });
      } else {
        if (ts > existing.latestTs) { existing.latest = email; existing.latestTs = ts; }
        if (!email.is_read) existing.hasUnread = true;
        if (email.has_pending_draft) existing.hasDraft = true;
      }
    }
    // Build result: standalone emails + one representative per thread
    const result = [...standalone];
    for (const info of threadInfo.values()) {
      const email = info.latest;
      const needsUnread = info.hasUnread && email.is_read;
      const needsDraft = info.hasDraft && !email.has_pending_draft;
      if (needsUnread || needsDraft) {
        result.push({ ...email, is_read: needsUnread ? false : email.is_read, has_pending_draft: needsDraft ? true : email.has_pending_draft });
      } else {
        result.push(email);
      }
    }
    return result;
  }, [filteredEmails]);

  // Notify parent of displayed (collapsed) email list for J/K navigation sync
  // BUG-T001 (2026-05-16): the useMemo above returns a new array reference
  // every time filteredEmails changes, even when the email IDs are identical
  // (e.g. when the search-as-you-type debounce fires and the filter result is
  // the same set of rows). Each new reference was forwarded to the parent's
  // setDisplayedEmailsState which re-rendered App and propagated back down,
  // triggering "Maximum update depth exceeded" inside SmartSearchBar when
  // typing in the search bar. Guard with an ID signature so we only notify
  // when the visible IDs actually changed.
  const lastSignatureRef = useRef<string>('');
  useEffect(() => {
    const signature = collapsedEmails.map(e => e.id).join('|');
    if (signature === lastSignatureRef.current) return;
    lastSignatureRef.current = signature;
    onDisplayedEmailsChange?.(collapsedEmails);
  }, [collapsedEmails, onDisplayedEmailsChange]);

  // Ref to track last checked email ID for shift-click range selection
  // Using ID (not index) so it remains valid after re-sorts from loadMore
  const lastCheckedIdRef = useRef<string | null>(null);

  // Multi-select handlers
  const handleCheckChange = useCallback((email: Email, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) {
        next.add(email.id);
      } else {
        next.delete(email.id);
      }
      // Auto-activate/deactivate multiSelectMode
      if (next.size > 0) {
        setMultiSelectMode(true);
      } else {
        setMultiSelectMode(false);
      }
      return next;
    });
    // Track last checked by ID (stable across re-sorts)
    lastCheckedIdRef.current = email.id;
  }, []);

  // Shift-click range selection handler
  const handleShiftClick = useCallback((email: Email) => {
    const currentIndex = collapsedEmails.findIndex(e => e.id === email.id);
    if (currentIndex === -1) return;

    const lastId = lastCheckedIdRef.current;
    if (lastId === null) {
      // No previous selection, just toggle this one
      handleCheckChange(email, !selectedIds.has(email.id));
      return;
    }

    // Resolve last ID to current index (valid even after re-sort)
    const lastIndex = collapsedEmails.findIndex(e => e.id === lastId);
    if (lastIndex === -1) {
      handleCheckChange(email, !selectedIds.has(email.id));
      return;
    }

    const start = Math.min(lastIndex, currentIndex);
    const end = Math.max(lastIndex, currentIndex);

    setSelectedIds((prev) => {
      const next = new Set(prev);
      for (let i = start; i <= end; i++) {
        next.add(collapsedEmails[i].id);
      }
      setMultiSelectMode(true);
      return next;
    });
    lastCheckedIdRef.current = email.id;
  }, [collapsedEmails, selectedIds, handleCheckChange]);

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(collapsedEmails.map((e) => e.id)));
    setMultiSelectMode(true);
  }, [collapsedEmails]);

  const deselectAll = useCallback(() => {
    setSelectedIds(new Set());
    setMultiSelectMode(false);
  }, []);

  const selectAllFromHere = useCallback(() => {
    // Find the last checked email index, select everything from there to the end
    const lastId = lastCheckedIdRef.current;
    const startIdx = lastId ? collapsedEmails.findIndex(e => e.id === lastId) : 0;
    const from = startIdx >= 0 ? startIdx : 0;
    const ids = new Set(collapsedEmails.slice(from).map(e => e.id));
    // Merge with existing selection
    setSelectedIds(prev => {
      const next = new Set(prev);
      ids.forEach(id => next.add(id));
      return next;
    });
    setMultiSelectMode(true);
  }, [collapsedEmails]);

  const handleMarkReadToggle = useCallback(async (email: Email, isRead: boolean) => {
    const patchedCounts = syncUnreadLabelCountsAfterReadStateChange(email, isRead);
    setEmails((prev) =>
      prev.map((e) => (e.id === email.id ? { ...e, is_read: isRead } : e))
    );
    // Patch the source-of-truth ref too, else any list rebuild (WS new-mail
    // upsert, search clear/close) replays the stale is_read and the row snaps
    // back to unread. Mirrors handleLabelUpdate below.
    allEmailsRef.current = allEmailsRef.current.map((e) => (e.id === email.id ? { ...e, is_read: isRead } : e));

    try {
      if (isRead) {
        await markEmailRead(email.id);
      } else {
        await markEmailUnread(email.id);
      }
      invalidateEmailCache();
      // Reconcile unread badge counts now that the server write has landed.
      // (The optimistic patch above already updated the badge instantly.)
      invalidateLabelCounts();
      showToast(isRead ? t('email_marked_read') : t('email_marked_unread'), 'success');
    } catch {
      if (patchedCounts) {
        syncUnreadLabelCountsAfterReadStateChange({ ...email, is_read: isRead }, !isRead);
      }
      setEmails((prev) =>
        prev.map((e) => (e.id === email.id ? { ...e, is_read: !isRead } : e))
      );
      allEmailsRef.current = allEmailsRef.current.map((e) => (e.id === email.id ? { ...e, is_read: !isRead } : e));
      showToast(tErrors('error_update'), 'error');
    }
  }, [showToast, t, tErrors]);

  const handleLabelUpdate = useCallback((email: Email, newLabels: EmailLabel[], silent?: boolean) => {
    setEmails(prev => prev.map(e => e.id === email.id ? { ...e, labels: newLabels } : e));
    allEmailsRef.current = allEmailsRef.current.map(e => e.id === email.id ? { ...e, labels: newLabels } : e);
    if (!silent) {
      const labelNames = newLabels.map(l => getLabelDisplayName(l.name)).join(' + ') || '?';
      showToast(`Label → ${labelNames}`, 'success');
    }
    // If a label filter is active and the email no longer matches it,
    // clear the filter so the user sees the email in its new section
    if (activeLabel) {
      const stillMatches = newLabels.some(l => l.name.toLowerCase() === activeLabel.toLowerCase());
      if (!stillMatches) {
        onLabelChange?.(null);
      }
    }
    setTimeout(() => refreshCounts(), 500);
  }, [showToast, refreshCounts, activeLabel, onLabelChange]);

  // Bulk archive handler
  const handleBulkArchive = useCallback(async () => {
    if (isBulkLoadingRef.current) return; // Prevent key-repeat re-entry
    const currentIds = selectedIdsRef.current;
    if (currentIds.size === 0) return;
    isBulkLoadingRef.current = true;

    const idsArray = Array.from(currentIds);
    setIsBulkLoading(true);
    markBulkTriagePending(idsArray);

    try {
      const result = await apiClient.bulkArchiveEmails(idsArray);
      invalidateEmailCache();
      idsArray.forEach(id => {
        hideEmailInCurrentFolder(id);
        clearEmailHiddenInFolder('archived', id);
      });
      setEmails(prev => prev.filter(e => !currentIds.has(e.id)));
      allEmailsRef.current = allEmailsRef.current.filter(e => !currentIds.has(e.id));
      if (result.accepted) {
        // Large wave — queued in the bulk-jobs queue. Track in Settings.
        showToast(t('bulk_queued', { count: result.target_total ?? idsArray.length }), 'info');
      } else {
        showToast(t('emails_archived', { count: idsArray.length }), 'success');
      }
      setSelectedIds(new Set());
      setMultiSelectMode(false);
    } catch {
      showToast(tErrors('error_bulk_archive'), 'error');
    } finally {
      clearBulkTriagePending(idsArray);
      setIsBulkLoading(false);
      isBulkLoadingRef.current = false;
    }
  }, [showToast, t, tErrors, markBulkTriagePending, clearBulkTriagePending, hideEmailInCurrentFolder, clearEmailHiddenInFolder]);

  // Bulk delete handler
  const handleBulkDelete = useCallback(async () => {
    if (isBulkLoadingRef.current) return; // Prevent key-repeat re-entry
    const currentIds = selectedIdsRef.current;
    if (currentIds.size === 0) return;
    isBulkLoadingRef.current = true;

    const idsArray = Array.from(currentIds);
    setIsBulkLoading(true);
    markBulkTriagePending(idsArray);

    try {
      const result = await apiClient.bulkDeleteEmails(idsArray);
      invalidateEmailCache();
      idsArray.forEach(id => {
        hideEmailInCurrentFolder(id);
        clearEmailHiddenInFolder('trash', id);
      });
      setEmails(prev => prev.filter(e => !currentIds.has(e.id)));
      allEmailsRef.current = allEmailsRef.current.filter(e => !currentIds.has(e.id));
      const updatedCount = result.updated_count ?? idsArray.length;
      if (result.accepted) {
        // Large wave — queued in the bulk-jobs queue. Track in Settings.
        showToast(t('bulk_queued', { count: result.target_total ?? idsArray.length }), 'info');
      } else if (result.partial && updatedCount < idsArray.length) {
        const failedCount = idsArray.length - updatedCount;
        showToast(t('bulk_delete_partial', { updated: updatedCount, failed: failedCount }), 'warning');
      } else {
        showToast(t('emails_deleted', { count: idsArray.length }), 'success');
      }
      setSelectedIds(new Set());
      setMultiSelectMode(false);
      // Refresh label counts so Bruit/Noise badge updates immediately
      setTimeout(() => refreshCounts(), 300);
    } catch {
      showToast(tErrors('error_bulk_delete'), 'error');
    } finally {
      clearBulkTriagePending(idsArray);
      setIsBulkLoading(false);
      isBulkLoadingRef.current = false;
    }
  }, [showToast, refreshCounts, t, tErrors, markBulkTriagePending, clearBulkTriagePending, hideEmailInCurrentFolder, clearEmailHiddenInFolder]);

  // Not-spam handler (single email)
  const handleNotSpam = useCallback((email: Email) => {
    if (pendingOpsRef.current.has(email.id)) return;
    pendingOpsRef.current.add(email.id);
    markTriagePending(email.id);

    apiClient.moveToNotSpam(email.id).then(() => {
      removeEmailAfterSuccessfulTriage(email, 'inbox', 'archive', () => {
        showToast(t('email_moved_inbox'), 'success');
        pendingOpsRef.current.delete(email.id);
      });
    }).catch(err => {
      console.error('[EmailList] not-spam failed:', err);
      showToast(tErrors('error_move'), 'error');
      clearTriagePending(email.id);
      pendingOpsRef.current.delete(email.id);
    });
  }, [clearTriagePending, markTriagePending, removeEmailAfterSuccessfulTriage, showToast, t, tErrors]);

  // Bulk not-spam handler
  const handleBulkNotSpam = useCallback(async () => {
    if (selectedIds.size === 0) return;

    const idsArray = Array.from(selectedIds);
    setIsBulkLoading(true);
    markBulkTriagePending(idsArray);

    try {
      const result = await apiClient.bulkMoveToNotSpam(idsArray);
      invalidateEmailCache();
      idsArray.forEach(id => {
        hideEmailInCurrentFolder(id);
        clearEmailHiddenInFolder('inbox', id);
      });
      setEmails(prev => prev.filter(e => !selectedIds.has(e.id)));
      allEmailsRef.current = allEmailsRef.current.filter(e => !selectedIds.has(e.id));
      if (result.accepted) {
        // Large wave — queued in the bulk-jobs queue. Track in Settings.
        showToast(t('bulk_queued', { count: result.target_total ?? idsArray.length }), 'info');
      } else {
        showToast(t('emails_moved_inbox', { count: idsArray.length }), 'success');
      }
      setSelectedIds(new Set());
      setMultiSelectMode(false);
    } catch {
      showToast(tErrors('error_bulk_move'), 'error');
    } finally {
      clearBulkTriagePending(idsArray);
      setIsBulkLoading(false);
    }
  }, [selectedIds, showToast, t, tErrors, markBulkTriagePending, clearBulkTriagePending, hideEmailInCurrentFolder, clearEmailHiddenInFolder]);

  // Empty spam folder handler
  const [isEmptyingSpam, setIsEmptyingSpam] = useState(false);
  const [showEmptySpamConfirm, setShowEmptySpamConfirm] = useState(false);
  const emptySpamCount = useBulkActionCount({
    endpoint: '/emails/empty-spam',
    enabled: showEmptySpamConfirm,
  });
  const confirmEmptySpam = useCallback(async () => {
    setIsEmptyingSpam(true);
    try {
      const result = await apiClient.emptySpamFolder();
      invalidateEmailCache();
      setEmails([]);
      allEmailsRef.current = [];
      loadEmails(false, true);
      if (result.accepted) {
        // Async: backend split into trash + rescue jobs. The total covers
        // both so the toast count matches the user's mental model
        // ("everything in spam is being processed").
        showToast(
          t('spam_cleanup_queued', { count: result.target_total ?? 0 }),
          'info',
        );
      } else {
        showToast(
          t('messages_deleted_permanently', { count: result.deleted_count ?? 0 }),
          'success',
        );
      }
    } catch {
      showToast(tErrors('error_empty_spam'), 'error');
    } finally {
      setIsEmptyingSpam(false);
    }
  }, [showToast, loadEmails, t, tErrors]);
  const handleEmptySpam = useCallback(() => {
    setShowEmptySpamConfirm(true);
  }, []);

  // Restore from trash handler (single email)
  const handleRestore = useCallback((email: Email) => {
    if (pendingOpsRef.current.has(email.id)) return;
    pendingOpsRef.current.add(email.id);
    markTriagePending(email.id);

    apiClient.restoreFromTrash(email.id).then(() => {
      removeEmailAfterSuccessfulTriage(email, 'inbox', 'archive', () => {
        showToast(t('email_restored'), 'success');
        pendingOpsRef.current.delete(email.id);
      });
    }).catch(err => {
      console.error('[EmailList] restore from trash failed:', err);
      showToast(tErrors('error_restore'), 'error');
      clearTriagePending(email.id);
      pendingOpsRef.current.delete(email.id);
    });
  }, [clearTriagePending, markTriagePending, removeEmailAfterSuccessfulTriage, showToast, t, tErrors]);

  // Unarchive handler (move from archive to inbox)
  const handleUnarchive = useCallback((email: Email) => {
    if (pendingOpsRef.current.has(email.id)) return;
    pendingOpsRef.current.add(email.id);
    markTriagePending(email.id);

    apiClient.unarchiveEmail(email.id).then(() => {
      removeEmailAfterSuccessfulTriage(email, 'inbox', 'archive', () => {
        showToast(t('email_moved_inbox'), 'success');
        pendingOpsRef.current.delete(email.id);
      });
    }).catch(err => {
      console.error('[EmailList] unarchive failed:', err);
      showToast(tErrors('error_move'), 'error');
      clearTriagePending(email.id);
      pendingOpsRef.current.delete(email.id);
    });
  }, [clearTriagePending, markTriagePending, removeEmailAfterSuccessfulTriage, showToast, t, tErrors]);

  // Move to spam handler (backend auto-learns patterns)
  const handleMoveToSpam = useCallback((email: Email) => {
    if (pendingOpsRef.current.has(email.id)) return;
    pendingOpsRef.current.add(email.id);
    markTriagePending(email.id);

    apiClient.moveToSpam(email.id, email.sender).then(() => {
      removeEmailAfterSuccessfulTriage(email, 'spam', 'archive', () => {
        showToast(t('spam_learned'), 'success');
        pendingOpsRef.current.delete(email.id);
      });
    }).catch(err => {
      console.error('[EmailList] move to spam failed:', err);
      showToast(tErrors('error_move'), 'error');
      clearTriagePending(email.id);
      pendingOpsRef.current.delete(email.id);
    });
  }, [clearTriagePending, markTriagePending, removeEmailAfterSuccessfulTriage, showToast, t, tErrors]);

  // Block sender handler. The backend hides EVERY email from that address, so
  // optimistically remove all same-sender rows (not just the clicked one) to
  // match — otherwise the action looked like it did nothing until a full refresh.
  const handleBlockSender = useCallback((email: Email) => {
    const target = senderAddress(email.sender);
    const matches = (e: Email) => senderAddress(e.sender) === target;
    const removed = allEmailsRef.current.filter(matches);
    if (removed.length === 0) removed.push(email);

    setEmails(prev => prev.filter(e => !matches(e)));
    allEmailsRef.current = allEmailsRef.current.filter(e => !matches(e));

    blockSender(email.sender).then(() => {
      invalidateEmailCache();
      showToast(t('sender_blocked'), 'success');
    }).catch(err => {
      console.error('[EmailList] block sender failed:', err);
      // Rollback every removed row
      setEmails(prev => sortByDateDesc([...removed, ...prev]));
      allEmailsRef.current = sortByDateDesc([...removed, ...allEmailsRef.current]);
      showToast(t('sender_block_failed'), 'error');
    });
  }, [showToast, t]);

  // Bulk restore from trash handler
  const handleBulkRestore = useCallback(async () => {
    if (selectedIds.size === 0) return;

    const idsArray = Array.from(selectedIds);
    setIsBulkLoading(true);
    markBulkTriagePending(idsArray);

    try {
      const result = await apiClient.bulkRestoreFromTrash(idsArray);
      invalidateEmailCache();
      idsArray.forEach(id => {
        hideEmailInCurrentFolder(id);
        clearEmailHiddenInFolder('inbox', id);
      });
      setEmails(prev => prev.filter(e => !selectedIds.has(e.id)));
      allEmailsRef.current = allEmailsRef.current.filter(e => !selectedIds.has(e.id));
      if (result.accepted) {
        // Large wave — queued in the bulk-jobs queue. Track in Settings.
        showToast(t('bulk_queued', { count: result.target_total ?? idsArray.length }), 'info');
      } else {
        showToast(t('emails_restored', { count: idsArray.length }), 'success');
      }
      setSelectedIds(new Set());
      setMultiSelectMode(false);
    } catch {
      showToast(tErrors('error_bulk_restore'), 'error');
    } finally {
      clearBulkTriagePending(idsArray);
      setIsBulkLoading(false);
    }
  }, [selectedIds, showToast, t, tErrors, markBulkTriagePending, clearBulkTriagePending, hideEmailInCurrentFolder, clearEmailHiddenInFolder]);

  // Empty trash folder handler
  const [isEmptyingTrash, setIsEmptyingTrash] = useState(false);
  const [showEmptyTrashConfirm, setShowEmptyTrashConfirm] = useState(false);
  const emptyTrashCount = useBulkActionCount({
    endpoint: '/emails/empty-trash',
    enabled: showEmptyTrashConfirm,
  });
  const [isCleaningNoise, setIsCleaningNoise] = useState(false);
  const [isMarkingNoiseRead, setIsMarkingNoiseRead] = useState(false);

  const confirmEmptyTrash = useCallback(async () => {
    setIsEmptyingTrash(true);
    try {
      const result = await apiClient.emptyTrashFolder();
      // Optimistic UI eviction is the same regardless of sync vs async:
      // the backend already updated the SQLite cache before answering 202,
      // and even in the sync path we want to clear the list immediately.
      invalidateEmailCache();
      setEmails([]);
      allEmailsRef.current = [];
      loadEmails(false, true);
      // Async path (queue): the worker drains the deletes against the
      // provider in the background. Toast directs the user to the
      // Background Tasks panel where they can pause/cancel.
      if (result.accepted) {
        showToast(
          t('trash_cleanup_queued', { count: result.target_total ?? 0 }),
          'info',
        );
      } else {
        showToast(
          t('messages_deleted_permanently', { count: result.deleted_count ?? 0 }),
          'success',
        );
      }
    } catch {
      showToast(tErrors('error_empty_trash'), 'error');
    } finally {
      setIsEmptyingTrash(false);
    }
  }, [showToast, loadEmails, t, tErrors]);
  const handleEmptyTrash = useCallback(() => {
    setShowEmptyTrashConfirm(true);
  }, []);
  const handleCleanNoise = useCallback(async () => {
    setIsCleaningNoise(true);
    try {
      const result = await apiClient.cleanNoise();
      if (result.pending) {
        showToast(t('noise_cleanup_started'), 'info');
      } else {
        // Labels are removed synchronously regardless of sync/async —
        // abort any stale in-flight fetch, clear the list, reload (the
        // refreshed inbox returns 0 Noise emails).
        if (abortControllerRef.current) {
          abortControllerRef.current.abort();
          abortControllerRef.current = null;
        }
        invalidateEmailCache();
        setEmails([]);
        allEmailsRef.current = [];
        loadEmails(false, true);
        // Refresh label counts so Bruit badge updates immediately
        setTimeout(() => refreshCounts(), 300);
        if (result.accepted) {
          // Trashing routed through the bulk-jobs queue — track/pause it
          // in Settings → Background Tasks.
          showToast(
            t('bulk_queued', { count: result.target_total ?? result.archived_count ?? 0 }),
            'info',
          );
        } else {
          const total = (result.archived_count || 0) + (result.deleted_count || 0);
          showToast(t('noise_cleaned', { count: total }), 'success');
        }
      }
    } catch {
      showToast(tErrors('generic'), 'error');
    } finally {
      setIsCleaningNoise(false);
    }
  }, [showToast, loadEmails, t, tErrors, refreshCounts]);

  const handleMarkNoiseRead = useCallback(async () => {
    setIsMarkingNoiseRead(true);
    try {
      const result = await apiClient.markNoiseRead();
      invalidateEmailCache();

      const markNoiseRowsRead = (items: Email[]) =>
        items.map(email => (
          email.labels?.some(label => label.name === 'Noise')
            ? { ...email, is_read: true }
            : email
        ));

      setEmails(prev => markNoiseRowsRead(prev));
      allEmailsRef.current = markNoiseRowsRead(allEmailsRef.current);
      loadEmails(false, true);
      setTimeout(() => refreshCounts(), 300);

      const count = result.target_total ?? result.updated_count ?? 0;
      showToast(
        result.accepted ? t('bulk_queued', { count }) : t('noise_marked_read', { count }),
        result.accepted ? 'info' : 'success',
      );
    } catch {
      showToast(tErrors('generic'), 'error');
    } finally {
      setIsMarkingNoiseRead(false);
    }
  }, [showToast, loadEmails, t, tErrors, refreshCounts]);

  // Expose bulk handlers to App via refs (for ribbon clicks + keyboard shortcuts)
  // useLayoutEffect runs synchronously after DOM commit — eliminates the null window between
  // cleanup (null) and re-assignment that caused second bulk-delete to silently fail.
  useLayoutEffect(() => {
    if (bulkArchiveRef) bulkArchiveRef.current = multiSelectMode && selectedIds.size > 0 ? handleBulkArchive : null;
    if (bulkDeleteRef) bulkDeleteRef.current = multiSelectMode && selectedIds.size > 0 ? handleBulkDelete : null;
    if (bulkNotSpamRef) bulkNotSpamRef.current = multiSelectMode && selectedIds.size > 0 && folder === 'spam' ? handleBulkNotSpam : null;
    if (bulkRestoreRef) bulkRestoreRef.current = multiSelectMode && selectedIds.size > 0 && folder === 'trash' ? handleBulkRestore : null;
    if (deselectAllRef) deselectAllRef.current = multiSelectMode ? deselectAll : null;
    if (selectAllRef) selectAllRef.current = selectAll;
    if (selectAllFromHereRef) selectAllFromHereRef.current = selectAllFromHere;
    if (deleteEmailOptimisticRef) deleteEmailOptimisticRef.current = handleOptimisticDelete;
    if (archiveEmailOptimisticRef) archiveEmailOptimisticRef.current = handleOptimisticArchive;
    return () => {
      if (bulkArchiveRef) bulkArchiveRef.current = null;
      if (bulkDeleteRef) bulkDeleteRef.current = null;
      if (bulkNotSpamRef) bulkNotSpamRef.current = null;
      if (bulkRestoreRef) bulkRestoreRef.current = null;
      if (deselectAllRef) deselectAllRef.current = null;
      if (selectAllRef) selectAllRef.current = null;
      if (selectAllFromHereRef) selectAllFromHereRef.current = null;
      if (deleteEmailOptimisticRef) deleteEmailOptimisticRef.current = null;
      if (archiveEmailOptimisticRef) archiveEmailOptimisticRef.current = null;
    };
  }, [multiSelectMode, selectedIds.size, folder, handleBulkArchive, handleBulkDelete, handleBulkNotSpam, handleBulkRestore, deselectAll, selectAll, selectAllFromHere, bulkArchiveRef, bulkDeleteRef, bulkNotSpamRef, bulkRestoreRef, deselectAllRef, selectAllRef, selectAllFromHereRef, deleteEmailOptimisticRef, archiveEmailOptimisticRef, handleOptimisticDelete, handleOptimisticArchive]);

  // Refresh label counts when email list size changes (debounced to avoid cascade)
  const prevEmailCountRef = useRef(0);
  useEffect(() => {
    if (filteredEmails.length > 0 && filteredEmails.length !== prevEmailCountRef.current) {
      prevEmailCountRef.current = filteredEmails.length;
      const timer = setTimeout(() => refreshCounts(), 2000);
      return () => clearTimeout(timer);
    }

  }, [filteredEmails.length]);

  const handleLabelClick = useCallback((labelName: string) => {
    if (onLabelChange) {
      if (activeLabel === labelName) {
        onLabelChange(null);
      } else {
        onLabelChange(labelName);
      }
    }
  }, [activeLabel, onLabelChange]);

  const hasActiveFilters = searchQuery.trim() !== '' || statusFilter !== 'all' || activeLabel !== null;


  // Show total email count for inbox tab; other folders display clean title only
  const headerCount = folder === 'inbox' ? collapsedEmails.length : 0;
  const displayNameFn = useMemo(() => {
    if (folder === 'sent') {
      const noRecipientLabel = t('drafts:no_recipient', { defaultValue: 'Sans destinataire' });
      return (email: Email) => getRecipientDisplay(email, noRecipientLabel);
    }
    if (!accountEmail) return getSenderDisplay;
    const ownEmail = accountEmail.toLowerCase();
    return (email: Email) => {
      if (email.sender && email.sender.toLowerCase() === ownEmail) return 'Moi';
      return getSenderDisplay(email);
    };
  }, [folder, accountEmail, t]);

  if ((loadingState === 'loading' || loadingState === 'idle') && emails.length === 0) {
    return (
      <div className="email-list-container" data-testid="email-list-container">
        <EmailListHeader
          folder={folder}
          folderTitle={folderTitle}
          activeLabel={activeLabel}
          unreadCount={0}
          favoriteLabels={[]}
          labelCounts={{}}
          onLabelClick={handleLabelClick}
          onClearLabel={() => onLabelChange?.(null)}
          showSearchBar={showSearchBar}
          onToggleSearchBar={toggleSearchBar}
          skeleton
        />
        <EmailSkeletonList count={10} />
      </div>
    );
  }

  if (noAccount) {
    return (
      <div className="email-list-container" data-testid="email-list-container">
        <div className="email-list-welcome">
          <span className="welcome-icon">&#9993;</span>
          <h3>{t('no_account_title')}</h3>
          <p>{t('no_account_desc')}</p>
          <button className="welcome-connect-btn" onClick={onOpenAccounts}>
            {t('no_account_btn')}
          </button>
        </div>
      </div>
    );
  }

  if (loadingState === 'error') {
    return (
      <div className="email-list-container" data-testid="email-list-container">
        <EmailListHeader
          folder={folder}
          folderTitle={folderTitle}
          activeLabel={activeLabel}
          unreadCount={0}
          favoriteLabels={[]}
          labelCounts={{}}
          onLabelClick={handleLabelClick}
          onClearLabel={() => onLabelChange?.(null)}
          showSearchBar={showSearchBar}
          onToggleSearchBar={toggleSearchBar}
          skeleton
        />
        <div className="email-list-error" data-testid="email-list-error">
          <span className="error-icon">!</span>
          <p data-testid="error-message">{error}</p>
          <button onClick={() => loadEmails(true)} className="retry-button" data-testid="retry-button" title={t('retry', { ns: 'common' })}>
            {t('retry', { ns: 'common' })}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="email-list-container" data-testid="email-list-container">
      <ConfirmationDialog
        isOpen={showEmptySpamConfirm}
        onConfirm={confirmEmptySpam}
        onCancel={() => setShowEmptySpamConfirm(false)}
        title={t('empty_spam_confirm_title')}
        message={
          <span style={{ display: 'block', whiteSpace: 'normal' }}>
            {t('empty_spam_confirm_message')}
            {emptySpamCount.count !== null && emptySpamCount.count > 0 && (
              <><br />{t('bulk_count_summary', { count: emptySpamCount.count })}</>
            )}
            {emptySpamCount.willBeAsync && (
              <><br />{t('bulk_queued_hint')}</>
            )}
          </span>
        }
        confirmLabel={t('empty_spam_confirm_label')}
        destructive
      />
      <ConfirmationDialog
        isOpen={showEmptyTrashConfirm}
        onConfirm={confirmEmptyTrash}
        onCancel={() => setShowEmptyTrashConfirm(false)}
        title={t('empty_trash_confirm_title')}
        message={
          <span style={{ display: 'block', whiteSpace: 'normal' }}>
            {t('empty_trash_confirm_message')}
            {emptyTrashCount.count !== null && emptyTrashCount.count > 0 && (
              <><br />{t('bulk_count_summary', { count: emptyTrashCount.count })}</>
            )}
            {emptyTrashCount.willBeAsync && (
              <><br />{t('bulk_queued_hint')}</>
            )}
          </span>
        }
        confirmLabel={t('empty_trash_confirm_label')}
        destructive
      />
      <EmailListHeader
        folder={folder}
        folderTitle={folderTitle}
        activeLabel={activeLabel}
        unreadCount={headerCount}
        favoriteLabels={favoriteLabels}
        labelCounts={labelCounts}
        onLabelClick={handleLabelClick}
        onClearLabel={() => onLabelChange?.(null)}
        showSearchBar={showSearchBar}
        onToggleSearchBar={toggleSearchBar}
        multiSelectMode={multiSelectMode}
        selectedCount={selectedIds.size}
        totalCount={collapsedEmails.length}
        onSelectAll={selectAll}
        onDeselectAll={deselectAll}
        onSelectAllFromHere={selectAllFromHere}
      />

      {showSearchBar && (
        <div className="email-list-search-bar" style={{ position: 'relative' }}>
          <SmartSearchBar
            onSearch={handleSearch}
            initialValue={searchQuery}
            isLoading={isSearching && loadingState === 'loading'}
            labels={allLabels}
            accountId={undefined}
            onClose={() => {
              setShowSearchBar(false);
              setSearchQuery('');
              setIsSearching(false);
              searchAbortRef.current?.abort();
              setEmails(allEmailsRef.current);
            }}
          />
          {isSearching && searchQuery && (
            <div className="search-results-count" aria-live="polite">
              {collapsedEmails.length > 0 ? (
                <>
                  <span className="search-results-count-number">{collapsedEmails.length}</span>
                  {' '}
                  {collapsedEmails.length === 1
                    ? t('search_results_one')
                    : t('search_results_other', { count: collapsedEmails.length })}
                  {' '}
                  <span className="search-results-query">« {searchQuery} »</span>
                </>
              ) : null}
              <span className="search-results-scope">
                {collapsedEmails.length > 0 && <span className="search-results-scope-sep" aria-hidden="true">·</span>}
                {t('search_scope_label', { folder: t(folder === 'inbox' ? 'title' : folder, { defaultValue: folder }) })}
              </span>
            </div>
          )}
        </div>
      )}

      {folder === 'spam' && !multiSelectMode && (
        <div className="spam-banner">
          <TrashIcon size={14} />
          <span>{autoEmptySpam ? t('spam_auto_delete_notice') : t('spam_auto_delete_disabled')}</span>
          <button
            className="spam-empty-btn"
            onClick={handleEmptySpam}
            disabled={isEmptyingSpam || collapsedEmails.length === 0}
            type="button"
            title={t('empty_spam_btn')}
          >
            {isEmptyingSpam ? <span className="banner-btn-spinner" /> : <TrashIcon size={14} />}
          </button>
        </div>
      )}

      {folder === 'inbox' && activeLabel === 'Noise' && !multiSelectMode && (
        <div className="noise-banner">
          <TrashIcon size={14} />
          <span>{autoDeleteNoise ? t('noise_auto_cleanup_notice') : t('noise_auto_cleanup_disabled')}</span>
          <div className="noise-banner-actions">
            <button
              className="noise-read-btn"
              onClick={handleMarkNoiseRead}
              disabled={isMarkingNoiseRead || collapsedEmails.length === 0}
              type="button"
              title={t('mark_noise_read_btn')}
            >
              {isMarkingNoiseRead ? <span className="banner-btn-spinner" /> : <CheckIcon size={14} />}
            </button>
            <button
              className="noise-clean-btn"
              onClick={handleCleanNoise}
              disabled={isCleaningNoise || collapsedEmails.length === 0}
              type="button"
              title={t('clean_noise_btn')}
            >
              {isCleaningNoise ? <span className="banner-btn-spinner" /> : <TrashIcon size={14} />}
            </button>
          </div>
        </div>
      )}

      {folder === 'trash' && !multiSelectMode && (
        <div className="trash-banner">
          <TrashIcon size={14} />
          <span>{autoEmptyTrash ? t('trash_auto_delete_notice') : t('trash_auto_delete_disabled')}</span>
          <button
            className="trash-empty-btn"
            onClick={handleEmptyTrash}
            disabled={isEmptyingTrash || collapsedEmails.length === 0}
            type="button"
            title={t('empty_trash_btn')}
          >
            {isEmptyingTrash ? <span className="banner-btn-spinner" /> : <TrashIcon size={14} />}
          </button>
        </div>
      )}


      {collapsedEmails.length === 0 ? (
        <EmailListEmpty
          folder={folder}
          activeLabel={activeLabel}
          hasActiveFilters={hasActiveFilters}
          noiseLabelCount={labelCounts['Noise'] || 0}
          hideNoise={hideNoise}
          onToggleHideNoise={toggleHideNoise}
          isSearching={isSearching}
          searchQuery={searchQuery}
        />
      ) : (
        <EmailListContent
          filteredEmails={collapsedEmails}
          selectedEmailId={selectedEmailId}
          handleEmailClick={handleEmailClick}
          onSwipeArchive={handleOptimisticArchive}
          onSwipeDelete={handleOptimisticDelete}
          handleMarkReadToggle={handleMarkReadToggle}
          handleLabelUpdate={handleLabelUpdate}
          showToast={showToast}
          multiSelectMode={multiSelectMode}
          selectedIds={selectedIds}
          handleCheckChange={handleCheckChange}
          handleShiftClick={handleShiftClick}
          animatingEmailId={animatingEmailId}
          animationType={animationType}
          shiftBelowIndex={shiftBelowIndex}
          shiftAmount={shiftAmount}
          flatRowsRef={flatRowsRef}
          onLoadMore={loadMore}
          hasMore={hasMore && !isSearching}
          isLoadingMore={isLoadingMore}
          localDraftEmailIds={localDraftEmailIds}
          getSenderDisplayFn={displayNameFn}
          folder={folder}
          wokeIds={snooze.wokeIds}
          wokeFollowupIds={snooze.wokeFollowupIds}
          sleepingIds={snooze.sleepingIds}
          snoozedMap={snooze.snoozedMap}
          dismissSnoozed={snooze.dismissSnoozed}
          pinnedIds={pinnedIds}
          onPinToggle={(email) => {
            togglePin(email.id);
            // If this was a woken snooze email, dismiss it so it leaves the top too
            if (snooze.wokeIds.has(email.id)) {
              const entry = snooze.snoozedMap.get(email.id);
              snooze.dismissSnoozed(email.id);
              // dismissSnoozed already deletes the backend reminder (+ toast on
              // failure) for followup-type entries; only handle the snooze-type
              // case here to avoid a redundant double-delete and double-toast.
              if (entry?.reminderId && entry.type !== 'followup') {
                apiClient.deleteReminder(entry.reminderId).catch(err => {
                  console.warn('[EmailList] onPinToggle deleteReminder failed:', entry?.reminderId, err);
                  // TC-05: surface the failure — otherwise the reminder re-injects
                  // on next restart and the woken email reappears at the top.
                  window.dispatchEvent(new CustomEvent('agentys:toast', {
                    detail: { message: i18n.t('common:toasts.reminder_delete_failed'), type: 'warning', duration: 5000 },
                  }));
                });
              }
            }
          }}
          onNotSpam={handleNotSpam}
          onRestore={handleRestore}
          onMoveToSpam={handleMoveToSpam}
          onBlockSender={handleBlockSender}
          onUnarchive={handleUnarchive}
          onDeleteDraft={onDeleteDraft}
          viewMode={viewMode}
          threadCounts={threadCounts}
          userLabelNames={userLabelNames}
          onOpenSnooze={handleOpenSnooze}
          triagePendingIds={triagePendingIds}
        />
      )}

      {!onToast && <ToastContainer toasts={toasts} onDismiss={dismissToast} />}

      {snoozeTarget && (
        <SnoozeDropdown
          position={snoozeTarget.pos}
          emailBody={snoozeTarget.email.body_preview}
          onSnooze={(date) => {
            writeSnoozeEntry(
              snoozeTarget.email.id,
              date,
              snoozeTarget.email.subject,
              'snooze',
              snoozeTarget.email.labels as unknown as string[]
            );
            setSnoozeTarget(null);
          }}
          onClose={() => setSnoozeTarget(null)}
        />
      )}
    </div>
  );
})
