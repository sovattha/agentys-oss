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
import React, { useState, useRef, useCallback, useEffect, useLayoutEffect } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import i18n from '../i18n';
import { formatShortDate, formatShortDateFromDate } from '../utils/dateFormat';
import { htmlToPreviewText } from '../utils/emailContent';
import type { Email, EmailLabel } from '../types/email';
import { LabelBadgeGroup } from './labels/LabelBadge';
import { LabelQuickPicker } from './labels/LabelQuickPicker';
import { learnFromCorrection } from '../api/labels';
import { isDefaultLabel } from '../types/labels';
import { unsubscribeBySender } from '../api/emails';
import { blockSender } from '../services/api';
import { exportEmailToPdf } from '../utils/exportEmailPdf';
import { API_URL } from '../config';
import { useQuickSteps } from '../hooks/useQuickSteps';
import { useQuickStepRunner } from '../hooks/useQuickStepRunner';
// Pulls in the shared `.quicksteps-confirm` modal styles used by
// QuickStepConfirm below — works whether or not the email detail
// (which also imports it) has been opened yet this session.
import './QuickStepsBar.css';
import { usePendingSends } from '../hooks/usePendingSends';
import type { EmailViewMode } from '../hooks/useEmailViewMode';
import { EditIcon, FollowUpIcon } from './icons/ActionIcons';
import { getInitials } from './Avatar';
import './SwipeableEmailItem.css';

/** Supprime les balises HTML et décode les entités d'un snippet de prévisualisation.
 *  Délègue au stripper partagé : décodage complet des entités (&#39; &rsquo;
 *  &mdash; …) ET aucune balise n'est parsée par le DOM, donc pas de chargement
 *  d'<img>/onerror ni de pixel de tracking. BUG-S002 fix. */
function stripHtml(html: string): string {
  return htmlToPreviewText(html);
}

/**
 * Decode HTML entities in a plain-text string (e.g. &#x27; → ', &amp; → &).
 * Uses a textarea so the browser handles all entity forms including named,
 * decimal, and hex numeric references. Safe: no innerHTML on user-visible nodes.
 * BUG-S001 fix: API returns HTML-encoded subject lines that were shown raw.
 */
function decodeHtmlEntities(text: string): string {
  try {
    const ta = document.createElement('textarea');
    ta.innerHTML = text;
    return ta.value;
  } catch {
    return text;
  }
}

// Pastel avatar colors — deterministic per sender name
const AVATAR_COLORS = [
  { bg: '#fce4ec', fg: '#c62828' },
  { bg: '#e3f2fd', fg: '#1565c0' },
  { bg: '#e8f5e9', fg: '#2e7d32' },
  { bg: '#fff8e1', fg: '#f57f17' },
  { bg: '#f3e5f5', fg: '#7b1fa2' },
  { bg: '#e0f2f1', fg: '#00695c' },
  { bg: '#e8eaf6', fg: '#283593' },
  { bg: '#fff3e0', fg: '#e65100' },
  { bg: '#e0f7fa', fg: '#00838f' },
  { bg: '#fce4ec', fg: '#ad1457' },
];

function getAvatarColor(name: string) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
}

// Module-level flag: tracks whether user is in keyboard-nav mode.
// Set true when arrow keys navigate emails, set false when mouse enters an item.
// Prevents hover-based Delete from intercepting keyboard-triggered actions.
let _keyboardNavMode = false;
export function setKeyboardNavMode(active: boolean) { _keyboardNavMode = active; }

// Track mouse position so we can resolve the email under cursor on keypress
let _mouseX = 0;
let _mouseY = 0;
if (typeof document !== 'undefined') {
  document.addEventListener('mousemove', (e) => { _mouseX = e.clientX; _mouseY = e.clientY; }, { passive: true });
}

// Synchronous set of email IDs currently being deleted (animation pending).
// Updated by EmailList.handleOptimisticDelete before React re-renders,
// so getEmailIdUnderCursor() can skip them immediately.
const _pendingDeleteIds = new Set<string>();
export function markDeletePending(id: string) { _pendingDeleteIds.add(id); }
export function unmarkDeletePending(id: string) { _pendingDeleteIds.delete(id); }

// Track the most recently initiated deletion so rapid successive Del presses
// can reliably find the NEXT email to delete (bypassing fragile hover tracking).
let _lastPendingDeleteId: string | null = null;
export function setLastPendingDeleteId(id: string) { _lastPendingDeleteId = id; }
export function getLastPendingDeleteId(): string | null { return _lastPendingDeleteId; }
export function clearLastPendingDeleteId() { _lastPendingDeleteId = null; }

/**
 * Returns the email id of the first non-animating email item at or below the
 * current cursor position. Skips ids in `_pendingDeleteIds` (rows whose removal
 * is in flight during the 260ms slide-out — populated by BOTH the delete and the
 * archive optimistic handlers) so rapid successive Del/E presses target the next
 * row rather than re-hitting the still-animating one.
 */
export function getEmailIdUnderCursor(): string | null {
  // Walk up from point to find the email item (or its ancestor)
  const getEmailId = (el: Element | null): string | null => {
    let node = el as HTMLElement | null;
    while (node) {
      if (node.dataset?.emailId) return node.dataset.emailId;
      node = node.parentElement;
    }
    return null;
  };

  // Try current cursor position first
  const atPoint = document.elementFromPoint(_mouseX, _mouseY);
  const idAtPoint = getEmailId(atPoint);
  if (idAtPoint && !_pendingDeleteIds.has(idAtPoint)) {
    return idAtPoint;
  }

  // The item at cursor is pending deletion: scan downward to find the next email
  for (let dy = 1; dy <= 120; dy += 4) {
    const el = document.elementFromPoint(_mouseX, _mouseY + dy);
    const id = getEmailId(el);
    if (!id || id === idAtPoint) continue;
    if (!_pendingDeleteIds.has(id)) {
      return id;
    }
  }

  return null;
}

/** Brief keyboard activation pulse on the currently hovered/selected item (5.2) */
export function triggerKeyboardPulse() {
  const el = document.querySelector('.swipeable-email-item.hovered') ||
             document.querySelector('.swipeable-email-item.selected');
  if (!el) return;
  el.classList.add('keyboard-activate');
  setTimeout(() => el.classList.remove('keyboard-activate'), 150);
}

// Module-level hover tracking — robust fallback for global keyboard handler.
// Per-item document listeners can miss events (react-window re-renders, timing);
// these module-level refs let the global handler act on the hovered email directly.
let _hoveredDeleteFn: (() => void) | null = null;
let _hoveredArchiveFn: (() => void) | null = null;
// Store a ref (not a value) so we always get the latest email even when react-window
// reuses a component at the same index with new props (e.g. after deletion shifts rows).
let _hoveredEmailRef: React.MutableRefObject<Email> | null = null;
// After a delete animation starts, CSS shifts cause adjacent emails to fire mouseenter
// events as their hit boxes move to the cursor position. Lock hover updates for 350ms
// so these spurious mouseenter events don't hijack the next Delete keypress target.
let _hoverLockUntil = 0;
export function lockHoverForAnimation() { _hoverLockUntil = Date.now() + 350; }
let _multiSelectActive = false;
export function setMultiSelectActive(active: boolean) { _multiSelectActive = active; }

/** Returns the currently hovered email (for global Delete handler). Null in keyboard-nav or multi-select mode. */
export function getHoveredEmail(): Email | null {
  return (_keyboardNavMode || _multiSelectActive) ? null : (_hoveredEmailRef?.current ?? null);
}

/** Called by the global keyboard handler as fallback when per-item listener misses */
export function deleteHoveredEmail(): boolean {
  if (_keyboardNavMode || _multiSelectActive || !_hoveredDeleteFn) return false;
  // If the hovered email is already pending deletion, return false so the
  // caller falls through to getEmailIdUnderCursor() for the next email.
  const hoveredId = _hoveredEmailRef?.current?.id;
  if (hoveredId && _pendingDeleteIds.has(hoveredId)) return false;
  _hoveredDeleteFn();
  return true;
}
export function archiveHoveredEmail(): boolean {
  if (_keyboardNavMode || _multiSelectActive || !_hoveredArchiveFn) return false;
  _hoveredArchiveFn();
  return true;
}
export function hasHoveredEmailForArchive(): boolean {
  return !_keyboardNavMode && !_multiSelectActive && _hoveredArchiveFn !== null
}
export function hasHoveredEmailForDelete(): boolean {
  return !_keyboardNavMode && !_multiSelectActive && _hoveredDeleteFn !== null
}

interface ContextMenuPosition {
  x: number;
  y: number;
}

interface SwipeableEmailItemProps {
  email: Email;
  selected: boolean;
  onSelect: (email: Email) => void;
  onSwipeArchive?: (email: Email) => void;
  onSwipeDelete?: (email: Email) => void;
  onMarkReadToggle?: (email: Email, isRead: boolean) => void;
  formatTime: (date: string) => string;
  getSenderDisplay: (email: Email) => string;
  onLabelUpdate?: (email: Email, newLabels: EmailLabel[], silent?: boolean) => void;
  onToast?: (message: string, type: 'success' | 'error' | 'info') => void;
  // Multi-select props
  multiSelectMode?: boolean;
  isChecked?: boolean;
  onCheckChange?: (email: Email, checked: boolean) => void;
  onShiftClick?: (email: Email) => void;
  /** Priority section key for contextual hover behavior */
  sectionKey?: string;
  /** Called when user snoozes this email (for Deep Focus stats tracking) */
  onSnoozed?: (email: Email) => void;
  /** Called when user opens the snooze picker — lifted to EmailList to survive react-window remounts */
  onOpenSnooze?: (email: Email, pos: { x: number; y: number }) => void;
  /** Whether a local reply draft exists for this email */
  hasLocalDraft?: boolean;
  /** Current folder — used for conditional context menu items */
  folder?: string;
  /** Called when user marks this email as not-spam */
  onNotSpam?: (email: Email) => void;
  /** Called when user restores this email from trash */
  onRestore?: (email: Email) => void;
  /** Called when user moves this email to spam (backend auto-learns patterns) */
  onMoveToSpam?: (email: Email) => void;
  /** Called when user blocks this sender — lets the host optimistically drop all
   *  same-sender rows. When omitted, falls back to an in-place block + toast. */
  onBlockSender?: (email: Email) => void;
  /** Called when user unarchives this email (moves from archive to inbox) */
  onUnarchive?: (email: Email) => void;
  /** Email view mode — compact (1-line) or comfortable (3-line) */
  viewMode?: EmailViewMode;
  /** Number of messages in this conversation thread */
  threadCount?: number;
  /** ISO date when snooze wakes (sleeping state) */
  snoozedUntil?: string | null;
  /** True when snooze has expired and email is pinned at top */
  isWoken?: boolean;
  /** True when woken entry is a follow-up reminder (vs regular snooze) */
  isFollowup?: boolean;
  /** True when this email is manually pinned */
  isPinned?: boolean;
  /** Called when user toggles pin on this email */
  onPinToggle?: (email: Email) => void;
  /** Called when user deletes the pending draft for this email */
  onDeleteDraft?: (email: Email) => void;
  /** Set of label names from the user's library — only these are displayed */
  userLabelNames?: ReadonlySet<string>;
  /** IDs of all currently selected emails — used to export all when multi-select is active */
  selectedIds?: Set<string>;
  /** True when a follow-up nudge is pending for this sent email */
  hasPendingFollowup?: boolean;
  /** True while a triage/move action is pending for this row */
  isTriagePending?: boolean;
}

/** Display-cased shortcut for the right-click menu kbd (e.g. "ctrl+1" → "Ctrl+1"). */
function formatShortcutLabel(value: string): string {
  return value
    .split('+')
    .map(part => (part.length === 1 ? part.toUpperCase() : part[0].toUpperCase() + part.slice(1)))
    .join('+')
}

interface QuickStepConfirmProps {
  stepName: string
  onConfirm: () => void
  onCancel: () => void
}

/** Confirmation modal shown when running a Quick Action whose chain sends
 *  real email (reply_template / forward). Esc cancels, Enter confirms. */
function QuickStepConfirm({ stepName, onConfirm, onCancel }: QuickStepConfirmProps) {
  const { t } = useTranslation('settings')
  const { t: tCommon } = useTranslation('common')
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
      if (e.key === 'Enter') onConfirm()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onCancel, onConfirm])

  return (
    <div className="quicksteps-confirm" role="dialog" aria-modal="true">
      <div className="quicksteps-confirm__panel">
        <h4>{t('quicksteps_confirm_title', { name: stepName })}</h4>
        <p>{t('quicksteps_confirm_chain_hint')}</p>
        <div className="quicksteps-confirm__cta">
          <button type="button" onClick={onCancel}>{tCommon('cancel')}</button>
          <button type="button" className="primary" onClick={onConfirm} autoFocus>
            {tCommon('confirm')}
          </button>
        </div>
        <p className="quicksteps-confirm__hint">
          {t('quicksteps_confirm_shift_hint')}
        </p>
      </div>
    </div>
  )
}

function TriagePendingBadge({ label }: { label: string }) {
  return (
    <span
      className="triage-pending-badge"
      data-testid="triage-pending-badge"
      aria-label={label}
      title={label}
    >
      <span className="triage-pending-spinner" aria-hidden="true" />
    </span>
  );
}

function formatSnoozeDate(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const tomorrow = new Date(now);
  tomorrow.setDate(tomorrow.getDate() + 1);
  const locale = i18n.language;

  if (date.toDateString() === tomorrow.toDateString()) {
    return i18n.t('common:tomorrow');
  }

  const diffMs = date.getTime() - now.getTime();
  const diffDays = diffMs / (1000 * 60 * 60 * 24);
  if (diffDays < 7) {
    return date.toLocaleString(locale, { weekday: 'short' });
  }

  return formatShortDateFromDate(date, locale);
}

export const SwipeableEmailItem = React.memo(function SwipeableEmailItem({
  email,
  selected,
  onSelect,
  onSwipeArchive,
  onSwipeDelete,
  onMarkReadToggle,
  formatTime,
  getSenderDisplay,
  onLabelUpdate,
  onToast,
  multiSelectMode = false,
  isChecked = false,
  onCheckChange,
  onShiftClick,
  sectionKey,
  onSnoozed: _onSnoozed,
  hasLocalDraft = false,
  folder,
  onNotSpam,
  onRestore,
  onMoveToSpam,
  onBlockSender,
  onUnarchive,
  viewMode = 'compact',
  threadCount,
  snoozedUntil,
  isWoken,
  isFollowup,
  isPinned,
  onPinToggle,
  onDeleteDraft,
  userLabelNames,
  selectedIds,
  onOpenSnooze,
  hasPendingFollowup = false,
  isTriagePending = false,
}: SwipeableEmailItemProps) {
  const { t } = useTranslation('inbox');
  const { t: tQuick } = useTranslation('settings');
  const [contextMenu, setContextMenu] = useState<ContextMenuPosition | null>(null);
  // Clamped on-screen positions — computed once each menu has measured itself,
  // so it never spills past a viewport edge (e.g. right-click near the list
  // bottom would otherwise clip the menu and overlap the footer bar).
  const [menuPos, setMenuPos] = useState<ContextMenuPosition | null>(null);
  const [isPdfExporting, setIsPdfExporting] = useState(false);
  const [labelPickerPos, setLabelPickerPos] = useState<ContextMenuPosition | null>(null);
  const submenuRef = useRef<HTMLDivElement | null>(null);
  const [submenuPos, setSubmenuPos] = useState<ContextMenuPosition | null>(null);
  const [submenuClamped, setSubmenuClamped] = useState<ContextMenuPosition | null>(null);
  const isHoveredRef = useRef(false);
  const contextMenuRef = useRef<HTMLDivElement>(null);
  // Quick Actions integration — surface user-defined chains at the top
  // of the right-click menu. The runner closes the menu after a successful
  // run via the onExecuted callback. Confirm modal renders via a portal,
  // so it overlays the closing menu without being clipped.
  const { steps: quickSteps } = useQuickSteps();
  const enabledQuickSteps = quickSteps.filter(s => s.enabled && !s.autoEnabled);
  const quickRunner = useQuickStepRunner(() => setContextMenu(null));
  // Pass email.id so the store subscription bails out (Object.is on the
  // per-email remaining) when another row's send is ticking — only the
  // counting-down row re-renders each second (audit 2026-06-02 O).
  const { isPendingSend: checkPendingSend, getPendingSendRemaining, cancelPendingSend: cancelSend } = usePendingSends(email.id);
  const emailPending = folder === 'sent' && checkPendingSend(email.id);
  const canToggleRead = folder !== 'sent' && Boolean(onMarkReadToggle);
  const nextReadState = !email.is_read;
  const readToggleLabel = nextReadState ? t('mark_as_read') : t('mark_as_unread');
  const [labelTriageCount, setLabelTriageCount] = useState(0);
  const isRowTriagePending = isTriagePending || labelTriageCount > 0;
  const beginLabelTriage = useCallback(() => {
    setLabelTriageCount(count => count + 1);
  }, []);
  const endLabelTriage = useCallback(() => {
    setLabelTriageCount(count => Math.max(0, count - 1));
  }, []);

  const handleReadToggleClick = useCallback((e: React.MouseEvent<HTMLButtonElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (!canToggleRead) return;
    onMarkReadToggle?.(email, nextReadState);
    setContextMenu(null);
  }, [canToggleRead, email, nextReadState, onMarkReadToggle]);

  const handleExportPdf = useCallback(async () => {
    setIsPdfExporting(true);
    setContextMenu(null);
    try {
      // If this email is checked and multiple are selected → export all selected
      const idsToExport = isChecked && selectedIds && selectedIds.size > 1
        ? Array.from(selectedIds)
        : [email.id];

      const results = await Promise.all(
        idsToExport.map(id =>
          fetch(`${API_URL}/api/emails/${encodeURIComponent(id)}`)
            .then(r => r.ok ? r.json() : null)
            .catch(() => null)
        )
      );

      const messages = results
        .filter(Boolean)
        .map((data: Record<string, unknown>) => ({
          subject: data.subject as string,
          sender: data.sender as string,
          senderName: data.sender_name as string,
          senderEmail: (data.sender_email || data.sender) as string,
          to: (data.to as string[]) || [],
          cc: (data.cc as string[]) || [],
          body: (data.body_html || data.body || '') as string,
          receivedAt: data.received_at as string,
          attachments: (data.attachments as Array<{ filename: string; size: number; content_type: string }>) || [],
        }))
        // Sort chronologically
        .sort((a, b) => (a.receivedAt || '').localeCompare(b.receivedAt || ''));

      if (messages.length === 0) throw new Error('no data');

      const pdfTitle = messages.length === 1
        ? (messages[0].subject || 'email')
        : `${messages.length} emails`;

      await exportEmailToPdf(pdfTitle, messages);
      onToast?.(t('pdf_export_success'), 'success');
    } catch {
      onToast?.(t('pdf_export_error'), 'error');
    } finally {
      setIsPdfExporting(false);
    }
  }, [email.id, isChecked, selectedIds, onToast, t]);

  // Refs for module-level hover tracking (always-fresh, no stale closures)
  const emailRef = useRef(email);
  emailRef.current = email;
  const onSwipeDeleteRef = useRef(onSwipeDelete);
  onSwipeDeleteRef.current = onSwipeDelete;
  const onSwipeArchiveRef = useRef(onSwipeArchive);
  onSwipeArchiveRef.current = onSwipeArchive;

  // Close context menu on click outside
  useEffect(() => {
    if (!contextMenu) return;

    const handleClickOutside = (e: MouseEvent) => {
      const inMain = contextMenuRef.current?.contains(e.target as Node);
      const inSub = submenuRef.current?.contains(e.target as Node);
      if (!inMain && !inSub) {
        setContextMenu(null);
        setSubmenuPos(null);
      }
    };

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setContextMenu(null);
        setSubmenuPos(null);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape);

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [contextMenu]);

  // Keep the right-click menu inside the viewport. It opens at the raw click
  // point, so a click near the bottom/right edge would clip it (and overlap
  // the footer bar). Measure once rendered, then clamp before the browser
  // paints — useLayoutEffect runs pre-paint, so there is no visible jump.
  useLayoutEffect(() => {
    if (!contextMenu) { setMenuPos(null); return; }
    const el = contextMenuRef.current;
    if (!el) return;
    const { width, height } = el.getBoundingClientRect();
    const margin = 8;
    setMenuPos({
      x: Math.max(margin, Math.min(contextMenu.x, window.innerWidth - width - margin)),
      y: Math.max(margin, Math.min(contextMenu.y, window.innerHeight - height - margin)),
    });
  }, [contextMenu]);

  // Same clamp for the Quick-actions submenu — its trigger handler already
  // flips it horizontally, this also keeps it off the bottom edge.
  useLayoutEffect(() => {
    if (!submenuPos) { setSubmenuClamped(null); return; }
    const el = submenuRef.current;
    if (!el) return;
    const { width, height } = el.getBoundingClientRect();
    const margin = 8;
    setSubmenuClamped({
      x: Math.max(margin, Math.min(submenuPos.x, window.innerWidth - width - margin)),
      y: Math.max(margin, Math.min(submenuPos.y, window.innerHeight - height - margin)),
    });
  }, [submenuPos]);

  // Ref-based keyboard handler (always up-to-date, no state re-renders)
  const keyHandlerRef = useRef<((e: KeyboardEvent) => void) | null>(null);
  const activeKeyListenerRef = useRef<((e: KeyboardEvent) => void) | null>(null);

  useEffect(() => {
    keyHandlerRef.current = (e: KeyboardEvent) => {
      // In keyboard-nav mode, let the global handler (useAppShortcuts) take care of actions
      if (_keyboardNavMode) return;
      // In multi-select mode, let the global handler run bulk actions
      if (multiSelectMode) return;

      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) return;

      if (e.key === 'F10' && e.shiftKey) {
        e.preventDefault();
        const rect = document.querySelector(`[data-email-id="${email.id}"]`)?.getBoundingClientRect();
        if (rect) setContextMenu({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 });
      }
    };
  }, [email.id, multiSelectMode]);

  // Cleanup listener on unmount
  useEffect(() => {
    return () => {
      if (activeKeyListenerRef.current) {
        document.removeEventListener('keydown', activeKeyListenerRef.current);
      }
      // Clear module-level hover tracking if this item was hovered
      if (isHoveredRef.current) {
        _hoveredEmailRef = null;
        _hoveredDeleteFn = null;
        _hoveredArchiveFn = null;
      }
    };
  }, []);

  // Hover-only keyboard listener — NOT for keyboard-selected items
  // Keyboard-selected items use the global useAppShortcuts handler instead
  const handleMouseEnter = useCallback(() => {
    _keyboardNavMode = false; // Mouse is active, exit keyboard-nav mode
    isHoveredRef.current = true;
    // Module-level hover tracking (robust fallback for global handler)
    // Store the ref itself so getHoveredEmail() always reads the latest email prop,
    // even when react-window reuses this component with a new email after a row deletion.
    // Skip if hover is locked: CSS shift animations can fire spurious mouseenter events
    // on adjacent emails as their hit boxes shift to the cursor position (350ms window).
    if (Date.now() < _hoverLockUntil) return;
    _hoveredEmailRef = emailRef;
    _hoveredDeleteFn = () => onSwipeDeleteRef.current?.(emailRef.current);
    _hoveredArchiveFn = () => onSwipeArchiveRef.current?.(emailRef.current);
    if (activeKeyListenerRef.current) {
      document.removeEventListener('keydown', activeKeyListenerRef.current);
    }
    const listener = (e: KeyboardEvent) => keyHandlerRef.current?.(e);
    activeKeyListenerRef.current = listener;
    document.addEventListener('keydown', listener);
  }, []);

  const handleMouseLeave = useCallback(() => {
    isHoveredRef.current = false;
    // During a delete animation, CSS translateX fires a spurious mouseleave on the
    // animating email. Keep hover tracking intact so the next Del keypress can still
    // find the correct target via _hoveredEmailRef (A) → next email (B).
    if (Date.now() < _hoverLockUntil) return;
    _hoveredEmailRef = null;
    _hoveredDeleteFn = null;
    _hoveredArchiveFn = null;
    if (activeKeyListenerRef.current) {
      document.removeEventListener('keydown', activeKeyListenerRef.current);
      activeKeyListenerRef.current = null;
    }
  }, []);

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (isRowTriagePending) return;
    setLabelPickerPos(null);
    setContextMenu({ x: e.clientX, y: e.clientY });
  }, [isRowTriagePending]);

  // Opens the label quick-picker anchored at the pointer. Wired to BOTH the
  // left-click and the right-click of a label badge: clicking a label is an
  // intent to *change* it, so the event must never bubble to the row's
  // open-email handler (LabelBadge/Group call stopPropagation) — otherwise the
  // email opens instead of letting you relabel.
  const openLabelPicker = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (isRowTriagePending) return;
    setContextMenu(null);
    setLabelPickerPos({ x: e.clientX, y: e.clientY });
  }, [isRowTriagePending]);

  const openLabelPickerFromContextMenu = useCallback((e?: React.MouseEvent<HTMLButtonElement>) => {
    e?.preventDefault();
    e?.stopPropagation();
    if (!contextMenu || isRowTriagePending) return;
    const pos = menuPos ?? contextMenu;
    setSubmenuPos(null);
    setContextMenu(null);
    setLabelPickerPos({ x: pos.x, y: pos.y });
  }, [contextMenu, isRowTriagePending, menuPos]);

  /**
   * Handle default label change (Classification section).
   * Replaces the default label while preserving custom labels.
   */
  const handleDefaultLabelPick = useCallback((newDefault: { name: string; color: string }, reason: string, reasonKey?: string) => {
    const oldLabels = (email.labels || []).map((l) => l.name);
    // Keep existing custom labels, replace default
    const customLabels = (email.labels || []).filter((l) => !isDefaultLabel(l.name));
    const newLabels: EmailLabel[] = [
      { name: newDefault.name, color: newDefault.color, confidence: 1.0 },
      ...customLabels,
    ];
    onLabelUpdate?.(email, newLabels);
    beginLabelTriage();

    learnFromCorrection({
      email_id: email.id,
      sender: email.sender,
      subject: email.subject,
      body: email.body_preview || '',
      old_labels: oldLabels,
      new_labels: newLabels.map((l) => l.name),
      reason: reason || undefined,
      reason_key: reasonKey,
    }).then((res) => {
      // Silently update with final labels from backend (includes custom labels from rules)
      // No toast here — the optimistic update already showed one
      if (res.final_labels && res.final_labels.length > 0) {
        const finalEmailLabels: EmailLabel[] = res.final_labels.map((l) => ({
          name: l.name,
          color: l.color || '#888',
          confidence: l.confidence ?? 1.0,
        }));
        // Update state without re-triggering toast — call setEmails directly via parent
        onLabelUpdate?.(email, finalEmailLabels, true);
      }
      if (res.rules_count > 0) {
        onToast?.(t('rule_learned'), 'success');
      }
    }).catch((err) => {
      console.error('learnFromCorrection failed:', err);
      onToast?.(t('rule_learn_failed'), 'error');
    }).finally(() => {
      endLabelTriage();
    });

    // Draft generation for Action emails is handled by the backend
    // in _trigger_draft_for_action_email (called by learn_from_correction).
    // No frontend trigger needed — avoids race condition & stale data.

    // Auto-unsubscribe when reason is "À désabonner"
    if (reason === 'À désabonner') {
      unsubscribeBySender(email.sender)
        .then((res) => {
          if (res.success) {
            onToast?.(t('unsubscribe_success'), 'success');
          } else {
            onToast?.(res.message || t('unsubscribe_not_found'), 'info');
          }
        })
        .catch(err => {
          console.error('[SwipeableEmailItem] unsubscribe failed:', err);
          onToast?.(t('unsubscribe_error'), 'error');
        });
    }

    setLabelPickerPos(null);
  }, [beginLabelTriage, email, endLabelTriage, onLabelUpdate, onToast, t]);

  /**
   * Handle custom label toggle (Tags section).
   * Adds or removes a custom label while preserving the default label.
   */
  const handleCustomLabelToggle = useCallback((customLabel: { name: string; color: string }, add: boolean) => {
    const oldLabels = (email.labels || []).map((l) => l.name);
    let newLabels: EmailLabel[];

    if (add) {
      // Add custom label, keep everything else
      newLabels = [
        ...(email.labels || []),
        { name: customLabel.name, color: customLabel.color, confidence: 1.0 },
      ];
    } else {
      // Remove custom label, keep everything else
      newLabels = (email.labels || []).filter((l) => l.name !== customLabel.name);
    }

    onLabelUpdate?.(email, newLabels);
    beginLabelTriage();

    learnFromCorrection({
      email_id: email.id,
      sender: email.sender,
      subject: email.subject,
      body: email.body_preview || '',
      old_labels: oldLabels,
      new_labels: newLabels.map((l) => l.name),
    }).then((res) => {
      if (res.final_labels && res.final_labels.length > 0) {
        const finalEmailLabels: EmailLabel[] = res.final_labels.map((l) => ({
          name: l.name,
          color: l.color || '#888',
          confidence: l.confidence ?? 1.0,
        }));
        onLabelUpdate?.(email, finalEmailLabels, true);
      }
    }).catch((err) => {
      console.error('learnFromCorrection failed:', err);
    }).finally(() => {
      endLabelTriage();
    });

    // Don't close the picker — user may want to toggle more tags
  }, [beginLabelTriage, email, endLabelTriage, onLabelUpdate]);

  // handleMarkReadToggle moved to context menu inline handler

  const handleCheckboxChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    e.stopPropagation();
    onCheckChange?.(email, e.target.checked);
  }, [email, onCheckChange]);

  const handleCheckboxClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation(); // Prevent email selection
    if (e.shiftKey && onShiftClick) {
      e.preventDefault();
      onShiftClick(email);
    }
  }, [email, onShiftClick]);

  const isUnread = folder === 'sent' ? false : !email.is_read;

  // QA 2026-05-19 — Bug #10: the row's inner <div role="button"> had no
  // accessible name, so screen readers announced every email as just
  // "button". Compose a label from sender + subject (with a graceful
  // fallback to the localized "(No subject)" placeholder).
  const _rowSubjectAria = decodeHtmlEntities(email.subject ?? '').trim() || t('no_subject');
  const _rowSenderAria = getSenderDisplay(email);
  const _rowAriaLabel = `${_rowSenderAria} — ${_rowSubjectAria}`;
  const handleRowSelect = useCallback(() => {
    if (isRowTriagePending) return;
    onSelect(email);
  }, [email, isRowTriagePending, onSelect]);
  const handleContentClick = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    e.stopPropagation();
    handleRowSelect();
  }, [handleRowSelect]);

  return (
    <li
      className={`swipeable-email-item ${viewMode !== 'compact' ? viewMode : ''} ${selected ? 'selected' : ''} ${isUnread ? 'unread' : ''} ${isPinned || isWoken ? 'pinned' : ''} ${isChecked ? 'checked' : ''} ${isRowTriagePending ? 'triage-pending' : ''}`}
      data-testid="email-item"
      data-email-id={email.id}
      data-unread={isUnread}
      role="option"
      aria-selected={selected || isChecked}
      aria-busy={isRowTriagePending || undefined}
      onContextMenu={handleContextMenu}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onClick={handleRowSelect}
    >
      <div
        className="email-content"
        onClick={handleContentClick}

        role="button"
        tabIndex={0}
        aria-label={_rowAriaLabel}
        aria-disabled={isRowTriagePending || undefined}
        onKeyDown={(e) => {
          if (isRowTriagePending) return;
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            handleRowSelect();
          }
        }}
      >
        {viewMode === 'comfortable' ? (
          <div className="email-row comfortable-style">
            <label className={`email-checkbox comfortable-checkbox ${multiSelectMode || isChecked ? 'visible' : ''}`} onClick={handleCheckboxClick}>
              <input
                type="checkbox"
                checked={isChecked}
                onChange={handleCheckboxChange}
                aria-label={t('select_email', { subject: email.subject })}
              />
              <span className="checkbox-custom" />
            </label>

            {/* Avatar circle — initiales 2 lettres via le canon Avatar.getInitials
                (règle app-wide 2026-06-09) ; la palette pastel reste propre à la
                liste (design densité confortable). */}
            {(() => {
              const displayName = getSenderDisplay(email);
              const avatarColor = getAvatarColor(displayName);
              const initial = getInitials(displayName, email.sender || '');
              return (
                <div
                  className="comfortable-avatar"
                  style={{ backgroundColor: avatarColor.bg, color: avatarColor.fg }}
                  aria-hidden="true"
                >
                  {initial}
                </div>
              );
            })()}

            <div className="comfortable-body">
              {/* Line 1: Sender + Draft badge + Time */}
              <div className="comfortable-line-1">
                <span className="email-sender" data-testid="email-sender">
                  {getSenderDisplay(email)}
                </span>
                {email.sender_spoofed && (
                  <span
                    className="email-spoof-badge"
                    title={t('sender_spoofed_tooltip', { defaultValue: 'Expéditeur suspect : nom contient des caractères invisibles ou trompeurs' })}
                    aria-label={t('sender_spoofed_label', { defaultValue: 'Expéditeur suspect' })}
                  >
                    ⚠
                  </span>
                )}
                {(isRowTriagePending || email.auto_badge || email.deadline_at || (snoozedUntil || isWoken) || (email.has_pending_draft || hasLocalDraft)) && (
                  <span className="email-badges-group">
                    {isRowTriagePending && <TriagePendingBadge label={t('triage_in_progress')} />}
                    {email.auto_badge && (
                      <AutoBadgeChip stepName={email.auto_badge.stepName} />
                    )}
                    {email.deadline_at && !email.emoji_marker?.include_deadline && (
                      <DeadlineChip iso={email.deadline_at} />
                    )}
                    {(snoozedUntil || isWoken) && (
                      <span className={`snooze-badge ${isWoken ? 'snooze-badge--woken' : 'snooze-badge--sleeping'}`} aria-label={isWoken ? t('reminder_expired') : t('reminder_on', { date: snoozedUntil })}>
                        {isWoken && !isFollowup && (
                          <span className="email-badge-zzz" data-testid="badge-zzz">
                            <svg width="10" height="10" viewBox="0 0 12 12" aria-hidden="true">
                              <path d="M6 1.5a3 3 0 0 0 4.5 4.5 4.5 4.5 0 1 1-4.5-4.5Z" fill="currentColor"/>
                            </svg>
                          </span>
                        )}
                        {isWoken && isFollowup && (
                          <span className="email-badge-followup" data-testid="badge-followup">
                            <svg width="10" height="10" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                              <path d="M6 1.5C4.07 1.5 2.5 3.07 2.5 5v2l-.75 1.5h8.5L9.5 7V5C9.5 3.07 7.93 1.5 6 1.5z" fill="currentColor"/>
                              <path d="M4.75 8.5a1.25 1.25 0 0 0 2.5 0" fill="currentColor"/>
                              <circle cx="6" cy="1.5" r="0.75" fill="currentColor"/>
                            </svg>
                          </span>
                        )}
                        {!isWoken && (
                          <>
                            <span className="snooze-badge-icon">
                              <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                                <circle cx="12" cy="12" r="10"/>
                                <polyline points="12 6 12 12 16 14"/>
                              </svg>
                            </span>
                            {snoozedUntil && (
                              <span className="snooze-badge-date">{formatSnoozeDate(snoozedUntil)}</span>
                            )}
                          </>
                        )}
                      </span>
                    )}
                    {(email.has_pending_draft || hasLocalDraft) && (
                      <span
                        className="draft-ready-badge"
                        data-testid="draft-ready-badge"
                        aria-live="polite"
                        aria-label={t('draft_ready')}
                        title={t('draft_ready')}
                      >
                        <EditIcon className="draft-ready-icon" size={11} />
                      </span>
                    )}
                  </span>
                )}
                <div className="comfortable-meta">
                  {/* Inline mark-as-read icon removed 2026-05-16 — action lives
                      in the right-click context menu only now. */}
                  <span className="email-time" data-testid="email-time">{formatTime(email.received_at)}</span>
                </div>
              </div>
              {/* Line 2: Subject + Thread count + Labels */}
              <div className="comfortable-line-2">
                {/* P3-24 (2026-05-17): localized no-subject fallback so the
                    English UI no longer shows the French (Sans objet) when
                    the backend returns an empty subject (e.g. Gmail
                    "no-subject" placeholder normalised to ""). */}
                <span className="email-subject" data-testid="email-subject" title={_rowSubjectAria}>{_rowSubjectAria}</span>
                {email.emoji_marker && (
                  <EmojiMarkerChip
                    emoji={email.emoji_marker.emoji}
                    text={email.emoji_marker.text}
                    color={email.emoji_marker.color}
                    chip={email.emoji_marker.chip}
                    deadlineIso={email.emoji_marker.include_deadline ? email.deadline_at ?? undefined : undefined}
                  />
                )}
                {(threadCount ?? 0) > 1 && (
                  <span className="thread-count-badge" aria-label={t('thread_count', { count: threadCount })}>({threadCount})</span>
                )}
                {email.labels && email.labels.length > 0 && (
                  <div className="comfortable-labels">
                    <LabelBadgeGroup
                      labels={email.labels}
                      maxVisible={3}
                      size="small"
                      onLabelClick={openLabelPicker}
                      onLabelContextMenu={openLabelPicker}
                      allowedLabels={userLabelNames}
                    />
                  </div>
                )}
                {hasPendingFollowup && (
                  <span className="followup-nudge-chip" aria-label={t('followup_chip_aria')}>🔁 {t('followup_chip')}</span>
                )}
              </div>
              {/* Line 3: Body preview */}
              {email.body_preview && (
                <div className="comfortable-line-3">
                  <span className="email-preview-text">{stripHtml(email.body_preview)}</span>
                </div>
              )}
            </div>

            {sectionKey === 'Noise' && (
              <button
                className="noise-unsubscribe-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  window.open(`mailto:?subject=Unsubscribe&body=Please unsubscribe me from ${email.sender}`, '_blank');
                }}
                title={t('unsubscribe')}
                aria-label={t('unsubscribe')}
              >
                {t('unsubscribe')}
              </button>
            )}
          </div>
        ) : (
          <div className="email-row gmail-style">
            <label className={`email-checkbox ${multiSelectMode || isChecked ? 'visible' : ''}`} onClick={handleCheckboxClick}>
              <input
                type="checkbox"
                checked={isChecked}
                onChange={handleCheckboxChange}
                aria-label={t('select_email', { subject: email.subject })}
              />
              <span className="checkbox-custom" />
            </label>

            {/* Sender - fixed width */}
            <span className="email-sender" data-testid="email-sender">
              {getSenderDisplay(email)}
            </span>

            {/* Label badges - between sender and subject */}
            <div className="email-label-column">
              {email.labels && email.labels.length > 0 && (
                <LabelBadgeGroup
                  labels={email.labels}
                  maxVisible={3}
                  size="small"
                  onLabelClick={openLabelPicker}
                  onLabelContextMenu={openLabelPicker}
                  allowedLabels={userLabelNames}
                />
              )}
              {hasPendingFollowup && (
                <span className="followup-nudge-chip" aria-label={t('followup_chip_aria')}>🔁 {t('followup_chip')}</span>
              )}
            </div>

            {/* Subject + body preview (preview revealed in Deep Focus hero card via CSS) */}
            <div className="email-content-line">
              {/* P3-24: same localized fallback for the compact/balanced row. */}
              <span className="email-subject" data-testid="email-subject" title={_rowSubjectAria}>{_rowSubjectAria}</span>
              {email.emoji_marker && (
                <EmojiMarkerChip
                  emoji={email.emoji_marker.emoji}
                  text={email.emoji_marker.text}
                  color={email.emoji_marker.color}
                  chip={email.emoji_marker.chip}
                  deadlineIso={email.emoji_marker.include_deadline ? email.deadline_at ?? undefined : undefined}
                />
              )}
              {(threadCount ?? 0) > 1 && (
                <span className="thread-count-badge" aria-label={t('thread_count', { count: threadCount })}>({threadCount})</span>
              )}
              {email.body_preview && (
                <span className="email-body-preview">{stripHtml(email.body_preview)}</span>
              )}
            </div>

            {/* Attachment indicator — before badges so draft badge stays rightmost */}
            {email.has_attachments && (
              <svg className="attachment-indicator" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-label={t('attachment')} role="img">
                <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
              </svg>
            )}

            {/* Snooze + draft + auto badges grouped — always rightmost before time */}
            {(isRowTriagePending || email.auto_badge || email.deadline_at || (snoozedUntil || isWoken) || (email.has_pending_draft || hasLocalDraft)) && (
              <span className="email-badges-group">
                {isRowTriagePending && <TriagePendingBadge label={t('triage_in_progress')} />}
                {email.auto_badge && (
                  <AutoBadgeChip stepName={email.auto_badge.stepName} />
                )}
                {email.deadline_at && !email.emoji_marker?.include_deadline && (
                  <DeadlineChip iso={email.deadline_at} />
                )}
                {(snoozedUntil || isWoken) && (
                  <span className={`snooze-badge ${isWoken ? 'snooze-badge--woken' : 'snooze-badge--sleeping'}`} aria-label={isWoken ? t('reminder_expired') : t('reminder_on', { date: snoozedUntil })}>
                    {isWoken && !isFollowup && (
                      <span className="email-badge-zzz" data-testid="badge-zzz">
                        <svg width="10" height="10" viewBox="0 0 12 12" aria-hidden="true">
                          <path d="M6 1.5a3 3 0 0 0 4.5 4.5 4.5 4.5 0 1 1-4.5-4.5Z" fill="currentColor"/>
                        </svg>
                      </span>
                    )}
                    {isWoken && isFollowup && (
                      <span className="email-badge-followup" data-testid="badge-followup">
                        <svg width="10" height="10" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                          <path d="M6 1.5C4.07 1.5 2.5 3.07 2.5 5v2l-.75 1.5h8.5L9.5 7V5C9.5 3.07 7.93 1.5 6 1.5z" fill="currentColor"/>
                          <path d="M4.75 8.5a1.25 1.25 0 0 0 2.5 0" fill="currentColor"/>
                          <circle cx="6" cy="1.5" r="0.75" fill="currentColor"/>
                        </svg>
                      </span>
                    )}
                    {!isWoken && (
                      <>
                        <span className="snooze-badge-icon">
                          <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                            <circle cx="12" cy="12" r="10"/>
                            <polyline points="12 6 12 12 16 14"/>
                          </svg>
                        </span>
                        {snoozedUntil && (
                          <span className="snooze-badge-date">{formatSnoozeDate(snoozedUntil)}</span>
                        )}
                      </>
                    )}
                  </span>
                )}
                {(email.has_pending_draft || hasLocalDraft) && (
                  <span
                    className="draft-ready-badge"
                    data-testid="draft-ready-badge"
                    aria-live="polite"
                    aria-label={t('draft_ready')}
                    title={t('draft_ready')}
                  >
                    <EditIcon className="draft-ready-icon" size={11} />
                  </span>
                )}
              </span>
            )}

            {/* Pending send badge */}
            {emailPending && (
              <span className="pending-send-badge" aria-label={t('sending_in_progress')}>
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <circle cx="12" cy="12" r="10"/>
                  <polyline points="12 6 12 12 16 14"/>
                </svg>
                <span className="pending-send-text">{getPendingSendRemaining(email.id)}s</span>
              </span>
            )}

            {/* Inline mark-as-read icon removed 2026-05-16 — action lives
                in the right-click context menu only now. */}

            {/* Time - fixed width */}
            <span className="email-time" data-testid="email-time">{formatTime(email.received_at)}</span>

{/* Contextual hover action for Noise emails — visibility controlled by CSS :hover */}
            {sectionKey === 'Noise' && (
              <button
                className="noise-unsubscribe-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  window.open(`mailto:?subject=Unsubscribe&body=Please unsubscribe me from ${email.sender}`, '_blank');
                }}
                title={t('unsubscribe')}
                aria-label={t('unsubscribe')}
              >
                {t('unsubscribe')}
              </button>
            )}
          </div>
        )}
      </div>

      {/* Context menu — portalled to body to escape react-window's transform rows */}
      {contextMenu && createPortal(
        <div
          ref={contextMenuRef}
          className="email-context-menu"
          style={{
            position: 'fixed',
            left: (menuPos ?? contextMenu).x,
            top: (menuPos ?? contextMenu).y,
          }}
          role="menu"
          aria-label={t('email_actions')}
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
          onContextMenu={(e) => {
            e.preventDefault();
            e.stopPropagation();
          }}
          onMouseOver={(e) => {
            const item = (e.target as HTMLElement).closest('.context-menu-item');
            if (item && !item.classList.contains('context-menu-item--has-submenu')) {
              setSubmenuPos(null);
            }
          }}
        >
          {/* Mark as read/unread — top position for non-default folders only.
              In the default (inbox/etc) branch this item is rendered below
              Snooze further down. Order chosen by user feedback 2026-05-16. */}
          {canToggleRead && (folder === 'spam' || folder === 'trash' || folder === 'archived') && (
            <button
              type="button"
              className="context-menu-item"
              onClick={handleReadToggleClick}
              role="menuitem"
            >
              {readToggleLabel}
            </button>
          )}
          {enabledQuickSteps.length > 0 && (
            <>
              <button
                type="button"
                role="menuitem"
                aria-haspopup="menu"
                aria-expanded={submenuPos !== null}
                className={`context-menu-item context-menu-item--has-submenu${submenuPos ? ' is-active' : ''}`}
                onMouseEnter={(e) => {
                  const rect = e.currentTarget.getBoundingClientRect();
                  const submenuWidth = 220;
                  const goLeft = rect.right + submenuWidth + 8 > window.innerWidth;
                  setSubmenuPos({
                    x: goLeft ? rect.left - submenuWidth - 4 : rect.right + 4,
                    y: rect.top,
                  });
                }}
                onClick={(e) => {
                  e.stopPropagation();
                  const rect = e.currentTarget.getBoundingClientRect();
                  const submenuWidth = 220;
                  const goLeft = rect.right + submenuWidth + 8 > window.innerWidth;
                  setSubmenuPos((cur) => cur ? null : {
                    x: goLeft ? rect.left - submenuWidth - 4 : rect.right + 4,
                    y: rect.top,
                  });
                }}
              >
                <span className="context-menu-item__name">
                  {tQuick('quicksteps_title', { defaultValue: 'Quick actions' })}
                </span>
                <span className="context-menu-item__chevron" aria-hidden="true">›</span>
              </button>
            </>
          )}
          {onLabelUpdate && (
            <button
              type="button"
              className="context-menu-item"
              onClick={openLabelPickerFromContextMenu}
              role="menuitem"
            >
              {t('labels', { ns: 'common', defaultValue: 'Labels' })}
            </button>
          )}
          {folder === 'sent' && emailPending ? (
            <>
              <button
                className="context-menu-item danger"
                onClick={() => {
                  cancelSend(email.id);
                  setContextMenu(null);
                  onToast?.(t('cancel_send_success'), 'success');
                }}
                role="menuitem"
              >
                {t('cancel_send', { remaining: getPendingSendRemaining(email.id) })}
              </button>
            </>
          ) : folder === 'spam' ? (
            <>
              <button
                className="context-menu-item"
                onClick={() => {
                  setContextMenu(null);
                  onNotSpam?.(email);
                }}
                role="menuitem"
              >
                {t('not_spam')}
              </button>
              <button
                className="context-menu-item danger"
                onClick={() => {
                  setContextMenu(null);
                  onSwipeDelete?.(email);
                }}
                role="menuitem"
              >
                {t('delete', { ns: 'common' })}
              </button>
            </>
          ) : folder === 'trash' ? (
            <>
              <button
                className="context-menu-item"
                onClick={() => {
                  setContextMenu(null);
                  onRestore?.(email);
                }}
                role="menuitem"
              >
                {t('restore')}
              </button>
              <button
                className="context-menu-item danger"
                onClick={() => {
                  setContextMenu(null);
                  onSwipeDelete?.(email);
                }}
                role="menuitem"
              >
                {t('delete_permanently')}
              </button>
            </>
          ) : folder === 'archived' ? (
            <>
              <button
                className="context-menu-item"
                onClick={() => {
                  setContextMenu(null);
                  onUnarchive?.(email);
                }}
                role="menuitem"
              >
                {t('unarchive')}
              </button>
              <button
                className="context-menu-item"
                onClick={() => {
                  setContextMenu(null);
                  onMoveToSpam?.(email);
                }}
                role="menuitem"
              >
                {t('move_to_spam')}
              </button>
              <button
                className="context-menu-item danger"
                onClick={() => {
                  setContextMenu(null);
                  onSwipeDelete?.(email);
                }}
                role="menuitem"
              >
                {t('delete', { ns: 'common' })}
              </button>
            </>
          ) : (
            <>
              {(email.has_pending_draft || hasLocalDraft) && onDeleteDraft && (
                <button
                  className="context-menu-item danger"
                  onClick={() => {
                    setContextMenu(null);
                    onDeleteDraft(email);
                  }}
                  role="menuitem"
                >
                  {t('delete_draft')}
                </button>
              )}
              <button
                className="context-menu-item"
                onClick={() => {
                  setContextMenu(null);
                  onPinToggle?.(email);
                }}
                role="menuitem"
              >
                {isPinned ? t('unpin') : t('pin')}
              </button>
              {/* Relabel: left-click or right-click directly on a label badge */}
              <button
                className="context-menu-item"
                onClick={() => {
                  const pos = menuPos ?? contextMenu;
                  onOpenSnooze?.(email, { x: pos.x, y: pos.y });
                  setContextMenu(null);
                }}
                role="menuitem"
              >
                {t('snooze')}
              </button>
              {/* Mark as read/unread sits directly below Snooze in the
                  inbox/default menu (user feedback 2026-05-16). */}
              {canToggleRead && (
                <button
                  type="button"
                  className="context-menu-item"
                  onClick={handleReadToggleClick}
                  role="menuitem"
                >
                  {readToggleLabel}
                </button>
              )}
              <button
                className="context-menu-item"
                onClick={() => {
                  setContextMenu(null);
                  onMoveToSpam?.(email);
                }}
                role="menuitem"
              >
                {t('move_to_spam')}
              </button>
              <button
                className="context-menu-item danger"
                onClick={() => {
                  setContextMenu(null);
                  onSwipeDelete?.(email);
                }}
                role="menuitem"
              >
                {t('delete', { ns: 'common' })}
              </button>
              <button
                className="context-menu-item danger"
                onClick={() => {
                  setContextMenu(null);
                  // Prefer the host callback so the list can optimistically drop
                  // every same-sender row (matches the backend). Fall back to an
                  // in-place block + toast for callers that don't provide it.
                  if (onBlockSender) {
                    onBlockSender(email);
                    return;
                  }
                  blockSender(email.sender)
                    .then(() => {
                      onToast?.(t('sender_blocked'), 'success');
                    })
                    .catch(() => {
                      onToast?.(t('sender_block_failed'), 'error');
                    });
                }}
                role="menuitem"
              >
                {t('block_sender')}
              </button>
            </>
          )}
          {/* Export PDF — available in all folders */}
          <button
            className="context-menu-item"
            onClick={handleExportPdf}
            disabled={isPdfExporting}
            role="menuitem"
          >
            {isPdfExporting ? t('pdf_exporting') : t('pdf_export')}
          </button>
        </div>,
        document.body
      )}

      {/* Quick actions submenu (portalled, anchored to the trigger above) */}
      {contextMenu && submenuPos && enabledQuickSteps.length > 0 && createPortal(
        <div
          ref={submenuRef}
          className="email-context-menu email-context-submenu"
          style={{ position: 'fixed', left: (submenuClamped ?? submenuPos).x, top: (submenuClamped ?? submenuPos).y }}
          role="menu"
          aria-label={tQuick('quicksteps_title', { defaultValue: 'Quick actions' })}
        >
          {enabledQuickSteps.map(step => (
            <button
              key={step.id}
              type="button"
              role="menuitem"
              className="context-menu-item context-menu-item--quickstep"
              disabled={quickRunner.runningStepId === step.id}
              onClick={(event) => {
                event.stopPropagation();
                const bypass = event.shiftKey;
                setContextMenu(null);
                setSubmenuPos(null);
                void quickRunner.run(step, email.id, { bypassConfirm: bypass });
              }}
            >
              <span className="context-menu-item__name">{step.name}</span>
              {step.shortcut && (
                <kbd className="context-menu-item__kbd">
                  {formatShortcutLabel(step.shortcut)}
                </kbd>
              )}
            </button>
          ))}
        </div>,
        document.body
      )}

      {/* Label quick picker */}
      {labelPickerPos && (
        <LabelQuickPicker
          position={labelPickerPos}
          currentLabels={email.labels || []}
          onSelectDefault={handleDefaultLabelPick}
          onToggleCustom={handleCustomLabelToggle}
          onClose={() => setLabelPickerPos(null)}
        />
      )}

      {/* Run-confirmation for Quick Actions whose chain sends real email
          (reply_template / forward). Renders via portal so it overlays
          the closing context menu without being clipped. */}
      {quickRunner.pendingConfirm && createPortal(
        <QuickStepConfirm
          stepName={quickRunner.pendingConfirm.name}
          onConfirm={quickRunner.confirm}
          onCancel={quickRunner.cancelConfirm}
        />,
        document.body,
      )}
    </li>
  );
}, (prev, next) => {
  // Custom comparator — skip re-render when these are unchanged
  return (
    prev.email.id === next.email.id &&
    prev.email.is_read === next.email.is_read &&
    prev.email.has_pending_draft === next.email.has_pending_draft &&
    prev.email.draft_skipped === next.email.draft_skipped &&
    prev.email.labels === next.email.labels &&
    prev.email.auto_badge === next.email.auto_badge &&
    prev.email.deadline_at === next.email.deadline_at &&
    prev.email.emoji_marker?.emoji === next.email.emoji_marker?.emoji &&
    prev.email.emoji_marker?.text === next.email.emoji_marker?.text &&
    prev.email.emoji_marker?.include_deadline === next.email.emoji_marker?.include_deadline &&
    prev.email.emoji_marker?.color === next.email.emoji_marker?.color &&
    prev.email.emoji_marker?.chip === next.email.emoji_marker?.chip &&
    prev.selected === next.selected &&
    prev.isChecked === next.isChecked &&
    prev.multiSelectMode === next.multiSelectMode &&
    prev.sectionKey === next.sectionKey &&
    prev.hasLocalDraft === next.hasLocalDraft &&
    prev.folder === next.folder &&
    prev.viewMode === next.viewMode &&
    prev.snoozedUntil === next.snoozedUntil &&
    prev.isWoken === next.isWoken &&
    prev.isFollowup === next.isFollowup &&
    prev.isPinned === next.isPinned &&
    prev.isTriagePending === next.isTriagePending &&
    prev.onPinToggle === next.onPinToggle &&
    prev.onMarkReadToggle === next.onMarkReadToggle &&
    prev.onMoveToSpam === next.onMoveToSpam &&
    prev.onBlockSender === next.onBlockSender &&
    prev.onUnarchive === next.onUnarchive &&
    prev.onDeleteDraft === next.onDeleteDraft
  );
});


/**
 * AutoBadgeChip — teal ⚡ Auto chip surfaced when an inbox row was auto-
 * actioned by a Quick Step with `showAutoBadge=true`. The shine animation
 * is a single one-shot sweep on mount (no infinite loop — would compete
 * with selection / hover affordances for attention). Mirrors the inline
 * chip pattern of `.followup-nudge-chip` next to label badges so it lands
 * in the same visual slot regardless of row layout (comfortable / gmail).
 */
function AutoBadgeChip({ stepName }: { stepName: string }) {
  const { t } = useTranslation('drafts');
  const label = stepName
    ? t('auto_actioned_chip_named', { name: stepName })
    : t('auto_actioned_chip');
  return (
    <span
      className="auto-badge-chip"
      title={label}
      aria-label={label}
    >
      <svg
        className="auto-badge-chip__zap"
        width="10" height="10" viewBox="0 0 24 24"
        fill="currentColor" aria-hidden="true"
      >
        <path d="M13 2 L4 14 L11 14 L10 22 L20 9 L13 9 Z" />
      </svg>
      <span className="auto-badge-chip__text">Auto</span>
    </span>
  );
}

/**
 * Format a deadline ISO for chip display. Delegates to `formatShortDate`,
 * which gives "Mar 15th" (EN ordinal) and "15 mars" (FR day-first), and
 * reads the current UI language from i18next so the chip follows the user
 * — passing `undefined` to `toLocaleDateString` would use the browser
 * locale, which can diverge from the in-app language switch.
 */
function formatDeadlineLabel(iso: string): string | null {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return formatShortDate(iso, i18n.language || 'en');
}

/** The "follow-up / relance" marker. Stored as the 🔁 emoji in `emoji_marker`
 *  (whitelisted, stamped by the follow-up Quick Step), but rendered as the
 *  line-art `FollowUpIcon` so the chip matches the DraftWakeToast and the rest
 *  of the icon set. Every OTHER marker (💰, ⭐, 🚩, …) stays a literal emoji.
 *  Must be the exact U+1F501 codepoint — 🔄 (U+1F504) is a distinct glyph. */
const FOLLOWUP_MARKER_EMOJI = '\u{1F501}'; // 🔁

/**
 * EmojiMarkerChip — emoji (+ optional text + optional merged deadline)
 * stamped by the `mark_with_emoji` Quick Step action. Sits right after
 * the subject so it reads like part of the email title:
 *   "Re: Invoice  💰 Stripe · Mar 15th"   (EN)
 *   "Re: Facture  💰 Stripe · 15 mars"    (FR)
 * When the marker has `include_deadline=true` AND the email has a
 * `deadline_at`, the standalone DeadlineChip is suppressed on that row
 * to avoid two parallel date markers.
 */
export function EmojiMarkerChip({
  emoji, text, deadlineIso, color, chip,
}: {
  emoji?: string;
  text?: string;
  deadlineIso?: string;
  color?: string;
  chip?: boolean;
}) {
  const dateLabel = deadlineIso ? formatDeadlineLabel(deadlineIso) : null;
  const parts: string[] = [];
  if (text) parts.push(text);
  if (dateLabel) parts.push(dateLabel);
  const tail = parts.join(' · ');
  // chip defaults to true (the pill); chip===false renders the marker bare,
  // with no background/border. A palette color tints the chip via the
  // --marker-color custom property — applied ONLY when it's a valid 6-digit
  // hex, so a malformed value can never land raw in the style attribute (the
  // FE half of the anti-injection lock; the backend whitelists at write).
  const isBare = chip === false;
  const hasColor = typeof color === 'string' && /^#[0-9a-fA-F]{6}$/.test(color);
  const className = [
    'emoji-marker-chip',
    isBare && 'emoji-marker-chip--bare',
    hasColor && 'emoji-marker-chip--colored',
  ].filter(Boolean).join(' ');
  const style = hasColor ? ({ '--marker-color': color } as React.CSSProperties) : undefined;
  return (
    <span
      className={className}
      title={tail || emoji || ''}
      style={style}
      aria-label={`Quick step marker ${emoji ?? ''}${tail ? ` ${tail}` : ''}`.trim()}
    >
      {emoji && (
        <span className="emoji-marker-chip__emoji" aria-hidden="true">
          {emoji === FOLLOWUP_MARKER_EMOJI ? <FollowUpIcon size={12} /> : emoji}
        </span>
      )}
      {tail && <span className="emoji-marker-chip__text">{tail}</span>}
    </span>
  );
}

/**
 * DeadlineChip — clock + date chip surfaced when an email has `deadline_at`
 * set. Populated automatically by the ingest-time deadline extractor (regex
 * on the body). Format is locale-aware short month + day; reads the active
 * UI language from i18next so EN gets "Mar 15th" and FR gets "15 mars".
 */
function DeadlineChip({ iso }: { iso: string }) {
  const label = formatDeadlineLabel(iso);
  if (!label) return null;
  const date = new Date(iso);
  return (
    <span
      className="deadline-chip"
      title={date.toLocaleString()}
      aria-label={`Deadline: ${label}`}
    >
      <svg
        className="deadline-chip__clock"
        width="10" height="10" viewBox="0 0 24 24"
        fill="none" stroke="currentColor" strokeWidth="2.2"
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
      >
        <circle cx="12" cy="12" r="9" />
        <polyline points="12 7 12 12 16 14" />
      </svg>
      <span className="deadline-chip__text">{label}</span>
    </span>
  );
}
