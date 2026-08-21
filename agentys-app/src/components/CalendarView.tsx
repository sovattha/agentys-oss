/* eslint-disable react-refresh/only-export-components */
import { useState, useEffect, useMemo, useCallback, useRef, memo } from 'react';
import { useTranslation } from 'react-i18next';
import { apiClient, ApiError } from '../services/api';
import { copyToClipboard } from '../utils/clipboard';
import { dedupHolidays, normalizeHolidayTitle, holidayTitlesWithin } from '../utils/holidayDedup';
import { CloseIcon, CheckIcon, EditIcon, TrashIcon, ChevronLeftIcon, ChevronRightIcon, SearchIcon } from './icons/ActionIcons';

/** Google Calendar colorId → hex (event colors 1-11) */
const GCAL_COLOR_MAP: Record<string, string> = {
  '1': '#7986cb', '2': '#33b679', '3': '#8e24aa', '4': '#e67c73',
  '5': '#f6bf26', '6': '#f4511e', '7': '#039be5', '8': '#616161',
  '9': '#3f51b5', '10': '#0b8043', '11': '#d50000',
};

/** Month keys in order (Jan..Dec) for i18n lookup */
const MONTH_KEYS = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'] as const;
/** Day-of-week keys in Mon..Sun order for i18n lookup */
const DAY_KEYS_MON_SUN = ['mon','tue','wed','thu','fri','sat','sun'] as const;
import type { Calendar, CalendarEvent, CalendarEventsResponse } from '../services/api';
import { CalendarSidebar } from './CalendarSidebar';
import { QuickEventPopover, parseDescriptionAndLabels, formatOrganizer, type EditEventData } from './Calendar/QuickEventPopover';
import { useDeepWorkSetting, type DeepWorkSettings } from '../hooks/useDeepWorkSetting';
import { fetchLabels } from '../api/labels';
import { DEFAULT_LABELS, getLabelDisplayName } from '../types/labels';
import { TZ2_COLOR_PRESETS, getTzLabel, useSecondaryTimezone, useTz2Color, TimezonePicker } from './TimezoneUtils';
import { formatEventDetailDate, formatEventDetailDateTime, formatHourMinute } from '../utils/dateFormat';
import i18n from '../i18n';
import { remapEventLabelOverride } from '../utils/eventLabelOverrides';
import './CalendarView.css';

const VISIBLE_CALENDARS_KEY = 'agentys-visible-calendars';
const EVENT_LABELS_KEY = 'agentys-calendar-event-labels';
const VIEW_MODE_KEY = 'agentys-calendar-view-mode';
const WEEK_START_KEY = 'agentys-cal-week-start';

type ViewMode = 1 | 3 | 7;

/** Get ISO 8601 week number */
function getWeekNumber(date: Date): number {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNum = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return Math.ceil(((d.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
}

/** Get start date for the current view (for 1-day: today, for 3-day: today, for 7: Monday) */
function getViewStart(date: Date, mode: ViewMode): Date {
  if (mode === 7) return getStartOfWeek(date);
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return d;
}

interface CalendarViewProps {
  accountId?: string;
  onOpenSettings?: () => void;
  onOpenAccounts?: () => void;
  onClose?: () => void;
  deepWorkSettings?: DeepWorkSettings;
  /** Increment to trigger "create event" popover from outside (e.g. sidebar "+") */
  createEventTrigger?: number;
  ribbonVisible?: boolean;
  onShowRibbon?: () => void;
  userEmail?: string;
  onComposeToAttendees?: (to: string, subject: string, body?: string) => void;
  /** Event ids that should display the "imminent" highlight (within next 30 min). */
  imminentEventIds?: Set<string>;
}

// Helper to get start of week (Monday)
function getStartOfWeek(date: Date): Date {
  const d = new Date(date);
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  d.setDate(diff);
  d.setHours(0, 0, 0, 0);
  return d;
}

// Helper to format date for API
function formatDateForApi(date: Date): string {
  return date.toISOString();
}

// Helper to format clock time — locale-aware (FR "17h00", EN/ES "17:00").
function formatTime(dateInput: string | Date): string {
  return formatHourMinute(new Date(dateInput), i18n.language);
}


/** Get local timezone abbreviation (e.g. "EST", "HNE", "CET") */
function getLocalTimezoneAbbr(): string {
  try {
    const parts = new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' }).formatToParts(new Date());
    const tzPart = parts.find(p => p.type === 'timeZoneName');
    return tzPart?.value || '';
  } catch {
    return '';
  }
}

// DAY_NAMES and MONTHS_FR removed — now using i18n common:days_short and common:months

// Hours for time column (5am to 11pm to avoid clipping early/late events)
const HOURS = Array.from({ length: 19 }, (_, i) => i + 5);
const HOUR_START = HOURS[0];        // 5
const HOUR_COUNT = HOURS.length;    // 19
const PX_PER_HOUR = 48;

/** Returns UTC offset in minutes for a given IANA timezone at a specific Date */
function getUtcOffsetMinutes(tz: string, date: Date): number {
  const parts = new Intl.DateTimeFormat('en', {
    timeZone: tz,
    timeZoneName: 'longOffset',
  }).formatToParts(date);
  const tzPart = parts.find(p => p.type === 'timeZoneName')?.value ?? '';
  const match = tzPart.match(/GMT([+-])(\d{1,2}):(\d{2})/);
  if (!match) return 0;
  return (match[1] === '+' ? 1 : -1) * (parseInt(match[2], 10) * 60 + parseInt(match[3], 10));
}

/** Returns a map of dateStr → offset diff (minutes) for days with a DST transition */
function findDstTransitions(tz: string, dates: Date[]): Map<string, number> {
  const result = new Map<string, number>();
  dates.forEach(d => {
    const noon = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 12);
    const nextNoon = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1, 12);
    const off1 = getUtcOffsetMinutes(tz, noon);
    const off2 = getUtcOffsetMinutes(tz, nextNoon);
    if (off1 !== off2) {
      const dateStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      result.set(dateStr, off2 - off1);
    }
  });
  return result;
}

/** Current time line position (updates every minute) */
function useNowPosition(): number {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);
  const hours = now.getHours() + now.getMinutes() / 60;
  return (hours - HOUR_START) * PX_PER_HOUR;
}

// ── Secondary Timezone (imported from TimezoneUtils to avoid pulling FullCalendar into Sidebar) ──
export { TZ2_COLOR_PRESETS, getTzLabel, useSecondaryTimezone, useTz2Color, TimezonePicker };

const TZ2_HOLIDAYS_STORAGE_KEY = 'agentys-calendar-tz2-holidays';
const PRIMARY_HOLIDAYS_STORAGE_KEY = 'agentys-calendar-primary-holidays';
// Fallback: browser IANA timezone (peut être imprécis sur Windows, ex: America/New_York au lieu d'America/Montreal)
const LOCAL_TZ_FALLBACK = Intl.DateTimeFormat().resolvedOptions().timeZone;

/** Map timezone → i18n key for country name (calendar:tz_country_*) */
const TIMEZONE_COUNTRY_KEY_MAP: Record<string, string> = {
  'Pacific/Honolulu': 'tz_country_us',
  'America/Anchorage': 'tz_country_us',
  'America/Los_Angeles': 'tz_country_us',
  'America/Denver': 'tz_country_us',
  'America/Chicago': 'tz_country_us',
  'America/New_York': 'tz_country_us',
  'America/Toronto': 'tz_country_canada',
  'America/Montreal': 'tz_country_canada',
  'America/Vancouver': 'tz_country_canada',
  'America/Edmonton': 'tz_country_canada',
  'America/Winnipeg': 'tz_country_canada',
  'America/Halifax': 'tz_country_canada',
  'America/Mexico_City': 'tz_country_mexico',
  'America/Bogota': 'tz_country_colombia',
  'America/Sao_Paulo': 'tz_country_brazil',
  'America/Argentina/Buenos_Aires': 'tz_country_argentina',
  'Europe/London': 'tz_country_uk',
  'Europe/Paris': 'tz_country_france',
  'Europe/Istanbul': 'tz_country_turkey',
  'Europe/Moscow': 'tz_country_russia',
  'Africa/Cairo': 'tz_country_egypt',
  'Africa/Johannesburg': 'tz_country_south_africa',
  'Asia/Dubai': 'tz_country_uae',
  'Asia/Kolkata': 'tz_country_india',
  'Asia/Bangkok': 'tz_country_thailand',
  'Asia/Singapore': 'tz_country_singapore',
  'Asia/Hong_Kong': 'tz_country_hong_kong',
  'Asia/Shanghai': 'tz_country_china',
  'Asia/Seoul': 'tz_country_south_korea',
  'Asia/Tokyo': 'tz_country_japan',
  'Australia/Sydney': 'tz_country_australia',
  'Pacific/Auckland': 'tz_country_new_zealand',
};

/** Convert a local hour (0-23) to the equivalent hour string in a target timezone.
 *  Locale-aware via formatHourMinute (FR "14h00", EN/ES "14:00"); the local
 *  column uses the same helper, so the two timezone columns stay matched
 *  (BUG-X008, 2026-05-17; locale-aware since 2026-06-01). */
function getHourInTimezone(localHour: number, targetTz: string): string {
  const now = new Date();
  now.setHours(localHour, 0, 0, 0);
  try {
    const raw = now.toLocaleTimeString('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: targetTz,
    });
    const m = raw.match(/^0?(\d{1,2}):(\d{2})$/);
    const h = m ? parseInt(m[1], 10) : localHour;
    const min = m ? parseInt(m[2], 10) : 0;
    return formatHourMinute(new Date(2000, 0, 1, h, min), i18n.language);
  } catch {
    return formatHourMinute(new Date(2000, 0, 1, localHour, 0), i18n.language);
  }
}

/** Map a calendar write (move/resize) API failure to a localized toast.
 *  apiClient throws an Error whose `.message` is the backend `error` code.
 *  `calendar_event_forbidden` (you're not the organizer / read-only calendar —
 *  re-auth won't help) and `missing_calendar_scope` (genuine scope) get
 *  specific guidance; anything else falls back to `fallbackKey`. The old code
 *  surfaced the raw error code (e.g. "missing_calendar_scope") to the user.
 *  Audit 2026-05-27. */
function calendarWriteErrorMessage(
  err: unknown,
  tc: (key: string) => string,
  fallbackKey: string,
): string {
  const code = err instanceof Error ? err.message : String(err);
  if (code === 'calendar_event_forbidden') return tc('toasts.calendar_event_not_organizer');
  if (code === 'missing_calendar_scope') return tc('toasts.calendar_event_reauth_needed');
  return tc(fallbackKey);
}

function CalendarViewInner({ accountId, onOpenSettings, onOpenAccounts, deepWorkSettings: externalDwSettings, createEventTrigger = 0, ribbonVisible, onShowRibbon: _onShowRibbon, userEmail, onComposeToAttendees, imminentEventIds }: CalendarViewProps) {
  const { t, i18n } = useTranslation('calendar');
  const { t: tc } = useTranslation('common');
  const lang = i18n.language || 'fr';

  /** Resolve a timezone to a translated country name */
  const getTzCountry = useCallback((tz: string): string => {
    const key = TIMEZONE_COUNTRY_KEY_MAP[tz];
    return key ? t(key) : '';
  }, [t]);
  const [viewMode, setViewMode] = useState<ViewMode>(() => {
    try {
      const stored = localStorage.getItem(VIEW_MODE_KEY);
      if (stored === '1' || stored === '3') return parseInt(stored) as ViewMode;
    } catch { /* noop */ }
    return 7;
  });
  const [currentWeekStart, setCurrentWeekStart] = useState<Date>(() => {
    try {
      const saved = sessionStorage.getItem(WEEK_START_KEY);
      if (saved) {
        const d = new Date(saved);
        if (!isNaN(d.getTime())) return getViewStart(d, 7);
      }
    } catch { /* noop */ }
    return getViewStart(new Date(), 7);
  });
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [lookaheadEvents, setLookaheadEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const initialLoadDoneRef = useRef(false);
  // Track the week key of the last fetch to detect week navigation
  const fetchingWeekRef = useRef<number>(0);
  // Grace period: keep recently-created events for 30s regardless of server propagation delay
  const recentlyCreatedRef = useRef<Map<string, number>>(new Map());
  // Monotonic fetch ID — discard stale responses when a newer fetch has been launched
  const fetchIdRef = useRef(0);
  // Prevent concurrent/duplicate fetches (e.g. React 18 StrictMode double-mount)
  const fetchInProgressRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [noAccount, setNoAccount] = useState(false);
  const [needsReauth, setNeedsReauth] = useState(false);
  const [calendarProvider, setCalendarProvider] = useState<string>('outlook');
  const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null);
  const [confirmDeleteEventId, setConfirmDeleteEventId] = useState<string | null>(null);
  const [editingEvent, setEditingEvent] = useState<EditEventData | null>(null);
  const [secondaryTz, setSecondaryTz] = useSecondaryTimezone();
  const [tz2Color] = useTz2Color();
  const [holidays, setHolidays] = useState<{ id: string; title: string; date: string }[]>([]);
  const [showTz2Holidays, setShowTz2Holidays] = useState(() => {
    try { return localStorage.getItem(TZ2_HOLIDAYS_STORAGE_KEY) !== 'false'; } catch { return true; }
  });
  const [primaryHolidays, setPrimaryHolidays] = useState<{ id: string; title: string; date: string }[]>([]);
  const [showPrimaryHolidays, setShowPrimaryHolidays] = useState(() => {
    try { return localStorage.getItem(PRIMARY_HOLIDAYS_STORAGE_KEY) !== 'false'; } catch { return true; }
  });
  // IP-detected region (plus précis que Intl sur Windows — ex: QC au lieu d'inférer depuis America/New_York)
  const [detectedTz, setDetectedTz] = useState<string>(LOCAL_TZ_FALLBACK);
  const [detectedCountry, setDetectedCountry] = useState<string | null>(null);
  const [detectedRegion, setDetectedRegion] = useState<string | null>(null);
  const weekBodyRef = useRef<HTMLDivElement>(null);
  const eventModalRef = useRef<HTMLDivElement>(null);
  const nowPosition = useNowPosition();
  const hasScrolledRef = useRef(false);
  const hasTz2 = secondaryTz.length > 0;
  const deepWorkLocal = useDeepWorkSetting(accountId ? Number(accountId) : undefined);
  const deepWork = externalDwSettings ? { settings: externalDwSettings } : deepWorkLocal;
  // Month/year picker state
  const [monthPickerOpen, setMonthPickerOpen] = useState(false);
  const [yearPickerOpen,  setYearPickerOpen]  = useState(false);
  const [monthPickerPos,  setMonthPickerPos]  = useState<{ top: number; left: number } | null>(null);
  const [yearPickerPos,   setYearPickerPos]   = useState<{ top: number; left: number } | null>(null);
  const monthBtnRef    = useRef<HTMLButtonElement>(null);
  const yearBtnRef     = useRef<HTMLButtonElement>(null);
  const monthPickerRef = useRef<HTMLDivElement>(null);
  const yearPickerRef  = useRef<HTMLDivElement>(null);

  // Manual event label overrides (eventId → {name, color})
  const [eventLabelOverrides, setEventLabelOverrides] = useState<Record<string, { name: string; color: string }>>(() => {
    try {
      const stored = localStorage.getItem(EVENT_LABELS_KEY);
      if (stored) return JSON.parse(stored);
    } catch { /* noop */ }
    return {};
  });

  // Delete event via X button — optimistic UI with rollback on error
  const handleQuickDelete = useCallback(async (e: React.MouseEvent, eventId: string) => {
    e.stopPropagation();
    e.preventDefault();
    setSelectedEvent(null);

    const removed = events.find(ev => ev.id === eventId);
    // Synthetic local-only events (deep-work / work-block) have no provider id.
    if (removed?.calendarId === '__deep_work__' || removed?.calendarId === '__work_block__') return;
    setEvents(prev => prev.filter(ev => ev.id !== eventId));

    try {
      // Pass the event's calendarId so secondary/shared-calendar deletes hit the
      // right calendar (omitting it targeted "primary" and silently no-op'd, so
      // the event reappeared on next refresh).
      await apiClient.deleteCalendarEvent(eventId, accountId, removed?.calendarId);
    } catch (err) {
      console.error('[CalendarView] Delete failed:', err);
      // Roll back the optimistic removal and surface a toast. TC-01: this path
      // used to setError(...), which flips the WHOLE calendar to a full-page
      // error screen whose Retry re-fetches events (never re-deletes) — losing
      // the user's calendar context. The modal-confirm delete path already uses
      // a toast; the X-button path was missed.
      if (removed) setEvents(prev => [...prev, removed]);
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: {
            message: tc('toasts.calendar_event_delete_failed'),
            type: 'error',
            duration: 6000,
          },
        }));
      }
    }
  }, [events, accountId, tc]);

  const setEventLabel = useCallback((eventId: string, label: { name: string; color: string } | null) => {
    setEventLabelOverrides(prev => {
      const next = { ...prev };
      if (label) {
        next[eventId] = label;
      } else {
        delete next[eventId];
      }
      try { localStorage.setItem(EVENT_LABELS_KEY, JSON.stringify(next)); } catch { /* noop */ }
      return next;
    });
  }, []);

  // Carry a manual label override across an event-id change. After create, the
  // optimistic `temp-…` id is swapped for the real provider id; without this the
  // colour applied to the optimistic event is orphaned and the meeting goes pale
  // once the create resolves. `toId === null` drops the override (create failed).
  const migrateEventLabel = useCallback((fromId: string, toId: string | null) => {
    setEventLabelOverrides(prev => {
      const next = remapEventLabelOverride(prev, fromId, toId);
      if (next === prev) return prev;
      try { localStorage.setItem(EVENT_LABELS_KEY, JSON.stringify(next)); } catch { /* noop */ }
      return next;
    });
  }, []);

  // Quick event creation popover
  const [quickEvent, setQuickEvent] = useState<{
    date: Date; hour: number; endHour?: number; endMinute?: number; anchorRect: DOMRect;
  } | null>(null);
  const [meetLinkToast, setMeetLinkToast] = useState<string | null>(null);
  const [meetLinkCopied, setMeetLinkCopied] = useState(false);
  const [createErrorToast, setCreateErrorToast] = useState<string | null>(null);

  // Drag-to-create state
  const dragCreateRef = useRef<{
    date: Date;
    startHour: number;
    startMinute: number;
    el: HTMLElement;
    ghostEl: HTMLElement | null;
  } | null>(null);

  // Resize ref
  const resizeRef = useRef<{
    event: CalendarEvent;
    startY: number;
    origHeight: number;
    origTop: number;
    el: HTMLElement;
    startScrollTop: number;
    edge: 'top' | 'bottom';
  } | null>(null);

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [searchExpanded, setSearchExpanded] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [searchResults, setSearchResults] = useState<CalendarEvent[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const searchFetchIdRef = useRef(0);
  const searchLoadedRef = useRef(false);

  // Label color maps for matching events
  const [labelColorMap, setLabelColorMap] = useState<Map<string, string>>(new Map()); // labelName(lower) → color
  const [labelPrefixColors, setLabelPrefixColors] = useState<Array<{ prefix: string; color: string }>>([]); // subject_prefix(lower) → color (sorted longest first)
  const [calendarColorMap, setCalendarColorMap] = useState<Map<string, string>>(new Map()); // calendarId → color
  const [customLabels, setCustomLabels] = useState<Array<{ name: string; color: string }>>([]); // non-default labels
  const calendarsRef = useRef<Calendar[]>([]);

  // Calendar filtering — toujours null au montage (show all) pour éviter que des IDs
  // périmés en localStorage cachent des événements avant que le sidebar valide les IDs réels.
  const [visibleCalendarIds, setVisibleCalendarIds] = useState<Set<string> | null>(null);
  // Real ID of the primary calendar (e.g. user email for Gmail). Used to resolve
  // the backend's "primary" alias on events so the primary toggle actually filters.
  const [primaryCalendarId, setPrimaryCalendarId] = useState<string | null>(null);
  // All calendar IDs the user has — passed to the backend so events from holiday
  // and other secondary calendars are fetched alongside the primary.
  const [allCalendarIds, setAllCalendarIds] = useState<string[]>([]);

  const handleToggleCalendar = useCallback((calendarId: string) => {
    setVisibleCalendarIds(prev => {
      const next = new Set(prev || []);
      if (next.has(calendarId)) {
        next.delete(calendarId);
      } else {
        next.add(calendarId);
      }
      try { localStorage.setItem(VISIBLE_CALENDARS_KEY, JSON.stringify([...next])); } catch { /* noop */ }
      return next;
    });
  }, []);

  // Charge les labels + rebuild les maps couleur (labelColor, prefix, calendar).
  // Réutilisable : appelée au mount, après handleCalendarsLoaded, et sur 'agentys:labels-updated'.
  const reloadLabelsAndColors = useCallback(async () => {
    try {
      const res = await fetchLabels();
      const lblMap = new Map<string, string>();
      const prefixList: Array<{ prefix: string; color: string }> = [];
      const customs: Array<{ name: string; color: string }> = [];
      const defaultNames = new Set(DEFAULT_LABELS.map(l => l.name));
      for (const label of res.labels) {
        lblMap.set(label.name.toLowerCase(), label.color);
        if (label.subject_prefix && label.subject_prefix.trim()) {
          prefixList.push({
            prefix: label.subject_prefix.trimEnd().toLowerCase(),
            color: label.color,
          });
        }
        if (!defaultNames.has(label.name)) {
          customs.push({ name: label.name, color: label.color });
        }
      }
      // Longest prefix wins (ex: "ACME PRJ-142" beats "ACME")
      prefixList.sort((a, b) => b.prefix.length - a.prefix.length);
      setLabelColorMap(lblMap);
      setLabelPrefixColors(prefixList);
      setCustomLabels(customs);
      // Rebuild calendarColorMap using current calendars
      // Priority: label color (user-defined) > calendar's own color from provider
      if (calendarsRef.current.length > 0) {
        const calMap = new Map<string, string>();
        for (const cal of calendarsRef.current) {
          const labelColor = lblMap.get(cal.name.toLowerCase());
          if (labelColor) {
            calMap.set(cal.id, labelColor);
          } else if (cal.color) {
            calMap.set(cal.id, cal.color);
          }
        }
        setCalendarColorMap(calMap);
      }
    } catch (err) {
      console.error('[CalendarView] fetch labels failed:', err);
    }
  }, []);

  // Refresh labels on mount and when any label is updated elsewhere
  useEffect(() => {
    reloadLabelsAndColors();
    const onLabelsUpdated = () => reloadLabelsAndColors();
    window.addEventListener('agentys:labels-updated', onLabelsUpdated);
    return () => window.removeEventListener('agentys:labels-updated', onLabelsUpdated);
  }, [reloadLabelsAndColors]);

  // BUG-S007 (2026-05-16): the browser tab title used to stay frozen on the
  // previous view (e.g. "Inbox - …") when the user navigated to the calendar.
  // Every other view (Drafts, En attente) updates the title — Calendar was
  // the outlier. Mirror that behaviour so the tab strip reflects context.
  useEffect(() => {
    const title = t('title', { defaultValue: 'Calendrier' });
    document.title = userEmail ? `${title} - ${userEmail}` : title;
  }, [t, userEmail]);

  const handleCalendarsLoaded = useCallback((ids: string[], cals?: Calendar[]) => {
    setAllCalendarIds(ids);
    const primaryCalForState = cals?.find(c => c.isPrimary) || cals?.[0];
    if (primaryCalForState?.id) setPrimaryCalendarId(primaryCalForState.id);
    setVisibleCalendarIds(() => {
      // Empty calendar list → show everything (no filter)
      if (ids.length === 0) return null;
      // Identifier le calendrier principal (le premier de la liste ou celui marqué isPrimary)
      const primaryCal = cals?.find(c => c.isPrimary) || cals?.[0];
      const primaryId = primaryCal?.id;
      // Valider les préférences stockées contre les IDs réels reçus du backend.
      // On ne garde que les IDs encore valides — évite les stale IDs (ex: vieux IDs Graph Outlook).
      try {
        const stored = localStorage.getItem(VISIBLE_CALENDARS_KEY);
        if (stored) {
          const storedIds: string[] = JSON.parse(stored);
          const validIds = storedIds.filter(id => ids.includes(id));
          if (validIds.length > 0) {
            // Toujours inclure le calendrier principal pour éviter qu'il soit masqué par erreur
            if (primaryId && !validIds.includes(primaryId)) {
              validIds.push(primaryId);
              try { localStorage.setItem(VISIBLE_CALENDARS_KEY, JSON.stringify(validIds)); } catch { /* noop */ }
            }
            return new Set(validIds); // préférences valides restaurées
          }
        }
      } catch { /* noop */ }
      // Pas de préférences valides → tout afficher et sauvegarder
      try { localStorage.setItem(VISIBLE_CALENDARS_KEY, JSON.stringify(ids)); } catch { /* noop */ }
      return new Set(ids);
    });
    if (cals) {
      calendarsRef.current = cals;
      // Derive provider from calendar data (google_calendar → gmail, outlook → outlook)
      const primaryCal = cals.find(c => c.isPrimary) || cals[0];
      if (primaryCal?.providerSource?.includes('google')) {
        setCalendarProvider('gmail');
      } else if (primaryCal?.providerSource?.includes('outlook') || primaryCal?.providerSource?.includes('microsoft')) {
        setCalendarProvider('outlook');
      }
      reloadLabelsAndColors();
    }
  }, [reloadLabelsAndColors]);

  const handleToggleTz2Holidays = useCallback(() => {
    setShowTz2Holidays(prev => {
      const next = !prev;
      try { localStorage.setItem(TZ2_HOLIDAYS_STORAGE_KEY, String(next)); } catch { /* noop */ }
      return next;
    });
  }, []);

  const handleTogglePrimaryHolidays = useCallback(() => {
    setShowPrimaryHolidays(prev => {
      const next = !prev;
      try { localStorage.setItem(PRIMARY_HOLIDAYS_STORAGE_KEY, String(next)); } catch { /* noop */ }
      return next;
    });
  }, []);

  // Détection IP au montage — corrige le fuseau imprécis sur Windows (America/New_York au lieu d'America/Montreal)
  // BUG-J003 fix: use AbortController so StrictMode's double-mount doesn't leave a
  // stale promise that updates state after the first mount has already been cleaned up.
  useEffect(() => {
    const controller = new AbortController();
    apiClient.detectRegion().then(res => {
      if (controller.signal.aborted) return;
      if (res.detected) {
        if (res.timezone) setDetectedTz(res.timezone);
        if (res.country) setDetectedCountry(res.country);
        if (res.region) setDetectedRegion(res.region);
      }
    }).catch(() => { /* noop — fallback sur LOCAL_TZ_FALLBACK */ });
    return () => controller.abort();
  }, []);

  const handleNavigateToDate = useCallback((date: Date) => {
    setCurrentWeekStart(getViewStart(date, viewMode));
    hasScrolledRef.current = false;
  }, [viewMode]);

  // Click on slot → open popover (or start drag-to-create)
  const handleSlotMouseDown = useCallback((e: React.MouseEvent, date: Date, hour: number) => {
    if (e.button !== 0) return; // Left click only
    // Stop propagation to prevent the mousedown (and subsequent click) from bubbling
    // to parent elements that might navigate away from the calendar (BUG-H004).
    e.stopPropagation();
    const el = e.currentTarget as HTMLElement;
    const column = el.closest('.calendar-day-column') as HTMLElement;
    if (!column) return;

    // Compute sub-hour minute from click position
    const rect = el.getBoundingClientRect();
    const yInSlot = e.clientY - rect.top;
    const startMinute = yInSlot >= 24 ? 30 : 0;

    dragCreateRef.current = {
      date,
      startHour: hour,
      startMinute,
      el: column,
      ghostEl: null,
    };

    const startY = e.clientY;

    const onMouseMove = (ev: MouseEvent) => {
      if (!dragCreateRef.current) return;
      const deltaY = ev.clientY - startY;
      if (Math.abs(deltaY) < 8 && !dragCreateRef.current.ghostEl) return; // Dead zone

      ev.preventDefault();
      document.body.style.cursor = 'crosshair';
      document.body.style.userSelect = 'none';

      // Create ghost element if not yet
      if (!dragCreateRef.current.ghostEl) {
        const ghost = document.createElement('div');
        ghost.className = 'calendar-ghost-event';
        dragCreateRef.current.el.appendChild(ghost);
        dragCreateRef.current.ghostEl = ghost;
      }

      const ghost = dragCreateRef.current.ghostEl;
      const { startHour: sh, startMinute: sm } = dragCreateRef.current;
      const topPx = (sh - HOUR_START) * PX_PER_HOUR + (sm / 60) * PX_PER_HOUR;

      // Calculate end position from mouse
      // getBoundingClientRect() already accounts for scroll — do NOT add scrollTop
      const colRect = dragCreateRef.current.el.getBoundingClientRect();
      const yInCol = ev.clientY - colRect.top;
      // Snap to 15min
      const snappedEnd = Math.round((yInCol / PX_PER_HOUR) * 60 / 15) * 15;
      const startMinutes = (sh - HOUR_START) * 60 + sm;
      const heightMinutes = Math.max(15, snappedEnd - startMinutes);
      const heightPx = (heightMinutes / 60) * PX_PER_HOUR;

      ghost.style.top = `${topPx}px`;
      ghost.style.height = `${Math.max(12, heightPx)}px`;

      const endH = Math.floor((startMinutes + heightMinutes) / 60) + HOUR_START;
      const endM = (startMinutes + heightMinutes) % 60;
      ghost.textContent = `${sh}:${String(sm).padStart(2, '0')} – ${endH}:${String(endM).padStart(2, '0')}`;
    };

    const onMouseUp = (ev: MouseEvent) => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';

      if (!dragCreateRef.current) return;
      const { ghostEl, startHour: sh, startMinute: sm, date: d, el: col } = dragCreateRef.current;

      if (ghostEl) {
        // Drag-to-create completed
        // getBoundingClientRect() already accounts for scroll — do NOT add scrollTop
        const colRect = col.getBoundingClientRect();
        const yInCol = ev.clientY - colRect.top;
        const snappedEnd = Math.round((yInCol / PX_PER_HOUR) * 60 / 15) * 15;
        const startMinutes = (sh - HOUR_START) * 60 + sm;
        const heightMinutes = Math.max(15, snappedEnd - startMinutes);
        const endH = Math.floor((startMinutes + heightMinutes) / 60) + HOUR_START;
        const endM = (startMinutes + heightMinutes) % 60;

        ghostEl.remove();
        dragCreateRef.current = null;

        // Open popover with calculated times
        const anchorRect = col.getBoundingClientRect();
        setQuickEvent({ date: d, hour: sh, endHour: endH, endMinute: endM, anchorRect });
      } else {
        // Simple click — open popover at clicked hour
        dragCreateRef.current = null;
        const anchorRect = rect;
        setQuickEvent({ date, hour, anchorRect });
      }
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  }, []);

  // ── Resize events ──
  const handleEventResizeStart = useCallback((e: React.MouseEvent, event: CalendarEvent, edge: 'top' | 'bottom' = 'bottom') => {
    e.stopPropagation();
    e.preventDefault();
    if (event.calendarId === '__deep_work__' || event.calendarId === '__work_block__') return;

    // Flag immédiatement comme drag pour bloquer le click (qui ouvrirait le modal)
    didDragRef.current = true;

    const el = (e.currentTarget as HTMLElement).parentElement as HTMLElement;
    const origHeight = parseFloat(el.style.height || '48');
    const origTop = parseFloat(el.style.top || '0');

    const startScrollTop = weekBodyRef.current?.scrollTop || 0;
    resizeRef.current = { event, startY: e.clientY, origHeight, origTop, el, startScrollTop, edge };
    el.classList.add('calendar-event--dragging');
    el.style.transition = 'none';
    document.body.style.cursor = 'ns-resize';
    document.body.style.userSelect = 'none';

    const onMouseMove = (ev: MouseEvent) => {
      if (!resizeRef.current) return;
      ev.preventDefault();
      const scrollDelta = (weekBodyRef.current?.scrollTop || 0) - resizeRef.current.startScrollTop;
      const deltaY = ev.clientY - resizeRef.current.startY + scrollDelta;
      const snapped = Math.round(deltaY / 12) * 12;
      if (resizeRef.current.edge === 'bottom') {
        const newHeight = Math.max(12, resizeRef.current.origHeight + snapped);
        resizeRef.current.el.style.height = `${newHeight}px`;
      } else {
        const maxDelta = resizeRef.current.origHeight - 12;
        const clampedDelta = Math.min(maxDelta, Math.max(-resizeRef.current.origTop, snapped));
        resizeRef.current.el.style.top = `${resizeRef.current.origTop + clampedDelta}px`;
        resizeRef.current.el.style.height = `${resizeRef.current.origHeight - clampedDelta}px`;
      }
    };

    const onMouseUp = async (ev: MouseEvent) => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';

      if (!resizeRef.current) return;
      const { event: resizeEvent, startY, el: resizeEl, startScrollTop: sst, edge: resizeEdge, origHeight: oh, origTop: ot } = resizeRef.current;
      const scrollDelta = (weekBodyRef.current?.scrollTop || 0) - sst;
      const deltaY = ev.clientY - startY + scrollDelta;
      let snappedDelta = Math.round(deltaY / 12) * 12;

      resizeEl.classList.remove('calendar-event--dragging');
      resizeEl.style.transition = '';
      resizeRef.current = null;

      if (Math.abs(snappedDelta) < 12) return;

      if (resizeEdge === 'bottom') {
        const deltaMinutes = (snappedDelta / PX_PER_HOUR) * 60;
        const origEnd = new Date(resizeEvent.end);
        const newEnd = new Date(origEnd.getTime() + deltaMinutes * 60_000);

        if (newEnd <= new Date(resizeEvent.start)) return;

        setEvents(prev => prev.map(ev =>
          ev.id === resizeEvent.id ? { ...ev, end: newEnd.toISOString() } : ev
        ));

        try {
          await apiClient.updateCalendarEvent(resizeEvent.id, {
            title: resizeEvent.title,
            start_time: resizeEvent.start,
            end_time: newEnd.toISOString(),
            description: resizeEvent.description,
            location: resizeEvent.location,
            calendar_id: resizeEvent.calendarId,
          });
          setTimeout(() => fetchEventsRef.current(), 2000);
        } catch (err) {
          // Audit Toast Site 4 (2026-05-12): rollback the optimistic resize
          // AND tell the user — silent revert looked like a flaky UI.
          console.error('[Calendar] Failed to resize event:', err);
          setEvents(prev => prev.map(ev =>
            ev.id === resizeEvent.id ? { ...ev, end: resizeEvent.end } : ev
          ));
          window.dispatchEvent(new CustomEvent('agentys:toast', {
            detail: {
              message: calendarWriteErrorMessage(err, tc, 'toasts.calendar_event_resize_failed'),
              type: 'error',
              duration: 6000,
            },
          }));
        }
      } else {
        const maxDelta = oh - 12;
        if (snappedDelta > maxDelta) snappedDelta = maxDelta;
        if (snappedDelta < -ot) snappedDelta = -ot;
        const deltaMinutes = (snappedDelta / PX_PER_HOUR) * 60;
        const origStart = new Date(resizeEvent.start);
        const newStart = new Date(origStart.getTime() + deltaMinutes * 60_000);

        if (newStart >= new Date(resizeEvent.end)) return;

        setEvents(prev => prev.map(ev =>
          ev.id === resizeEvent.id ? { ...ev, start: newStart.toISOString() } : ev
        ));

        try {
          await apiClient.updateCalendarEvent(resizeEvent.id, {
            title: resizeEvent.title,
            start_time: newStart.toISOString(),
            end_time: resizeEvent.end,
            description: resizeEvent.description,
            location: resizeEvent.location,
            calendar_id: resizeEvent.calendarId,
          });
          setTimeout(() => fetchEventsRef.current(), 2000);
        } catch (err) {
          // Audit Toast Site 4 (2026-05-12): same as the bottom-resize path.
          console.error('[Calendar] Failed to resize event (top):', err);
          setEvents(prev => prev.map(ev =>
            ev.id === resizeEvent.id ? { ...ev, start: resizeEvent.start } : ev
          ));
          window.dispatchEvent(new CustomEvent('agentys:toast', {
            detail: {
              message: calendarWriteErrorMessage(err, tc, 'toasts.calendar_event_resize_failed'),
              type: 'error',
              duration: 6000,
            },
          }));
        }
      }
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  }, []);

  // ── Drag & drop events to change time ──
  // Pure DOM manipulation during drag — no React state to avoid re-renders that kill the ref
  const dragRef = useRef<{
    event: CalendarEvent
    startY: number
    startX: number
    origTop: number
    el: HTMLElement
    origColIndex: number
    curColIndex: number
    startScrollTop: number
  } | null>(null)

  // Guard: true when last mousedown led to an actual drag (so onClick should not open modal)
  const didDragRef = useRef(false)

  const handleEventDragStart = useCallback((e: React.MouseEvent, event: CalendarEvent) => {
    // Only real calendar events (not virtual slots)
    if (event.calendarId === '__deep_work__' || event.calendarId === '__work_block__') return
    // Followups ont des IDs synthétiques (followup_*) qui ne correspondent à aucun
    // event Google — un PATCH déclencherait un 404 "Event not found".
    if (event.event_type === 'followup') return
    // Calendriers read-only (Holidays, Birthdays, calendriers partagés en lecture):
    // empêche le drag — sinon Google renvoie 403/404 et l'utilisateur voit un toast d'erreur.
    const cal = calendarsRef.current.find(c => c.id === event.calendarId)
    if (cal && cal.canEdit === false) return
    // Prevent slot's mousedown from firing (avoids opening new-event form on event click)
    e.stopPropagation();

    const el = e.currentTarget as HTMLElement
    const origTop = parseFloat(el.style.top || '0')

    // Determine which column index this event lives in
    const cols = weekBodyRef.current?.querySelectorAll('.calendar-day-column')
    let origColIndex = 0
    if (cols) {
      const colEl = el.closest('.calendar-day-column')
      cols.forEach((c, i) => { if (c === colEl) origColIndex = i })
    }

    const startScrollTop = weekBodyRef.current?.scrollTop || 0
    dragRef.current = { event, startY: e.clientY, startX: e.clientX, origTop, el, origColIndex, curColIndex: origColIndex, startScrollTop }

    // Add drag class directly on DOM (no React state → no re-render → el stays valid)
    el.classList.add('calendar-event--dragging')
    // Kill CSS transition so transform changes are instant
    el.style.transition = 'none'
    document.body.style.cursor = 'grabbing'
    // Prevent text selection while dragging
    document.body.style.userSelect = 'none'

    const onMouseMove = (ev: MouseEvent) => {
      if (!dragRef.current) return
      ev.preventDefault()
      const { startY, origTop, el: dragEl, origColIndex: origIdx, startScrollTop: sst } = dragRef.current

      // Vertical: snap to 15min increments (48px/hr → 12px per 15min)
      // Include scroll delta so scrolling during drag doesn't misplace the event
      const scrollDelta = (weekBodyRef.current?.scrollTop || 0) - sst
      const deltaY = ev.clientY - startY + scrollDelta
      const snappedDelta = Math.round(deltaY / 12) * 12
      const clampedDelta = Math.max(-origTop, snappedDelta)

      // Horizontal: detect target column by cursor position
      let targetColIndex = origIdx
      const currentCols = weekBodyRef.current?.querySelectorAll('.calendar-day-column')
      if (currentCols) {
        currentCols.forEach((col, i) => {
          const rect = col.getBoundingClientRect()
          if (ev.clientX >= rect.left && ev.clientX < rect.right) targetColIndex = i
        })
      }
      dragRef.current.curColIndex = targetColIndex

      // Compute horizontal offset between original column and target column
      let colTranslateX = 0
      if (currentCols && targetColIndex !== origIdx) {
        const origRect = currentCols[origIdx].getBoundingClientRect()
        const targetRect = currentCols[targetColIndex].getBoundingClientRect()
        colTranslateX = targetRect.left - origRect.left
      }

      dragEl.style.transform = `translate(${colTranslateX}px, ${clampedDelta}px)`
    }

    const onMouseUp = async (ev: MouseEvent) => {
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''

      if (!dragRef.current) return
      const { event: dragEvent, startY, el: dragEl, origColIndex: origIdx, curColIndex: targetIdx, startScrollTop: sst } = dragRef.current
      const scrollDelta = (weekBodyRef.current?.scrollTop || 0) - sst
      const deltaY = ev.clientY - startY + scrollDelta
      const snappedDelta = Math.round(deltaY / 12) * 12

      // Clean up DOM classes/styles
      dragEl.classList.remove('calendar-event--dragging')
      dragEl.style.transition = ''
      dragEl.style.transform = ''
      dragRef.current = null

      // If barely moved and same column, treat as click — let onClick handler open the detail
      didDragRef.current = false;
      if (Math.abs(snappedDelta) < 12 && targetIdx === origIdx) {
        return // onClick will fire and open the modal
      }
      // Real drag: mark so onClick doesn't also open modal
      didDragRef.current = true;

      // Compute new start/end times (vertical delta + cross-day delta)
      const deltaMinutes = (snappedDelta / PX_PER_HOUR) * 60
      const deltaColDays = targetIdx - origIdx
      const origStart = new Date(dragEvent.start)
      const origEnd = new Date(dragEvent.end)
      const newStart = new Date(origStart.getTime() + deltaColDays * 86_400_000 + deltaMinutes * 60_000)
      const newEnd = new Date(origEnd.getTime() + deltaColDays * 86_400_000 + deltaMinutes * 60_000)

      // Optimistic local update
      setEvents(prev => prev.map(ev =>
        ev.id === dragEvent.id
          ? { ...ev, start: newStart.toISOString(), end: newEnd.toISOString() }
          : ev
      ))

      // Persist via API
      try {
        await apiClient.updateCalendarEvent(dragEvent.id, {
          title: dragEvent.title,
          start_time: newStart.toISOString(),
          end_time: newEnd.toISOString(),
          description: dragEvent.description,
          location: dragEvent.location,
          calendar_id: dragEvent.calendarId,
        })
        // Refresh after 2s to sync with server (fetchEventsRef is stable across renders)
        setTimeout(() => fetchEventsRef.current(), 2000)
      } catch (err) {
        // Audit 2026-05-27: surface a localized message, not the raw backend
        // error code. A non-organizer move now returns `calendar_event_forbidden`
        // → "only the organizer can reschedule", instead of the misleading
        // `missing_calendar_scope` shown verbatim before.
        console.error('[Calendar] Failed to move event:', err)
        setCreateErrorToast(calendarWriteErrorMessage(err, tc, 'toasts.calendar_event_update_failed'))
        setTimeout(() => setCreateErrorToast(null), 5000)
        // Rollback
        setEvents(prev => prev.map(ev =>
          ev.id === dragEvent.id
            ? { ...ev, start: dragEvent.start, end: dragEvent.end }
            : ev
        ))
      }
    }

    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
  }, []);

  // Calculate visible dates based on viewMode
  const weekDates = useMemo(() => {
    return Array.from({ length: viewMode }, (_, i) => {
      const d = new Date(currentWeekStart);
      d.setDate(d.getDate() + i);
      return d;
    });
  }, [currentWeekStart, viewMode]);

  // DST (changement d'heure) — calcul local, sans appel API
  const localTz = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, []);
  const dstTransitions = useMemo(() => {
    const result = new Map<string, { diff: number; label: string }>();
    findDstTransitions(localTz, weekDates).forEach((diff, date) => {
      result.set(date, { diff, label: getTzLabel(localTz) });
    });
    if (secondaryTz && secondaryTz !== localTz) {
      findDstTransitions(secondaryTz, weekDates).forEach((diff, date) => {
        if (!result.has(date)) result.set(date, { diff, label: getTzLabel(secondaryTz) });
      });
    }
    return result;
  }, [weekDates, localTz, secondaryTz]);

  // Scroll to current time on first load
  useEffect(() => {
    if (!loading && !hasScrolledRef.current && weekBodyRef.current) {
      const scrollTarget = Math.max(0, nowPosition - 120); // 120px above current time
      weekBodyRef.current.scrollTop = scrollTarget;
      hasScrolledRef.current = true;
    }
  }, [loading, nowPosition]);

  // Navigation handlers
  const goToPreviousPeriod = () => {
    const prev = new Date(currentWeekStart);
    prev.setDate(prev.getDate() - viewMode);
    setCurrentWeekStart(prev);
  };

  const goToNextPeriod = () => {
    const next = new Date(currentWeekStart);
    next.setDate(next.getDate() + viewMode);
    setCurrentWeekStart(next);
  };

  const goToToday = () => {
    setCurrentWeekStart(getViewStart(new Date(), viewMode));
    hasScrolledRef.current = false;
  };

  const handleSetViewMode = useCallback((mode: ViewMode) => {
    setViewMode(mode);
    try { localStorage.setItem(VIEW_MODE_KEY, String(mode)); } catch { /* noop */ }
    // Re-anchor the view start
    setCurrentWeekStart(prev => getViewStart(prev, mode));
  }, []);

  // ── Month/Year pickers ──
  const closeAllPickers = useCallback(() => {
    setMonthPickerOpen(false);
    setYearPickerOpen(false);
  }, []);

  const openMonthPicker = () => {
    if (monthBtnRef.current) {
      const r = monthBtnRef.current.getBoundingClientRect();
      const dropdownW = 220;
      const left = r.left + dropdownW > window.innerWidth ? r.right - dropdownW : r.left;
      setMonthPickerPos({ top: r.bottom + 4, left });
    }
    setYearPickerOpen(false);
    setMonthPickerOpen(v => !v);
  };

  const openYearPicker = () => {
    if (yearBtnRef.current) {
      const r = yearBtnRef.current.getBoundingClientRect();
      const dropdownW = 100;
      const left = r.left + dropdownW > window.innerWidth ? r.right - dropdownW : r.left;
      setYearPickerPos({ top: r.bottom + 4, left });
    }
    setMonthPickerOpen(false);
    setYearPickerOpen(v => !v);
  };

  const goToMonthYear = useCallback((month: number, year: number) => {
    const target = new Date(year, month, 1);
    setCurrentWeekStart(getViewStart(target, viewMode));
    closeAllPickers();
  }, [viewMode, closeAllPickers]);

  // ── Keyboard shortcuts ──
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && selectedEvent) {
        e.preventDefault();
        setSelectedEvent(null);
        setConfirmDeleteEventId(null);
        return;
      }

      // Skip if typing in an input/textarea/contenteditable
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (e.target as HTMLElement)?.isContentEditable) return;
      // Raccourci 'B' / 'C' : création rapide d'événement — autorisé même quand un événement
      // est sélectionné (ferme la modale puis ouvre le popover de création).
      const isCreateShortcut = e.key === 'b' || e.key === 'B' || e.key === 'c' || e.key === 'C';
      if (isCreateShortcut && selectedEvent) {
        e.preventDefault();
        setSelectedEvent(null); // Fermer la modale de détail
        // Le popover de création sera ouvert par le case 'b'/'c' ci-dessous
        // après un tick pour laisser React mettre à jour l'état
        setTimeout(() => {
          const now = new Date();
          const todayCol = weekBodyRef.current?.querySelector('.calendar-day-column.is-today');
          const col = todayCol ?? weekBodyRef.current?.querySelector('.calendar-day-column');
          if (col) {
            const rect = col.getBoundingClientRect();
            const date = todayCol ? now : (weekDates[0] ?? now);
            setQuickEvent({ date, hour: now.getHours(), anchorRect: rect });
          } else if (weekBodyRef.current) {
            // Fallback: use body rect if columns not yet in DOM
            const rect = weekBodyRef.current.getBoundingClientRect();
            setQuickEvent({ date: weekDates[0] ?? now, hour: now.getHours(), anchorRect: rect });
          } else {
            const cx = window.innerWidth / 2;
            const cy = window.innerHeight / 2;
            const fakeRect = new DOMRect(cx, cy - 100, 0, 200);
            setQuickEvent({ date: weekDates[0] ?? now, hour: now.getHours(), anchorRect: fakeRect });
          }
        }, 0);
        return;
      }

      // Skip if popover/modal is open — also consume the event to block key-repeat
      // side-effects (e.g. 'B' repeating into the title input during the 80ms focus delay)
      if (quickEvent || selectedEvent) { e.preventDefault(); return; }

      switch (e.key) {
        case 't':
        case 'T':
          e.preventDefault();
          goToToday();
          break;
        case 'ArrowLeft':
          e.preventDefault();
          goToPreviousPeriod();
          break;
        case 'ArrowRight':
          e.preventDefault();
          goToNextPeriod();
          break;
        case '1':
          e.preventDefault();
          handleSetViewMode(1);
          break;
        case '3':
          e.preventDefault();
          handleSetViewMode(3);
          break;
        case '7':
          e.preventDefault();
          handleSetViewMode(7);
          break;
        case 'c':
        case 'C': {
          e.preventDefault();
          // Open create popover at current hour on today's column
          const now = new Date();
          const todayCol = weekBodyRef.current?.querySelector('.calendar-day-column.is-today');
          if (todayCol) {
            const rect = todayCol.getBoundingClientRect();
            setQuickEvent({ date: now, hour: now.getHours(), anchorRect: rect });
          }
          break;
        }
        case '=':
          e.preventDefault();
          goToNextPeriod();
          break;
        case '-':
          e.preventDefault();
          goToPreviousPeriod();
          break;
        case 'b':
        case 'B': {
          e.preventDefault();
          e.stopPropagation();
          // BUG-X001 fix (2026-05-17): if the popover is already open, ignore.
          // Rapid double-press of B (mount → unmount → mount within a few ms)
          // was tripping a React Hooks "Should have a queue" error inside the
          // popover's effect chain on the second mount. Treat the second press
          // as a no-op — the popover is already there.
          if (quickEvent) return;
          const now = new Date();
          const todayCol = weekBodyRef.current?.querySelector('.calendar-day-column.is-today');
          if (todayCol) {
            const rect = todayCol.getBoundingClientRect();
            setQuickEvent({ date: now, hour: now.getHours(), anchorRect: rect });
          } else {
            // Today not visible — anchor to first visible column, use that day's date
            const firstCol = weekBodyRef.current?.querySelector('.calendar-day-column');
            if (firstCol) {
              const rect = firstCol.getBoundingClientRect();
              setQuickEvent({ date: weekDates[0] ?? now, hour: now.getHours(), anchorRect: rect });
            } else if (weekBodyRef.current) {
              // Fallback: calendar body exists but columns not yet in DOM — use the body rect
              // (BUG-H003: silent failure when querySelector finds nothing)
              const rect = weekBodyRef.current.getBoundingClientRect();
              setQuickEvent({ date: weekDates[0] ?? now, hour: now.getHours(), anchorRect: rect });
            } else {
              const cx = window.innerWidth / 2;
              const cy = window.innerHeight / 2;
              const fakeRect = new DOMRect(cx, cy - 100, 0, 200);
              setQuickEvent({ date: weekDates[0] ?? now, hour: now.getHours(), anchorRect: fakeRect });
            }
          }
          break;
        }
        case 'Escape':
          if (monthPickerOpen || yearPickerOpen) {
            e.preventDefault();
            closeAllPickers();
            return;
          }
          break;
      }
    };
    document.addEventListener('keydown', handler, true);
    return () => document.removeEventListener('keydown', handler, true);
  }, [quickEvent, selectedEvent, goToToday, goToPreviousPeriod, goToNextPeriod, handleSetViewMode, monthPickerOpen, yearPickerOpen, closeAllPickers, weekDates]);

  useEffect(() => {
    if (selectedEvent) {
      requestAnimationFrame(() => {
        eventModalRef.current?.focus();
      });
    }
  }, [selectedEvent]);

  // External "create event" trigger (from sidebar "+" button)
  const createTriggerRef = useRef(createEventTrigger);
  useEffect(() => {
    if (createEventTrigger > 0 && createEventTrigger !== createTriggerRef.current) {
      createTriggerRef.current = createEventTrigger;
      const now = new Date();
      // Anchor to the calendar main area center
      const calMain = document.querySelector('.calendar-main');
      if (calMain) {
        const rect = calMain.getBoundingClientRect();
        const fakeRect = new DOMRect(rect.left + 60, rect.top + 40, 0, 0);
        setQuickEvent({ date: now, hour: now.getHours(), anchorRect: fakeRect });
      }
    }
  }, [createEventTrigger]);


  // Close month picker on outside click
  useEffect(() => {
    if (!monthPickerOpen) return;
    const handler = (e: MouseEvent) => {
      if (
        monthPickerRef.current && !monthPickerRef.current.contains(e.target as Node) &&
        monthBtnRef.current && !monthBtnRef.current.contains(e.target as Node)
      ) setMonthPickerOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [monthPickerOpen]);

  // Close year picker on outside click
  useEffect(() => {
    if (!yearPickerOpen) return;
    const handler = (e: MouseEvent) => {
      if (
        yearPickerRef.current && !yearPickerRef.current.contains(e.target as Node) &&
        yearBtnRef.current && !yearBtnRef.current.contains(e.target as Node)
      ) setYearPickerOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [yearPickerOpen]);

  // Auto-scroll year picker to current year
  useEffect(() => {
    if (!yearPickerOpen || !yearPickerRef.current) return;
    const active = yearPickerRef.current.querySelector('.cal-picker-active');
    active?.scrollIntoView({ block: 'center', behavior: 'instant' });
  }, [yearPickerOpen]);

  // Fetch events
  const fetchEvents = useCallback(async () => {
    // Skip fetch while user is dragging — re-render would destroy DOM refs
    if (dragRef.current || dragCreateRef.current) return;

    // Guard against React 18 StrictMode double-invocation: if a fetch is already in flight,
    // skip. StrictMode unmounts+remounts synchronously (µs) while API calls take 100 ms+,
    // so this ref is still true on the spurious second call. Legitimate re-fetches (week/
    // account changes) always wait for the previous fetch to finish (finally clears the ref).
    if (fetchInProgressRef.current) return;
    fetchInProgressRef.current = true;

    // Assign a unique ID to this fetch — any response from a previous fetch will be discarded
    const myFetchId = ++fetchIdRef.current;

    // Detect week navigation vs same-week refresh
    const weekKey = currentWeekStart.getTime();
    const isWeekChange = fetchingWeekRef.current !== weekKey;
    fetchingWeekRef.current = weekKey;

    // On week navigation: keep only events in the new week's range + temp events.
    // setEvents([]) was too aggressive — it wiped optimistic events just created
    // for a different week before Google/Outlook had time to propagate them.
    if (isWeekChange && initialLoadDoneRef.current) {
      const weekEnd = new Date(currentWeekStart);
      weekEnd.setDate(weekEnd.getDate() + viewMode);
      setEvents(prev => prev.filter(e => {
        if (!e.id || e.id.startsWith('temp-')) return true;
        const evStart = new Date(e.start);
        return evStart >= currentWeekStart && evStart < weekEnd;
      }));
    }

    // Only show full-page spinner on initial load, not on refreshes
    if (!initialLoadDoneRef.current) {
      setLoading(true);
    }
    setError(null);
    setNoAccount(false);
    setNeedsReauth(false);

    try {
      // Skip pre-flight status check — go directly to events.
      const periodEnd = new Date(currentWeekStart);
      periodEnd.setDate(periodEnd.getDate() + viewMode);

      let response: CalendarEventsResponse;
      try {
        response = await apiClient.getCalendarEvents(
          formatDateForApi(currentWeekStart),
          formatDateForApi(periodEnd),
          undefined,  // calendarId
          accountId,  // pass current account
          undefined,  // limit
          allCalendarIds.length > 0 ? allCalendarIds : undefined,
        );
      } catch (firstErr) {
        // If request fails with account_id, retry without it — backend will use active account
        if (accountId && firstErr instanceof ApiError && firstErr.status === 400) {
          console.warn('[CalendarView] Retrying without account_id');
          response = await apiClient.getCalendarEvents(
            formatDateForApi(currentWeekStart),
            formatDateForApi(periodEnd),
            undefined,
            undefined,
            undefined,
            allCalendarIds.length > 0 ? allCalendarIds : undefined,
          );
        } else {
          throw firstErr;
        }
      }

      // Discard stale response — a newer fetchEvents() call was launched while we were waiting
      if (myFetchId !== fetchIdRef.current) return;

      if (response.error) {
        if (response.error === 'No OAuth account found' ||
            response.error === 'Calendar not available for this account' ||
            response.error === 'Calendar not supported' ||
            response.error.includes('No account')) {
          setNoAccount(true);
          setEvents([]);
        } else {
          setError(response.message || response.error);
          // Don't clear events on non-fatal errors — preserve optimistic updates
        }
      } else {
        const fresh = response.events || [];

        // Deduplicate fresh events: same (title, start, end) can appear when React StrictMode
        // double-invokes effects or when the provider has propagation duplicates.
        const seenKeys = new Set<string>();
        const deduped = fresh.filter(e => {
          const key = `${e.title}|${e.start}|${e.end ?? ''}`;
          if (seenKeys.has(key)) return false;
          seenKeys.add(key);
          return true;
        });
        // Merge: keep optimistic events that the server hasn't returned yet.
        // Limit kept to the current week range to avoid cross-week contamination.
        const periodEnd = new Date(currentWeekStart);
        periodEnd.setDate(periodEnd.getDate() + viewMode);
        setEvents(prev => {
          const freshIds = new Set(deduped.map(e => e.id));
          // Content keys of the fresh server rows — used to drop an optimistic
          // temp-/recent twin once the server has ALREADY returned the real-id
          // version of the same meeting. Without this the same meeting rendered
          // twice (temp- + real-id) until the next refresh (chaos audit 2026-06-02).
          const freshContentKeys = new Set(deduped.map(e => `${e.title}|${e.start}|${e.end ?? ''}`));
          const kept = prev.filter(e => {
            if (freshIds.has(e.id)) return false;
            const contentKey = `${e.title}|${e.start}|${e.end ?? ''}`;
            // Keep temp (optimistic) events — UNLESS a content-equivalent real
            // row already arrived from the server (then the real one wins).
            if (!e.id || e.id.startsWith('temp-')) return !freshContentKeys.has(contentKey);
            // Grace period: keep recently-created events (≤30s) even if the
            // server hasn't propagated yet — same content-twin guard.
            const createdAt = recentlyCreatedRef.current.get(e.id);
            if (createdAt && Date.now() - createdAt < 30_000) return !freshContentKeys.has(contentKey);
            // Only keep real events within the current fetch range
            const evStart = new Date(e.start);
            return evStart >= currentWeekStart && evStart < periodEnd;
          });
          return [...deduped, ...kept];
        });
        // Sync selectedEvent with fresh data so meetLink / organizer appear without re-click
        setSelectedEvent(prev => {
          if (!prev) return null;
          // Exact match first; fall back to title+start match for optimistic (temp-id) events
          return fresh.find(e => e.id === prev.id)
            ?? (prev.id.startsWith('temp-') ? fresh.find(e => e.title === prev.title && e.start === prev.start) ?? prev : prev);
        });
      }
    } catch (err: unknown) {
      // Discard stale error — a newer fetchEvents() call was launched
      if (myFetchId !== fetchIdRef.current) return;

      console.error('Calendar fetch error:', err, 'type:', typeof err, 'status:', (err as {status?: number})?.status, 'message:', (err as Error)?.message);

      // Detect 403 scope error from API
      if (err instanceof ApiError && err.status === 403) {
        setNeedsReauth(true);
        setEvents([]);
        return;
      }

      const errorMessage = err instanceof Error ? err.message : String(err);
      if (errorMessage.includes('Calendar not available') ||
          errorMessage.includes('Calendar not supported') ||
          errorMessage.includes('No OAuth account') ||
          errorMessage.includes('No account')) {
        setNoAccount(true);
        setEvents([]);
      } else {
        // Show actual error for debugging — not just i18n key
        setError(errorMessage || t('error_load'));
        // Don't clear events on transient errors — preserve optimistic updates
      }
    } finally {
      fetchInProgressRef.current = false; // allow next legitimate fetch
      if (myFetchId === fetchIdRef.current) {
        setLoading(false);
        initialLoadDoneRef.current = true;
        // Purge grace period entries older than 30s
        const _now = Date.now();
        recentlyCreatedRef.current.forEach((ts, id) => {
          if (_now - ts >= 30_000) recentlyCreatedRef.current.delete(id);
        });
      }
    }
  }, [currentWeekStart, viewMode, accountId, allCalendarIds]);

  // Trigger fetch on mount and when key data params change
  // Note: Don't add fetchEvents to deps array since it's recreated when these deps change
  // This avoids the pattern where useEffect([fetchEvents]) triggers constantly
  // Instead, the fetchInProgressRef guard at line 1150 handles StrictMode double-invoke
  useEffect(() => {
    fetchEvents();
  }, [currentWeekStart, viewMode, accountId, allCalendarIds]);

  // Stable ref to always hold the latest fetchEvents — used in setTimeout callbacks
  // to avoid stale closures capturing an outdated currentWeekStart.
  const fetchEventsRef = useRef(fetchEvents);
  useEffect(() => { fetchEventsRef.current = fetchEvents; }, [fetchEvents]);

  useEffect(() => {
    try { sessionStorage.setItem(WEEK_START_KEY, currentWeekStart.toISOString()); } catch { /* noop */ }
  }, [currentWeekStart]);

  // Refresh when an absence event is created/updated/deleted via auto-reply settings
  useEffect(() => {
    const handler = () => fetchEvents();
    window.addEventListener('agentys:calendar-synced', handler);
    return () => window.removeEventListener('agentys:calendar-synced', handler);
  }, [fetchEvents]);

  // Cleanup orphaned "Absence" calendar events when auto-reply is disabled
  useEffect(() => {
    let cancelled = false;
    import('../hooks/useSettingsCache').then(({ fetchSettingsCached }) => {
      fetchSettingsCached(accountId ? Number(accountId) : undefined).then(settings => {
        if (cancelled || settings.auto_reply_enabled) return;
        // Auto-reply is OFF — delete any leftover "Absence" events
        const now = new Date();
        const start = new Date(now); start.setMonth(start.getMonth() - 1);
        const end = new Date(now); end.setMonth(end.getMonth() + 6);
        apiClient.getCalendarEvents(
          start.toISOString(), end.toISOString(), undefined, accountId, 100
        ).then(async res => {
          if (cancelled) return;
          const orphans = (res.events || []).filter(e => e.title === 'Absence' && e.id);
          for (const o of orphans) {
            try {
              await apiClient.deleteCalendarEvent(o.id, accountId);
            } catch { /* best-effort */ }
          }
          if (orphans.length > 0 && !cancelled) {
            // Refresh calendar after deletions propagate
            setTimeout(() => { if (!cancelled) fetchEventsRef.current(); }, 2000);
          }
        }).catch(err => {
          // FE-08: was a silent empty catch. Phantom "Absence" events left on the
          // provider calendar are invisible to the user; at least log for ops.
          console.warn('[CalendarView] orphan Absence cleanup failed:', err);
        });
      }).catch(() => {});
    });
    return () => { cancelled = true; };
   
  }, [accountId]);

  const handleQuickEventSave = useCallback(async (data: {
    title: string; startTime: string; endTime: string; attendees: string[];
    location?: string; description?: string; reminders?: number[];
    recurrence?: string; allDay?: boolean; conference?: boolean; colorId?: string;
  }) => {
    // Optimistic: close popover and show event immediately
    setQuickEvent(null);

    const tempId = `temp-${Date.now()}`;
    const optimisticEvent: CalendarEvent = {
      id: tempId,
      title: data.title,
      start: data.startTime,
      end: data.endTime,
      attendees: data.attendees,
      isAllDay: data.allDay || false,
      calendarId: '',
      status: 'confirmed',
      providerSource: 'google',
      isRecurring: !!data.recurrence,
      location: data.location,
      description: data.description,
      color: data.colorId,
    };
    setEvents(prev => [...prev, optimisticEvent]);

    // Créer l'évènement D'ABORD — naviguer ensuite
    // (appeler setCurrentWeekStart avant l'await déclenchait useEffect([fetchEvents])
    //  qui fetchait la nouvelle semaine avant que l'évènement existe → réponse vide →
    //  l'évènement optimiste disparaissait)
    try {
      const result = await apiClient.createCalendarEvent({
        title: data.title,
        start_time: data.startTime,
        end_time: data.endTime,
        attendees: data.attendees,
        location: data.location,
        description: data.description,
        reminders: data.reminders,
        recurrence: data.recurrence,
        all_day: data.allDay,
        conference: data.conference,
        account_id: accountId,
        color_id: data.colorId,
      });

      // Replace temp ID with real ID so the event persists across refreshes
      const realId = result.event_id;
      if (realId) {
        setEvents(prev => prev.map(e => e.id === tempId ? { ...e, id: realId } : e));
        // Carry a label applied to the still-optimistic event onto the real id,
        // else a labelled meeting loses its colour once the create resolves.
        migrateEventLabel(tempId, realId);
        // Keep an open detail modal attached to the same event after the id swap.
        setSelectedEvent(prev => prev && prev.id === tempId ? { ...prev, id: realId } : prev);
        // Register grace period: preserve this event for 30s regardless of server propagation
        recentlyCreatedRef.current.set(realId, Date.now());
      }

      if (result.meet_link) {
        setMeetLinkToast(result.meet_link);
        setTimeout(() => setMeetLinkToast(null), 10000);
        setSelectedEvent(prev =>
          prev && (prev.id === tempId || prev.id === realId || (prev.title === data.title && prev.start === data.startTime))
            ? { ...prev, id: realId || prev.id, meetLink: result.meet_link ?? undefined }
            : prev
        );
      }

      // Naviguer vers la semaine de l'évènement APRÈS création.
      // Ne pas appeler setCurrentWeekStart si la semaine est identique : cela
      // déclencherait useEffect([fetchEvents]) immédiatement avant que Google/Outlook
      // ait propagé l'évènement → réponse sans le nouvel évènement → disparition.
      const eventDate = new Date(data.startTime);
      const newWeekStart = getViewStart(eventDate, viewMode);
      if (newWeekStart.getTime() !== currentWeekStart.getTime()) {
        setCurrentWeekStart(newWeekStart);
      }

      // Toujours rafraîchir après 2s pour laisser le provider propager l'évènement.
      // Utilise fetchEventsRef (latest ref) pour garantir le bon currentWeekStart
      // même après une navigation vers une autre semaine.
      setTimeout(() => {
        fetchEventsRef.current();
      }, 2000);
    } catch (err) {
      // Rollback optimistic event and show non-intrusive toast
      setEvents(prev => prev.filter(e => e.id !== tempId));
      // Drop the orphaned label override for the rolled-back temp event.
      migrateEventLabel(tempId, null);
      const msg = err instanceof Error ? err.message : t('error_load');
      setCreateErrorToast(msg);
      setTimeout(() => setCreateErrorToast(null), 5000);
    }
  }, [viewMode, currentWeekStart, accountId, t, migrateEventLabel]);

  const handleUpdateEvent = useCallback(async (eventId: string, data: {
    title: string; startTime: string; endTime: string; attendees: string[];
    location?: string; description?: string; reminders?: number[];
    recurrence?: string; allDay?: boolean; conference?: boolean; calendarId?: string;
  }) => {
    setEditingEvent(null);
    setSelectedEvent(null);

    // Optimistic update
    setEvents(prev => prev.map(ev => ev.id === eventId ? {
      ...ev,
      title: data.title,
      start: data.startTime,
      end: data.endTime,
      attendees: data.attendees,
      isAllDay: data.allDay || false,
      location: data.location,
      description: data.description,
    } : ev));

    try {
      await apiClient.updateCalendarEvent(eventId, {
        title: data.title,
        start_time: data.startTime,
        end_time: data.endTime,
        attendees: data.attendees,
        location: data.location,
        description: data.description,
        reminders: data.reminders,
        recurrence: data.recurrence,
        all_day: data.allDay,
        conference: data.conference,
        // Route to the event's own calendar (secondary/shared); omitting it
        // defaulted to 'primary' → Google 404 → silent revert. Skip synthetic ids.
        calendar_id:
          data.calendarId && data.calendarId !== '__deep_work__' && data.calendarId !== '__work_block__'
            ? data.calendarId
            : undefined,
        account_id: accountId,
      });
      fetchEvents();
    } catch (err) {
      // Audit F-06 / Toast Site 5 (2026-05-12): the refetch silently
      // reverts the user's edit. Surface a toast so they know their
      // changes were not saved.
      console.error('[CalendarView] event update failed:', err);
      fetchEvents(); // rollback by refetching
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: {
            message: tc('toasts.calendar_event_update_failed'),
            type: 'error',
            duration: 6000,
          },
        }));
      }
    }
  }, [fetchEvents]);

  // Fetch lookahead events (next 8 days) when QuickEventPopover opens — used by ASAP
  // scheduler so it sees conflicts outside the currently displayed week
  useEffect(() => {
    if (!quickEvent) { setLookaheadEvents([]); return; }
    const now = new Date();
    const end = new Date(now);
    end.setDate(end.getDate() + 8);
    apiClient.getCalendarEvents(formatDateForApi(now), formatDateForApi(end))
      .then(res => setLookaheadEvents(res.events ?? []))
      .catch(() => { /* best effort */ });
  }, [quickEvent]);

  // BUG-Y002 / F-03: holiday dedup lives in ../utils/holidayDedup (pure +
  // unit-tested). dedupHolidays() collapses exact dupes, wording variants, and
  // the same holiday shifted ±1 day across a tz boundary — the old inline
  // `${date}|${title}` key could not merge an adjacent-day copy.

  // Fetch holidays for secondary timezone
  // BUG-J003 fix: AbortController prevents stale state updates from concurrent fetches
  // triggered by StrictMode double-mount or rapid week navigation.
  useEffect(() => {
    if (!secondaryTz) {
      setHolidays([]);
      return;
    }
    const controller = new AbortController();
    const periodEnd = new Date(currentWeekStart);
    periodEnd.setDate(periodEnd.getDate() + viewMode);
    apiClient.getHolidays(
      secondaryTz,
      formatDateForApi(currentWeekStart),
      formatDateForApi(periodEnd),
    ).then(res => {
      if (controller.signal.aborted) return;
      setHolidays(dedupHolidays(res.holidays || []));
    }).catch(err => {
      if (controller.signal.aborted) return;
      console.error('[CalendarView] fetch holidays failed:', err);
      setHolidays([]);
    });
    return () => controller.abort();
  }, [secondaryTz, currentWeekStart]);

  // Get holidays for a specific day
  const getHolidaysForDay = useCallback((date: Date) => {
    const dateStr = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    return holidays.filter(h => h.date === dateStr);
  }, [holidays]);

  // Fetch holidays for primary (local) timezone
  // BUG-J003 fix: AbortController prevents stale updates from cancelled fetches.
  useEffect(() => {
    if (!detectedTz || detectedTz === secondaryTz) {
      setPrimaryHolidays([]);
      return;
    }
    const controller = new AbortController();
    const periodEnd = new Date(currentWeekStart);
    periodEnd.setDate(periodEnd.getDate() + viewMode);
    apiClient.getPublicHolidays(
      detectedCountry ? { country: detectedCountry, region: detectedRegion ?? undefined } : { timezone: detectedTz },
      formatDateForApi(currentWeekStart),
      formatDateForApi(periodEnd),
    ).then(res => {
      if (controller.signal.aborted) return;
      setPrimaryHolidays(dedupHolidays(res.holidays || []));
    }).catch(() => {
      if (controller.signal.aborted) return;
      setPrimaryHolidays([]);
    });
    return () => controller.abort();
  }, [currentWeekStart, viewMode, secondaryTz, detectedTz]);

  // BUG-Y002 fix: also dedupe ACROSS primary and secondary holiday lists
  // (same holiday returned by both providers — e.g. Canada appearing in both
  // Quebec primary and US Eastern secondary buckets). Primary wins.
  const getPrimaryHolidaysForDay = useCallback((date: Date) => {
    const dateStr = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    return primaryHolidays.filter(h => h.date === dateStr);
  }, [primaryHolidays]);

  // Title normalization for cross-list dedup now lives in ../utils/holidayDedup
  // (normalizeHolidayTitle / holidayTitlesWithin), used in the all-day render.

  // Filter events by visible calendars + search query
  const filteredEvents = useMemo(() => {
    let result = events;
    // Only filter when the set is non-empty — an empty Set would hide all events
    // (happens during loading race or if the calendars API returned nothing)
    if (visibleCalendarIds !== null && visibleCalendarIds.size > 0) {
      result = result.filter(e => {
        // calendarId vide = optimistic event en cours de création → toujours afficher
        if (!e.calendarId) return true;
        // Grace period: événement venant d'être créé → toujours afficher (30s)
        const createdAt = recentlyCreatedRef.current.get(e.id);
        if (createdAt && Date.now() - createdAt < 30_000) return true;
        // Resolve the "primary" alias to the user's actual primary calendar ID.
        // Gmail returns events tagged with "primary" instead of the real calendar ID;
        // Outlook hardcodes "primary" and matches it via list_calendars fallback.
        // Either way, the toggle keys on the real ID, so we must resolve.
        const effectiveId = e.calendarId === 'primary' && primaryCalendarId
          ? primaryCalendarId
          : e.calendarId;
        return visibleCalendarIds.has(effectiveId);
      });
    }
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      result = result.filter(e =>
        e.title.toLowerCase().includes(q) ||
        (e.attendees || []).some(a => a.toLowerCase().includes(q)) ||
        (e.location || '').toLowerCase().includes(q)
      );
    }
    return result;
  }, [events, visibleCalendarIds, searchQuery, primaryCalendarId]);

  // ── Event search across a wide date range ──
  const isSearching = searchQuery.trim().length >= 2;

  useEffect(() => {
    if (!isSearching) {
      searchLoadedRef.current = false;
      setSearchLoading(false);
      return;
    }
    if (searchLoadedRef.current) return;

    const myId = ++searchFetchIdRef.current;
    setSearchLoading(true);
    (async () => {
      try {
        const now = new Date();
        const rangeStart = new Date(now);
        rangeStart.setFullYear(rangeStart.getFullYear() - 1);
        const rangeEnd = new Date(now);
        rangeEnd.setFullYear(rangeEnd.getFullYear() + 1);
        const resp = await apiClient.getCalendarEvents(
          formatDateForApi(rangeStart),
          formatDateForApi(rangeEnd),
          undefined,
          accountId,
        );
        if (myId !== searchFetchIdRef.current) return;
        setSearchResults(resp.events || []);
        searchLoadedRef.current = true;
      } catch (e) {
        console.warn('[CalendarView] search fetch error', e);
      } finally {
        if (myId === searchFetchIdRef.current) setSearchLoading(false);
      }
    })();
  }, [isSearching, accountId]);

  const filteredSearchResults = useMemo(() => {
    if (!isSearching) return [];
    const q = searchQuery.trim().toLowerCase();
    const visible = (visibleCalendarIds && visibleCalendarIds.size > 0)
      ? searchResults.filter(e => {
          if (!e.calendarId) return true;
          const effectiveId = e.calendarId === 'primary' && primaryCalendarId
            ? primaryCalendarId
            : e.calendarId;
          return visibleCalendarIds.has(effectiveId);
        })
      : searchResults;
    return visible
      .filter(e =>
        e.title.toLowerCase().includes(q) ||
        (e.description || '').toLowerCase().includes(q) ||
        (e.location || '').toLowerCase().includes(q) ||
        (e.attendees || []).some(a => a.toLowerCase().includes(q))
      )
      .sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime());
  }, [isSearching, searchQuery, searchResults, visibleCalendarIds, primaryCalendarId]);

  const groupedSearchResults = useMemo(() => {
    const groups: Array<{ key: string; date: Date; events: CalendarEvent[] }> = [];
    const byKey = new Map<string, { key: string; date: Date; events: CalendarEvent[] }>();
    for (const e of filteredSearchResults) {
      const d = new Date(e.start);
      const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
      let group = byKey.get(key);
      if (!group) {
        group = { key, date: d, events: [] };
        byKey.set(key, group);
        groups.push(group);
      }
      group.events.push(e);
    }
    return groups;
  }, [filteredSearchResults]);

  // Generate virtual Deep Work email check slot events
  const deepWorkCheckEvents = useMemo((): CalendarEvent[] => {
    if (!deepWork.settings.enabled || !deepWork.settings.emailsEnabled || deepWork.settings.checkSlots.length === 0) return [];
    const virtualEvents: CalendarEvent[] = [];
    for (const date of weekDates) {
      const isoDay = date.getDay() === 0 ? 7 : date.getDay();
      if (!deepWork.settings.weekdays.includes(isoDay)) continue;
      for (let i = 0; i < deepWork.settings.checkSlots.length; i++) {
        const slot = deepWork.settings.checkSlots[i];
        const [h, m] = slot.start.split(':').map(Number);
        const start = new Date(date);
        start.setHours(h, m, 0, 0);
        const end = new Date(start);
        end.setMinutes(end.getMinutes() + slot.duration);
        virtualEvents.push({
          id: `dw-check-${date.toISOString().slice(0, 10)}-${i}`,
          title: t('consult_emails'),
          start: start.toISOString(),
          end: end.toISOString(),
          isAllDay: false,
          calendarId: '__deep_work__',
          status: 'confirmed',
          location: '',
          description: '',
          organizer: '',
          attendees: [],
          color: '#10b981',
          providerSource: 'local',
          isRecurring: true,
        });
      }
    }
    return virtualEvents;
  }, [deepWork.settings.enabled, deepWork.settings.emailsEnabled, deepWork.settings.checkSlots, deepWork.settings.weekdays, weekDates]);

  // Generate virtual personal work block events — amber
  const workBlockEvents = useMemo((): CalendarEvent[] => {
    if (!deepWork.settings.enabled || !deepWork.settings.workEnabled || deepWork.settings.personalBlocks.length === 0) return [];
    const virtualEvents: CalendarEvent[] = [];
    for (const date of weekDates) {
      const isoDay = date.getDay() === 0 ? 7 : date.getDay();
      if (!deepWork.settings.weekdays.includes(isoDay)) continue;
      for (let i = 0; i < deepWork.settings.personalBlocks.length; i++) {
        const block = deepWork.settings.personalBlocks[i];
        const [h, m] = block.start.split(':').map(Number);
        const start = new Date(date);
        start.setHours(h, m, 0, 0);
        const end = new Date(start);
        end.setMinutes(end.getMinutes() + block.duration);
        virtualEvents.push({
          id: `wb-${date.toISOString().slice(0, 10)}-${i}`,
          title: block.label || t('personal_work'),
          start: start.toISOString(),
          end: end.toISOString(),
          isAllDay: false,
          calendarId: '__work_block__',
          status: 'confirmed',
          location: '',
          description: '',
          organizer: '',
          attendees: [],
          color: '#d97706',
          providerSource: 'local',
          isRecurring: true,
        });
      }
    }
    return virtualEvents;
  }, [deepWork.settings.enabled, deepWork.settings.workEnabled, deepWork.settings.personalBlocks, deepWork.settings.weekdays, weekDates]);

  // Lookahead dates (next 8 days from now) — used to generate virtual blocks for ASAP slot filtering
  const lookaheadDates = useMemo((): Date[] => {
    if (!quickEvent) return [];
    const dates: Date[] = [];
    const now = new Date();
    for (let i = 0; i < 8; i++) {
      const d = new Date(now);
      d.setDate(d.getDate() + i);
      d.setHours(0, 0, 0, 0);
      dates.push(d);
    }
    return dates;
  }, [quickEvent]);

  const lookaheadDeepWorkEvents = useMemo((): CalendarEvent[] => {
    if (!quickEvent || !deepWork.settings.enabled || deepWork.settings.checkSlots.length === 0) return [];
    const virtualEvents: CalendarEvent[] = [];
    for (const date of lookaheadDates) {
      const isoDay = date.getDay() === 0 ? 7 : date.getDay();
      if (!deepWork.settings.weekdays.includes(isoDay)) continue;
      for (let i = 0; i < deepWork.settings.checkSlots.length; i++) {
        const slot = deepWork.settings.checkSlots[i];
        const [h, m] = slot.start.split(':').map(Number);
        const start = new Date(date);
        start.setHours(h, m, 0, 0);
        const end = new Date(start);
        end.setMinutes(end.getMinutes() + slot.duration);
        virtualEvents.push({
          id: `la-dw-${date.toISOString().slice(0, 10)}-${i}`,
          title: t('consult_emails'),
          start: start.toISOString(),
          end: end.toISOString(),
          isAllDay: false,
          calendarId: '__deep_work__',
          status: 'confirmed',
          location: '', description: '', organizer: '', attendees: [],
          color: '#10b981', providerSource: 'local', isRecurring: true,
        });
      }
    }
    return virtualEvents;
  }, [quickEvent, deepWork.settings.enabled, deepWork.settings.checkSlots, deepWork.settings.weekdays, lookaheadDates, t]);

  const lookaheadWorkBlockEvents = useMemo((): CalendarEvent[] => {
    if (!quickEvent || deepWork.settings.personalBlocks.length === 0) return [];
    const virtualEvents: CalendarEvent[] = [];
    for (const date of lookaheadDates) {
      const isoDay = date.getDay() === 0 ? 7 : date.getDay();
      if (!deepWork.settings.weekdays.includes(isoDay)) continue;
      for (let i = 0; i < deepWork.settings.personalBlocks.length; i++) {
        const block = deepWork.settings.personalBlocks[i];
        const [h, m] = block.start.split(':').map(Number);
        const start = new Date(date);
        start.setHours(h, m, 0, 0);
        const end = new Date(start);
        end.setMinutes(end.getMinutes() + block.duration);
        virtualEvents.push({
          id: `la-wb-${date.toISOString().slice(0, 10)}-${i}`,
          title: block.label || t('personal_work'),
          start: start.toISOString(),
          end: end.toISOString(),
          isAllDay: false,
          calendarId: '__work_block__',
          status: 'confirmed',
          location: '', description: '', organizer: '', attendees: [],
          color: '#d97706', providerSource: 'local', isRecurring: true,
        });
      }
    }
    return virtualEvents;
  }, [quickEvent, deepWork.settings.personalBlocks, deepWork.settings.weekdays, lookaheadDates]);

  // Filter events by day
  const getEventsForDay = (date: Date) => {
    const dayStart = new Date(date);
    dayStart.setHours(0, 0, 0, 0);
    const dayEnd = new Date(date);
    dayEnd.setHours(23, 59, 59, 999);

    return filteredEvents.filter(event => {
      const eventStart = new Date(event.start);
      const eventEnd = new Date(event.end);
      return eventStart <= dayEnd && eventEnd >= dayStart && !event.isAllDay;
    });
  };

  // Get all-day events for a day (including multi-day events that span this day)
  const getAllDayEventsForDay = (date: Date) => {
    const dayStart = new Date(date);
    dayStart.setHours(0, 0, 0, 0);
    const dayEnd = new Date(date);
    dayEnd.setHours(23, 59, 59, 999);

    return filteredEvents.filter(event => {
      if (!event.isAllDay) return false;
      const eventStart = new Date(event.start);
      // All-day end is EXCLUSIVE (Google/iCal: a 1-day event on the 3rd ends at
      // the 4th's midnight). Using `>= dayStart` made the event also render on
      // that exclusive end day → it appeared duplicated on the following day.
      // Compare with `> dayStart` (half-open range). Guard against providers
      // that emit end<=start so the event still shows on at least its start day.
      let eventEnd = new Date(event.end);
      if (eventEnd <= eventStart) eventEnd = new Date(eventStart.getTime() + 86400000);
      return eventStart <= dayEnd && eventEnd > dayStart;
    });
  };

  // Calculate event position
  const getEventStyle = (
    event: CalendarEvent,
    dayDate: Date,
    layout: { colIndex: number; colCount: number } = { colIndex: 0, colCount: 1 }
  ) => {
    const eventStart = new Date(event.start);
    const eventEnd = new Date(event.end);

    // Clamp to day boundaries
    const dayStart = new Date(dayDate);
    dayStart.setHours(HOUR_START, 0, 0, 0);
    const dayEnd = new Date(dayDate);
    dayEnd.setHours(23, 0, 0, 0);

    const clampedStart = eventStart < dayStart ? dayStart : eventStart;
    // Défendre contre les événements sans heure de fin (null/undefined/Invalid Date)
    const validEnd = event.end && !isNaN(eventEnd.getTime()) ? eventEnd : new Date(eventStart.getTime() + 30 * 60_000);
    const clampedEnd = validEnd > dayEnd ? dayEnd : validEnd;

    const startHour = clampedStart.getHours() + clampedStart.getMinutes() / 60;
    const endHour = clampedEnd.getHours() + clampedEnd.getMinutes() / 60;

    const top = (startHour - HOUR_START) * PX_PER_HOUR;
    // min 48px (= une rangée de slot) — évite le rendu "slider" pour les événements ultra-courts
    const height = Math.max((endHour - startHour) * PX_PER_HOUR, 48);

    if (layout.colCount === 1) {
      return { top: `${top}px`, height: `${height}px` };
    }
    const colWidthPct = 100 / layout.colCount;
    return {
      top: `${top}px`,
      height: `${height}px`,
      left: `calc(${layout.colIndex * colWidthPct}% + 2px)`,
      width: `calc(${colWidthPct}% - 4px)`,
    } as React.CSSProperties;
  };

  const computeDayLayout = (
    events: CalendarEvent[]
  ): Map<string, { colIndex: number; colCount: number }> => {
    if (events.length === 0) return new Map();
    const sorted = [...events].sort(
      (a, b) => new Date(a.start).getTime() - new Date(b.start).getTime()
    );
    const columns: CalendarEvent[][] = [];
    const eventToCol = new Map<string, number>();

    for (const event of sorted) {
      const eStart = new Date(event.start).getTime();
      let placed = false;
      for (let c = 0; c < columns.length; c++) {
        const last = columns[c][columns[c].length - 1];
        if (new Date(last.end).getTime() <= eStart) {
          columns[c].push(event);
          eventToCol.set(event.id, c);
          placed = true;
          break;
        }
      }
      if (!placed) {
        columns.push([event]);
        eventToCol.set(event.id, columns.length - 1);
      }
    }

    const result = new Map<string, { colIndex: number; colCount: number }>();
    for (const event of sorted) {
      const eStart = new Date(event.start).getTime();
      const eEnd   = new Date(event.end).getTime();
      const colIndex = eventToCol.get(event.id)!;
      let maxCol = colIndex;
      for (const other of sorted) {
        if (other.id === event.id) continue;
        if (new Date(other.start).getTime() < eEnd && new Date(other.end).getTime() > eStart) {
          maxCol = Math.max(maxCol, eventToCol.get(other.id)!);
        }
      }
      result.set(event.id, { colIndex, colCount: maxCol + 1 });
    }
    return result;
  };

  // Check if date is today
  const isToday = (date: Date) => {
    const today = new Date();
    return date.toDateString() === today.toDateString();
  };

  // Check if this week contains today
  const weekContainsToday = useMemo(() => {
    const today = new Date();
    return weekDates.some(d => d.toDateString() === today.toDateString());
  }, [weekDates]);

  // No account connected - show placeholder
  if (noAccount) {
    return (
      <div className="calendar-view">
        <div className="calendar-placeholder">
          <div className="calendar-icon">
            <svg aria-hidden="true" width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <rect width="18" height="18" x="3" y="4" rx="2" ry="2" />
              <line x1="16" x2="16" y1="2" y2="6" />
              <line x1="8" x2="8" y1="2" y2="6" />
              <line x1="3" x2="21" y1="10" y2="10" />
              <path d="m9 16 2 2 4-4" />
            </svg>
          </div>
          <h2>{t('connect_calendar')}</h2>
          <p>{t('connect_calendar_desc')}</p>
          <button className="calendar-connect-btn" onClick={onOpenSettings}>
            {t('connect_calendar_btn')}
          </button>
        </div>
      </div>
    );
  }

  // Needs re-authentication for calendar scopes
  if (needsReauth) {
    return (
      <div className="calendar-view">
        <div className="calendar-placeholder">
          <div className="calendar-icon" style={{ color: 'var(--warning)' }}>
            <svg aria-hidden="true" width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
              <line x1="12" x2="12" y1="9" y2="13" />
              <line x1="12" x2="12.01" y1="17" y2="17" />
            </svg>
          </div>
          <h2>{t('reauth_title')}</h2>
          <p>{t('reauth_desc', { provider: calendarProvider === 'gmail' ? 'Google Calendar' : 'Microsoft Calendar' /* outlook, hotmail, imap, etc. */ })}</p>
          <div style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
            <button className="calendar-connect-btn" onClick={onOpenAccounts ?? onOpenSettings}>
              {t('reauth_btn')}
            </button>
            <button className="calendar-error-btn" onClick={() => { setNeedsReauth(false); fetchEvents(); }}>
              {t('retry')}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Loading state
  if (loading) {
    return (
      <div className="calendar-view">
        <div className="calendar-loading">
          <div className="calendar-loading-spinner" />
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="calendar-view">
        <div className="calendar-error">
          <div className="calendar-error-icon">
            <svg aria-hidden="true" width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" x2="12" y1="8" y2="12" />
              <line x1="12" x2="12.01" y1="16" y2="16" />
            </svg>
          </div>
          <h3>{t('error_load')}</h3>
          <p>{error}</p>
          <button className="calendar-error-btn" onClick={fetchEvents}>
            {t('retry')}
          </button>
        </div>
      </div>
    );
  }

  const periodEnd = new Date(currentWeekStart);
  periodEnd.setDate(periodEnd.getDate() + viewMode - 1);

  // Dynamic grid template for view mode
  const gridCols = `56px ${hasTz2 ? '48px ' : ''}repeat(${viewMode}, 1fr)`;

  return (
    <div className="calendar-view">
      {/* Toolbar */}
      <div className="calendar-header">
        <div className="calendar-nav">
          <button className="calendar-nav-btn calendar-today-btn" onClick={goToToday}>
            {t('today_btn')}
          </button>
          <button className="calendar-chevron-btn" onClick={goToPreviousPeriod} aria-label={t('prev_period')}>
            <ChevronLeftIcon />
          </button>
          <button className="calendar-chevron-btn" onClick={goToNextPeriod} aria-label={t('next_period')}>
            <ChevronRightIcon />
          </button>
          <div className="calendar-month-title">
            <span className="cal-picker-wrapper">
              <button ref={monthBtnRef} className="cal-picker-btn" onClick={openMonthPicker}
                aria-label={t('choose_month')} aria-expanded={monthPickerOpen}>
                {tc(`months.${MONTH_KEYS[currentWeekStart.getMonth()]}`)}
              </button>
              {monthPickerOpen && monthPickerPos && (
                <div ref={monthPickerRef} className="cal-picker-dropdown cal-month-picker"
                  style={{ top: monthPickerPos.top, left: monthPickerPos.left }}>
                  {MONTH_KEYS.map((key, i) => (
                    <button key={i}
                      className={`cal-picker-month-cell${i === currentWeekStart.getMonth() ? ' cal-picker-active' : ''}`}
                      onClick={() => goToMonthYear(i, currentWeekStart.getFullYear())}>
                      {tc(`months.${key}`)}
                    </button>
                  ))}
                </div>
              )}
            </span>
            {' '}
            <span className="cal-picker-wrapper">
              <button ref={yearBtnRef} className="cal-picker-btn" onClick={openYearPicker}
                aria-label={t('choose_year')} aria-expanded={yearPickerOpen}>
                {currentWeekStart.getFullYear()}
              </button>
              {yearPickerOpen && yearPickerPos && (
                <div ref={yearPickerRef} className="cal-picker-dropdown cal-year-picker"
                  style={{ top: yearPickerPos.top, left: yearPickerPos.left }}>
                  {Array.from({ length: 21 }, (_, i) => currentWeekStart.getFullYear() - 10 + i).map(y => (
                    <button key={y}
                      className={`cal-picker-year-item${y === currentWeekStart.getFullYear() ? ' cal-picker-active' : ''}`}
                      onClick={() => goToMonthYear(currentWeekStart.getMonth(), y)}>
                      {y}
                    </button>
                  ))}
                </div>
              )}
            </span>
          </div>
          {/* P3-25 (2026-05-17): the week-number pill used to be a decorative
              <span> — it looked clickable (pill shape, accent color) but did
              nothing. Convert to a focusable button that prompts for a week
              number and jumps the calendar there via setCurrentWeekStart.
              Using window.prompt keeps the patch small; a richer popover can
              come later. */}
          <button
            type="button"
            className="calendar-week-number"
            aria-label={t('week_number_jump_aria', 'Jump to week')}
            title={t('week_number_jump_title', 'Jump to week')}
            onClick={() => {
              const current = getWeekNumber(currentWeekStart);
              const raw = window.prompt(t('week_number_prompt', 'Jump to which week of the year?'), String(current));
              if (!raw) return;
              const n = Number.parseInt(raw, 10);
              if (!Number.isFinite(n) || n < 1 || n > 53) return;
              // ISO week → Monday of that week in the currentWeekStart year.
              const year = currentWeekStart.getFullYear();
              // Use the standard ISO-8601 algorithm: Jan 4 is always in W1.
              const jan4 = new Date(year, 0, 4);
              const jan4Day = jan4.getDay() || 7; // 1..7 (Mon..Sun)
              const week1Monday = new Date(jan4);
              week1Monday.setDate(jan4.getDate() - (jan4Day - 1));
              const target = new Date(week1Monday);
              target.setDate(week1Monday.getDate() + (n - 1) * 7);
              setCurrentWeekStart(getViewStart(target, viewMode));
            }}
          >
            {t('week_number', { n: getWeekNumber(currentWeekStart) })}
          </button>
        </div>

        <div className="calendar-header-right">

          {/* Search */}
          <div className={`calendar-search-wrapper${searchExpanded || searchQuery ? ' calendar-search-wrapper--expanded' : ''}`}>
            <button
              type="button"
              className="calendar-search-icon-btn"
              onClick={() => {
                setSearchExpanded(true);
                setTimeout(() => searchInputRef.current?.focus(), 0);
              }}
              title={t('search_placeholder')}
              aria-label={t('search_placeholder')}
            >
              <SearchIcon />
            </button>
            <input
              ref={searchInputRef}
              className="calendar-search-input"
              type="text"
              placeholder={t('search_placeholder')}
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              onBlur={() => { if (!searchQuery) setSearchExpanded(false); }}
              onKeyDown={e => {
                if (e.key === 'Escape') {
                  setSearchQuery('');
                  setSearchExpanded(false);
                  searchInputRef.current?.blur();
                }
              }}
            />
          </div>

        </div>
      </div>

      {/* Content row: main + sidebar */}
      <div className="calendar-content-row">
      <div className="calendar-main">
      {/* Event search results — replaces week view while searching */}
      {isSearching && (
        <div className="calendar-search-results">
          <div className="calendar-search-results-header">
            {searchLoading ? (
              <span className="calendar-search-results-count">…</span>
            ) : (
              <span className="calendar-search-results-count">
                {t('search_results_count', { count: filteredSearchResults.length })}
              </span>
            )}
          </div>
          {!searchLoading && filteredSearchResults.length === 0 ? (
            <div className="calendar-search-empty">
              {t('search_no_results', { q: searchQuery.trim() })}
            </div>
          ) : (
            <div className="calendar-search-results-list">
              {groupedSearchResults.map(group => (
                <div key={group.key} className="calendar-search-day-group">
                  <div className="calendar-search-day-header">
                    {formatEventDetailDate(group.date, lang)}
                  </div>
                  {group.events.map(ev => {
                    const start = new Date(ev.start);
                    const end = ev.end ? new Date(ev.end) : null;
                    const timeLabel = ev.isAllDay
                      ? t('all_day_label')
                      : `${formatTime(start)}${end ? ` – ${formatTime(end)}` : ''}`;
                    const color = (ev.calendarId && calendarColorMap.get(ev.calendarId)) || '#4285F4';
                    return (
                      <button
                        key={ev.id}
                        type="button"
                        className="calendar-search-result-row"
                        onClick={() => {
                          setSelectedEvent(ev);
                          handleNavigateToDate(new Date(ev.start));
                        }}
                      >
                        <span className="calendar-search-result-dot" style={{ background: color }} />
                        <span className="calendar-search-result-time">{timeLabel}</span>
                        <span className="calendar-search-result-title">{ev.title || t('event_untitled', '(sans titre)')}</span>
                        {ev.location && (
                          <span className="calendar-search-result-location">{ev.location}</span>
                        )}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Week view */}
      <div className="calendar-week-container" style={isSearching ? { display: 'none' } : undefined}>
        {/* Week header with day names and dates */}
        <div className="calendar-week-header" style={{ gridTemplateColumns: gridCols }}>
          <div className="calendar-time-header">
            <span className="calendar-tz-abbr">{getLocalTimezoneAbbr()}</span>
          </div>
          {hasTz2 && (
            <div className="calendar-tz2-header">
              <span className="calendar-tz2-label">{getTzLabel(secondaryTz)}</span>
              <button
                className="calendar-tz2-remove"
                onClick={() => setSecondaryTz('')}
                title={t('remove_timezone')}
              >
                <CloseIcon size={10} />
              </button>
            </div>
          )}
          {weekDates.map((date, i) => {
            const jsDay = date.getDay();
            const dayIdx = jsDay === 0 ? 6 : jsDay - 1; // Mon=0 ... Sun=6
            const weekend = jsDay === 0 || jsDay === 6;
            const today = isToday(date);
            const cls = [
              'calendar-week-header-cell',
              today && 'is-today',
              weekend && 'is-weekend',
            ].filter(Boolean).join(' ');
            return (
              <div key={i} className={cls}>
                <span className={`calendar-day-name${today ? ' today' : ''}`}>{tc(`days_short.${DAY_KEYS_MON_SUN[dayIdx]}`)}</span>
                <span className={`calendar-day-number${today ? ' calendar-day-number--today' : ''}`}>{date.getDate()}</span>
              </div>
            );
          })}
        </div>

        {/* All-day events section (user events + holidays + DST) */}
        {(filteredEvents.some(e => e.isAllDay) || (showTz2Holidays && holidays.length > 0) || (showPrimaryHolidays && primaryHolidays.length > 0) || dstTransitions.size > 0) && (
          <div className="calendar-allday-section" style={{ gridTemplateColumns: gridCols }}>
            <div className="calendar-allday-label" />
            {hasTz2 && <div className="calendar-tz2-allday-spacer" />}
            {weekDates.map((date, i) => {
              const dayPrimaryHolidays = showPrimaryHolidays ? getPrimaryHolidaysForDay(date) : [];
              const dateStr = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
              // BUG-Y002 / F-03: suppress a secondary-tz holiday when the primary
              // (local) list already shows the SAME normalized title within ±1
              // day — catches a tz-shifted copy of the same holiday.
              // Session Z update: cross-LANGUAGE pairs (primary "Victoria Day" EN
              // vs secondary "Fête de la Reine" FR) are NOW merged via the
              // HOLIDAY_ALIASES table inside normalizeHolidayTitle().
              const primaryTitlesNearDay = showPrimaryHolidays
                ? holidayTitlesWithin(primaryHolidays, dateStr, 1)
                : new Set<string>();
              const dayHolidays = showTz2Holidays
                ? getHolidaysForDay(date).filter(
                    h => !primaryTitlesNearDay.has(normalizeHolidayTitle(h.title)),
                  )
                : [];
              // BUG-Y002 (Session AA fix): also suppress all-day calendar events
              // whose title canonicalizes to a holiday already shown by the
              // primary or secondary holiday lists. This catches the "Jours
              // fériés - Canada" Google Calendar that ships its own copy of
              // Victoria Day / Fête de la Reine on Mon AND Tue (tz shift in
              // Google's data).
              const shownHolidayTitles = new Set<string>([
                ...primaryTitlesNearDay,
                ...dayHolidays.map(h => normalizeHolidayTitle(h.title)),
              ]);
              // Also include holiday titles from neighbouring days (±1) of the
              // SECONDARY list, since the duplicate calendar entry can land on
              // either side of the canonical date.
              if (showTz2Holidays) {
                for (const ttl of holidayTitlesWithin(holidays, dateStr, 1)) {
                  shownHolidayTitles.add(ttl);
                }
              }
              const dst = dstTransitions.get(dateStr);
              return (
                <div key={i} className="calendar-allday-cell">
                  {dst && (
                    <div
                      className="calendar-allday-event calendar-dst-banner"
                      title={dst.diff > 0 ? t('dst_summer') : t('dst_winter')}
                    >
                      <span className="calendar-dst-label">{dst.label}</span>
                      <svg className="calendar-event-icon" width="9" height="9" viewBox="0 0 24 24" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="10" />
                        <polyline points="12 6 12 12 16 14" />
                      </svg>
                      {dst.diff > 0 ? t('dst_summer_label') : t('dst_winter_label')}
                    </div>
                  )}
                  {dayPrimaryHolidays.map(h => (
                    <div
                      key={h.id}
                      className="calendar-allday-event calendar-holiday calendar-holiday--primary"
                      title={h.title}
                    >
                      <svg className="calendar-event-icon" width="9" height="9" viewBox="0 0 24 24" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                        <line x1="16" y1="2" x2="16" y2="6" />
                        <line x1="8" y1="2" x2="8" y2="6" />
                        <line x1="3" y1="10" x2="21" y2="10" />
                      </svg>
                      {h.title}
                    </div>
                  ))}
                  {dayHolidays.map(h => (
                    <div
                      key={h.id}
                      className="calendar-allday-event calendar-holiday"
                      title={`${h.title} (${getTzLabel(secondaryTz)})`}
                    >
                      <span className="calendar-holiday-flag">{getTzLabel(secondaryTz)}</span>
                      <svg className="calendar-event-icon" width="9" height="9" viewBox="0 0 24 24" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                        <line x1="16" y1="2" x2="16" y2="6" />
                        <line x1="8" y1="2" x2="8" y2="6" />
                        <line x1="3" y1="10" x2="21" y2="10" />
                      </svg>
                      {h.title}
                    </div>
                  ))}
                  {getAllDayEventsForDay(date)
                    .filter(event => !shownHolidayTitles.has(normalizeHolidayTitle(event.title)))
                    .map(event => (
                    <div
                      key={event.id}
                      className="calendar-allday-event"
                      onClick={() => setSelectedEvent(event)}
                      title={event.title}
                    >
                      {event.title}
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        )}

        {/* Week body with time slots */}
        <div className="calendar-week-body" style={{ gridTemplateColumns: gridCols }} ref={weekBodyRef}>
          {/* Time column (local) */}
          <div className="calendar-time-column">
            {HOURS.map(hour => {
              const cls = [
                'calendar-time-slot',
                (hour < 8 || hour >= 17) && 'off-hours',
                (hour === 8 || hour === 17) && 'work-bound',
              ].filter(Boolean).join(' ');
              const label = formatHourMinute(new Date(2000, 0, 1, hour, 0), lang);
              return (
                <div key={hour} className={cls}>
                  {label}
                </div>
              );
            })}
          </div>

          {/* Secondary timezone column — right next to local time */}
          {hasTz2 && (
              <div className="calendar-tz2-column">
                {HOURS.map(hour => {
                  const tzTime = getHourInTimezone(hour, secondaryTz);
                  // Hour-of-day for work-hours styling below. parseInt stops at
                  // the first non-digit, so it handles both "14h00" and "14:00".
                  const tzHour = parseInt(tzTime, 10);
                  const cls = [
                    'calendar-tz2-slot',
                    (tzHour < 8 || tzHour >= 17) && 'off-hours',
                    (tzHour === 8 || tzHour === 17) && 'work-bound',
                  ].filter(Boolean).join(' ');
                  return (
                    <div key={hour} className={cls}>
                      {tzTime}
                    </div>
                  );
                })}
              </div>
          )}

          {/* Day columns */}
          {weekDates.map((date, dayIndex) => {
            const jsDay = date.getDay();
            const colCls = [
              'calendar-day-column',
              isToday(date) && 'is-today',
              (jsDay === 0 || jsDay === 6) && 'is-weekend',
            ].filter(Boolean).join(' ');
            return (
            <div
              key={dayIndex}
              className={colCls}
            >
              {/* Hour slots (for grid) */}
              {HOURS.map(hour => (
                <div
                  key={hour}
                  className={`calendar-hour-slot${hour < 8 || hour >= 17 ? ' off-hours' : ''}`}
                  onMouseDown={(e) => handleSlotMouseDown(e, date, hour)}
                />
              ))}

              {/* Current time indicator — only on today's column */}
              {isToday(date) && weekContainsToday && nowPosition >= 0 && nowPosition <= HOUR_COUNT * PX_PER_HOUR && (
                <div
                  className="calendar-now-line"
                  style={{ top: `${nowPosition}px` }}
                />
              )}

              {/* Events + Deep Work check slots (layout partagé) */}
              {(() => {
                const dayEvents = getEventsForDay(date);
                const dayDWEvents = deepWorkCheckEvents.filter(ev =>
                  new Date(ev.start).toDateString() === date.toDateString()
                );
                const dayWorkBlockEvents = workBlockEvents.filter(ev =>
                  new Date(ev.start).toDateString() === date.toDateString()
                );
                const layoutMap = computeDayLayout([...dayEvents, ...dayDWEvents, ...dayWorkBlockEvents]);
                return (<>
                {dayEvents.map(event => {
                const layout = layoutMap.get(event.id) ?? { colIndex: 0, colCount: 1 };
                const style  = getEventStyle(event, date, layout);
                const heightPx = parseFloat(style.height as string);
                const isCompact = heightPx < 52; // compact si < ~1h (48px/hr + marge)
                // Match label color: manual override > gcal color > calendar > title direct > title prefix
                const manualOverride = eventLabelOverrides[event.id];
                const titleLower = event.title.toLowerCase();
                const labelColor = manualOverride?.color
                  || (event.color && GCAL_COLOR_MAP[event.color]) || (event.color?.startsWith('#') ? event.color : undefined)
                  || calendarColorMap.get(event.calendarId)
                  || labelColorMap.get(titleLower)
                  || labelPrefixColors.find(({ prefix }) => titleLower.startsWith(prefix))?.color;
                const eventStyle = labelColor
                  ? { ...style, '--event-color': labelColor, borderLeftColor: labelColor, background: `color-mix(in srgb, ${labelColor} 10%, var(--surface-primary))` } as React.CSSProperties
                  : style;
                return (
                <div
                  key={event.id}
                  className={`calendar-event ${event.status || ''}${isCompact ? ' calendar-event--compact' : ''}${imminentEventIds?.has(event.id) ? ' calendar-event--imminent' : ''}`}
                  style={eventStyle}
                  onMouseDown={(e) => { didDragRef.current = false; handleEventDragStart(e, event); }}
                  onClick={(e) => { e.stopPropagation(); if (!didDragRef.current) { setSelectedEvent(event); } didDragRef.current = false; }}
                  onContextMenu={(e) => e.preventDefault()}
                >
                  <div className="calendar-event-title">
                    <span className="calendar-event-title-text">{event.title}</span>
                    <button
                      className="calendar-event-delete-btn"
                      onClick={(e) => handleQuickDelete(e, event.id)}
                      onMouseDown={(e) => e.stopPropagation()}
                      title={t('delete_event_btn')}
                      aria-label={t('delete_event_label')}
                    >
                      <CloseIcon size={10} />
                    </button>
                  </div>
                  <div className="calendar-event-time">
                    {formatTime(event.start)} – {formatTime(event.end)}
                  </div>
                  {!isCompact && event.location && (
                    <div className="calendar-event-location">{event.location}</div>
                  )}
                  {/* Resize handles (top + bottom) */}
                  <div
                    className="calendar-event-resize-handle calendar-event-resize-handle--top"
                    onMouseDown={(e) => handleEventResizeStart(e, event, 'top')}
                  />
                  <div
                    className="calendar-event-resize-handle"
                    onMouseDown={(e) => handleEventResizeStart(e, event, 'bottom')}
                  />
                </div>
                );
                })}
                {dayDWEvents.map(ev => {
                  const layout = layoutMap.get(ev.id) ?? { colIndex: 0, colCount: 1 };
                  return (
                  <div
                    key={ev.id}
                    className="calendar-event calendar-event--deep-work"
                    style={getEventStyle(ev, date, layout)}
                    title={`${t('consult_emails')} · ${formatTime(ev.start)} – ${formatTime(ev.end)}`}
                    // BUG-Y004 fix: deep-work and work-block events used to lack
                    // an onClick — clicks fell through to the empty-slot handler
                    // and opened the "Create event" modal. Now they open the
                    // detail panel like regular events. stopPropagation prevents
                    // the slot's onClick from also firing.
                    onClick={(e) => { e.stopPropagation(); setSelectedEvent(ev); }}
                  >
                    <div className="calendar-event-title">
                      <svg aria-hidden="true" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: 4, verticalAlign: -1 }}>
                        <polyline points="22 12 16 12 14 15 10 15 8 12 2 12" />
                        <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
                      </svg>
                      {t('emails_label')}
                    </div>
                    <div className="calendar-event-time">
                      {formatTime(ev.start)} – {formatTime(ev.end)}
                    </div>
                  </div>
                  );
                })}
                {dayWorkBlockEvents.map(ev => {
                  const layout = layoutMap.get(ev.id) ?? { colIndex: 0, colCount: 1 };
                  return (
                  <div
                    key={ev.id}
                    className="calendar-event calendar-event--work-block"
                    style={getEventStyle(ev, date, layout)}
                    title={`${ev.title} · ${formatTime(ev.start)} – ${formatTime(ev.end)}`}
                    // BUG-Y004 fix: same as deep-work above — clicks must open
                    // the detail panel, not fall through to the slot handler.
                    onClick={(e) => { e.stopPropagation(); setSelectedEvent(ev); }}
                  >
                    <div className="calendar-event-title">
                      <svg aria-hidden="true" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: 4, verticalAlign: -1 }}>
                        <rect width="18" height="18" x="3" y="3" rx="2" />
                        <path d="M3 9h18" />
                        <path d="M9 21V9" />
                      </svg>
                      <span className="calendar-event-title-text">{ev.title}</span>
                    </div>
                    <div className="calendar-event-time">
                      {formatTime(ev.start)} – {formatTime(ev.end)}
                    </div>
                  </div>
                  );
                })}
                </>);
              })()}


            </div>
            ); })}
        </div>
      </div>
      </div>{/* end calendar-main */}

      <CalendarSidebar
        currentWeekStart={currentWeekStart}
        onNavigateToDate={handleNavigateToDate}
        visibleCalendarIds={visibleCalendarIds}
        onToggleCalendar={handleToggleCalendar}
        onCalendarsLoaded={handleCalendarsLoaded}
        userEmail={userEmail}
        tz2Country={secondaryTz ? getTzCountry(secondaryTz) : ''}
        tz2Color={tz2Color.hue}
        showTz2Holidays={showTz2Holidays}
        onToggleTz2Holidays={handleToggleTz2Holidays}
        primaryTzCountry={detectedTz !== secondaryTz ? getTzCountry(detectedTz) : ''}
        showPrimaryHolidays={showPrimaryHolidays}
        onTogglePrimaryHolidays={handleTogglePrimaryHolidays}
      />
      </div>{/* end calendar-content-row */}

      {/* Quick event creation popover */}
      {quickEvent && (
        <QuickEventPopover
          date={quickEvent.date}
          hour={quickEvent.hour}
          endHour={quickEvent.endHour}
          endMinute={quickEvent.endMinute}
          anchorRect={quickEvent.anchorRect}
          onSave={handleQuickEventSave}
          onClose={() => setQuickEvent(null)}
          localEvents={[...events, ...lookaheadEvents, ...deepWorkCheckEvents, ...workBlockEvents, ...lookaheadDeepWorkEvents, ...lookaheadWorkBlockEvents]}
          userEmail={userEmail}
          calendarProvider={calendarProvider}
        />
      )}

      {/* Conference link toast (Google Meet / Teams) */}
      {createErrorToast && (
        <div className="calendar-create-error-toast">
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" /><line x1="12" x2="12" y1="8" y2="12" /><line x1="12" x2="12.01" y1="16" y2="16" />
          </svg>
          <span>{createErrorToast}</span>
          <button type="button" className="calendar-meet-toast-close" onClick={() => setCreateErrorToast(null)}>
            <CloseIcon />
          </button>
        </div>
      )}

      {meetLinkToast && (
        <div className="calendar-meet-toast" role="status" aria-live="polite">
          <div className="calendar-meet-toast__icon" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="m22 8-6 4 6 4V8Z" /><rect width="14" height="12" x="2" y="6" rx="2" ry="2" />
            </svg>
          </div>
          <div className="calendar-meet-toast__body">
            <div className="calendar-meet-toast__title">{t('meet_toast_title')}</div>
            <a
              href={meetLinkToast}
              target="_blank"
              rel="noopener noreferrer"
              className="calendar-meet-toast__url"
            >
              {meetLinkToast.replace(/^https?:\/\//, '')}
            </a>
          </div>
          <div className="calendar-meet-toast__actions">
            <button
              type="button"
              className={`calendar-meet-toast__btn calendar-meet-toast__btn--secondary${meetLinkCopied ? ' is-copied' : ''}`}
              onClick={() => {
                void copyToClipboard(meetLinkToast);
                setMeetLinkCopied(true);
                setTimeout(() => setMeetLinkCopied(false), 1500);
              }}
            >
              {meetLinkCopied ? (
                <>
                  <CheckIcon size={12} />
                  {t('meet_toast_copied')}
                </>
              ) : (
                t('meet_toast_copy')
              )}
            </button>
            <a
              href={meetLinkToast}
              target="_blank"
              rel="noopener noreferrer"
              className="calendar-meet-toast__btn calendar-meet-toast__btn--primary"
            >
              {t('meet_toast_open')}
            </a>
          </div>
          <button
            type="button"
            className="calendar-meet-toast__close"
            onClick={() => setMeetLinkToast(null)}
            aria-label={t('reminder_action_dismiss')}
          >
            <CloseIcon size={14} />
          </button>
        </div>
      )}


      {/* Event detail modal */}
      {selectedEvent && (
        <div
          className="calendar-event-modal-overlay"
          onClick={() => { setSelectedEvent(null); setConfirmDeleteEventId(null); }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.stopPropagation();
              setSelectedEvent(null);
              setConfirmDeleteEventId(null);
            }
          }}
        >
          <div
            ref={eventModalRef}
            className="calendar-event-modal"
            role="dialog"
            aria-modal="true"
            aria-label={selectedEvent.title}
            tabIndex={-1}
            onClick={e => e.stopPropagation()}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                e.stopPropagation();
                setSelectedEvent(null);
                setConfirmDeleteEventId(null);
              }
            }}
          >
            <div className="calendar-event-modal-header">
              <h3 className="calendar-event-modal-title">{selectedEvent.title}</h3>
              <div className="calendar-event-modal-header-actions">
                <button
                  className="calendar-event-modal-close"
                  onClick={() => { setSelectedEvent(null); setConfirmDeleteEventId(null); }}
                >
                  <CloseIcon />
                </button>
              </div>
            </div>

            <div className="calendar-event-modal-section">
              <div className="calendar-event-modal-label">{t('date_time')}</div>
              <div className="calendar-event-modal-value">
                {selectedEvent.isAllDay ? (
                  formatEventDetailDate(new Date(selectedEvent.start), lang)
                ) : (
                  <>
                    {formatEventDetailDateTime(new Date(selectedEvent.start), lang)}
                    {' – '}
                    {formatTime(selectedEvent.end)}
                  </>
                )}
              </div>
            </div>

            {selectedEvent.location && (
              <div className="calendar-event-modal-section">
                <div className="calendar-event-modal-label">{t('location')}</div>
                <div className="calendar-event-modal-value">{selectedEvent.location}</div>
              </div>
            )}

            {selectedEvent.description && parseDescriptionAndLabels(selectedEvent.description).notes && (
              <div className="calendar-event-modal-section">
                <div className="calendar-event-modal-label">{t('description')}</div>
                <div className="calendar-event-modal-value">{parseDescriptionAndLabels(selectedEvent.description).notes}</div>
              </div>
            )}

            {selectedEvent.attendees && selectedEvent.attendees.length > 0 && (
              <div className="calendar-event-modal-section">
                <div className="calendar-event-modal-label">{t('attendees')}</div>
                <div className="calendar-event-modal-value">
                  {selectedEvent.attendees.join(', ')}
                </div>
              </div>
            )}

            {onComposeToAttendees && selectedEvent.attendees && (() => {
              const emailable = selectedEvent.attendees.filter(a => !userEmail || a.toLowerCase() !== userEmail.toLowerCase());
              if (emailable.length === 0) return null;
              return (
                <div className="calendar-event-modal-section">
                  <button
                    className="calendar-event-modal-link calendar-event-modal-email-attendees"
                    onClick={() => {
                      onComposeToAttendees(emailable.join(', '), selectedEvent.title, selectedEvent.description || '');
                      setSelectedEvent(null);
                    }}
                  >
                    <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="2" y="4" width="20" height="16" rx="2" />
                      <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
                    </svg>
                    {t('email_all_attendees')}
                  </button>
                </div>
              );
            })()}

            {(() => {
              const org = formatOrganizer(selectedEvent.organizer);
              return org ? (
                <div className="calendar-event-modal-section">
                  <div className="calendar-event-modal-label">{t('organizer')}</div>
                  <div className="calendar-event-modal-value">{org}</div>
                </div>
              ) : null;
            })()}

            {selectedEvent.meetLink && (
              <div className="calendar-event-modal-section">
                <a
                  href={selectedEvent.meetLink}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="calendar-event-modal-link calendar-event-modal-meet-link"
                >
                  <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polygon points="23 7 16 12 23 17 23 7" />
                    <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
                  </svg>
                  {selectedEvent.meetLink.includes('teams.microsoft.com') ? t('join_teams') : selectedEvent.meetLink.includes('meet.google.com') ? t('join_meet') : t('join_conference')}
                </a>
              </div>
            )}

            {/* Label picker */}
            <div className="calendar-event-modal-section">
              <div className="calendar-event-modal-label">{t('label')}</div>
              <div className="calendar-event-label-picker">
                {[...DEFAULT_LABELS.map(l => ({ name: l.name, color: l.color, description: l.description })), ...customLabels.map(l => ({ ...l, description: '' }))].map(label => {
                  const currentOverride = eventLabelOverrides[selectedEvent.id];
                  const isActive = currentOverride?.name === label.name;
                  return (
                    <button
                      key={label.name}
                      className={`cal-label-chip${isActive ? ' cal-label-chip--active' : ''}`}
                      style={{ '--chip-color': label.color } as React.CSSProperties}
                      onClick={() => {
                        if (isActive) {
                          setEventLabel(selectedEvent.id, null);
                        } else {
                          setEventLabel(selectedEvent.id, { name: label.name, color: label.color });
                        }
                      }}
                      title={label.description}
                    >
                      <span className="cal-label-chip-dot" style={{ background: label.color }} />
                      <span className="cal-label-chip-name">{getLabelDisplayName(label.name)}</span>
                      {isActive && (
                        <CheckIcon size={12} className="cal-label-chip-check" />
                      )}
                    </button>
                  );
                })}
              </div>
            </div>

            {selectedEvent.htmlLink && (
              <div className="calendar-event-modal-section">
                <a
                  href={selectedEvent.htmlLink}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="calendar-event-modal-link"
                >
                  <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                    <polyline points="15 3 21 3 21 9" />
                    <line x1="10" x2="21" y1="14" y2="3" />
                  </svg>
                  {t('open_in_calendar')}
                </a>
              </div>
            )}

            <div className="calendar-event-modal-section calendar-event-modal-actions-row">
              <button
                className="calendar-event-modal-icon-btn calendar-event-modal-edit-btn"
                onClick={(e) => {
                    e.stopPropagation();
                    // BUG-004: fermer le modal de détail avant d'ouvrir l'édition
                    // pour éviter que les deux modaux soient visibles simultanément
                    setSelectedEvent(null);
                    setEditingEvent({
                      eventId: selectedEvent.id,
                      title: selectedEvent.title,
                      start: selectedEvent.start,
                      end: selectedEvent.end,
                      location: selectedEvent.location,
                      description: selectedEvent.description,
                      attendees: selectedEvent.attendees,
                      isAllDay: selectedEvent.isAllDay,
                      // Carry the source calendar so editing a secondary/shared
                      // event saves to the right calendar (not 'primary' → 404).
                      calendarId: selectedEvent.calendarId,
                    });
                }}
                title={t('edit_event')}
              >
                <EditIcon size={16} />
              </button>
              {confirmDeleteEventId === selectedEvent.id ? (
                /* Inline confirmation — avoids window.confirm which freezes the Tauri WebView */
                <span className="calendar-event-modal-delete-confirm">
                  <span className="calendar-event-modal-delete-confirm-text">{t('delete_confirm_short', 'Supprimer ?')}</span>
                  <button
                    className="calendar-event-modal-icon-btn icon-btn--delete-confirm"
                    onClick={() => {
                      const eventId = selectedEvent.id;
                      setConfirmDeleteEventId(null);
                      setSelectedEvent(null);
                      const removed = events.find(ev => ev.id === eventId);
                      setEvents(prev => prev.filter(ev => ev.id !== eventId));
                      // Pass account + the event's own calendarId so a delete on a
                      // secondary/shared calendar isn't silently routed to "primary".
                      apiClient.deleteCalendarEvent(eventId, accountId, removed?.calendarId).catch(() => {
                        if (removed) setEvents(prev => [...prev, removed]);
                        if (typeof window !== 'undefined') {
                          window.dispatchEvent(new CustomEvent('agentys:toast', {
                            detail: {
                              message: tc('toasts.calendar_event_delete_failed'),
                              type: 'error',
                              duration: 6000,
                            },
                          }));
                        }
                      });
                    }}
                    title={t('confirm')}
                    aria-label={t('confirm')}
                  ><CheckIcon size={16} /></button>
                  <button
                    className="calendar-event-modal-icon-btn"
                    onClick={() => setConfirmDeleteEventId(null)}
                    title={t('cancel')}
                    aria-label={t('cancel')}
                  ><CloseIcon size={16} /></button>
                </span>
              ) : (
                <button
                  className="calendar-event-modal-icon-btn calendar-event-modal-delete-icon icon-btn--delete"
                  onClick={() => setConfirmDeleteEventId(selectedEvent.id)}
                  title={t('delete_event')}
                >
                  <TrashIcon size={16} />
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Edit event popover (opens over modal) */}
      {editingEvent && (
        <QuickEventPopover
          date={new Date(editingEvent.start)}
          hour={new Date(editingEvent.start).getHours()}
          anchorRect={document.querySelector('.calendar-event-modal')?.getBoundingClientRect() ?? new DOMRect(window.innerWidth / 2 - 180, 100, 360, 400)}
          onSave={handleQuickEventSave}
          onClose={() => setEditingEvent(null)}
          localEvents={[...events, ...lookaheadEvents]}
          userEmail={userEmail}
          editEvent={editingEvent}
          onUpdate={handleUpdateEvent}
          calendarProvider={calendarProvider}
        />
      )}

      {/* Shortcuts ribbon */}
      <div className={`shortcuts-ribbon ${ribbonVisible ? 'shortcuts-ribbon--visible' : 'shortcuts-ribbon--hidden'}`}>
        <div className="shortcut-group">
          <div className="shortcut-item"><span className="shortcut-key">=</span><span className="shortcut-label">{t('shortcut_next_week')}</span></div>
          <div className="shortcut-item"><span className="shortcut-key">-</span><span className="shortcut-label">{t('shortcut_prev_week')}</span></div>
          <div className="shortcut-item"><span className="shortcut-key">T</span><span className="shortcut-label">{t('shortcut_today')}</span></div>
          <div className="shortcut-item shortcut-item--highlighted"><span className="shortcut-key">B</span><span className="shortcut-label">{t('shortcut_create_event')}</span></div>
        </div>
      </div>
    </div>
  );
}

/** Memoized export — prevents re-renders when App re-renders with stable props */
export const CalendarView = memo(CalendarViewInner);
