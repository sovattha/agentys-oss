import { useState, useEffect, useLayoutEffect, useCallback, memo, useMemo, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { formatDayMonth, formatHourMinute } from '../utils/dateFormat';
import { htmlToPreviewText } from '../utils/emailContent';
import { apiClient, type PendingDraft } from '../services/api';
import { getWebSocketClient } from '../services/websocket';
import { deleteAllSavedDrafts, type SavedDraft } from '../services/draftStorage';
import { EmptyState, EmptyFolderIcon } from './EmptyState';
import ConfirmationDialog from './ConfirmationDialog';
import { useBulkActionCount } from '../hooks/useBulkActionCount';
import { usePinned } from '../hooks/usePinned';
import { TrashIcon } from './icons/ActionIcons';
import { EmojiMarkerChip } from './SwipeableEmailItem';
import './PendingDraftList.css';

interface PendingDraftListProps {
  onDraftSelect?: (draft: PendingDraft) => void;
  selectedDraftId?: string | null;
  onDraftsLoaded?: (drafts: PendingDraft[]) => void;
  savedDrafts?: SavedDraft[];
  onSavedDraftClick?: (draft: SavedDraft) => void;
  onSavedDraftDelete?: (draftId: string) => void;
  onCompose?: () => void;
  onNavigateUp?: () => void;
  onNavigateDown?: () => void;
  onSearch?: () => void;
  /** Increment to trigger a re-fetch without unmounting the component. */
  refreshTrigger?: number;
  accountId?: number;
}

/** Parse date string, fixing malformed formats like "+00:00Z". */
function parseDate(s: string): Date {
  if (s && s.endsWith('+00:00Z')) {
    return new Date(s.slice(0, -6) + 'Z');
  }
  return new Date(s);
}

function formatDraftTime(dateString: string, locale: string): string {
  const date = parseDate(dateString);
  const now = new Date();
  const isToday = date.toDateString() === now.toDateString();

  if (isToday) {
    return formatHourMinute(date, locale);
  }

  const day = date.getDate();
  const monthName = date.toLocaleString(locale, { month: 'short' });
  return formatDayMonth(day, monthName, locale);
}

function getDateSectionKey(dateString: string): string {
  const date = parseDate(dateString);
  const now = new Date();

  if (date.toDateString() === now.toDateString()) return 'today';

  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return 'yesterday';

  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const diffDays = Math.floor((startOfToday.getTime() - startOfDay.getTime()) / (1000 * 60 * 60 * 24));

  if (diffDays <= 7) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const d = String(date.getDate()).padStart(2, '0');
    return `day-${y}-${m}-${d}`;
  }

  return `month-${date.getFullYear()}-${date.getMonth()}`;
}

function getSectionLabel(sectionKey: string, locale: string, todayLabel: string, yesterdayLabel: string): string {
  if (sectionKey === 'today') return todayLabel;
  if (sectionKey === 'yesterday') return yesterdayLabel;

  if (sectionKey.startsWith('day-')) {
    const dateStr = sectionKey.replace('day-', '');
    const date = new Date(dateStr + 'T00:00:00');
    const day = date.getDate();
    const monthName = date.toLocaleString(locale, { month: 'long' });
    return formatDayMonth(day, monthName, locale);
  }

  if (sectionKey.startsWith('month-')) {
    const parts = sectionKey.replace('month-', '').split('-');
    const year = parseInt(parts[0]);
    const month = parseInt(parts[1]);
    const date = new Date(year, month, 1);
    return date.toLocaleString(locale, { month: 'long', year: 'numeric' });
  }

  return sectionKey;
}

/** Returns empty string if the subject is just email addresses (no real title). */
function sanitizeSubject(subject: string): string {
  if (!subject) return '';
  const core = subject.replace(/^Re:\s*/i, '').trim();
  if (core.includes('@')) return '';
  return subject;
}

/** BUG-AA001/AB002 fix (Session AB, 2026-05-22): derive a short title preview
 *  from the AI-generated body when the email subject is missing or got
 *  sanitised away (e.g. when the original email subject was just an address).
 *  Returns up to ~60 chars of the first non-empty body line. Used as a
 *  fallback so the Drafts list no longer shows long runs of "(Sans objet)"
 *  rows when the AI did write a substantive reply. */
/** Max HTML chars fed to the preview/meaningfulness regex pipeline. A ~60-char
 *  preview never needs more than a few KB of markup, but an UN-capped huge body
 *  (forwarded newsletter, inline base64 images) ran htmlToPreviewText's regexes
 *  on multiple MB and blocked the main thread for seconds — the telemetry-
 *  confirmed 18s /drafts freeze (2026-06-24, stability audit). 8 KB yields far
 *  more than 60 chars of visible text. */
const DRAFT_PREVIEW_BODY_CAP = 8192;

function previewFromBody(body: string | null | undefined): string {
  if (!body) return '';
  // Cap BEFORE the regex pipeline (see DRAFT_PREVIEW_BODY_CAP).
  const capped = body.length > DRAFT_PREVIEW_BODY_CAP ? body.slice(0, DRAFT_PREVIEW_BODY_CAP) : body;
  // Shared stripper → full entity decode (&rsquo; &mdash; … no longer leak as
  // literal text) and tracking-safe tag removal. Pick the first non-empty line.
  const text = htmlToPreviewText(capped, { preserveLineBreaks: true })
    .split('\n')
    .map(l => l.trim())
    .find(l => l.length > 0) ?? '';
  if (!text) return '';
  const chars = Array.from(text);
  return chars.length > 60 ? chars.slice(0, 57).join('').trimEnd() + '…' : text;
}

/** Humanise an email local-part into a Title Case display name.
 *  "alexandre.simon@hotmail.com" → "Alexandre Simon"
 *  "bob+work@example.com"            → "Bob Work"
 *  "support@stripe.com"              → "Support"
 *  Empty / non-email input is returned unchanged.
 */
function humaniseSender(raw: string): string {
  if (!raw) return raw;
  const atIdx = raw.indexOf('@');
  const local = atIdx > 0 ? raw.substring(0, atIdx) : raw;
  if (!local) return raw;
  const parts = local
    .split(/[._\-+]/)
    .filter(p => p.length > 0)
    .map(p => p.charAt(0).toUpperCase() + p.slice(1).toLowerCase());
  return parts.join(' ') || local;
}

function getSenderDisplay(draft: PendingDraft): string {
  // Normalize ALL paths through humaniseSender so the Drafts list
  // doesn't mix "alexandre.simon" (raw local-part), "Alexandre
  // Simon" (display name with space), and "Alexandre.Simon@hot…"
  // (truncated full email). After this every row reads as a clean
  // "Firstname Lastname".
  const name = (draft.email_sender_name || '').trim();
  if (name) {
    // Display names from Gmail sometimes come as "Alexandre.Simon"
    // (machine-formatted local-part) — fix that too.
    return name.includes('.') && !name.includes(' ')
      ? humaniseSender(name)
      : name;
  }
  return humaniseSender(draft.email_sender ?? '');
}


export const PendingDraftList = memo(function PendingDraftList({ onDraftSelect, selectedDraftId, onDraftsLoaded, savedDrafts, onSavedDraftClick, onSavedDraftDelete: _onSavedDraftDelete, onCompose: _onCompose, onNavigateUp: _onNavigateUp, onNavigateDown: _onNavigateDown, onSearch: _onSearch, refreshTrigger, accountId: _accountId }: PendingDraftListProps) {
  const { t, i18n } = useTranslation(['drafts', 'common']);
  // Pinned thread ids (shared with the inbox). A woken follow-up draft is
  // pinned by the wake sweep (its email_id == the pinned thread_id), which
  // floats it into the "Pinned" section below — mirroring the inbox.
  const { pinnedIds, togglePin } = usePinned();
  // Local-only pins for saved (compose/reply) drafts. AI drafts pin their
  // email thread via usePinned (shared with the inbox); saved drafts have no
  // thread, so they get a separate localStorage-backed pin set keyed by the
  // saved-draft id. These never reach the inbox — they only float the draft
  // into the "Pinned" section of this list.
  const PINNED_SAVED_DRAFTS_STORAGE_KEY = 'agentys:pinned-saved-drafts';
  const [pinnedSavedIds, setPinnedSavedIds] = useState<Set<string>>(() => {
    try {
      const raw = localStorage.getItem(PINNED_SAVED_DRAFTS_STORAGE_KEY);
      return raw ? new Set(JSON.parse(raw) as string[]) : new Set();
    } catch {
      return new Set();
    }
  });
  const toggleSavedPin = useCallback((savedId: string) => {
    setPinnedSavedIds(prev => {
      const next = new Set(prev);
      if (next.has(savedId)) next.delete(savedId);
      else next.add(savedId);
      try {
        localStorage.setItem(PINNED_SAVED_DRAFTS_STORAGE_KEY, JSON.stringify(Array.from(next)));
      } catch { /* localStorage quota or disabled — ignore */ }
      return next;
    });
  }, []);
  // Right-click context menu for draft rows — a Pin/Unpin action. AI drafts
  // pin their thread (shared with the inbox); saved drafts pin locally. The
  // handler also suppresses the browser's native context menu on every row.
  const [contextMenu, setContextMenu] = useState<
    { x: number; y: number; kind: 'ai' | 'saved'; refId: string; isPinned: boolean } | null
  >(null);
  const [menuPos, setMenuPos] = useState<{ x: number; y: number } | null>(null);
  const contextMenuRef = useRef<HTMLDivElement>(null);
  // isRefreshing state removed (unused)
  const [drafts, setDrafts] = useState<PendingDraft[]>([]);
  const [loadingState, setLoadingState] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);
  const [, setPendingCount] = useState(0);
  // isDeletingHistory state removed (unused)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [multiSelectMode, setMultiSelectMode] = useState(false);
  const [isPurgingDrafts, setIsPurgingDrafts] = useState(false);
  const [showPurgeConfirm, setShowPurgeConfirm] = useState(false);
  const { t: tInbox } = useTranslation('inbox');
  const purgeCount = useBulkActionCount({
    endpoint: '/pending-drafts/purge-all',
    enabled: showPurgeConfirm,
  });

  // Track viewed draft IDs (persisted to localStorage) — used to render the green
  // "new draft" indicator on AI drafts the user hasn't opened yet, mirroring the
  // unread vertical bar pattern from SwipeableEmailItem.
  const VIEWED_DRAFTS_STORAGE_KEY = 'agentys:viewed-drafts';
  const [viewedDraftIds, setViewedDraftIds] = useState<Set<string>>(() => {
    try {
      const raw = localStorage.getItem(VIEWED_DRAFTS_STORAGE_KEY);
      return raw ? new Set(JSON.parse(raw) as string[]) : new Set();
    } catch {
      return new Set();
    }
  });
  const markDraftViewed = useCallback((draftId: string) => {
    setViewedDraftIds(prev => {
      if (prev.has(draftId)) return prev;
      const next = new Set(prev);
      next.add(draftId);
      try {
        localStorage.setItem(VIEWED_DRAFTS_STORAGE_KEY, JSON.stringify(Array.from(next)));
        // Notifies useUnviewedDraftCount so the sidebar green dot updates without
        // waiting for a re-fetch (storage event doesn't fire in the same window).
        window.dispatchEvent(new Event('agentys:viewed-drafts-changed'));
      } catch { /* localStorage quota or disabled — ignore */ }
      return next;
    });
  }, []);
  const loadDrafts = useCallback(async () => {
    setLoadingState('loading');
    setError(null);
    try {
      const response = await apiClient.listPendingDrafts(100);
      setDrafts(response.drafts);
      setPendingCount(response.pending_count);
      onDraftsLoaded?.(response.drafts);
      setLoadingState('success');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Erreur inconnue';
      setError(message);
      setLoadingState('error');
    }
  }, [onDraftsLoaded]);

  const handlePurgeAllDrafts = useCallback(async () => {
    setIsPurgingDrafts(true);
    try {
      // Clear local saved drafts first (always succeeds)
      deleteAllSavedDrafts();
      // Purge backend AI drafts
      await apiClient.purgeAllDrafts();
      // Reload to reflect cleared state
      await loadDrafts();
    } catch (err) {
      console.error('[PendingDraftList] purge failed:', err);
      // Reload anyway to show current state
      await loadDrafts();
    } finally {
      setIsPurgingDrafts(false);
    }
  }, [loadDrafts]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      if (!cancelled) {
        await loadDrafts();
      }
    };
    run();
    return () => { cancelled = true; };

  }, []);

  // Re-fetch when parent signals a refresh (replaces key={refreshKey} unmount pattern)
  const prevTriggerRef = useRef(refreshTrigger);
  useEffect(() => {
    if (refreshTrigger !== undefined && refreshTrigger !== prevTriggerRef.current) {
      prevTriggerRef.current = refreshTrigger;
      loadDrafts();
    }
  }, [refreshTrigger, loadDrafts]);

  // Rafraîchir les drafts sur événements WebSocket (draft_ready, draft_complete)
  // Remplace le polling 30s — élimine 2 requêtes HTTP/minute en arrière-plan
  useEffect(() => {
    const ws = getWebSocketClient();
    const unsubscribe = ws.subscribe((event) => {
      if (event.type === 'draft_ready' || event.type === 'draft_complete') {
        loadDrafts();
      }
    });
    return unsubscribe;
  }, [loadDrafts]);

  // Close the context menu on outside-click or Escape (mirrors the inbox row menu).
  useEffect(() => {
    if (!contextMenu) return;
    const onDown = (e: MouseEvent) => {
      if (!contextMenuRef.current?.contains(e.target as Node)) setContextMenu(null);
    };
    const onEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') setContextMenu(null); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onEsc);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onEsc);
    };
  }, [contextMenu]);

  // Clamp the menu inside the viewport before paint so a click near the edge
  // doesn't open a clipped menu (useLayoutEffect runs pre-paint — no jump).
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

  const handleDraftClick = (draft: PendingDraft) => {
    markDraftViewed(draft.id);
    onDraftSelect?.(draft);
  };


  const toggleSelect = useCallback((id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      if (next.size > 0) setMultiSelectMode(true);
      else setMultiSelectMode(false);
      return next;
    });
  }, []);

  // Build a unified list: saved drafts + AI drafts, sorted by date descending
  type UnifiedDraft =
    | { kind: 'saved'; id: string; subject: string; sender: string; time: Date; saved: SavedDraft }
    | { kind: 'ai'; id: string; subject: string; sender: string; time: Date; preview: string; draft: PendingDraft };

  // Merge AI-generated PendingDrafts and locally-saved compose/reply drafts so
  // the user can recover any draft they closed via the X button. App.tsx's
  // handleOpenNewMessage already routes recovery through this list (see comment
  // at App.tsx:511) — without this merge, closed compose drafts simply vanished.
  const unifiedDrafts = useMemo<UnifiedDraft[]>(() => {
    // BUG-AA001 fix (Session AA): the QA suite reported up to 20 drafts in
    // a single day, most rendered as "(Sans objet)" with no recoverable
    // content. They come from a backend daemon path that opens an empty
    // pending-draft shell as soon as the user previews an email, even when
    // the user never types anything. Until the daemon side adds the gate,
    // hide the no-subject + no-body shells client-side — they have nothing
    // to recover. We still keep drafts that have a body (auto-generated AI
    // reply) or any subject the user typed.
    // BUG-AA001 fix (Session AB strengthened, 2026-05-22): require either a
    // non-trivial subject OR a body containing at least a few real characters.
    // The previous "subject OR body" gate let through AI drafts whose body was
    // only an HTML wrapper / signature stub (length > 0 after stripping tags
    // but 0 meaningful chars), giving the long run of "(Sans objet)" rows the
    // QA suite kept reporting.
    const isMeaningfulAiDraft = (d: PendingDraft) => {
      const rawSubject = (d.draft_subject || d.email_subject || '').trim();
      // Cheap path first : a draft with a subject is meaningful — skip the body
      // regex entirely (avoids the un-capped tag-strip on every body).
      if (rawSubject.length > 0) return true;
      // Body must have meaningful content (more than just punctuation/whitespace).
      // Cap before the regex (see DRAFT_PREVIEW_BODY_CAP) — un-capped strip on a
      // multi-MB body was part of the 18s /drafts freeze.
      const cleanedBody = (d.draft_body || '')
        .slice(0, DRAFT_PREVIEW_BODY_CAP)
        .replace(/<br\s*\/?>(\s*)/gi, '\n')
        .replace(/<[^>]*>/g, '')
        .replace(/&nbsp;/gi, ' ')
        .trim();
      return cleanedBody.replace(/[\s\W]/g, '').length >= 4;
    };
    const aiItems: UnifiedDraft[] = drafts
      .filter(isMeaningfulAiDraft)
      .map((d) => {
        const cleanSubject = sanitizeSubject(d.draft_subject || d.email_subject || '');
        // BUG-AA001/AB002 (Session AB): when no usable subject, show the
        // first words of the AI body so the user can tell drafts apart
        // instead of seeing 15× "(Sans objet)" in a row.
        const fallback = cleanSubject || previewFromBody(d.draft_body) || t('drafts:no_subject');
        return {
          kind: 'ai' as const,
          id: d.id,
          subject: fallback,
          sender: getSenderDisplay(d),
          time: new Date(d.created_at),
          preview: (d.draft_body ?? '').substring(0, 100),
          draft: d,
        };
      });
    const savedItems: UnifiedDraft[] = (savedDrafts ?? []).map((s) => {
      if (s.type === 'compose') {
        const to = (s.to || '').trim();
        return {
          kind: 'saved' as const,
          id: s.id,
          subject: s.subject?.trim() || t('drafts:no_subject'),
          // Humanise the recipient address so saved compose drafts
          // render uniformly with AI drafts (no "alexandre@hot…" vs
          // "Alexandre Simon" mismatch).
          // BUG-S009 fix (2026-05-16): localised "no recipient" placeholder
          // — bare em-dash looked like a glitch in the drafts list.
          sender: to ? (humaniseSender(to) || to) : t('drafts:no_recipient', { defaultValue: 'Sans destinataire' }),
          time: new Date(s.savedAt),
          saved: s,
        };
      }
      return {
        kind: 'saved' as const,
        id: s.id,
        subject: s.emailSubject?.trim() || t('drafts:no_subject'),
        sender: humaniseSender(s.emailSender || '') || (s.emailSender || ''),
        time: new Date(s.savedAt),
        saved: s,
      };
    });
    return [...aiItems, ...savedItems].sort((a, b) => b.time.getTime() - a.time.getTime());
  }, [drafts, savedDrafts, t]);

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(unifiedDrafts.map(d => d.id)));
    setMultiSelectMode(true);
  }, [unifiedDrafts]);

  const deselectAll = useCallback(() => {
    setSelectedIds(new Set());
    setMultiSelectMode(false);
  }, []);

  // Group drafts by date sections (includes section counts)
  type FlatRow =
    | { type: 'header'; label: string; count: number; key: string }
    | { type: 'draft'; item: UnifiedDraft; key: string };

  const flatRows = useMemo<FlatRow[]>(() => {
    const rows: FlatRow[] = [];
    const locale = i18n.language;
    const todayLabel = t('common:today');
    const yesterdayLabel = t('common:yesterday');

    // Pinned section: pinned drafts float to the top under a dedicated
    // "Pinned" header, mirroring the inbox. An AI draft is matched by its
    // email_id (== the pinned thread_id); a saved compose/reply draft is
    // matched by its local pin (pinnedSavedIds), keyed by the saved-draft id.
    const isPinnedItem = (item: UnifiedDraft) =>
      item.kind === 'ai'
        ? pinnedIds.has(item.draft.email_id)
        : pinnedSavedIds.has(item.id);
    const pinnedItems = unifiedDrafts.filter(isPinnedItem);
    const restItems = unifiedDrafts.filter(item => !isPinnedItem(item));

    if (pinnedItems.length > 0) {
      rows.push({ type: 'header', label: tInbox('qs_pinned'), count: pinnedItems.length, key: 'header-pinned' });
      for (const item of pinnedItems) {
        rows.push({ type: 'draft', item, key: `pinned-${item.id}` });
      }
    }

    // Date sections for the remaining (unpinned) drafts.
    const counts = new Map<string, number>();
    for (const item of restItems) {
      const key = getDateSectionKey(item.time.toISOString());
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    let currentSection = '';
    for (const item of restItems) {
      const sectionKey = getDateSectionKey(item.time.toISOString());
      if (sectionKey !== currentSection) {
        currentSection = sectionKey;
        const label = getSectionLabel(sectionKey, locale, todayLabel, yesterdayLabel);
        if (label) {
          rows.push({ type: 'header', label, count: counts.get(sectionKey) || 0, key: `header-${sectionKey}` });
        }
      }
      rows.push({ type: 'draft', item, key: item.id });
    }
    return rows;
  }, [unifiedDrafts, pinnedIds, pinnedSavedIds, tInbox, t, i18n.language]);

  const allSelected = unifiedDrafts.length > 0 && selectedIds.size === unifiedDrafts.length;
  const someSelected = selectedIds.size > 0 && !allSelected;

  const headerEl = (
    <div className="draft-list-header">
      {multiSelectMode && (
        <button
          className={`draft-header-select-btn${someSelected ? ' partial' : ''}${allSelected ? ' all' : ''}`}
          onClick={allSelected ? deselectAll : selectAll}
          aria-label={allSelected ? t('common:deselect_all') : t('common:select_all')}
        >
          {allSelected ? (
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 16 16" fill="none">
              <rect x="1" y="1" width="14" height="14" rx="3" fill="var(--accent-primary)" stroke="var(--accent-primary)" strokeWidth="1.5" />
              <path d="M4.5 8L7 10.5L11.5 5.5" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          ) : someSelected ? (
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 16 16" fill="none">
              <rect x="1" y="1" width="14" height="14" rx="3" fill="var(--accent-primary)" stroke="var(--accent-primary)" strokeWidth="1.5" />
              <line x1="4.5" y1="8" x2="11.5" y2="8" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          ) : (
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 16 16" fill="none">
              <rect x="1" y="1" width="14" height="14" rx="3" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.5" />
            </svg>
          )}
          {selectedIds.size > 0 && (
            <span className="draft-header-select-count">{selectedIds.size}</span>
          )}
        </button>
      )}
      <div className="draft-header-tabs">
        <button className="draft-header-tab active">
          {t('drafts:title')}
        </button>
      </div>
      <div className="draft-header-actions">
      </div>
    </div>
  );

  if (loadingState === 'loading' && unifiedDrafts.length === 0) {
    return (
      <div className="draft-list-container">
        {headerEl}
        <div className="pending-draft-list-loading" role="status" aria-busy="true">
          <div className="loading-spinner" />
          <span>{t('drafts:loading')}</span>
        </div>
      </div>
    );
  }

  if (loadingState === 'error') {
    return (
      <div className="draft-list-container">
        {headerEl}
        <div className="pending-draft-list-error" role="alert" aria-live="assertive">
          <span className="error-icon">!</span>
          <p>{error}</p>
          <button onClick={loadDrafts} className="retry-button">
            {t('common:retry')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="draft-list-container">
      {headerEl}

      {unifiedDrafts.length > 0 && (
        <div className="drafts-banner">
          <TrashIcon size={14} />
          <span>{t('drafts:cleanup_hint')}</span>
          <button
            className="drafts-cleanup-btn icon-btn--delete"
            onClick={() => setShowPurgeConfirm(true)}
            disabled={isPurgingDrafts || unifiedDrafts.length === 0}
            type="button"
            title={t('drafts:cleanup_btn')}
          >
            {isPurgingDrafts ? <span className="banner-btn-spinner" /> : <TrashIcon size={14} />}
          </button>
        </div>
      )}

      <ConfirmationDialog
        isOpen={showPurgeConfirm}
        onConfirm={handlePurgeAllDrafts}
        onCancel={() => setShowPurgeConfirm(false)}
        title={tInbox('purge_drafts_confirm_title')}
        message={
          <span style={{ display: 'block', whiteSpace: 'normal' }}>
            {tInbox('purge_drafts_confirm_message')}
            {purgeCount.count !== null && purgeCount.count > 0 && (
              <><br />{tInbox('purge_drafts_count_summary', { count: purgeCount.count })}</>
            )}
          </span>
        }
        confirmLabel={tInbox('purge_drafts_confirm_label')}
        destructive
      />

      {unifiedDrafts.length === 0 ? (
        <EmptyState
          icon={<EmptyFolderIcon />}
          title={t('drafts:empty_title')}
          subtitle=""
        />
      ) : (
        <div className="draft-list-scroll" aria-live="polite">
          {flatRows.map((row) => {
            if (row.type === 'header') {
              return (
                <div key={row.key} className="draft-date-separator">
                  <span className="draft-date-label">{row.label}</span>
                  <span className="draft-date-count">{row.count}</span>
                </div>
              );
            }

            const item = row.item;
            // Pinned drafts get a red leading bar, mirroring the inbox. AI
            // drafts pin their thread (pinnedIds); saved drafts pin locally
            // (pinnedSavedIds). Either way the row floats to "Pinned" above.
            const isPinned = item.kind === 'ai'
              ? pinnedIds.has(item.draft.email_id)
              : pinnedSavedIds.has(item.id);
            return (
              <div
                key={row.key}
                className={`draft-item${item.kind === 'ai' && selectedDraftId === item.id ? ' selected' : ''}${selectedIds.has(item.id) ? ' checked' : ''}${item.kind === 'ai' && !viewedDraftIds.has(item.id) ? ' unread' : ''}${isPinned ? ' pinned' : ''}`}
                data-testid="draft-item"
                onClick={() => {
                  if (item.kind === 'ai') handleDraftClick(item.draft);
                  else onSavedDraftClick?.(item.saved);
                }}
                onContextMenu={(e) => {
                  // Suppress the browser's native menu on every draft row and
                  // open our Pin/Unpin menu. AI drafts pin their thread; saved
                  // drafts pin locally (refId is the saved-draft id).
                  e.preventDefault();
                  setContextMenu({
                    x: e.clientX,
                    y: e.clientY,
                    kind: item.kind,
                    refId: item.kind === 'ai' ? item.draft.email_id : item.id,
                    isPinned,
                  });
                }}
              >
                <div className="draft-row">
                  <label className={`draft-checkbox${selectedIds.has(item.id) ? ' checked' : ''}`} onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selectedIds.has(item.id)}
                      onChange={() => toggleSelect(item.id)}
                      aria-label={t('drafts:select')}
                    />
                    <span className="checkbox-custom" />
                  </label>

                  <span className="draft-row-sender">{item.sender}</span>
                  <div className="draft-row-subject-cell">
                    <span className="draft-row-subject">{item.subject}</span>
                  </div>
                  {/* All trailing chips (🔁 follow-up marker, ⚡ Auto, 💤
                      snoozed) cluster in ONE content-sized cell right before
                      the date, so they sit tight against each other and the
                      date — no chip stranded at the subject edge. The date is
                      the last fixed column and the subject's 1fr absorbs the
                      slack, so the date stays at a constant X regardless of
                      how many chips a row carries. */}
                  <span className="draft-row-meta-col">
                    {item.kind === 'ai' && item.draft.emoji_marker && (
                      <EmojiMarkerChip
                        emoji={item.draft.emoji_marker.emoji}
                        text={item.draft.emoji_marker.text}
                        color={item.draft.emoji_marker.color}
                        chip={item.draft.emoji_marker.chip}
                      />
                    )}
                    {item.kind === 'ai' && item.draft.routing_tier === 'followup' && (
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
                    {item.kind === 'ai' && item.draft.snoozed_until && (
                      <span
                        className="draft-row-snoozed-chip"
                        title={`Snoozed until ${new Date(item.draft.snoozed_until).toLocaleString(i18n.language)}`}
                        aria-label={`Snoozed until ${new Date(item.draft.snoozed_until).toLocaleString(i18n.language)}`}
                      >
                        <svg width="10" height="10" viewBox="0 0 12 12" aria-hidden="true">
                          <path d="M6 2.5a2.4 2.4 0 0 0 3.6 3.6 3.6 3.6 0 1 1-3.6-3.6Z" fill="currentColor" />
                        </svg>
                        <span>{formatDraftTime(item.draft.snoozed_until, i18n.language)}</span>
                      </span>
                    )}
                  </span>
                  <span className="draft-row-time">{formatDraftTime(item.time.toISOString(), i18n.language)}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {contextMenu && createPortal(
        <div
          ref={contextMenuRef}
          className="email-context-menu"
          style={{ position: 'fixed', left: (menuPos ?? contextMenu).x, top: (menuPos ?? contextMenu).y }}
          role="menu"
          aria-label={tInbox('email_actions')}
        >
          <button
            type="button"
            className="context-menu-item"
            onClick={() => {
              if (contextMenu.kind === 'ai') togglePin(contextMenu.refId);
              else toggleSavedPin(contextMenu.refId);
              setContextMenu(null);
            }}
            role="menuitem"
          >
            {contextMenu.isPinned ? tInbox('unpin') : tInbox('pin')}
          </button>
        </div>,
        document.body
      )}

    </div>
  );
})
