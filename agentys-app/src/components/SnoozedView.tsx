/* eslint-disable react-refresh/only-export-components */
import React, { Suspense, useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { lazyWithRetry as lazy } from '../utils/lazyWithRetry';
import { useTranslation } from 'react-i18next';
import type { Email } from '../types/email';
import type { Followup, PendingDraft, ScheduledEmailDTO, SnoozedPendingDraft } from '../services/api';
import { fetchEmails } from '../api/emails';
import { apiClient } from '../services/api';
import { useSnooze, writeSnoozeEntry, type SnoozedEntry } from '../hooks/useSnooze';
import { useScheduledEmails } from '../hooks/useScheduledEmails';
import { useOptimisticMutation } from '../hooks/useOptimisticMutation';
const EmailDetailModal = lazy(() => import('./EmailDetailModal').then(m => ({ default: m.EmailDetailModal })));
const PendingDraftDetail = lazy(() => import('./PendingDraftDetail').then(m => ({ default: m.PendingDraftDetail })));
const ScheduledDetail = lazy(() => import('./ScheduledDetail').then(m => ({ default: m.ScheduledDetail })));
import { LabelBadgeGroup } from './labels/LabelBadge';
import { FollowupDatePicker } from './FollowupDatePicker';
import { formatShortDateFromDate, formatLongDateFromDate, formatHourMinute } from '../utils/dateFormat';
import ConfirmationDialog from './ConfirmationDialog';
import { EmptyState, ScheduledIcon } from './EmptyState';
import './SnoozedView.css';

interface BadgeDateLabels { overdue: string; today: string; tomorrow: string }

function formatBadgeDate(iso: string, labels: BadgeDateLabels, lang: string): string {
  const d = new Date(iso);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const tomorrow = new Date(today); tomorrow.setDate(today.getDate() + 1);
  const dayOf = new Date(d.getFullYear(), d.getMonth(), d.getDate());

  if (dayOf < today) return labels.overdue;
  if (dayOf.getTime() === today.getTime()) return labels.today;
  if (dayOf.getTime() === tomorrow.getTime()) return labels.tomorrow;
  const diffDays = Math.round((dayOf.getTime() - today.getTime()) / 86400000);
  if (diffDays <= 7) return new Intl.DateTimeFormat(lang, { weekday: 'long' }).format(d);
  return formatShortDateFromDate(d, lang);
}

function formatBadgeTime(iso: string, lang: string): string {
  return formatHourMinute(new Date(iso), lang);
}

export function formatTime(iso: string, lang = 'fr'): string {
  const d = new Date(iso);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return formatHourMinute(d, lang);
  }
  return formatShortDateFromDate(d, lang);
}

function getSectionKey(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const tomorrow = new Date(today); tomorrow.setDate(today.getDate() + 1);
  const dayOf = new Date(d.getFullYear(), d.getMonth(), d.getDate());

  if (dayOf < today) return '0-overdue';
  if (dayOf.getTime() === today.getTime()) return '1-today';
  if (dayOf.getTime() === tomorrow.getTime()) return '2-tomorrow';
  // Beyond tomorrow → one section per calendar day, sortable lexicographically
  return `3-date-${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function getSectionLabel(sectionKey: string, lang: string, fixedLabels: Record<string, string>): string {
  if (sectionKey.startsWith('3-date-')) {
    const [year, month, day] = sectionKey.replace('3-date-', '').split('-').map(Number);
    const date = new Date(year, month - 1, day);
    // English ordinal ("May 27th"); FR/ES stay day-first via the shared helper.
    return formatLongDateFromDate(date, lang);
  }
  return fixedLabels[sectionKey] ?? '';
}

type Category = 'snooze' | 'reminder' | 'scheduled';
export type FilterKey = 'all' | Category;

type UnifiedItem =
  | { kind: 'snooze'; email: Email; wakeDate: string }
  | { kind: 'followup'; followup: Followup }
  | { kind: 'scheduled'; scheduled: ScheduledEmailDTO }
  // Draft created by the `create_snoozed_followup_draft` Quick Step
  // action, still snoozed in "Later". Surfaces in regular Drafts once
  // the wake-time sweep flips the reminder to notified=true.
  | { kind: 'draft'; draft: SnoozedPendingDraft };

function getItemDate(item: UnifiedItem): string {
  if (item.kind === 'snooze') return item.wakeDate;
  if (item.kind === 'followup') return item.followup.due_date;
  if (item.kind === 'draft') return item.draft.wake_at;
  return item.scheduled.send_at;
}

function getItemId(item: UnifiedItem): string {
  if (item.kind === 'snooze') return item.email.id;
  if (item.kind === 'followup') return item.followup.id;
  if (item.kind === 'draft') return `draft:${item.draft.id}`;
  return `scheduled:${item.scheduled.id}`;
}

function getItemEmailId(item: UnifiedItem): string | null {
  if (item.kind === 'snooze') return item.email.id;
  if (item.kind === 'followup') return item.followup.email_id;
  return null;
}

function getItemCategory(item: UnifiedItem, snoozedMap: Map<string, SnoozedEntry>): Category {
  if (item.kind === 'scheduled') return 'scheduled';
  if (item.kind === 'followup') return 'reminder';
  // Snoozed follow-up drafts render under the 'snooze' category — the
  // zzz icon matches the .draft-row-snoozed-chip in PendingDraftList,
  // so the same draft reads the same way whether the user lands on it
  // from Later or from Drafts. ('reminder' would show a bell, which is
  // the icon for follow-up nudges on inbox emails — different concept.)
  if (item.kind === 'draft') return 'snooze';
  const entry = snoozedMap.get(item.email.id);
  if (entry?.type === 'followup') return 'reminder';
  return 'snooze';
}

/** Position the SchedulePicker so it stays inside the viewport.
 *  The picker is ~320px wide × ~360px tall and renders ~240px above the
 *  trigger by default (see SchedulePicker.tsx). When the trigger is too
 *  close to a viewport edge we flip the anchor.
 */
function computeSchedulePickerPos(rect: DOMRect): { x: number; y: number; buttonTop: number } {
  const PICKER_W = 320;
  const PICKER_H = 360;
  const MARGIN = 12;
  const vw = typeof window !== 'undefined' ? window.innerWidth : 1280;
  const vh = typeof window !== 'undefined' ? window.innerHeight : 720;

  // Default: anchor left edge to trigger left, picker opens upward
  let x = rect.left;
  // Flip horizontally if it would overflow the right edge
  if (x + PICKER_W + MARGIN > vw) {
    x = Math.max(MARGIN, rect.right - PICKER_W);
  }
  // Clamp left edge
  if (x < MARGIN) x = MARGIN;

  // SchedulePicker computes top as `buttonTop - 240` (opens upward).
  // If that would clip above the viewport, push buttonTop down enough that
  // (buttonTop - 240) becomes a safe value, OR fall back to opening below.
  let buttonTop = rect.top;
  if (buttonTop - 240 < MARGIN) {
    // Not enough room above — open below instead
    buttonTop = rect.bottom + 240 + 4; // resulting top = rect.bottom + 4
  }
  // Final guard: if the resulting top still overflows the bottom, clamp
  const resultingTop = buttonTop - 240;
  if (resultingTop + PICKER_H + MARGIN > vh) {
    buttonTop = vh - PICKER_H - MARGIN + 240;
  }

  return { x, y: rect.bottom, buttonTop };
}

/** Convert a recipient email into a humanised display name.
 *  "alexandre.simon@hotmail.com" → "Alexandre Simon"
 *  "bob+work@example.com"            → "Bob Work"
 *  "support@stripe.com"              → "Support"
 */
function formatRecipientDisplay(email: string): string {
  const local = (email.split('@')[0] || email).trim();
  if (!local) return email;
  const parts = local
    .split(/[._\-+]/)
    .filter(p => p.length > 0)
    .map(p => p.charAt(0).toUpperCase() + p.slice(1).toLowerCase());
  return parts.join(' ') || local;
}

interface SnoozedViewProps {
  onEmailSelect?: (email: Email) => void | Promise<void>;
  selectedEmailId?: string | null;
  onClose?: () => void;
  defaultFilter?: FilterKey;
}

export function SnoozedView({ onEmailSelect, defaultFilter = 'all' }: SnoozedViewProps) {
  const { t, i18n } = useTranslation(['common', 'drafts']);
  const { t: tInbox } = useTranslation('inbox');
  const lang = i18n.language || 'en';
  const badgeLabels: BadgeDateLabels = { overdue: t('overdue'), today: t('today_short'), tomorrow: t('tomorrow') };
  const SECTION_LABELS: Record<string, string> = {
    '0-overdue': t('overdue'),
    '1-today': t('today'),
    '2-tomorrow': t('tomorrow'),
  };
  const { snoozedMap, sleepingIds, dismissSnoozed } = useSnooze();
  const {
    items: scheduledList,
    cancel: cancelScheduled,
    patch: patchScheduled,
    sendNow: sendScheduledNow,
  } = useScheduledEmails();
  const [allEmails, setAllEmails] = useState<Email[]>([]);
  const [followups, setFollowups] = useState<Followup[]>([]);
  const [snoozedDrafts, setSnoozedDrafts] = useState<SnoozedPendingDraft[]>([]);
  const [supplementalEmails, setSupplementalEmails] = useState<Map<string, Email>>(new Map());
  const [loading, setLoading] = useState(true);
  const [selectedEmail, setSelectedEmail] = useState<Email | null>(null);
  const [selectedScheduled, setSelectedScheduled] = useState<ScheduledEmailDTO | null>(null);
  const [emailDraft, setEmailDraft] = useState<PendingDraft | null>(null);
  // Del-key target awaiting confirmation (scheduled-cancel / draft-delete are
  // irreversible, so they route through ConfirmationDialog before removing).
  const [pendingDelete, setPendingDelete] = useState<UnifiedItem | null>(null);
  const [, setSelectedFollowupEmailId] = useState<string | null>(null);
  const [removingIds, setRemovingIds] = useState<Set<string>>(new Set());
  const [refreshKey, setRefreshKey] = useState(0);
  const [filter, setFilter] = useState<FilterKey>(defaultFilter);
  const [rowPicker, setRowPicker] = useState<{
    pos: { x: number; y: number; buttonTop: number };
    initial: Date;
    apply: (newDate: Date) => Promise<void>;
  } | null>(null);
  const removingTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  // Refs to read latest snoozedMap/sleepingIds inside effects without adding them as deps
  const snoozedMapRef = useRef(snoozedMap);
  snoozedMapRef.current = snoozedMap;
  const sleepingIdsRef = useRef(sleepingIds);
  sleepingIdsRef.current = sleepingIds;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      fetchEmails({ limit: 200 }),
      apiClient.listFollowups({ status: 'pending' }),
      apiClient.listSnoozedFollowupDrafts().catch(() => ({ count: 0, drafts: [] })),
    ]).then(([emailsRes, followupsRes, snoozedRes]) => {
      if (!cancelled) {
        setAllEmails(emailsRes.emails ?? emailsRes ?? []);
        setFollowups(followupsRes.followups ?? []);
        setSnoozedDrafts(snoozedRes.drafts ?? []);
        setLoading(false);
      }
    }).catch(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [refreshKey]);

  // For snooze/followup emails missing from allEmails (multi-account or pagination), fetch individually
  useEffect(() => {
    if (loading) return;
    const allEmailIds = new Set(allEmails.map(e => e.id));
    const missingIds = new Set<string>();
    // Synthetic local IDs minted by NewMessageModal (sendId = `sent:compose-${Date.now()}`)
    // never reach the mail server, so the /api/emails/<id> lookup is guaranteed to
    // 404. Skip them — the consumer that needs the body should keep the draft
    // payload locally instead of relying on a server fetch.
    const isLocalSyntheticId = (id: string) => id.startsWith('sent:compose-');
    for (const [id] of snoozedMapRef.current) {
      if (sleepingIdsRef.current.has(id) && !allEmailIds.has(id) && !isLocalSyntheticId(id)) {
        missingIds.add(id);
      }
    }
    for (const f of followups) {
      if (!allEmailIds.has(f.email_id) && !isLocalSyntheticId(f.email_id)) {
        missingIds.add(f.email_id);
      }
    }
    if (missingIds.size === 0) return;
    let cancelled = false;
    Promise.all([...missingIds].map(id => apiClient.getEmail(id).catch(() => null)))
      .then(results => {
        if (cancelled) return;
        const map = new Map<string, Email>();
        for (const email of results) {
          if (email) map.set(email.id, email);
        }
        if (map.size > 0) setSupplementalEmails(map);
      });
    return () => { cancelled = true; };
  }, [loading, allEmails, followups, refreshKey]);

  // Unified lookup: allEmails + supplemental fetches
  const emailLookup = useMemo(() => {
    const map = new Map<string, Email>(allEmails.map(e => [e.id, e] as [string, Email]));
    for (const [id, email] of supplementalEmails) map.set(id, email);
    return map;
  }, [allEmails, supplementalEmails]);

  // Animate then remove an item
  const animateRemove = useCallback((id: string, onDone: () => void) => {
    setRemovingIds(prev => new Set(prev).add(id));
    const timer = setTimeout(() => {
      setRemovingIds(prev => { const next = new Set(prev); next.delete(id); return next; });
      onDone();
    }, 220);
    removingTimers.current.set(id, timer);
  }, []);

  // Build unified items list
  const allItems: UnifiedItem[] = useMemo(() => {
    const items: UnifiedItem[] = [];
    // Snoozed (incl. followup-via-snooze entries)
    for (const [id, entry] of snoozedMap) {
      if (!sleepingIds.has(id)) continue;
      const email = emailLookup.get(id);
      if (email) {
        items.push({ kind: 'snooze', email, wakeDate: entry.date });
      } else {
        items.push({
          kind: 'snooze',
          email: {
            id,
            sender: entry.sender || '',
            sender_name: entry.senderName || null,
            subject: entry.subject || '(sans sujet)',
            received_at: new Date().toISOString(),
            has_attachments: false,
            conversation_id: null,
            is_read: true,
            body_preview: undefined,
            labels: (entry.labels as import('../types/email').EmailLabel[] | undefined),
          },
          wakeDate: entry.date,
        });
      }
    }
    // Followups (API-backed reminders)
    for (const f of followups) {
      items.push({ kind: 'followup', followup: f });
    }
    // Snoozed follow-up drafts (created by create_snoozed_followup_draft
    // Quick Step action, still gated by their draft_followup reminder).
    for (const d of snoozedDrafts) {
      items.push({ kind: 'draft', draft: d });
    }
    // Scheduled sends
    for (const s of scheduledList) {
      items.push({ kind: 'scheduled', scheduled: s });
    }
    items.sort((a, b) => getItemDate(a).localeCompare(getItemDate(b)));
    return items;
  }, [snoozedMap, sleepingIds, emailLookup, followups, snoozedDrafts, scheduledList]);

  // Counts per category
  const categoryCounts = useMemo(() => {
    const counts = { all: allItems.length, snooze: 0, reminder: 0, scheduled: 0 };
    for (const item of allItems) {
      counts[getItemCategory(item, snoozedMap)]++;
    }
    return counts;
  }, [allItems, snoozedMap]);

  // Filter items
  const filteredItems = useMemo(() => {
    if (filter === 'all') return allItems;
    return allItems.filter(item => getItemCategory(item, snoozedMap) === filter);
  }, [allItems, filter, snoozedMap]);

  // Group filtered items by section
  const sortedSections = useMemo(() => {
    const sections: Map<string, UnifiedItem[]> = new Map();
    for (const item of filteredItems) {
      const key = getSectionKey(getItemDate(item));
      if (!sections.has(key)) sections.set(key, []);
      sections.get(key)!.push(item);
    }
    return [...sections.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [filteredItems]);

  // Keep selectedScheduled in sync with the underlying list (after patch/cancel)
  useEffect(() => {
    if (!selectedScheduled) return;
    const fresh = scheduledList.find(s => s.id === selectedScheduled.id);
    if (!fresh) {
      setSelectedScheduled(null);
    } else if (fresh !== selectedScheduled) {
      setSelectedScheduled(fresh);
    }
  }, [scheduledList, selectedScheduled]);

  const handleSelectEmail = useCallback((email: Email) => {
    setSelectedEmail(email);
    setSelectedScheduled(null);
    setEmailDraft(null);
    setSelectedFollowupEmailId(null);
    onEmailSelect?.(email);
    apiClient.getPendingDraftByEmailId(email.id).then(draft => {
      setEmailDraft(draft ?? null);
    }).catch(err => {
      // Audit F-07 (2026-05-12): log so a transient draft-load failure is
      // diagnosable. We deliberately do NOT toast here because pending
      // drafts are a "nice to have" overlay — the email itself still
      // displays; a toast on every email click would be noisy.
      console.warn('[SnoozedView] draft load failed for email_id=%s', email.id, err);
    });
  }, [onEmailSelect]);

  const handleSelectFollowup = useCallback((followup: Followup) => {
    setSelectedFollowupEmailId(followup.email_id);
    setSelectedScheduled(null);
    setSelectedEmail(null);
    const emailObj = emailLookup.get(followup.email_id);
    if (emailObj) {
      setSelectedEmail(emailObj);
      onEmailSelect?.(emailObj);
    }
  }, [emailLookup, onEmailSelect]);

  const handleSelectScheduled = useCallback((scheduled: ScheduledEmailDTO) => {
    setSelectedScheduled(scheduled);
    setSelectedEmail(null);
    setEmailDraft(null);
    setSelectedFollowupEmailId(null);
  }, []);

  const handleSelectSnoozedDraft = useCallback((draft: SnoozedPendingDraft) => {
    // Drop the SnoozedPendingDraft's `wake_at` extension before storing —
    // PendingDraftDetail expects a plain PendingDraft. The wake date lives
    // on the list row, not on the detail panel.
    const plain: PendingDraft = { ...draft };
    delete (plain as { wake_at?: string }).wake_at;
    setEmailDraft(plain);
    setSelectedEmail(null);
    setSelectedScheduled(null);
    setSelectedFollowupEmailId(null);
  }, []);

  const handleItemClick = useCallback((item: UnifiedItem) => {
    if (item.kind === 'snooze') handleSelectEmail(item.email);
    else if (item.kind === 'followup') handleSelectFollowup(item.followup);
    else if (item.kind === 'draft') handleSelectSnoozedDraft(item.draft);
    else handleSelectScheduled(item.scheduled);
  }, [handleSelectEmail, handleSelectFollowup, handleSelectScheduled, handleSelectSnoozedDraft]);

  const handleUnsnooze = useCallback((e: React.MouseEvent | undefined, emailId: string, subject: string) => {
    e?.stopPropagation();
    animateRemove(emailId, () => dismissSnoozed(emailId));
    if (selectedEmail?.id === emailId) {
      setSelectedEmail(null);
      setSelectedFollowupEmailId(null);
    }
    void subject;
  }, [dismissSnoozed, animateRemove, selectedEmail]);

  // Audit Cluster D (2026-05-17) Toast Site 10 / #330: previously `catch
  // { /* silently ignore */ }` — the animation played, the row vanished
  // locally, but if updateFollowup failed it returned at next sync and
  // the user saw the row reappear with no explanation.
  //
  // Audit regressions (2026-05-17 batch4) F-05: rollback now restores only
  // the failed followup (id-keyed, idempotent guard) instead of replaying a
  // whole-array `prev` snapshot, which can resurrect siblings the user
  // completed in between rapid clicks.
  const runFollowupComplete = useOptimisticMutation<void>({
    scope: 'snoozed-followup-complete',
    i18nKey: 'toasts.followup_complete_failed',
  });
  const handleFollowupDone = useCallback(async (e: React.MouseEvent | undefined, followupId: string, subject: string) => {
    e?.stopPropagation();
    animateRemove(followupId, async () => {
      const removed = followups.find(f => f.id === followupId);
      setFollowups(p => p.filter(f => f.id !== followupId));
      await runFollowupComplete(
        async () => {
          await apiClient.updateFollowup(followupId, { action: 'complete' });
        },
        () => {
          if (!removed) return;
          setFollowups(p => (p.some(f => f.id === followupId) ? p : [...p, removed]));
        },
      );
    });
    void subject;
  }, [animateRemove, followups, runFollowupComplete]);

  const handleBadgeReschedule = useCallback((e: React.MouseEvent, item: UnifiedItem) => {
    e.stopPropagation();
    // Snoozed drafts don't support reschedule from the row badge (yet) —
    // the wake date is bound to the reminder created by the Quick Step
    // rule, and changing it would create a mismatch with what /api/drafts
    // surfaces. Click is a no-op for now; users can delete the draft and
    // re-fire the rule if they want a different wake date.
    if (item.kind === 'draft') return;

    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const pos = computeSchedulePickerPos(rect);
    const initial = new Date(getItemDate(item));

    let apply: (newDate: Date) => Promise<void>;
    if (item.kind === 'snooze') {
      const entry = snoozedMap.get(item.email.id);
      apply = async (newDate) => {
        writeSnoozeEntry(
          item.email.id,
          newDate,
          entry?.subject ?? item.email.subject ?? '',
          entry?.type ?? 'snooze',
          entry?.labels,
          entry?.sender ?? item.email.sender,
          entry?.senderName ?? item.email.sender_name ?? undefined,
        );
      };
    } else if (item.kind === 'followup') {
      const followupId = item.followup.id;
      apply = async (newDate) => {
        await apiClient.updateFollowup(followupId, { due_date: newDate.toISOString() });
        setFollowups(prev => prev.map(f =>
          f.id === followupId ? { ...f, due_date: newDate.toISOString() } : f
        ));
      };
    } else {
      const scheduledId = item.scheduled.id;
      apply = async (newDate) => {
        await patchScheduled(scheduledId, { send_at: newDate.toISOString() });
      };
    }

    setRowPicker({ pos, initial, apply });
  }, [snoozedMap, patchScheduled]);

  const handleDeleteSnoozedDraft = useCallback(async (
    e: React.MouseEvent | undefined, draftId: string,
  ) => {
    e?.stopPropagation();
    const rowId = `draft:${draftId}`;
    if (emailDraft?.id === draftId) setEmailDraft(null);
    animateRemove(rowId, async () => {
      try {
        await apiClient.rejectPendingDraft(draftId);
        setSnoozedDrafts(prev => prev.filter(d => d.id !== draftId));
      } catch {
        // silently ignore — backend will report 404 if the draft was
        // already cleaned up by the wake-time sweep
      }
    });
  }, [animateRemove, emailDraft]);

  const handleScheduledRowCancel = useCallback(async (e: React.MouseEvent | undefined, scheduled: ScheduledEmailDTO) => {
    e?.stopPropagation();
    const rowId = `scheduled:${scheduled.id}`;
    if (selectedScheduled?.id === scheduled.id) setSelectedScheduled(null);
    animateRemove(rowId, async () => {
      await cancelScheduled(scheduled.id);
    });
  }, [animateRemove, cancelScheduled, selectedScheduled]);

  const handleRowPickerSelect = useCallback(async (date: Date) => {
    if (!rowPicker) return;
    // The followup branch calls apiClient.updateFollowup raw (throws on
    // non-ok), unlike the scheduled branch whose patchScheduled swallows the
    // error and toasts internally. Without this guard a failed reschedule left
    // the picker open and nothing updated silently. Mirror the safe scheduled
    // path: toast on failure and still close the picker.
    try {
      await rowPicker.apply(date);
    } catch {
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: { message: i18n.t('common:toasts.followup_reschedule_failed'), type: 'error', duration: 6000 },
      }));
    } finally {
      setRowPicker(null);
    }
  }, [rowPicker]);

  const handleCloseDetail = useCallback(() => {
    setSelectedEmail(null);
    setSelectedScheduled(null);
    setEmailDraft(null);
    setSelectedFollowupEmailId(null);
  }, []);

  // Navigation between items — operates on filteredItems
  const selectedItemIndex = useMemo(() => {
    if (selectedScheduled) {
      return filteredItems.findIndex(item => item.kind === 'scheduled' && item.scheduled.id === selectedScheduled.id);
    }
    if (selectedEmail) {
      return filteredItems.findIndex(item => getItemEmailId(item) === selectedEmail.id);
    }
    return -1;
  }, [selectedEmail, selectedScheduled, filteredItems]);

  const handleNavigatePrev = useCallback(() => {
    if (selectedItemIndex > 0) handleItemClick(filteredItems[selectedItemIndex - 1]);
  }, [selectedItemIndex, filteredItems, handleItemClick]);

  const handleNavigateNext = useCallback(() => {
    if (selectedItemIndex < filteredItems.length - 1) handleItemClick(filteredItems[selectedItemIndex + 1]);
  }, [selectedItemIndex, filteredItems, handleItemClick]);

  // The Later item whose detail is currently open — Del's target. Covers
  // drafts (tracked via emailDraft, which selectedItemIndex doesn't) on top of
  // the snooze/followup/scheduled cases that selectedItemIndex resolves.
  const activeItem = useMemo<UnifiedItem | null>(() => {
    if (emailDraft) {
      return filteredItems.find(i => i.kind === 'draft' && i.draft.id === emailDraft.id) ?? null;
    }
    return selectedItemIndex >= 0 ? filteredItems[selectedItemIndex] : null;
  }, [emailDraft, selectedItemIndex, filteredItems]);

  // Remove a Later item via its kind's primary action (the same call the row's
  // × button makes), then advance selection to the neighbour so repeated Del
  // presses can triage down the list without re-navigating.
  const removeActiveItem = useCallback((item: UnifiedItem) => {
    const idx = filteredItems.findIndex(i => getItemId(i) === getItemId(item));
    const next = idx >= 0 ? (filteredItems[idx + 1] ?? filteredItems[idx - 1] ?? null) : null;

    if (item.kind === 'snooze') handleUnsnooze(undefined, item.email.id, item.email.subject ?? '');
    else if (item.kind === 'followup') handleFollowupDone(undefined, item.followup.id, item.followup.email_subject ?? '');
    else if (item.kind === 'scheduled') handleScheduledRowCancel(undefined, item.scheduled);
    else handleDeleteSnoozedDraft(undefined, item.draft.id);

    if (next) handleItemClick(next);
    else handleCloseDetail();
  }, [filteredItems, handleUnsnooze, handleFollowupDone, handleScheduledRowCancel, handleDeleteSnoozedDraft, handleItemClick, handleCloseDetail]);

  // Keyboard shortcuts: ↑/↓ to navigate filtered rows, Esc to close detail panel.
  // Listens on window so events dispatched by the App-level ribbon (synthetic
  // KeyboardEvent fired on window) reach this handler too.
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't interfere when an input/textarea/contenteditable has focus,
      // or while the row picker is open (it owns its own Escape).
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName?.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || target?.isContentEditable) return;
      if (rowPicker || pendingDelete) return;

      if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (selectedItemIndex < 0) {
          if (filteredItems.length > 0) handleItemClick(filteredItems[filteredItems.length - 1]);
        } else if (selectedItemIndex > 0) {
          handleItemClick(filteredItems[selectedItemIndex - 1]);
        }
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (selectedItemIndex < 0) {
          if (filteredItems.length > 0) handleItemClick(filteredItems[0]);
        } else if (selectedItemIndex < filteredItems.length - 1) {
          handleItemClick(filteredItems[selectedItemIndex + 1]);
        }
      } else if (e.key === 'Escape') {
        if (selectedEmail || selectedScheduled) {
          e.preventDefault();
          handleCloseDetail();
        }
      } else if (e.key === 'Delete' || e.key === 'Backspace') {
        // Del removes the open item (Backspace too — it's the delete key on
        // macOS, matching the inbox binding). snooze/followup are recoverable
        // (the email returns to the inbox / the reminder is marked done) so they
        // fire instantly; scheduled-cancel and draft-delete are irreversible, so
        // they route through a confirm first.
        if (!activeItem) return;
        e.preventDefault();
        if (activeItem.kind === 'snooze' || activeItem.kind === 'followup') {
          removeActiveItem(activeItem);
        } else {
          setPendingDelete(activeItem);
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [filteredItems, selectedItemIndex, handleItemClick, handleCloseDetail, selectedEmail, selectedScheduled, rowPicker, pendingDelete, activeItem, removeActiveItem]);

  const headerTitle = tInbox('later', 'Plus tard');
  // Include `emailDraft` so clicking a snoozed-draft row (which sets only
  // `emailDraft`, not `selectedEmail` since there is no underlying inbox
  // email to load) opens the detail panel.
  const isDetailOpen = !!(selectedEmail || selectedScheduled || emailDraft);

  if (loading) {
    return (
      <div className="snoozed-view snoozed-view--loading">
        <div className="loading-spinner-small" />
        <span>{t('loading')}</span>
      </div>
    );
  }

  // Filter pills (always rendered when there's content; hidden if all empty)
  const filterPills = (
    <div className="sv-filters" role="tablist" aria-label={t('later_filters', 'Filtres')}>
      {(['all', 'snooze', 'reminder', 'scheduled'] as FilterKey[]).map(key => {
        const count = key === 'all' ? categoryCounts.all : categoryCounts[key];
        const labelMap: Record<FilterKey, string> = {
          all: t('filter_all', 'Tout'),
          snooze: t('filter_snoozed', 'Reportés'),
          reminder: t('filter_reminders', 'Rappels'),
          scheduled: t('filter_sending', 'Envois'),
        };
        const isActive = filter === key;
        const isEmpty = count === 0;
        return (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={isActive}
            className={`sv-filter${isActive ? ' sv-filter--active' : ''}${isEmpty ? ' sv-filter--empty' : ''} sv-filter--${key}`}
            onClick={() => !isEmpty && setFilter(key)}
            disabled={isEmpty && !isActive}
            data-testid={`later-filter-${key}`}
          >
            <span className="sv-filter-label">{labelMap[key]}</span>
            <span className="sv-filter-count">{count}</span>
          </button>
        );
      })}
    </div>
  );

  if (allItems.length === 0) {
    return (
      <div className="snoozed-view snoozed-view--empty">
        {/* Shared EmptyState (same recipe as the inbox/sent/drafts folders) —
            title only, no explainer line. */}
        <EmptyState
          icon={<ScheduledIcon />}
          title={t('later_empty_title', 'Rien de prévu pour plus tard')}
        />
      </div>
    );
  }

  const activeEmailId = selectedEmail?.id ?? null;
  const activeScheduledId = selectedScheduled?.id ?? null;

  const navInfo = isDetailOpen && selectedItemIndex >= 0 ? {
    current: selectedItemIndex + 1,
    total: filteredItems.length,
    hasPrev: selectedItemIndex > 0,
    hasNext: selectedItemIndex < filteredItems.length - 1,
  } : undefined;

  return (
    <div className={`snoozed-view ${isDetailOpen ? 'has-detail' : ''}`}>
      <div className="snoozed-list-panel">
        {/* Header */}
        <div className="sv-header">
          <h1 className="sv-header-title">{headerTitle}</h1>
        </div>

        {/* Filter pills */}
        {filterPills}

        <div className="snoozed-list" role="list">
          {filteredItems.length === 0 ? (
            <div className="sv-filter-empty">
              <p className="sv-filter-empty-title">
                {filter === 'snooze' && t('filter_empty_snoozed', 'Aucun report')}
                {filter === 'reminder' && t('filter_empty_reminders', 'Aucun rappel')}
                {filter === 'scheduled' && t('filter_empty_sending', 'Aucun envoi programmé')}
              </p>
              <button type="button" className="sv-filter-empty-reset" onClick={() => setFilter('all')}>
                {t('filter_empty_reset', 'Tout afficher')}
              </button>
            </div>
          ) : sortedSections.map(([sectionKey, items]) => (
            <React.Fragment key={sectionKey}>
              <div className="sv-section-separator">
                <span className={`sv-section-label${sectionKey === '0-overdue' ? ' sv-section-label--overdue' : ''}`}>
                  {getSectionLabel(sectionKey, lang, SECTION_LABELS)}
                </span>
              </div>

              {items.map(item => {
                const itemId = getItemId(item);
                const category = getItemCategory(item, snoozedMap);
                const testIdSuffix = item.kind === 'scheduled'
                  ? item.scheduled.id
                  : item.kind === 'followup'
                    ? item.followup.id
                    : item.kind === 'draft'
                      ? item.draft.id
                      : item.email.id;
                const isSelected = item.kind === 'scheduled'
                  ? activeScheduledId === item.scheduled.id
                  : item.kind === 'draft'
                    ? emailDraft?.id === item.draft.id
                    : activeEmailId === getItemEmailId(item);
                const isUnread = item.kind === 'snooze' ? !item.email.is_read : false;
                const isRemoving = removingIds.has(itemId);
                const date = getItemDate(item);

                let sender: string;
                let senderTitle: string | undefined;
                let subject: string;
                let receivedAt: string | null = null;
                let isOutgoing = false;
                let followupEmail: Email | undefined;

                if (item.kind === 'snooze') {
                  sender = item.email.sender_name || item.email.sender.split('@')[0] || '';
                  subject = item.email.subject || t('no_subject');
                  receivedAt = item.email.received_at;
                } else if (item.kind === 'followup') {
                  followupEmail = emailLookup.get(item.followup.email_id);
                  sender = item.followup.email_sender
                    || followupEmail?.sender_name
                    || (followupEmail?.sender?.split('@')[0] ?? '')
                    || '';
                  subject = item.followup.email_subject || item.followup.title || t('no_subject');
                  receivedAt = followupEmail?.received_at || item.followup.due_date;
                } else if (item.kind === 'draft') {
                  // Snoozed follow-up draft — the user is the author and the
                  // "sender" cell shows the recipient (who they're following
                  // up with), matching the scheduled-send convention.
                  const recipient = item.draft.email_sender || '';
                  sender = recipient ? formatRecipientDisplay(recipient) : '';
                  senderTitle = recipient;
                  subject = item.draft.draft_subject
                    || item.draft.email_subject
                    || t('no_subject');
                  isOutgoing = true;
                } else {
                  // scheduled — outgoing send
                  const primary = item.scheduled.to[0] || '';
                  const extras = item.scheduled.to.length - 1;
                  sender = primary
                    ? formatRecipientDisplay(primary) + (extras > 0 ? ` +${extras}` : '')
                    : '';
                  senderTitle = item.scheduled.to.join(', ');
                  subject = item.scheduled.subject || t('no_subject');
                  isOutgoing = true;
                }

                return (
                  <div
                    key={itemId}
                    className={`sv-row email-row gmail-style sv-row--${category}${isSelected ? ' selected' : ''}${isUnread ? ' unread' : ''}${isRemoving ? ' is-removing' : ''}${isOutgoing ? ' sv-row--outgoing' : ''}`}
                    onClick={() => !isRemoving && handleItemClick(item)}
                    role="listitem"
                    tabIndex={0}
                    onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') handleItemClick(item); }}
                    data-testid={`later-row-${category}-${testIdSuffix}`}
                  >
                    {/* Wake/send date — placed FIRST so the chip+date column is
                        the leftmost element. In the Later view, time IS the
                        primary information (when does this fire?), so it leads
                        the row, ahead of sender/subject. The whole chip+date is
                        the click target to reschedule for ALL three types. */}
                    <span
                      className={`sv-wake sv-wake--${category} sv-wake--clickable`}
                      onClick={(e) => handleBadgeReschedule(e, item)}
                      role="button"
                      title={tInbox('reschedule', 'Reprogrammer')}
                      aria-label={tInbox('reschedule', 'Reprogrammer')}
                      data-testid={`later-reschedule-${category}-${testIdSuffix}`}
                    >
                      {category === 'reminder' ? (
                        <span className="email-badge-followup" aria-hidden="true">
                          <svg width="10" height="10" viewBox="0 0 12 12" fill="none">
                            <path d="M6 1.5C4.07 1.5 2.5 3.07 2.5 5v2l-.75 1.5h8.5L9.5 7V5C9.5 3.07 7.93 1.5 6 1.5z" fill="currentColor"/>
                            <path d="M4.75 8.5a1.25 1.25 0 0 0 2.5 0" fill="currentColor"/>
                            <circle cx="6" cy="1.5" r="0.75" fill="currentColor"/>
                          </svg>
                        </span>
                      ) : category === 'scheduled' ? (
                        <span className="email-badge-scheduled" aria-hidden="true">
                          <svg width="10" height="10" viewBox="0 0 12 12" fill="currentColor">
                            <polygon points="10.5,1.5 1.5,5.5 5,6.5 6.5,10.5"/>
                          </svg>
                        </span>
                      ) : (
                        <span className="email-badge-zzz" aria-hidden="true">
                          <svg width="10" height="10" viewBox="0 0 12 12">
                            <path d="M6 2.5a2.4 2.4 0 0 0 3.6 3.6 3.6 3.6 0 1 1-3.6-3.6Z" fill="currentColor"/>
                          </svg>
                        </span>
                      )}
                      <span className="sv-wake-day">{formatBadgeDate(date, badgeLabels, lang)}</span>
                      <span className="sv-wake-time">{formatBadgeTime(date, lang)}</span>
                    </span>

                    {/* Sender (or recipient for outgoing) */}
                    <div className="email-sender" title={senderTitle}>
                      {sender}
                    </div>

                    {/* Labels */}
                    <div className="email-label-column">
                      {(() => {
                        let emailLabels: Array<{ name: string; color: string }> | undefined;
                        if (item.kind === 'snooze') {
                          if (item.email.labels && item.email.labels.length > 0) {
                            emailLabels = item.email.labels;
                          } else {
                            const entry = snoozedMap.get(item.email.id);
                            if (entry?.labels && entry.labels.length > 0) {
                              emailLabels = (entry.labels as unknown as Array<{ name: string; color: string }>).map(l =>
                                typeof l === 'string' ? { name: l, color: '#6b7280' } : l
                              );
                            } else {
                              const found = emailLookup.get(item.email.id);
                              if (found?.labels && found.labels.length > 0) {
                                emailLabels = found.labels;
                              }
                            }
                          }
                        } else if (item.kind === 'followup') {
                          if (followupEmail?.labels && followupEmail.labels.length > 0) {
                            emailLabels = followupEmail.labels;
                          }
                        }
                        return emailLabels && emailLabels.length > 0
                          ? <LabelBadgeGroup labels={emailLabels} maxVisible={3} size="small" />
                          : null;
                      })()}
                    </div>

                    {/* Subject */}
                    <div className="email-content-line">
                      <span className="email-subject">{subject}</span>
                      {item.kind === 'draft' && (
                        // ⚡ Auto chip — signals this row was created by a
                        // ``create_snoozed_followup_draft`` Quick Step.
                        // Reuses the inbox-list ``.auto-badge-chip`` styles
                        // (SwipeableEmailItem.tsx:1305) so the badge looks
                        // identical wherever it appears. Right-aligned into its
                        // own trailing column via CSS (`.sv-row .email-content-line
                        // .auto-badge-chip { margin-left: auto }`) so every Auto
                        // chip lines up just before the date slot instead of
                        // riding the end of each variable-length subject.
                        <span
                          className="auto-badge-chip"
                          title={t('drafts:auto_actioned_chip')}
                          aria-label={t('drafts:auto_actioned_chip')}
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
                      )}
                    </div>

                    {/* Received time (incoming) — render nbsp when empty so cell keeps its 60px width */}
                    <span className="email-time">
                      {receivedAt ? formatTime(receivedAt, lang) : ' '}
                    </span>

                    {/* Hover actions */}
                    {item.kind === 'snooze' && (
                      <button
                        className="sv-action-btn"
                        onClick={e => handleUnsnooze(e, item.email.id, subject)}
                        title={t('unsnooze_of', { subject })}
                        aria-label={t('unsnooze_of', { subject })}
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M18 6 6 18"/><path d="m6 6 12 12"/>
                        </svg>
                      </button>
                    )}
                    {item.kind === 'followup' && (
                      <button
                        className="sv-action-btn sv-action-btn--done"
                        onClick={e => handleFollowupDone(e, item.followup.id, subject)}
                        title={t('mark_done_of', { subject })}
                        aria-label={t('mark_done_of', { subject })}
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                          <polyline points="20 6 9 17 4 12"/>
                        </svg>
                      </button>
                    )}
                    {item.kind === 'scheduled' && (
                      <button
                        className="sv-action-btn sv-action-btn--cancel"
                        onClick={e => handleScheduledRowCancel(e, item.scheduled)}
                        title={tInbox('cancel', 'Annuler')}
                        aria-label={tInbox('cancel', 'Annuler')}
                        data-testid={`later-cancel-${item.scheduled.id}`}
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M18 6 6 18"/><path d="m6 6 12 12"/>
                        </svg>
                      </button>
                    )}
                    {item.kind === 'draft' && (
                      <button
                        className="sv-action-btn sv-action-btn--cancel"
                        onClick={e => handleDeleteSnoozedDraft(e, item.draft.id)}
                        title={tInbox('cancel', 'Annuler')}
                        aria-label={tInbox('cancel', 'Annuler')}
                        data-testid={`later-cancel-draft-${item.draft.id}`}
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M18 6 6 18"/><path d="m6 6 12 12"/>
                        </svg>
                      </button>
                    )}
                  </div>
                );
              })}
            </React.Fragment>
          ))}
        </div>
      </div>

      {isDetailOpen && (
        <>
          <div className="resize-handle" />
          <div className="email-detail-panel detail-ready">
            <Suspense fallback={null}>
              {selectedScheduled ? (
                <ScheduledDetail
                  key={selectedScheduled.id}
                  item={selectedScheduled}
                  onClose={handleCloseDetail}
                  onSendNow={sendScheduledNow}
                  onCancel={cancelScheduled}
                />
              ) : emailDraft ? (
                // Covers both:
                //  - snoozed follow-up draft (no original inbox email)
                //  - regular inbox email that has a pending draft attached
                // PendingDraftDetail handles both shapes (its draft prop
                // carries email_subject/email_sender so it can render the
                // recipient context without needing a separate email row).
                <PendingDraftDetail
                  key={emailDraft.id}
                  draft={emailDraft}
                  onDraftUpdated={updated => setEmailDraft(updated)}
                  onDraftValidated={() => { setSelectedEmail(null); setEmailDraft(null); setRefreshKey(k => k + 1); }}
                  onDraftScheduled={() => { setSelectedEmail(null); setEmailDraft(null); setRefreshKey(k => k + 1); }}
                  onDraftRejected={() => { setSelectedEmail(null); setEmailDraft(null); }}
                  onClose={handleCloseDetail}
                  navInfo={navInfo}
                  onNavigatePrev={handleNavigatePrev}
                  onNavigateNext={handleNavigateNext}
                />
              ) : selectedEmail ? (
                <EmailDetailModal
                  emailId={selectedEmail.id}
                  isOpen={true}
                  onClose={handleCloseDetail}
                  inline={true}
                  emailLabels={selectedEmail.labels}
                  folderName={headerTitle}
                  navInfo={navInfo}
                  onNavigatePrev={handleNavigatePrev}
                  onNavigateNext={handleNavigateNext}
                  onDraftGenerated={() => {
                    apiClient.getPendingDraftByEmailId(selectedEmail.id).then(draft => {
                      if (draft) setEmailDraft(draft);
                    }).catch(err => {
                      // Audit F-07 (2026-05-12): same pattern as handleSelectEmail.
                      console.warn('[SnoozedView] post-generation draft load failed:', err);
                    });
                  }}
                  onReplySent={() => { setSelectedEmail(null); setRefreshKey(k => k + 1); }}
                />
              ) : null}
            </Suspense>
          </div>
        </>
      )}

      {rowPicker && (
        <FollowupDatePicker
          position={rowPicker.pos}
          forceCalendar
          title={tInbox('reschedule', 'Reprogrammer')}
          onSelect={handleRowPickerSelect}
          onClose={() => setRowPicker(null)}
        />
      )}

      {pendingDelete && (
        <ConfirmationDialog
          isOpen
          destructive
          title={pendingDelete.kind === 'scheduled'
            ? t('later_cancel_scheduled_title', 'Annuler cet envoi programmé ?')
            : t('later_delete_draft_title', 'Supprimer ce brouillon ?')}
          message={pendingDelete.kind === 'scheduled'
            ? t('later_cancel_scheduled_msg', "Cet email ne sera pas envoyé.")
            : t('later_delete_draft_msg', 'Ce brouillon de relance sera définitivement supprimé.')}
          confirmLabel={pendingDelete.kind === 'scheduled'
            ? t('later_cancel_scheduled_confirm', "Annuler l'envoi")
            : t('later_delete_draft_confirm', 'Supprimer')}
          onConfirm={() => removeActiveItem(pendingDelete)}
          onCancel={() => setPendingDelete(null)}
        />
      )}
    </div>
  );
}
