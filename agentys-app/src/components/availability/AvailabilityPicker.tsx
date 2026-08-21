import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { apiClient, type CalendarEvent } from '../../services/api';
import { useAnimatedUnmount } from '../../hooks/useAnimatedUnmount';
import { useDeepWorkSetting } from '../../hooks/useDeepWorkSetting';
import { fetchLabels } from '../../api/labels';
import { formatAvailability, type AvailabilitySlot } from '../../utils/availabilityFormatter';
import { formatHourMinute } from '../../utils/dateFormat';
import { CloseIcon, CheckIcon, ChevronLeftIcon, ChevronRightIcon } from '../icons/ActionIcons';
// Pull in CalendarView's CSS so the picker's grid uses the EXACT same
// visual treatment (fonts, colors, day labels, event cards, hour slots,
// today gradient, now-line) as the user's existing Calendar tab. The
// picker only adds its own .av-* layer (overlay, slots, dock).
import '../CalendarView.css';
import './AvailabilityPicker.css';

// ---------------------------------------------------------------------------
// Layout constants. Tuned for a 7-day grid that fits in a viewport without
// scrolling on a typical 1080p screen, and matches the visual cadence of
// Google Calendar / Superhuman.
// ---------------------------------------------------------------------------
// Aligned with CalendarView.tsx so the picker looks pixel-identical to
// the user's existing Calendar tab. Any change to those constants in
// CalendarView should be mirrored here.
const SLOT_MINUTES_QUANTUM = 15;       // grid resolution
const PIXELS_PER_HOUR = 48;            // matches CalendarView.tsx PX_PER_HOUR
const PIXELS_PER_MINUTE = PIXELS_PER_HOUR / 60;
const DAY_START_HOUR = 5;              // matches CalendarView HOURS[0] (5 AM)
const DAY_END_HOUR = 24;               // 5 + 19 hours visible (matches HOUR_COUNT)
const VISIBLE_HOURS = DAY_END_HOUR - DAY_START_HOUR;
const WORKING_HOURS_START = 8;          // matches CalendarView's "off-hours" boundary
const WORKING_HOURS_END = 17;
const DURATION_OPTIONS_MIN = [15, 30, 45, 60] as const;

const DAY_KEY_FMT: Intl.DateTimeFormatOptions = {
  year: 'numeric', month: '2-digit', day: '2-digit',
};

interface AvailabilityPickerProps {
  isOpen: boolean;
  onClose: () => void;
  onInsert: (formatted: string) => void;
  /** When true, append the saved booking_url after the inserted slots. */
  appendBookingLink?: boolean;
  bookingUrl?: string;
  accountId?: number;
  /** Initial duration in minutes. Default 60. */
  initialDuration?: number;
  /**
   * Locale for the formatted output ("Voici mes disponibilités" / "Here are
   * my availabilities" / "today (May 13)" vs "aujourd'hui (13 mai)"). When
   * provided, overrides the app UI language — use this to match the
   * REPLY language rather than the UI language (e.g. the composer's
   * `voiceLanguage` state). Falls back to `i18n.language` when omitted.
   */
  language?: string;
}

interface SelectedSlot {
  /** Local-time Date — start of the selection. */
  start: Date;
  /** Local-time Date — end. */
  end: Date;
  /** Stable id for React keys + delete actions. */
  id: string;
}

type Duration = (typeof DURATION_OPTIONS_MIN)[number] | number;

// ---------------------------------------------------------------------------
// Date utilities. All grid math happens in the user's *browser* timezone —
// the formatter takes care of timezone conversion at insertion time.
// ---------------------------------------------------------------------------

function startOfWeek(d: Date): Date {
  const out = new Date(d);
  const dow = out.getDay(); // 0=Sun
  out.setDate(out.getDate() - dow);
  out.setHours(0, 0, 0, 0);
  return out;
}

function addDays(d: Date, n: number): Date {
  const out = new Date(d);
  out.setDate(out.getDate() + n);
  return out;
}

function dayKey(d: Date): string {
  return d.toLocaleDateString('en-CA', DAY_KEY_FMT);
}

/** Snap a y-pixel offset (within the day column) to the nearest 15-min block. */
function pxToMinutes(yPx: number): number {
  const minutes = yPx / PIXELS_PER_MINUTE;
  return Math.floor(minutes / SLOT_MINUTES_QUANTUM) * SLOT_MINUTES_QUANTUM;
}

function minutesToPx(min: number): number {
  return min * PIXELS_PER_MINUTE;
}

/** Convert minutes-from-day-start into a Date on the given column day. */
function minutesToDate(columnDate: Date, minFromGridStart: number): Date {
  const out = new Date(columnDate);
  out.setHours(DAY_START_HOUR, 0, 0, 0);
  out.setMinutes(out.getMinutes() + minFromGridStart);
  return out;
}

/** Minutes elapsed between two dates on the same column day, relative to grid start. */
function dateToMinutes(date: Date, columnDate: Date): number {
  const startOfGrid = new Date(columnDate);
  startOfGrid.setHours(DAY_START_HOUR, 0, 0, 0);
  return Math.round((date.getTime() - startOfGrid.getTime()) / 60000);
}

function rangesOverlap(aStart: Date, aEnd: Date, bStart: Date, bEnd: Date): boolean {
  return aStart < bEnd && bStart < aEnd;
}

function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

// ---------------------------------------------------------------------------
// Event color resolution — mirrors CalendarView's logic for the most common
// case (event.color either as a Google colorId 1-11, or as a #hex string).
// We don't replicate the calendar/label/prefix maps here; those need extra
// state CalendarView builds. event.color alone covers most user events.
// ---------------------------------------------------------------------------
const GCAL_COLOR_MAP: Record<string, string> = {
  '1': '#7986cb', '2': '#33b679', '3': '#8e24aa', '4': '#e67c73',
  '5': '#f6bf26', '6': '#f4511e', '7': '#039be5', '8': '#616161',
  '9': '#3f51b5', '10': '#0b8043', '11': '#d50000',
};

// Heuristic title-prefix coloring for events that don't carry a color
// of their own. Mirrors what CalendarView does via labelPrefixColors so
// the same recurring patterns ("Emails", "Travail personnel", "Absence",
// etc.) get the same hue across both surfaces.
const TITLE_PREFIX_COLORS: Array<{ pattern: RegExp; color: string }> = [
  { pattern: /^emails?\b/i,                color: '#10b981' }, // teal/green
  { pattern: /^travail\s+personnel\b/i,    color: '#f97316' }, // orange
  { pattern: /^(focus|deep\s*work)\b/i,    color: '#f97316' },
  { pattern: /^(absence|vacation|conge)\b/i,color: '#ea580c' }, // burnt orange
  { pattern: /^(meeting|reunion|appel)\b/i, color: '#0d9488' }, // accent teal
  { pattern: /^(call|appel)\b/i,            color: '#0d9488' },
];

function resolveEventColor(event: CalendarEvent): string | undefined {
  // CalendarEvent shape varies by source — some adapters use `color`,
  // some use `colorId`. Accept either.
  const raw = (event as unknown as { color?: string; colorId?: string }).color
    ?? (event as unknown as { color?: string; colorId?: string }).colorId;
  if (raw) {
    if (raw.startsWith('#')) return raw;
    const mapped = GCAL_COLOR_MAP[raw];
    if (mapped) return mapped;
  }
  const title = (event.title || '').trim();
  if (title) {
    const match = TITLE_PREFIX_COLORS.find(p => p.pattern.test(title));
    if (match) return match.color;
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AvailabilityPicker({
  isOpen,
  onClose,
  onInsert,
  appendBookingLink,
  bookingUrl,
  accountId,
  initialDuration = 60,
  language,
}: AvailabilityPickerProps) {
  const { t, i18n } = useTranslation('availability');
  const { t: tc } = useTranslation('common');
  const { shouldRender, isClosing, handleClose } = useAnimatedUnmount(isOpen, onClose);

  const [weekStart, setWeekStart] = useState<Date>(() => startOfWeek(new Date()));
  const [duration, setDuration] = useState<Duration>(initialDuration);
  const [selected, setSelected] = useState<SelectedSlot[]>([]);
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const deepWork = useDeepWorkSetting();
  // Label colors — same source as CalendarView, so events that match a
  // user-defined label by exact title or by subject_prefix get the same
  // hue in the picker that they have in the Calendar tab.
  const [labelColorMap, setLabelColorMap] = useState<Map<string, string>>(new Map());
  const [labelPrefixColors, setLabelPrefixColors] = useState<Array<{ prefix: string; color: string }>>([]);

  const days = useMemo(
    () => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)),
    [weekStart],
  );

  // Virtual deep-work events (recurring "Emails" check slots, daily). Mirrors
  // CalendarView's logic so the picker shows the same recurring blocks you
  // see in your Calendar tab. These are NOT real calendar events — they're
  // generated from your Settings → Productivity → Deep Work configuration.
  const deepWorkCheckEvents = useMemo((): CalendarEvent[] => {
    if (!deepWork.settings.enabled || !deepWork.settings.emailsEnabled || !deepWork.settings.checkSlots?.length) return [];
    const out: CalendarEvent[] = [];
    for (const date of days) {
      const isoDay = date.getDay() === 0 ? 7 : date.getDay();
      if (!deepWork.settings.weekdays?.includes(isoDay)) continue;
      for (let i = 0; i < deepWork.settings.checkSlots.length; i++) {
        const slot = deepWork.settings.checkSlots[i];
        const [h, m] = slot.start.split(':').map(Number);
        const start = new Date(date);
        start.setHours(h, m, 0, 0);
        const end = new Date(start);
        end.setMinutes(end.getMinutes() + slot.duration);
        out.push({
          id: `dw-check-${date.toISOString().slice(0, 10)}-${i}`,
          title: t('emails_check', 'Emails'),
          start: start.toISOString(),
          end: end.toISOString(),
          isAllDay: false,
          calendarId: '__deep_work__',
          color: '#10b981',
        } as unknown as CalendarEvent);
      }
    }
    return out;
  }, [deepWork.settings.enabled, deepWork.settings.emailsEnabled, deepWork.settings.checkSlots, deepWork.settings.weekdays, days, t]);

  const workBlockEvents = useMemo((): CalendarEvent[] => {
    if (!deepWork.settings.enabled || !deepWork.settings.workEnabled || !deepWork.settings.personalBlocks?.length) return [];
    const out: CalendarEvent[] = [];
    for (const date of days) {
      const isoDay = date.getDay() === 0 ? 7 : date.getDay();
      if (!deepWork.settings.weekdays?.includes(isoDay)) continue;
      for (let i = 0; i < deepWork.settings.personalBlocks.length; i++) {
        const block = deepWork.settings.personalBlocks[i];
        const [h, m] = block.start.split(':').map(Number);
        const start = new Date(date);
        start.setHours(h, m, 0, 0);
        const end = new Date(start);
        end.setMinutes(end.getMinutes() + block.duration);
        out.push({
          id: `wb-${date.toISOString().slice(0, 10)}-${i}`,
          title: block.label || t('personal_work', 'Travail personnel'),
          start: start.toISOString(),
          end: end.toISOString(),
          isAllDay: false,
          calendarId: '__work_block__',
          color: '#d97706',
        } as unknown as CalendarEvent);
      }
    }
    return out;
  }, [deepWork.settings.enabled, deepWork.settings.workEnabled, deepWork.settings.personalBlocks, deepWork.settings.weekdays, days, t]);

  // All events that should be rendered as time-bound blocks in the grid.
  const timedEvents = useMemo(() => {
    const realTimed = events.filter(
      e => !(e as unknown as { isAllDay?: boolean }).isAllDay,
    );
    return [...realTimed, ...deepWorkCheckEvents, ...workBlockEvents];
  }, [events, deepWorkCheckEvents, workBlockEvents]);

  const allDayEvents = useMemo(
    () => events.filter(e => (e as unknown as { isAllDay?: boolean }).isAllDay),
    [events],
  );

  // Detect the user's IANA timezone — used by the formatter at insert time.
  const userTimezone = useMemo(() => {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    } catch {
      return 'UTC';
    }
  }, []);

  // Short timezone label shown in the bottom dock (e.g. "EDT", "CEST").
  const tzLabel = useMemo(() => {
    try {
      const parts = new Intl.DateTimeFormat('en', {
        timeZone: userTimezone, timeZoneName: 'short',
      }).formatToParts(new Date());
      return parts.find(p => p.type === 'timeZoneName')?.value || userTimezone;
    } catch {
      return userTimezone;
    }
  }, [userTimezone]);

  // Fetch existing calendar events for the visible week.
  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    setLoading(true);
    const start = new Date(weekStart);
    const end = addDays(weekStart, 7);
    apiClient.getCalendarEvents(
      start.toISOString(),
      end.toISOString(),
      undefined,
      accountId !== undefined ? String(accountId) : undefined,
      200,
    ).then(res => {
      if (cancelled) return;
      setEvents(res.events || []);
    }).catch(() => {
      if (!cancelled) setEvents([]);
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [isOpen, weekStart, accountId]);

  // Reset state on open/close.
  useEffect(() => {
    if (isOpen) {
      setSelected([]);
      setWeekStart(startOfWeek(new Date()));
    }
  }, [isOpen]);

  // Load labels once when the picker opens — populates labelColorMap
  // (exact title match) and labelPrefixColors (subject_prefix match).
  // Same logic as CalendarView; only the consumer side differs.
  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    fetchLabels().then(res => {
      if (cancelled) return;
      const lblMap = new Map<string, string>();
      const prefixList: Array<{ prefix: string; color: string }> = [];
      for (const label of res.labels || []) {
        if (label.color) {
          lblMap.set(label.name.toLowerCase(), label.color);
          if (label.subject_prefix?.trim()) {
            prefixList.push({
              prefix: label.subject_prefix.trimEnd().toLowerCase(),
              color: label.color,
            });
          }
        }
      }
      // Longest prefix wins so "ACME PRJ-142" beats just "ACME".
      prefixList.sort((a, b) => b.prefix.length - a.prefix.length);
      setLabelColorMap(lblMap);
      setLabelPrefixColors(prefixList);
    }).catch(() => { /* labels endpoint may be down — graceful degrade */ });
    return () => { cancelled = true; };
  }, [isOpen]);

  // Esc to close.
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        handleClose();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isOpen, handleClose]);

  // ─── Mouse handling: click-to-create, drag-to-create, drag-to-resize ──
  //
  // Three interactions on the column grid:
  //   1. Click on empty time → creates a slot of `duration` minutes,
  //      snapped to the nearest 15-min grid.
  //   2. Click + drag on empty time → creates a variable-length slot,
  //      anchored where the mouse went down, extended as it moves.
  //   3. Click + drag on a slot's resize handle (top or bottom 6px) →
  //      resizes that slot from the dragged edge.
  //
  // Better-than-Superhuman: every operation respects the existing-event
  // boundary. We clamp the drag end to just before/after a busy block so
  // the user can't offer a time that overlaps a real meeting.
  type DragState =
    | null
    | {
        kind: 'creating';
        columnDay: Date;
        columnEl: HTMLElement;
        anchorMin: number;
        currentMin: number;
        /** true once the mouse has moved beyond a small threshold — lets us
         *  distinguish "click" (no movement, fall back to fixed duration)
         *  from "drag" (use anchor-to-current as the slot range). */
        moved: boolean;
      }
    | {
        kind: 'resizing';
        slotId: string;
        edge: 'top' | 'bottom';
        columnDay: Date;
        columnEl: HTMLElement;
        currentMin: number;
        /** The opposite edge (anchor) — stays fixed while we drag the other. */
        anchorMin: number;
      };

  const [drag, setDrag] = useState<DragState>(null);
  const dragRef = useRef<DragState>(null);
  dragRef.current = drag;

  const dayHasEvent = useCallback((columnDay: Date, start: Date, end: Date): boolean => {
    // All-day events (Absence, vacation, holidays) are surfaced via the
    // banner at the top of the picker but DO NOT block selection — the
    // user might be "out" yet still want to offer specific hours. Only
    // timed events that actually overlap the proposed slot count.
    const cols = events.filter(e => {
      if ((e as unknown as { isAllDay?: boolean }).isAllDay) return false;
      const es = new Date(e.start);
      return dayKey(es) === dayKey(columnDay);
    });
    return cols.some(e => rangesOverlap(start, end, new Date(e.start), new Date(e.end)));
  }, [events]);

  const slotOverlapsSelection = useCallback(
    (start: Date, end: Date, ignoreId?: string): boolean => {
      return selected.some(s =>
        s.id !== ignoreId && rangesOverlap(start, end, s.start, s.end),
      );
    },
    [selected],
  );

  /**
   * Find the latest "blocker" minute < target that would overlap. Used to clamp
   * a drag's far edge to the nearest busy boundary.
   */
  const clampToColumnBounds = useCallback(
    (
      columnDay: Date,
      candidateMin: number,
      anchorMin: number,
      ignoreSlotId?: string,
    ): number => {
      // 1. Hard grid bounds.
      let clamped = Math.max(0, Math.min(VISIBLE_HOURS * 60, candidateMin));


      // 3. Find busy blocks on this day (events + other selections).
      //    All-day events (Absence, vacation, holidays) are intentionally
      //    NOT treated as blockers — see the all-day banner comment in the
      //    JSX. Otherwise an "Absence" all-day event would clamp every
      //    click to 0-min and the user couldn't pick any slot on that day.
      const blockers: Array<{ startMin: number; endMin: number; }> = [];
      events.forEach(ev => {
        if ((ev as unknown as { isAllDay?: boolean }).isAllDay) return;
        const es = new Date(ev.start);
        if (dayKey(es) !== dayKey(columnDay)) return;
        const ee = new Date(ev.end);
        blockers.push({
          startMin: dateToMinutes(es, columnDay),
          endMin: dateToMinutes(ee, columnDay),
        });
      });
      selected.forEach(s => {
        if (s.id === ignoreSlotId) return;
        if (dayKey(s.start) !== dayKey(columnDay)) return;
        blockers.push({
          startMin: dateToMinutes(s.start, columnDay),
          endMin: dateToMinutes(s.end, columnDay),
        });
      });

      // 4. Clamp against blockers in the direction of travel.
      for (const b of blockers) {
        // Anchor is below the blocker → can't go above the blocker's bottom.
        if (anchorMin >= b.endMin && clamped < b.endMin) {
          clamped = Math.max(clamped, b.endMin);
        }
        // Anchor is above the blocker → can't go below the blocker's top.
        if (anchorMin <= b.startMin && clamped > b.startMin) {
          clamped = Math.min(clamped, b.startMin);
        }
      }

      // Snap to grid (15-min quantum).
      clamped = Math.round(clamped / SLOT_MINUTES_QUANTUM) * SLOT_MINUTES_QUANTUM;
      return clamped;
    },
    [events, selected],
  );

  // Hot refs so the global mouse handlers (attached at mousedown time)
  // always read the latest functions/state. Using refs sidesteps the React
  // re-render cycle that would otherwise miss a fast mouseup arriving
  // before useEffect could attach the listeners.
  const dragLatestRefs = useRef({
    duration: duration as number,
    clampToColumnBounds,
    dayHasEvent,
    slotOverlapsSelection,
    selected,
  });
  dragLatestRefs.current = {
    duration: duration as number,
    clampToColumnBounds,
    dayHasEvent,
    slotOverlapsSelection,
    selected,
  };

  const handleColumnMouseDown = useCallback(
    (e: React.MouseEvent<HTMLDivElement>, columnDay: Date) => {
      if (e.button !== 0) return; // only primary mouse button
      const target = e.target as HTMLElement;
      // Ignore clicks on busy events (read-only in the picker) or on
      // a slot's × delete button (handled by its own onClick).
      if (target.closest('.calendar-event')) return;
      if (target.closest('.av-slot-remove')) return;

      const columnEl = e.currentTarget;
      let initial: DragState;

      // Resize-handle on an existing slot?
      const handle = target.closest('.av-slot-resize') as HTMLElement | null;
      if (handle) {
        const slotId = handle.dataset.slotId;
        const edge = handle.dataset.edge as 'top' | 'bottom' | undefined;
        const slot = selected.find(s => s.id === slotId);
        if (!slotId || !edge || !slot) return;
        const anchorEdge = edge === 'top' ? slot.end : slot.start;
        const movingEdge = edge === 'top' ? slot.start : slot.end;
        initial = {
          kind: 'resizing',
          slotId,
          edge,
          columnDay,
          columnEl,
          anchorMin: dateToMinutes(anchorEdge, columnDay),
          currentMin: dateToMinutes(movingEdge, columnDay),
        };
      } else {
        // Click on the slot body itself (not on a handle, not on ×) → no-op.
        if (target.closest('.av-slot')) return;

        // Click on empty grid → start a "creating" drag.
        const rect = columnEl.getBoundingClientRect();
        const yPx = e.clientY - rect.top;
        const anchorMin = pxToMinutes(yPx);
        initial = {
          kind: 'creating',
          columnDay,
          columnEl,
          anchorMin,
          currentMin: anchorMin,
          moved: false,
        };
      }

      e.preventDefault();
      // Set state for re-render AND ref synchronously — the global handlers
      // we're about to attach read from the ref, so they always see the
      // latest drag value even if React's batched update hasn't flushed.
      setDrag(initial);
      dragRef.current = initial;

      // Attach listeners SYNCHRONOUSLY here (not via useEffect). A click
      // = mousedown then mouseup with no DOM tasks in between, so an
      // effect-based listener attachment would miss the mouseup.
      const onMouseMove = (ev: MouseEvent) => {
        const cur = dragRef.current;
        if (!cur) return;
        const { clampToColumnBounds: clamp } = dragLatestRefs.current;
        const rect = cur.columnEl.getBoundingClientRect();
        const yPx = Math.max(0, Math.min(rect.height, ev.clientY - rect.top));
        const rawMin = pxToMinutes(yPx);

        let next: DragState;
        if (cur.kind === 'creating') {
          const moved = Math.abs(rawMin - cur.anchorMin) >= SLOT_MINUTES_QUANTUM;
          const clamped = clamp(cur.columnDay, rawMin, cur.anchorMin);
          next = { ...cur, currentMin: clamped, moved: cur.moved || moved };
        } else {
          const clamped = clamp(cur.columnDay, rawMin, cur.anchorMin, cur.slotId);
          next = { ...cur, currentMin: clamped };
        }
        dragRef.current = next;
        setDrag(next);
      };

      const onMouseUp = () => {
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);

        const cur = dragRef.current;
        const latest = dragLatestRefs.current;
        if (!cur) { setDrag(null); return; }

        if (cur.kind === 'creating') {
          let startMin: number;
          let endMin: number;
          if (cur.moved) {
            startMin = Math.min(cur.anchorMin, cur.currentMin);
            endMin = Math.max(cur.anchorMin, cur.currentMin);
          } else {
            // Click (no drag) → fixed-duration default, clamped to next blocker.
            startMin = cur.anchorMin;
            endMin = cur.anchorMin + latest.duration;
            endMin = latest.clampToColumnBounds(cur.columnDay, endMin, startMin);
          }
          if (endMin - startMin < SLOT_MINUTES_QUANTUM) {
            dragRef.current = null;
            setDrag(null);
            return;
          }
          const start = minutesToDate(cur.columnDay, startMin);
          const end = minutesToDate(cur.columnDay, endMin);
          if (latest.dayHasEvent(cur.columnDay, start, end) ||
              latest.slotOverlapsSelection(start, end)) {
            dragRef.current = null;
            setDrag(null);
            return;
          }
          setSelected(prev => [...prev, { start, end, id: uid() }]);
          dragRef.current = null;
          setDrag(null);
          return;
        }

        // resizing
        const slot = latest.selected.find(s => s.id === cur.slotId);
        if (!slot) { dragRef.current = null; setDrag(null); return; }
        const startMin = Math.min(cur.anchorMin, cur.currentMin);
        const endMin = Math.max(cur.anchorMin, cur.currentMin);
        if (endMin - startMin < SLOT_MINUTES_QUANTUM) {
          dragRef.current = null;
          setDrag(null);
          return;
        }
        const newStart = minutesToDate(cur.columnDay, startMin);
        const newEnd = minutesToDate(cur.columnDay, endMin);
        setSelected(prev => prev.map(s =>
          s.id === cur.slotId ? { ...s, start: newStart, end: newEnd } : s,
        ));
        dragRef.current = null;
        setDrag(null);
      };

      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', onMouseUp);
    },
    [selected],
  );

  const handleRemoveSlot = useCallback((id: string) => {
    setSelected(prev => prev.filter(s => s.id !== id));
  }, []);

  // ─── Insert ────────────────────────────────────────────────────────

  const handleInsert = useCallback(() => {
    if (selected.length === 0) return;
    const slots: AvailabilitySlot[] = selected.map(s => ({
      start: s.start, end: s.end,
    }));
    // Reply language wins over UI language — the formatted prose lands in
    // the reply body, which is written in the reply language regardless of
    // what locale the user reads the app in. Falls back to i18n.language
    // when caller omits `language` or passes 'auto' (no detected reply lang).
    const effectiveLocale =
      (language && language !== 'auto' ? language : i18n.language) || 'en';
    const formatted = formatAvailability(slots, {
      locale: effectiveLocale,
      timezone: userTimezone,
      // HTML output → TipTap renders <p> paragraphs, <ul><li> as a real
      // bullet list (proper indent + spacing), and <a href> as a real
      // clickable link. `insertText` calls TipTap's insertContent which
      // auto-detects HTML and parses it into nodes.
      output: 'html',
      // No TZ suffix in the inserted text — recipients usually share
      // the user's timezone and "EDT" is visual noise in the email body.
      bookingUrl: appendBookingLink && bookingUrl ? bookingUrl : undefined,
    });
    onInsert(formatted);
    handleClose();
  }, [selected, language, i18n.language, userTimezone, appendBookingLink, bookingUrl, onInsert, handleClose]);

  // ─── Rendering helpers ─────────────────────────────────────────────

  const monthLabel = useMemo(() => {
    const last = addDays(weekStart, 6);
    const sameMonth = weekStart.getMonth() === last.getMonth();
    if (sameMonth) {
      return new Intl.DateTimeFormat(i18n.language, {
        month: 'long', year: 'numeric',
      }).format(weekStart);
    }
    const a = new Intl.DateTimeFormat(i18n.language, { month: 'short' }).format(weekStart);
    const b = new Intl.DateTimeFormat(i18n.language, { month: 'short', year: 'numeric' }).format(last);
    return `${a} – ${b}`;
  }, [weekStart, i18n.language]);

  const todayKey = dayKey(new Date());

  if (!shouldRender) return null;

  // Portal to document.body so the full-screen panel escapes any ancestor
  // that has `transform`/`filter`/`will-change` set (which would otherwise
  // make `position: fixed` resolve relative to that ancestor instead of the
  // viewport — the bug that was breaking the takeover when the picker was
  // mounted inside the compose modal). The picker is now a true viewport-
  // level surface, identical in scope to the user's existing Calendar tab.
  return createPortal(
    <div
      className={`av-overlay${isClosing ? ' closing' : ''}`}
      role="dialog"
      aria-labelledby="av-title"
      aria-modal="true"
      data-escape-owner=""
    >
      <div className="av-panel">
        {/* Header ───────────────────────────────────────────── */}
        <div className="av-header">
          {/* sr-only heading for accessibility — visual purpose conveyed
              by the calendar grid + footer hint, à la Superhuman. */}
          <h2 id="av-title" className="av-sr-only">{t('picker_title')}</h2>
          <div className="av-header-nav">
            <button
              type="button"
              className="av-nav-btn av-nav-today"
              onClick={() => setWeekStart(startOfWeek(new Date()))}
            >
              {tc('today', 'Today')}
            </button>
            <button
              type="button"
              className="av-nav-btn"
              onClick={() => setWeekStart(prev => addDays(prev, -7))}
              aria-label={tc('previous', 'Previous')}
            >
              <ChevronLeftIcon size={16} />
            </button>
            <button
              type="button"
              className="av-nav-btn"
              onClick={() => setWeekStart(prev => addDays(prev, 7))}
              aria-label={tc('next', 'Next')}
            >
              <ChevronRightIcon size={16} />
            </button>
            <span className="av-header-month">{monthLabel}</span>
          </div>
          <button
            type="button"
            className="av-close"
            onClick={handleClose}
            aria-label={tc('close', 'Close')}
          >
            <CloseIcon size={16} />
          </button>
        </div>

        {/* Day labels row — uses the SAME CSS classes as CalendarView's
            week-header so the picker is visually identical to the user's
            existing Calendar tab. */}
        <div
          className="calendar-week-header"
          style={{ gridTemplateColumns: '56px repeat(7, 1fr)' }}
        >
          <div className="calendar-time-header">
            <span className="calendar-tz-abbr">{tzLabel}</span>
          </div>
          {days.map(d => {
            const jsDay = d.getDay();
            const isToday = dayKey(d) === todayKey;
            const isWeekend = jsDay === 0 || jsDay === 6;
            const cls = [
              'calendar-week-header-cell',
              isToday && 'is-today',
              isWeekend && 'is-weekend',
            ].filter(Boolean).join(' ');
            return (
              <div key={dayKey(d)} className={cls}>
                <span className={`calendar-day-name${isToday ? ' today' : ''}`}>
                  {new Intl.DateTimeFormat(i18n.language, { weekday: 'short' }).format(d)}
                </span>
                <span className={`calendar-day-number${isToday ? ' calendar-day-number--today' : ''}`}>
                  {new Intl.DateTimeFormat(i18n.language, { day: 'numeric' }).format(d)}
                </span>
              </div>
            );
          })}
        </div>

        {/* All-day banner row (Absence, vacation, holidays). Same look as
            CalendarView. Renders only when at least one all-day event is
            present in the visible week. These do NOT block selection — the
            user is only flagged that they're "out" but might still want
            to offer specific hours. */}
        {allDayEvents.length > 0 && (
          <div
            className="calendar-allday-section"
            style={{ gridTemplateColumns: '56px repeat(7, 1fr)' }}
          >
            <div className="calendar-allday-label" />
            {days.map(d => {
              const dayAllDay = allDayEvents.filter(ev => {
                const es = new Date(ev.start);
                const ee = new Date(ev.end);
                // All-day events can span multiple days — render on every
                // day they cover.
                return es <= d && ee > d;
              });
              return (
                <div key={dayKey(d)} className="calendar-allday-cell">
                  {dayAllDay.map(ev => {
                    const color = resolveEventColor(ev) || '#ea580c';
                    return (
                      <div
                        key={ev.id}
                        className="calendar-allday-event"
                        style={{ background: color, color: '#fff' }}
                        title={ev.title || t('busy_unnamed')}
                      >
                        {ev.title || t('busy_unnamed')}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        )}

        {/* Grid body — uses CalendarView's `calendar-week-body` so the
            time column, day columns, hour slots, events, and now-line all
            inherit the existing Calendar tab's visual treatment. The
            picker only adds its own selection layer (.av-slot) on top. */}
        <div
          className="calendar-week-body av-week-body"
          style={{ gridTemplateColumns: '56px repeat(7, 1fr)' }}
        >
          {/* Time column (local) — 5:00 / 6:00 / … / 23:00 */}
          <div className="calendar-time-column">
            {Array.from({ length: VISIBLE_HOURS }, (_, i) => {
              const hour = DAY_START_HOUR + i;
              const cls = [
                'calendar-time-slot',
                (hour < WORKING_HOURS_START || hour >= WORKING_HOURS_END) && 'off-hours',
                (hour === WORKING_HOURS_START || hour === WORKING_HOURS_END) && 'work-bound',
              ].filter(Boolean).join(' ');
              return (
                <div key={hour} className={cls}>
                  {formatHourMinute(new Date(2000, 0, 1, hour, 0), i18n.language)}
                </div>
              );
            })}
          </div>

          {/* Day columns */}
          {days.map((columnDay) => {
            const dayEvents = timedEvents.filter(
              e => dayKey(new Date(e.start)) === dayKey(columnDay),
            );
            const daySelected = selected.filter(
              s => dayKey(s.start) === dayKey(columnDay),
            );
            const jsDay = columnDay.getDay();
            const isToday = dayKey(columnDay) === todayKey;
            const isWeekend = jsDay === 0 || jsDay === 6;
            const colCls = [
              'calendar-day-column',
              isToday && 'is-today',
              isWeekend && 'is-weekend',
              drag && 'av-is-dragging',
            ].filter(Boolean).join(' ');
            return (
              <div
                key={dayKey(columnDay)}
                className={colCls}
                onMouseDown={(e) => handleColumnMouseDown(e, columnDay)}
              >
                {/* Hour slots (matches CalendarView) — 48 px each.
                    onMouseDown is wired here AS WELL AS on the column so
                    the picker reliably picks up the click even if some
                    layered element somehow blocks bubbling. */}
                {Array.from({ length: VISIBLE_HOURS }, (_, i) => {
                  const hour = DAY_START_HOUR + i;
                  const offHours = hour < WORKING_HOURS_START || hour >= WORKING_HOURS_END;
                  return (
                    <div
                      key={hour}
                      className={`calendar-hour-slot${offHours ? ' off-hours' : ''}`}
                      onMouseDown={(e) => {
                        // Manufacture a column-relative event by fixing the
                        // currentTarget to the parent column. The handler
                        // reads `e.currentTarget.getBoundingClientRect()`
                        // for column-relative coords.
                        const col = (e.currentTarget as HTMLElement).parentElement as HTMLElement | null;
                        if (!col) return;
                        const synthetic = {
                          ...e,
                          currentTarget: col,
                          target: e.target,
                          button: e.button,
                          clientX: e.clientX,
                          clientY: e.clientY,
                          preventDefault: () => e.preventDefault(),
                          stopPropagation: () => e.stopPropagation(),
                        } as unknown as React.MouseEvent<HTMLDivElement>;
                        handleColumnMouseDown(synthetic, columnDay);
                      }}
                    />
                  );
                })}

                {/* "Now" indicator on today's column */}
                {isToday && <NowLine columnDay={columnDay} />}

                {/* Existing busy events — same .calendar-event styling
                    as the user's Calendar tab. Color comes from the event's
                    own color (Google Calendar colorId or hex), surfaced
                    via the same `--event-color` CSS variable that
                    CalendarView.css uses for its background gradient. */}
                {dayEvents.map(ev => {
                  const start = new Date(ev.start);
                  const end = new Date(ev.end);
                  const top = Math.max(0, dateToMinutes(start, columnDay) * PIXELS_PER_MINUTE);
                  const height = Math.max(
                    16,
                    (dateToMinutes(end, columnDay) - dateToMinutes(start, columnDay)) * PIXELS_PER_MINUTE,
                  );
                  if (top + height < 0) return null;
                  if (top > VISIBLE_HOURS * PIXELS_PER_HOUR) return null;
                  // Color resolution mirrors CalendarView's chain:
                  // event.color/colorId → exact label name → label
                  // subject_prefix → built-in prefix heuristic.
                  const titleLower = (ev.title || '').toLowerCase();
                  const color = resolveEventColor(ev)
                    || labelColorMap.get(titleLower)
                    || labelPrefixColors.find(({ prefix }) => titleLower.startsWith(prefix))?.color;
                  const evStyle = color
                    ? ({
                        top,
                        height,
                        '--event-color': color,
                        borderLeftColor: color,
                        background: `color-mix(in srgb, ${color} 10%, var(--surface-primary))`,
                      } as React.CSSProperties)
                    : { top, height };
                  // Add CalendarView's variant class so deep-work and work-
                  // block events get the same treatment as in your Calendar
                  // tab (mint green for "Emails", amber for "Travail
                  // personnel" with a matching left-border accent).
                  const cal = (ev as unknown as { calendarId?: string }).calendarId;
                  const variant =
                    cal === '__deep_work__' ? ' calendar-event--deep-work' :
                    cal === '__work_block__' ? ' calendar-event--work-block' :
                    '';
                  return (
                    <div
                      key={ev.id}
                      className={`calendar-event av-event-readonly${variant}`}
                      style={evStyle}
                      title={ev.title || t('busy_unnamed')}
                    >
                      <span className="calendar-event-title">
                        {ev.title || t('busy_unnamed')}
                      </span>
                    </div>
                  );
                })}

                {/* Selected availability slots */}
                {daySelected.map(s => {
                      // If a resize is active for this slot, render the in-progress
                      // range instead of the committed one (so the user sees the
                      // edge moving live).
                      const live = drag && drag.kind === 'resizing' && drag.slotId === s.id
                        ? {
                            start: minutesToDate(columnDay, Math.min(drag.anchorMin, drag.currentMin)),
                            end: minutesToDate(columnDay, Math.max(drag.anchorMin, drag.currentMin)),
                          }
                        : { start: s.start, end: s.end };
                      const top = dateToMinutes(live.start, columnDay) * PIXELS_PER_MINUTE;
                      const height =
                        (dateToMinutes(live.end, columnDay) - dateToMinutes(live.start, columnDay))
                        * PIXELS_PER_MINUTE;
                      return (
                        <div
                          key={s.id}
                          className="av-slot"
                          style={{ top, height }}
                        >
                          <div
                            className="av-slot-resize av-slot-resize--top"
                            data-slot-id={s.id}
                            data-edge="top"
                            aria-hidden="true"
                          />
                          <span className="av-slot-time">
                            {fmtSlotLabel(live.start, live.end, i18n.language)}
                          </span>
                          <button
                            type="button"
                            className="av-slot-remove"
                            onMouseDown={(e) => e.stopPropagation()}
                            onClick={(e) => { e.stopPropagation(); handleRemoveSlot(s.id); }}
                            aria-label={tc('delete', 'Remove')}
                          >
                            <CloseIcon size={11} />
                          </button>
                          <div
                            className="av-slot-resize av-slot-resize--bottom"
                            data-slot-id={s.id}
                            data-edge="bottom"
                            aria-hidden="true"
                          />
                        </div>
                      );
                    })}

                    {/* Live "ghost" slot during a creating drag */}
                    {drag && drag.kind === 'creating'
                      && dayKey(drag.columnDay) === dayKey(columnDay)
                      && drag.moved && (() => {
                        const startMin = Math.min(drag.anchorMin, drag.currentMin);
                        const endMin = Math.max(drag.anchorMin, drag.currentMin);
                        const ghostTop = startMin * PIXELS_PER_MINUTE;
                        const ghostHeight = (endMin - startMin) * PIXELS_PER_MINUTE;
                        const ghostStart = minutesToDate(columnDay, startMin);
                        const ghostEnd = minutesToDate(columnDay, endMin);
                        return (
                          <div className="av-slot av-slot--ghost" style={{ top: ghostTop, height: ghostHeight }}>
                            <span className="av-slot-time">
                              {fmtSlotLabel(ghostStart, ghostEnd, i18n.language)}
                            </span>
                          </div>
                        );
                      })()}
              </div>
            );
          })}
        </div>

        {/* Floating dock pill — Superhuman-style: small, centered at the
            bottom of the screen. The hint text floats just above as its
            own tooltip, only while no slot is selected. Cancel = Esc;
            kept as a discreet ghost button for mouse users. */}
        <div className="av-dock-floating">
          {selected.length === 0 && (
            <div className="av-dock-hint" role="status">
              {t('select_times_hint')}
            </div>
          )}
          <div className="av-dock">
            <DurationChip
              value={duration as number}
              onChange={(v) => setDuration(v)}
              t={t as unknown as (key: string, ...args: unknown[]) => string}
            />
            <span className="av-dock-tz" title={userTimezone}>{tzLabel}</span>
            <button
              type="button"
              className="av-dock-cancel"
              onClick={handleClose}
            >
              {tc('cancel', 'Cancel')}
            </button>
            <button
              type="button"
              className="av-dock-insert"
              onClick={handleInsert}
              disabled={selected.length === 0 || loading}
            >
              {t('insert')}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function NowLine({ columnDay }: { columnDay: Date }) {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);
  if (dayKey(now) !== dayKey(columnDay)) return null;
  const minutes = dateToMinutes(now, columnDay);
  if (minutes < 0 || minutes > VISIBLE_HOURS * 60) return null;
  return <div className="av-now-line" style={{ top: minutesToPx(minutes) }} />;
}

function DurationChip({
  value,
  onChange,
  t,
}: {
  value: number;
  onChange: (v: number) => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  t: (key: string, ...args: any[]) => string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  return (
    <div className="av-duration-chip" ref={ref}>
      <button
        type="button"
        className="av-duration-trigger"
        onClick={() => setOpen(o => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>
        {t('duration_minutes', { count: value })}
      </button>
      {open && (
        <div className="av-duration-menu" role="listbox">
          {DURATION_OPTIONS_MIN.map(d => (
            <button
              key={d}
              type="button"
              role="option"
              aria-selected={d === value}
              className={`av-duration-option${d === value ? ' selected' : ''}`}
              onClick={() => { onChange(d); setOpen(false); }}
            >
              {t('duration_minutes', { count: d })}
              {d === value && (
                <CheckIcon size={12} />
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Slot label format — locale-aware via formatHourMinute (FR "8h00 – 8h30",
 * EN/ES "08:00 – 08:30"). Follows the UI language (i18n.language, passed by the
 * caller), matching CalendarView's `formatTime` so the picker grid and the
 * Calendar tab render clock times in the same notation. Note: the prose that
 * actually gets inserted into the email uses availabilityFormatter (always "h",
 * by deliberate design) — this is only the on-screen picker label.
 */
function fmtSlotLabel(start: Date, end: Date, locale: string): string {
  return `${formatHourMinute(start, locale)} – ${formatHourMinute(end, locale)}`;
}
