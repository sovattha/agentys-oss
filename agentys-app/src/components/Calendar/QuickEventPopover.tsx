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
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import i18n from '../../i18n';
import { ContactAutocomplete } from '../compose';
import { RecurrencePicker } from './RecurrencePicker';
import { PickATimePicker } from './PickATimePicker';
import { apiClient, type CalendarEvent } from '../../services/api';
import { formatCompactDate, formatCompactDateTime, getOrdinalSuffix } from '../../utils/dateFormat';
import { fmtClockTime } from '../../utils/availabilityFormatter';
import { fetchLabels, createLabel } from '../../api/labels';
import { pushModalOpen, popModalOpen } from '../../utils/modalOpenFlag';
import type { Label } from '../../types/labels';
import type { ContactGroup } from '../../hooks/useContactGroups';
import { RichTextEditor } from '../ui/RichTextEditor';
import { CloseIcon, CheckIcon, ChevronLeftIcon, ChevronRightIcon, SearchIcon } from '../icons/ActionIcons';

// Domaines connus par provider — utilisés pour détecter une incompatibilité cross-provider
// sur la fonctionnalité "Voir les créneaux" (free/busy inter-provider non supporté)
const GMAIL_DOMAINS = new Set(['gmail.com', 'googlemail.com']);
const OUTLOOK_DOMAINS = new Set(['outlook.com', 'hotmail.com', 'live.com', 'msn.com', 'hotmail.fr', 'live.fr']);

/** Retourne true si le free/busy est exploitable avec ce provider pour ces participants. */
export function isFreeBusyCompatible(attendees: string[], provider?: string): boolean {
  if (attendees.length === 0) return false;
  return !attendees.some(email => {
    const domain = email.split('@')[1]?.toLowerCase() ?? '';
    if (provider === 'gmail') return OUTLOOK_DOMAINS.has(domain);
    if (provider === 'outlook') return GMAIL_DOMAINS.has(domain);
    return false;
  });
}

/** Encode notes + labels projet dans le champ description.
 *  Format : "notes\n[tags:enc1,enc2]" — noms encodés avec encodeURIComponent. */
export function buildDescriptionWithLabels(notes: string, labels: string[]): string {
  const base = notes.trim();
  if (labels.length === 0) return base;
  const tag = `[tags:${labels.map(encodeURIComponent).join(',')}]`;
  return base ? `${base}\n${tag}` : tag;
}

/** Calcule les coordonnées CSS du popover en fonction du rect d'ancrage et de la taille de la fenêtre.
 *  Fonction pure — testable sans DOM. */
export function computePopoverPosition(
  anchorRect: { top: number; left: number; right: number },
  viewportWidth: number,
  viewportHeight: number,
  popoverHeight: number,
): { left: number; top: number } {
  const popoverWidth = 480;
  const gap = 12;
  let left = anchorRect.right + gap;
  let top = anchorRect.top - 20;

  if (left + popoverWidth > viewportWidth - 20) {
    left = anchorRect.left - popoverWidth - gap;
  }
  if (left < 20) left = 20;

  const maxTop = viewportHeight - popoverHeight - 20;
  if (top > maxTop) top = maxTop;
  if (top < 20) top = 20;

  return { left, top };
}

/** Strip provider-injected boilerplate (Microsoft Teams, Google Meet, Zoom) from
 *  an event description so only the human-written note remains.
 *
 *  BUG-X009 fix (2026-05-17): external calendar events (synced from Teams/Meet)
 *  arrive with the user's note followed by 10–30 lines of join URLs, meeting IDs,
 *  secret codes, dial-in numbers and locale codes. Showing all of that raw in the
 *  Description pane is unreadable. We keep only the text BEFORE the first
 *  recognizable boilerplate marker.
 *
 *  2026-06-01 fix: booking systems (Acuity Scheduling) export descriptions as
 *  "Nom: … Téléphone: … E-mail: … Lieu ============ <zoom link> Infolettre
 *  ============ <newsletter pitch> <jotform links>". The useful contact header
 *  sits before the first "============" rule; everything after is boilerplate.
 *  We treat a run of "=" (with an optional single-word section header such as
 *  "Lieu"/"Infolettre") as a cut marker, inline or on its own line.
 */
export function stripExternalMeetingMetadata(description: string): string {
  if (!description) return description;
  // Markers seen across providers. We split on the FIRST hit and keep the head.
  // The thick horizontal rule (~50+ underscores) is the most reliable Teams
  // signal; the URL-anchored phrases catch the variants that omit the rule.
  const markers = [
    /_{20,}/,                                  // Teams' long horizontal rule
    /-{20,}/,                                  // Google Meet / Zoom separator
    /(?:\s|^)[^\s=]{1,24}\s*={5,}/,            // Acuity "Lieu ===" rule — swallow the single-word header before it
    /={8,}/,                                   // bare "============" rule (no header)
    /https?:\/\/app\.acuityscheduling\.com/i,  // Acuity booking-link boilerplate
    /Réunion Microsoft Teams[\s\S]*?(?:Cliquez|Join|<https?:)/i,
    /Microsoft Teams (?:meeting|Besprechung|réunion)/i,
    /(?:Join|Rejoindre|Beitreten) Microsoft Teams Meeting/i,
    /Cliquez ici pour vous joindre/i,
    /Click here to join the meeting/i,
    /Hier klicken, um an der Besprechung teilzunehmen/i,
    /<https:\/\/teams\.live\.com/i,
    /<https:\/\/teams\.microsoft\.com/i,
    /Join Zoom Meeting/i,
    /https:\/\/[^\s]*\.zoom\.us\//i,
    /Join with Google Meet/i,
    /https:\/\/meet\.google\.com\//i,
  ];
  let cutAt = description.length;
  for (const re of markers) {
    const m = re.exec(description);
    if (m && m.index < cutAt) cutAt = m.index;
  }
  return description.slice(0, cutAt).trim();
}

/** Parse une description et en extrait les notes propres + les labels encodés.
 *  BUG-004 fix : [tags:...] peut apparaître n'importe où dans la description (pas seulement à la fin).
 *  BUG-X009 fix : strip Teams/Meet/Zoom boilerplate before returning notes.
 */
export function parseDescriptionAndLabels(description: string): { notes: string; labels: string[] } {
  // Match [tags:...] anywhere in the string (possibly with surrounding newlines)
  const tagPattern = /\n?\[tags:([^\]]+)\]/g;
  const allLabels: string[] = [];
  let match: RegExpExecArray | null;
  while ((match = tagPattern.exec(description)) !== null) {
    const tags = match[1].split(',').map(s => { try { return decodeURIComponent(s.trim()); } catch { return s.trim(); } }).filter(Boolean);
    allLabels.push(...tags);
  }
  const withoutTags = description.replace(/\n?\[tags:[^\]]+\]/g, '').trim();
  const notes = stripExternalMeetingMetadata(withoutTags);
  return { notes, labels: allLabels };
}

/** Return a human-meaningful organizer to display, or null to hide the field.
 *
 *  2026-06-01 fix: Google returns the *calendar id* as `organizer.email` for
 *  events owned by a secondary/shared/resource calendar — e.g.
 *  `47f9e61e4f267a2cb9173be1af598ec880047dbffc92938ac687d7f937596…@group.calendar.google.com`.
 *  Surfacing that long hex hash as the "Organisateur" is meaningless. The
 *  backend (normalize_organizer) now prefers the display name and drops the
 *  hash, but this guard also hides it for already-cached events that still
 *  carry the raw id. A real email/name passes through unchanged.
 */
export function formatOrganizer(organizer: string | null | undefined): string | null {
  const v = (organizer || '').trim();
  if (!v) return null;
  if (/@[\w.-]*calendar\.google\.com$/i.test(v)) return null;  // opaque Google calendar id
  const local = v.split('@')[0];
  if (/^[0-9a-f]{30,}$/i.test(local)) return null;             // bare hex hash, no/garbage domain
  return v;
}

// Google Calendar event colorIds (1-11) — used to map label hex colors
const GCAL_COLORS: [string, string][] = [
  ['1', '#7986cb'], ['2', '#33b679'], ['3', '#8e24aa'], ['4', '#e67c73'],
  ['5', '#f6bf26'], ['6', '#f4511e'], ['7', '#039be5'], ['8', '#616161'],
  ['9', '#3f51b5'], ['10', '#0b8043'], ['11', '#d50000'],
];

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '');
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

/** Map a hex color to the nearest Google Calendar colorId ("1"-"11"). */
export function hexToGcalColorId(hex: string): string {
  const [r, g, b] = hexToRgb(hex);
  let best = '3'; // default: grape
  let bestDist = Infinity;
  for (const [id, ref] of GCAL_COLORS) {
    const [rr, rg, rb] = hexToRgb(ref);
    const d = (r - rr) ** 2 + (g - rg) ** 2 + (b - rb) ** 2;
    if (d < bestDist) { bestDist = d; best = id; }
  }
  return best;
}

/**
 * Applique ou retire le préfixe de sujet du label dans le titre de l'événement.
 * - Sélection : préfixe ajouté si titre vide ou commence par l'ancien préfixe
 * - Désélection : préfixe retiré si le titre commence par lui
 * - Titre saisi manuellement (hors préfixe) : jamais écrasé
 */
export function applyLabelPrefix(
  currentTitle: string,
  newPrefix: string | undefined | null,
  prevPrefix: string | undefined | null,
): string {
  // Normalise le préfixe : toujours terminé par un espace
  const fmt = (p: string | undefined | null): string =>
    p ? (p.trimEnd() + ' ') : '';

  const prev = fmt(prevPrefix);
  const next = fmt(newPrefix);

  // Partie du titre saisie par l'utilisateur (hors préfixe actif)
  const userPart = prev && currentTitle.startsWith(prev)
    ? currentTitle.slice(prev.length)
    : currentTitle;

  if (next) {
    // Titre vide ou composé uniquement d'espaces → préfixe seul, sans espaces parasites
    if (!currentTitle.trim()) return next;
    // Titre commençait par l'ancien préfixe → remplacer le préfixe, conserver la suite
    if (prev && currentTitle.startsWith(prev)) return next + userPart;
    return currentTitle; // titre saisi manuellement → ne pas écraser
  }

  // Suppression du préfixe (désélection du label)
  if (prev && currentTitle.startsWith(prev)) {
    return userPart;
  }
  return currentTitle;
}

export interface QuickEventData {
  title: string;
  startTime: string;
  endTime: string;
  attendees: string[];
  location?: string;
  description?: string;
  labels?: string[];
  colorId?: string;
  reminders?: number[];
  recurrence?: string;
  allDay?: boolean;
  conference?: boolean;
  /** Source calendar id, so an edit/update targets the right (e.g. secondary) calendar. */
  calendarId?: string;
}

/** Pre-fill data for editing an existing event */
export interface EditEventData {
  eventId: string;
  title: string;
  start: string;
  end: string;
  location?: string;
  description?: string;
  attendees?: string[];
  isAllDay?: boolean;
  conference?: boolean;
  /** Source calendar id — carried back into the update so secondary/shared events save. */
  calendarId?: string;
}

interface QuickEventPopoverProps {
  date: Date;
  hour: number;
  endHour?: number;
  endMinute?: number;
  anchorRect: DOMRect;
  onSave: (data: QuickEventData) => Promise<void>;
  onClose: () => void;
  /** Local-only events (Deep Work) invisible to freebusy API */
  localEvents?: CalendarEvent[];
  /** Authenticated user's email — used to detect non-Google attendees */
  userEmail?: string;
  /** When set, popover is in edit mode with pre-filled data */
  editEvent?: EditEventData;
  /** Called instead of onSave when editing */
  onUpdate?: (eventId: string, data: QuickEventData) => Promise<void>;
  /** Calendar provider — 'gmail' or 'outlook' — to show correct conference label */
  calendarProvider?: string;
}

// Quick duration presets — replace the old piecewise slider, which
// duplicated the time row (slider said "1h00" while the row said
// "12:00 – 13:00"). The four most-used durations are one click away; any
// other duration is set by editing the end time directly in the When row.
const DURATION_PRESETS: readonly number[] = [30, 60, 90, 120];

/** "30m", "1h", "1h30", "2h" — no padded minutes on the hour. */
function formatDurationLabel(mins: number): string {
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m === 0 ? `${h}h` : `${h}h${String(m).padStart(2, '0')}`;
}

// Reminder options — label for "None" is resolved at render time via i18n
const REMINDER_OPTIONS_RAW = [
  { labelKey: 'qe_reminder_none', label: '', value: 0 },
  { labelKey: '', label: '5min', value: 5 },
  { labelKey: '', label: '15min', value: 15 },
  { labelKey: '', label: '30min', value: 30 },
  { labelKey: '', label: '1h', value: 60 },
];

// Strict YYYY-MM-DD parse with calendar validation. Returns null for
// malformed strings AND for impossible dates (Feb 30, Nov 31, etc.) which
// the JS Date constructor would otherwise silently roll over.
function parseCompactDate(s: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s.trim());
  if (!m) return null;
  const y = parseInt(m[1], 10);
  const mo = parseInt(m[2], 10) - 1;
  const d = parseInt(m[3], 10);
  const date = new Date(y, mo, d);
  if (date.getFullYear() !== y || date.getMonth() !== mo || date.getDate() !== d) return null;
  return date;
}

function toISOLocal(date: Date, hour: number, minute: number): string {
  const d = new Date(date);
  d.setHours(hour, minute, 0, 0);
  // Send as UTC — backend forwards to Google/Outlook with "timeZone: UTC"
  return d.toISOString();
}

const QE_DAY_LABELS = ['L', 'M', 'M', 'J', 'V', 'S', 'D'];

function getQeMonthNames(): string[] {
  return Array.from({ length: 12 }, (_, m) =>
    new Date(2000, m, 1).toLocaleString(i18n.language, { month: 'long' })
      .replace(/^./, c => c.toUpperCase())
  );
}

function buildQeCalendarDays(year: number, month: number): (number | null)[] {
  const firstDay = new Date(year, month, 1).getDay(); // 0=Sun
  const offset = (firstDay + 6) % 7; // Mon-first
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells: (number | null)[] = [];
  for (let i = 0; i < offset; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  return cells;
}

function toLocalDateStr(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

export function QuickEventPopover({
  date: propDate, hour: propHour, endHour: propEndHour, endMinute: propEndMinute, anchorRect, onSave, onClose, localEvents, editEvent, onUpdate, calendarProvider,
}: QuickEventPopoverProps) {
  const { t } = useTranslation('calendar');

  // Resolve reminder labels (first one needs i18n)
  const REMINDER_OPTIONS = REMINDER_OPTIONS_RAW.map(opt =>
    opt.labelKey ? { ...opt, label: t(opt.labelKey) } : opt
  );

  const isEditMode = !!editEvent;

  // Pre-fill from editEvent when in edit mode
  const [title, setTitle] = useState(editEvent?.title ?? '');
  const [eventDate, setEventDate] = useState(() => {
    if (editEvent) return new Date(editEvent.start);
    return propDate;
  });
  const [showDatePicker, setShowDatePicker] = useState(false);
  const [calYear, setCalYear] = useState(eventDate.getFullYear());
  const [calMonth, setCalMonth] = useState(eventDate.getMonth());
  const datePickerRef = useRef<HTMLButtonElement>(null);
  const [startHour, setStartHour] = useState(() => {
    if (editEvent) return new Date(editEvent.start).getHours();
    return propHour;
  });
  const [startMinute, setStartMinute] = useState(() => {
    if (editEvent) return new Date(editEvent.start).getMinutes();
    return 0;
  });
  const [hourText, setHourText] = useState(() => String(startHour).padStart(2, '0'));
  const [minuteText, setMinuteText] = useState(() => String(startMinute).padStart(2, '0'));
  // Typeable date input. Mirror of eventDate as YYYY-MM-DD; synced whenever
  // eventDate is reset programmatically (suggestion pick, calendar picker)
  // via the effect below. Strict format on commit; revert on invalid.
  const [dateText, setDateText] = useState(() => formatCompactDate(eventDate));
  const [showMinutePicker, setShowMinutePicker] = useState(false);
  const [duration, setDuration] = useState(() => {
    if (editEvent) {
      const s = new Date(editEvent.start).getTime();
      const e = new Date(editEvent.end).getTime();
      return Math.round((e - s) / 60000);
    }
    return propEndHour != null ? ((propEndHour - propHour) * 60 + (propEndMinute || 0)) : 60;
  });
  // End time is derived from start + duration, but shown in editable inputs
  // (same boxes as the start time). These mirror the derived value; a manual
  // edit commits back into `duration` on blur.
  const [endHourText, setEndHourText] = useState(() =>
    String(Math.floor((startHour * 60 + startMinute + duration) / 60) % 24).padStart(2, '0'));
  const [endMinuteText, setEndMinuteText] = useState(() =>
    String((startHour * 60 + startMinute + duration) % 60).padStart(2, '0'));
  const [attendeesStr, setAttendeesStr] = useState(editEvent?.attendees?.join(', ') ?? '');
  const [saving, setSaving] = useState(false);
  const [showLocation, setShowLocation] = useState(!!editEvent?.location);
  const [showNotes, setShowNotes] = useState(!!editEvent?.description);
  const [showReminder, setShowReminder] = useState(false);
  const [showRecurrence, setShowRecurrence] = useState(false);
  const [showLabelPicker, setShowLabelPicker] = useState(false);
  const [projectLabels, setProjectLabels] = useState<Label[]>([]);
  const labelPickerRef = useRef<HTMLDivElement>(null);
  const [newLabelName, setNewLabelName] = useState('');
  const [creatingLabel, setCreatingLabel] = useState(false);
  const [createLabelError, setCreateLabelError] = useState<string | null>(null);

  // En mode édition, parser la description existante pour séparer notes et labels
  const parsedEdit = editEvent?.description ? parseDescriptionAndLabels(editEvent.description) : null;
  const [selectedLabels, setSelectedLabels] = useState<string[]>(parsedEdit?.labels ?? []);

  const [location, setLocation] = useState(editEvent?.location ?? '');
  const [notes, setNotes] = useState(parsedEdit?.notes ?? editEvent?.description ?? '');
  const [reminder, setReminder] = useState(30);
  const [recurrence, setRecurrence] = useState<string | null>(null);
  const allDay = editEvent?.isAllDay ?? false;
  const [conference, setConference] = useState(editEvent?.conference ?? false);
  const [showScheduler, setShowScheduler] = useState(false);

  // Top-3 inline slot suggestions — auto-loaded when attendees are present
  // and the provider supports free/busy. Each suggestion is clickable to
  // apply to the form. The full picker is one click away via the link below.
  const [topSlots, setTopSlots] = useState<{ start: string; end: string }[] | null>(null);
  const [topSlotsLoading, setTopSlotsLoading] = useState(false);
  const topSlotsTokenRef = useRef(0);

  const [slotConfirm, setSlotConfirm] = useState<string | null>(null);
  const slotConfirmTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [asapError, setAsapError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const workStart = 8;
  const workEnd = 17;

  const [contactGroups, setContactGroups] = useState<ContactGroup[]>([]);
  const [addedGroupIds, setAddedGroupIds] = useState<Set<string>>(new Set());
  const [attachmentName, setAttachmentName] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Groupes de contacts suggérés : ceux dont label_name correspond à un label sélectionné
  const suggestedGroups = useMemo(() =>
    contactGroups.filter(g => g.label_name && selectedLabels.includes(g.label_name)),
    [contactGroups, selectedLabels],
  );

  const popoverRef = useRef<HTMLDivElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const [, forcePositionUpdate] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => titleRef.current?.focus(), 80);
    // Same lifecycle: clear the slot-confirm badge timer if the popover
    // unmounts while it's still pending (otherwise setSlotConfirm fires
    // after unmount and React warns).
    return () => {
      clearTimeout(t);
      if (slotConfirmTimerRef.current) {
        clearTimeout(slotConfirmTimerRef.current);
        slotConfirmTimerRef.current = null;
      }
    };
  }, []);

  // Keep the typeable date input synced with eventDate when the date is
  // updated programmatically (suggestion click, calendar picker). Manual
  // typing only updates dateText — eventDate is committed on blur/Enter,
  // so this effect doesn't fire mid-typing.
  useEffect(() => {
    setDateText(formatCompactDate(eventDate));
  }, [eventDate]);

  // Recalcule la position quand la hauteur du popover change (contenu dynamique).
  // requestAnimationFrame garantit qu'on lit offsetHeight après le repaint (F2: race condition).
  // Also re-positions on window scroll/resize so the popover stays anchored
  // when the underlying calendar grid scrolls under it.
  useEffect(() => {
    const el = popoverRef.current;
    const bump = () => requestAnimationFrame(() => forcePositionUpdate(n => n + 1));
    const ro = el ? new ResizeObserver(bump) : null;
    if (el && ro) ro.observe(el);
    window.addEventListener('resize', bump);
    window.addEventListener('scroll', bump, true);
    return () => {
      ro?.disconnect();
      window.removeEventListener('resize', bump);
      window.removeEventListener('scroll', bump, true);
    };
  }, []);

  // Fermer le label picker sur clic extérieur
  useEffect(() => {
    if (!showLabelPicker) return;
    const handler = (e: MouseEvent) => {
      if (labelPickerRef.current && !labelPickerRef.current.contains(e.target as Node)) {
        setShowLabelPicker(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showLabelPicker]);

  // Mini-calendar helpers

  const QE_MONTH_NAMES = useMemo(() => getQeMonthNames(), [i18n.language]);
  const qeCalDays = useMemo(() => buildQeCalendarDays(calYear, calMonth), [calYear, calMonth]);
  const today = useMemo(() => new Date(), []);


  // Charger les labels projet et les groupes de contacts au montage
  useEffect(() => {
    let cancelled = false;
    fetchLabels().then(res => {
      if (!cancelled) setProjectLabels(res.labels.filter(l => l.is_project === true));
    }).catch(() => { /* silencieux — labels non critiques */ });
    apiClient.listContactGroups().then(res => {
      if (!cancelled) setContactGroups(res.groups ?? []);
    }).catch(() => { /* silencieux — groupes non critiques */ });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      // Hierarchical close: if a sub-picker is open, close it first instead
      // of nuking the whole popover and losing in-progress edits.
      if (showDatePicker) { setShowDatePicker(false); return; }
      if (showMinutePicker) { setShowMinutePicker(false); return; }
      if (showLabelPicker) { setShowLabelPicker(false); return; }
      onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose, showDatePicker, showMinutePicker, showLabelPicker]);

  // Suppress app-level global shortcuts (N, Quick Step hotkeys, …) while
  // the event form is open. Refcounted so overlapping owners (App modals,
  // shadcn dialogs) can't race and leave the flag stuck.
  useEffect(() => {
    pushModalOpen();
    return popModalOpen;
  }, []);

  const totalStartMin = startHour * 60 + startMinute;
  const totalEndMin = totalStartMin + duration;
  const endHour = Math.floor(totalEndMin / 60);
  const endMinute = totalEndMin % 60;

  // Mirror the derived end time into its editable inputs whenever the start
  // time or duration moves it (preset chip, wheel, scheduler pick).
  useEffect(() => {
    setEndHourText(String(endHour % 24).padStart(2, '0'));
    setEndMinuteText(String(endMinute).padStart(2, '0'));
  }, [endHour, endMinute]);

  // Commit a hand-typed end time back into `duration`. An end at or before
  // the start is read as next-day (Google Calendar behavior: 23:30 → 00:30).
  const commitEndTime = () => {
    const eh = Math.min(23, Math.max(0, parseInt(endHourText) || 0));
    const em = Math.min(59, Math.max(0, parseInt(endMinuteText) || 0));
    const endTotal = eh * 60 + em;
    setDuration(endTotal > totalStartMin ? endTotal - totalStartMin : endTotal + 1440 - totalStartMin);
    setEndHourText(String(eh).padStart(2, '0'));
    setEndMinuteText(String(em).padStart(2, '0'));
  };

  const computeStyle = useCallback((): React.CSSProperties => {
    const popoverHeight = popoverRef.current?.offsetHeight || 520;
    const { left, top } = computePopoverPosition(
      anchorRect,
      window.innerWidth,
      window.innerHeight,
      popoverHeight,
    );
    return { position: 'fixed', left, top, width: 480, zIndex: 1100 };
  }, [anchorRect]);

  const updateTitleOnLabelChange = useCallback((prevLabels: string[], newLabels: string[]) => {
    const prevFirstLabel = projectLabels.find(l => l.name === prevLabels[0]);
    const newFirstLabel = projectLabels.find(l => l.name === newLabels[0]);
    const prevPrefix = prevFirstLabel?.subject_prefix ?? null;
    const newPrefix = newFirstLabel?.subject_prefix ?? null;
    if (prevPrefix !== newPrefix) {
      setTitle(current => applyLabelPrefix(current, newPrefix, prevPrefix));
    }
  }, [projectLabels]);

  // Gestionnaire commun pour sélectionner/désélectionner un label (dropdown + badge).
  // Ne modifie plus la durée ni la visio : l'utilisateur garde le contrôle total sur ces
  // paramètres (cf. rapport de refactor calendrier 2026-04-13 — kill auto-Meet surprise).
  const handleLabelToggle = useCallback((labelName: string, isSelected: boolean) => {
    const newLabels = isSelected
      ? selectedLabels.filter(n => n !== labelName)
      : [...selectedLabels, labelName];
    setSelectedLabels(newLabels);
    updateTitleOnLabelChange(selectedLabels, newLabels);
    return newLabels;
  }, [selectedLabels, updateTitleOnLabelChange]);

  const handleCreateLabel = useCallback(async () => {
    const name = newLabelName.trim();
    if (!name || creatingLabel) return;
    setCreatingLabel(true);
    setCreateLabelError(null);
    try {
      const palette = ['#3b82f6', '#22c55e', '#eab308', '#ec4899', '#8b5cf6', '#f97316'];
      const color = palette[projectLabels.length % palette.length];
      const res = await createLabel({ name, color, is_project: true });
      setProjectLabels(prev => [...prev, res.label]);
      setNewLabelName('');
      const prevSelected = selectedLabels;
      const newSelected = [...prevSelected, res.label.name];
      setSelectedLabels(newSelected);
      updateTitleOnLabelChange(prevSelected, newSelected);
      setShowLabelPicker(false);
    } catch (err) {
      setCreateLabelError(err instanceof Error ? err.message : t('qe_create_event_error'));
    } finally {
      setCreatingLabel(false);
    }
  }, [newLabelName, creatingLabel, projectLabels, selectedLabels, updateTitleOnLabelChange, t]);

  const handleAddGroup = useCallback((group: ContactGroup) => {
    const groupEmails = (group.members ?? []).map(m => m.email.toLowerCase());
    const currentParts = attendeesStr.split(',').map(s => s.trim()).filter(Boolean);
    const isAdded = addedGroupIds.has(group.id);

    if (isAdded) {
      // Toggle off — remove all emails from the group.
      const kept = currentParts.filter(p => !groupEmails.includes(p.toLowerCase()));
      setAttendeesStr(kept.join(', '));
      setAddedGroupIds(prev => {
        const next = new Set(prev);
        next.delete(group.id);
        return next;
      });
      return;
    }

    // Toggle on — add missing emails.
    const existing = new Set(currentParts.map(p => p.toLowerCase()));
    const newEmails = (group.members ?? [])
      .map(m => m.email)
      .filter(e => !existing.has(e.toLowerCase()));
    if (newEmails.length > 0) {
      const parts = [attendeesStr.trim(), ...newEmails].filter(Boolean);
      setAttendeesStr(parts.join(', '));
    }
    setAddedGroupIds(prev => new Set([...prev, group.id]));
    if (group.virtual_meeting) {
      setConference(true);
    }
  }, [attendeesStr, addedGroupIds]);

  const handleSave = async () => {
    if (!title.trim() || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      const attendees = attendeesStr
        .split(',')
        .map(s => s.trim())
        .filter(Boolean);

      const data: QuickEventData = {
        title: title.trim(),
        startTime: allDay
          ? toLocalDateStr(new Date(eventDate.getFullYear(), eventDate.getMonth(), eventDate.getDate()))
          : toISOLocal(eventDate, startHour, startMinute),
        endTime: allDay
          ? toLocalDateStr(new Date(eventDate.getFullYear(), eventDate.getMonth(), eventDate.getDate() + 1))
          : toISOLocal(eventDate, endHour, endMinute),
        attendees,
      };

      if (location.trim()) data.location = location.trim();
      // When editing, the notes field was seeded with the DISPLAY-stripped
      // description (join links / booking boilerplate hidden for readability).
      // If the user didn't touch the notes, rebuilding from that stripped text
      // would DESTROY the original join link / dial-in / contact info. So only
      // rewrite from `notes` when the user actually edited it; otherwise keep
      // the full original body and just re-encode the (possibly changed) labels.
      const notesUnchanged = isEditMode && !!editEvent && notes === (parsedEdit?.notes ?? '');
      const descSource = notesUnchanged
        ? (editEvent?.description || '').replace(/\n?\[tags:[^\]]+\]/g, '').trim()
        : notes;
      const desc = buildDescriptionWithLabels(descSource, selectedLabels);
      if (desc) data.description = desc;
      if (selectedLabels.length > 0) {
        data.labels = selectedLabels;
        const labelColor = projectLabels.find(l => l.name === selectedLabels[0])?.color;
        if (labelColor) data.colorId = hexToGcalColorId(labelColor);
      }
      if (reminder !== 30) data.reminders = reminder === 0 ? [] : [reminder];
      if (recurrence) data.recurrence = recurrence;
      if (allDay) data.allDay = true;
      if (conference) data.conference = true;
      // Carry the source calendar so an edit on a secondary/shared calendar
      // targets the right calendar (omitting it routed to 'primary' → 404 → revert).
      if (isEditMode && editEvent?.calendarId) data.calendarId = editEvent.calendarId;

      if (isEditMode && editEvent && onUpdate) {
        await onUpdate(editEvent.eventId, data);
      } else {
        await onSave(data);
      }
      // Own the close contract: callers also close optimistically today, but
      // a future caller shouldn't have to remember — onClose is idempotent.
      onClose();
    } catch {
      setSaveError(t('qe_create_event_error'));
    } finally {
      setSaving(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSave();
    }
  };

  const attendeesList = attendeesStr
    .split(',')
    .map(s => s.trim())
    .filter(Boolean);

  const freeBusyCompatible = isFreeBusyCompatible(attendeesList, calendarProvider);

  // Stable signature derived from the attendees STRING (not the array, whose
  // ref changes every render) so the suggestion fetch effect only re-runs
  // when the actual list of recipients changes.
  const attendeesKey = useMemo(() =>
    attendeesStr
      .split(',')
      .map(s => s.trim().toLowerCase())
      .filter(Boolean)
      .sort()
      .join(','),
    [attendeesStr],
  );

  const localEventsKey = useMemo(
    () => (localEvents ?? []).map(e => `${e.id}:${e.start}:${e.end}`).join('|'),
    [localEvents],
  );

  const handleSchedulerSelect = (start: string, end: string) => {
    const s = new Date(start);
    const e = new Date(end);
    const diffMin = Math.round((e.getTime() - s.getTime()) / 60000);

    setEventDate(new Date(s.getFullYear(), s.getMonth(), s.getDate()));
    setStartHour(s.getHours());
    setHourText(String(s.getHours()).padStart(2, '0'));
    setStartMinute(s.getMinutes());
    setMinuteText(String(s.getMinutes()).padStart(2, '0'));
    setDuration(diffMin);
    setShowScheduler(false);
    setAsapError(null);

    // Confirmation badge — timer is unmount-safe via slotConfirmTimerRef cleanup.
    setSlotConfirm(formatCompactDateTime(s));
    if (slotConfirmTimerRef.current) clearTimeout(slotConfirmTimerRef.current);
    slotConfirmTimerRef.current = setTimeout(() => {
      setSlotConfirm(null);
      slotConfirmTimerRef.current = null;
    }, 4000);
  };

  // Auto-fetch top-3 free slots (next 7 days) when attendees + filters
  // change. Debounced 350ms so typing in the attendee field doesn't
  // hammer the backend. Cleared when there are no attendees so stale
  // suggestions don't linger from a previous edit.
  useEffect(() => {
    if (!attendeesKey || !freeBusyCompatible) {
      setTopSlots(null);
      setTopSlotsLoading(false);
      return;
    }

    // `cancelled` gates the promise resolution paths so we don't call
    // setTopSlots/setTopSlotsLoading after the effect (or the component)
    // tears down. The token guard alone only suppresses stale-result
    // collisions between concurrent fetches.
    let cancelled = false;

    const handle = setTimeout(() => {
      const token = ++topSlotsTokenRef.current;
      setTopSlotsLoading(true);

      const now = new Date();
      const horizon = new Date(now);
      horizon.setDate(horizon.getDate() + 7);

      const extraBusy = (localEvents ?? [])
        .filter(ev => {
          const evStart = new Date(ev.start);
          const evEnd = new Date(ev.end);
          return evEnd > now && evStart < horizon;
        })
        .map(ev => ({ start: ev.start, end: ev.end }));

      apiClient.findFreeBusySlots({
        attendees: attendeesKey.split(','),
        start: now.toISOString(),
        end: horizon.toISOString(),
        duration_minutes: duration,
        work_hours_only: true,
        work_start: workStart,
        work_end: workEnd,
        extra_busy: extraBusy.length > 0 ? extraBusy : undefined,
      }).then(result => {
        if (cancelled || token !== topSlotsTokenRef.current) return;
        const future = (result.slots || []).filter(s => new Date(s.start) > new Date());
        setTopSlots(future.slice(0, 3));
      }).catch(() => {
        if (cancelled || token !== topSlotsTokenRef.current) return;
        setTopSlots([]);
      }).finally(() => {
        if (!cancelled && token === topSlotsTokenRef.current) setTopSlotsLoading(false);
      });
    }, 350);

    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
    // localEventsKey is the stable signature; localEvents itself reflows
    // every render even when the same set of events is present.

  }, [attendeesKey, duration, workStart, workEnd, freeBusyCompatible, localEventsKey]);


  // Count of visible optional fields (for row-delay stagger)
  let rowIdx = 1; // context=0, title=0, attendees=1 (toggles moved
                  // below When-row → now dynamic via ++rowIdx)

  return (
    <>
      <div className="qe-overlay" onClick={() => { if (!saving) onClose(); }} />

      <div
        ref={popoverRef}
        className="qe-popover"
        style={computeStyle()}
        onClick={e => e.stopPropagation()}
      >
        {/* Close button */}
        <button type="button" className="qe-close-btn" onClick={onClose} aria-label={t('qe_close')}>
          <CloseIcon size={14} />
        </button>

        {/* Context row — label chip + group-suggestion chips share a single
            horizontal line. Saves vertical space, and the cause-effect
            relationship (label → suggested groups for that label) reads
            more naturally side-by-side than stacked. */}
        <div className="qe-context-row">
        {/* Project label chip — tag icon opens full dropdown, shows selected label name */}
        {(() => {
          const hasSelection = selectedLabels.length > 0
          const hasLabels = projectLabels.length > 0
          // When a label is selected, the chip shows the label's name (and its
          // color) in place of the generic "Étiquette" text — same pattern as
          // group chips in ContactGroupsManager.
          const selectedLabelObjects = projectLabels.filter(l => selectedLabels.includes(l.name))
          const primaryLabel = selectedLabelObjects[0]
          const additionalCount = selectedLabelObjects.length - 1
          const chipStyle: React.CSSProperties | undefined = primaryLabel
            ? { color: primaryLabel.color, borderColor: primaryLabel.color }
            : undefined
          return (
            <div className="qe-label-pills" ref={labelPickerRef}>
              {/* Chip "Étiquette" — visuellement identique aux toggles (Lieu,
                  Notes, Rappel...) via `.qe-label-chip-toggle` qui partage les
                  styles de `.qe-toggle-btn` (voir CalendarView.css). Classe
                  distincte pour éviter que cette chip apparaisse dans les
                  sélecteurs `.qe-toggle-btn` utilisés par les tests E2E et ne
                  décale leurs indices `.nth(N)`. */}
              <button
                type="button"
                className={`qe-label-chip-toggle${hasSelection || showLabelPicker ? ' active' : ''}`}
                style={chipStyle}
                onClick={() => setShowLabelPicker(v => !v)}
                aria-expanded={showLabelPicker}
                aria-label={primaryLabel ? `${primaryLabel.name}${additionalCount > 0 ? ` +${additionalCount}` : ''}` : t('qe_label_toggle')}
              >
                <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" />
                  <line x1="7" y1="7" x2="7.01" y2="7" />
                </svg>
                {primaryLabel ? (
                  <>
                    {primaryLabel.name}
                    {additionalCount > 0 && <span className="qe-label-chip-more"> +{additionalCount}</span>}
                  </>
                ) : (
                  t('qe_label_toggle')
                )}
              </button>
              {showLabelPicker && !hasLabels && (
                <div className="qe-label-dropdown qe-label-dropdown--pills">
                  <div className="qe-label-create-inline" style={{ padding: '10px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <div style={{ fontSize: 12, color: '#6b7280' }}>{t('qe_label_create_hint', { defaultValue: 'Créer votre première étiquette' })}</div>
                    <input
                      type="text"
                      className="qe-field-input"
                      placeholder={t('qe_label_create_placeholder', { defaultValue: 'Ex. Réunion client' })}
                      value={newLabelName}
                      maxLength={40}
                      onChange={e => setNewLabelName(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === 'Enter') { e.preventDefault(); handleCreateLabel(); }
                        e.stopPropagation();
                      }}
                      autoFocus
                    />
                    <button
                      type="button"
                      className="qe-slot-browse-btn"
                      onClick={handleCreateLabel}
                      disabled={!newLabelName.trim() || creatingLabel}
                    >
                      {creatingLabel ? '…' : t('qe_label_create_btn', { defaultValue: 'Créer' })}
                    </button>
                    {createLabelError && <div className="qe-slot-error">{createLabelError}</div>}
                  </div>
                </div>
              )}
              {showLabelPicker && hasLabels && (
                <div className="qe-label-dropdown qe-label-dropdown--pills">
                  {projectLabels.map(label => {
                    const isSelected = selectedLabels.includes(label.name)
                    return (
                      <button
                        key={label.name}
                        type="button"
                        className={`qe-label-option${isSelected ? ' selected' : ''}`}
                        onMouseDown={e => e.stopPropagation()}
                        onClick={() => {
                          handleLabelToggle(label.name, isSelected)
                          setShowLabelPicker(false)
                        }}
                      >
                        <span className="qe-label-dot" style={{ background: label.color }} />
                        <span className="qe-label-name">{label.name}</span>
                        {label.is_favorite && (
                          <svg aria-hidden="true" className="qe-label-fav-star" width="11" height="11" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round">
                            <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                          </svg>
                        )}
                        {isSelected && (
                          <CheckIcon size={11} className="qe-label-option-check" />
                        )}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })()}

        {/* Groupes de contacts suggérés — juste après la ligne Étiquette (cause → conséquence) */}
        {suggestedGroups.length > 0 && (
          <div className="qe-group-suggestions" style={{ '--row-delay': '0.15' } as React.CSSProperties}>
            {suggestedGroups.map(group => {
              const isAdded = addedGroupIds.has(group.id);
              return (
                <button
                  key={group.id}
                  type="button"
                  className={`qe-group-chip${isAdded ? ' added' : ''}`}
                  onMouseDown={e => e.stopPropagation()}
                  onClick={() => handleAddGroup(group)}
                  aria-pressed={isAdded}
                  aria-label={`${group.name} (${group.members.length})`}
                  title={(group.members ?? []).map(m => (m.name || m.email).replace(/[\r\n\t]/g, ' ')).join(', ')}
                >
                  <span className="qe-group-chip-name">{group.name}</span>
                  {isAdded && (
                    <CheckIcon size={10} className="qe-group-chip-check" />
                  )}
                </button>
              );
            })}
          </div>
        )}
        </div>

        {/* Title */}
        <div className="qe-title-row" style={{ '--row-delay': '0' } as React.CSSProperties}>
          <input
            ref={titleRef}
            className="qe-title-input"
            type="text"
            placeholder={t('qe_new_event_placeholder')}
            value={title}
            onChange={e => setTitle(e.target.value)}
            onKeyDown={handleKeyDown}
            maxLength={200}
            aria-label={t('qe_event_title_label')}
          />
          <div className="qe-title-line" />
        </div>

        {/* Participants — always visible.
            Left silhouette icon masquée quand la ligne contient déjà des chips
            (chaque chip a son avatar avec initiales → icône redondante, gain
            d'espace horizontal sur les lignes qui wrap). */}
        <div className={`qe-attendees-row${attendeesStr.trim() ? ' qe-attendees-row--has-chips' : ''}`} style={{ '--row-delay': '1' } as React.CSSProperties}>
          <svg aria-hidden="true" className="qe-attendees-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" />
            <path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" />
          </svg>
          <ContactAutocomplete
            value={attendeesStr}
            onChange={setAttendeesStr}
            placeholder={t('qe_add_participants')}
            className="qe-contact-autocomplete"
            includeSelf
          />
        </div>

        {/* Smart scheduler — hidden when cross-provider (Outlook↔Gmail
            free/busy unsupported). Notice + Workhours controls were removed
            from this popover; defaults (1h notice, 8–17 Mon–Fri) drive the
            suggestion API call. Users who need different windows go through
            "Browse more slots" (PickATimePicker). */}
        {freeBusyCompatible && (
          <div className="qe-field-row" style={{ '--row-delay': `${++rowIdx}` } as React.CSSProperties}>
              <div className="qe-slot-suggestions">
                <div className="qe-slot-suggestions-header">
                  <span>{t('qe_suggestions_label')}</span>
                </div>
                {topSlotsLoading && (!topSlots || topSlots.length === 0) ? (
                  <div className="qe-slot-suggestions-grid" aria-live="polite" aria-busy="true">
                    <span className="qe-slot-suggestion-skel" />
                    <span className="qe-slot-suggestion-skel" />
                    <span className="qe-slot-suggestion-skel" />
                  </div>
                ) : topSlots && topSlots.length === 0 ? (
                  <div className="qe-slot-suggestions-empty">
                    {t('qe_suggestions_empty')}
                  </div>
                ) : topSlots && topSlots.length > 0 ? (
                  <div className="qe-slot-suggestions-grid">
                  {topSlots.map((slot, i) => {
                    const s = new Date(slot.start);
                    const e = new Date(slot.end);
                    const lang = i18n.language || 'en';
                    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
                    const nowD = new Date();
                    const todayD = new Date(nowD.getFullYear(), nowD.getMonth(), nowD.getDate());
                    const tomorrowD = new Date(todayD);
                    tomorrowD.setDate(tomorrowD.getDate() + 1);
                    const slotDay = new Date(s.getFullYear(), s.getMonth(), s.getDate());
                    // English-locale day labels use the user's preferred
                    // ordinal style ("May 18th"); other locales fall back to
                    // the native "DD MMM" pattern from Intl.DateTimeFormat
                    // since ordinal suffixes (-st, -nd, -rd, -th) are
                    // English-specific and look broken in FR/ES/DE.
                    const isEnglish = lang.startsWith('en');
                    let dayLabel: string;
                    if (slotDay.getTime() === todayD.getTime()) {
                      dayLabel = t('scheduler_today');
                    } else if (slotDay.getTime() === tomorrowD.getTime()) {
                      dayLabel = t('scheduler_tomorrow');
                    } else if (isEnglish) {
                      const monthShort = new Intl.DateTimeFormat(lang, { month: 'short' }).format(s);
                      dayLabel = `${monthShort} ${getOrdinalSuffix(s.getDate())}`;
                    } else {
                      dayLabel = new Intl.DateTimeFormat(lang, { month: 'short', day: 'numeric' }).format(s);
                    }
                    // Derived selection — a slot is "selected" when the
                    // current form state (date + start hour/minute + duration)
                    // matches it. handleSchedulerSelect writes exactly those
                    // fields so the match is reliable after a pick. If the
                    // user opens the popover on a cell-clicked slot that
                    // happens to coincide with a free slot, that's a happy
                    // alignment — show it as already-selected.
                    const slotDurationMin = Math.round((e.getTime() - s.getTime()) / 60000);
                    const isSelected =
                      eventDate.getFullYear() === s.getFullYear() &&
                      eventDate.getMonth() === s.getMonth() &&
                      eventDate.getDate() === s.getDate() &&
                      startHour === s.getHours() &&
                      startMinute === s.getMinutes() &&
                      duration === slotDurationMin;
                    return (
                      <button
                        key={`${slot.start}-${i}`}
                        type="button"
                        className={`qe-slot-suggestion${i === 0 ? ' is-earliest' : ''}${isSelected ? ' selected' : ''}`}
                        onClick={() => handleSchedulerSelect(slot.start, slot.end)}
                        aria-pressed={isSelected}
                        title={`${dayLabel} ${fmtClockTime(s, lang, tz)} – ${fmtClockTime(e, lang, tz)}`}
                      >
                        {isSelected ? (
                          <CheckIcon size={12} className="qe-slot-suggestion-corner" aria-label={t('qe_suggestion_selected', { defaultValue: 'Selected' })} />
                        ) : i === 0 ? (
                          <svg
                            aria-label={t('qe_suggestion_earliest')}
                            className="qe-slot-suggestion-corner qe-slot-suggestion-corner--bolt"
                            width="11" height="11" viewBox="0 0 24 24" fill="currentColor"
                          >
                            <path d="m13 2-2 14h6L9 22l2-14H5l6-6z" />
                          </svg>
                        ) : null}
                        <span className="qe-slot-suggestion-day">{dayLabel}</span>
                        <span className="qe-slot-suggestion-time">
                          {fmtClockTime(s, lang, tz)} – {fmtClockTime(e, lang, tz)}
                        </span>
                      </button>
                    );
                  })}
                  </div>
                ) : null}
                <button
                  type="button"
                  className="qe-slot-browse-link"
                  onClick={() => setShowScheduler(true)}
                >
                  <SearchIcon size={12} />
                  {t('qe_browse_more_slots')}
                </button>
              </div>
            {slotConfirm && (
              <div className="qe-slot-confirm">
                <CheckIcon size={12} />
                {slotConfirm}
              </div>
            )}
            {asapError && (
              <div className="qe-slot-error">{asapError}</div>
            )}
          </div>
        )}

        {/* When — date + time editor. Always visible: the user wants both
            suggested times AND a directly editable date/time field on
            screen at the same time. The date input is typeable
            (YYYY-MM-DD); the calendar icon to its right opens the
            existing grid picker. */}
        <div className="qe-when-row" style={{ '--row-delay': `${++rowIdx}` } as React.CSSProperties}>
          <svg aria-hidden="true" className="qe-when-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
          {/* Boxed field — input + calendar-picker button live INSIDE one
              bordered box (same family as the time digit boxes) instead of
              the icon floating after the field. */}
          <div className="qe-date-field">
            <input
              type="text"
              className="qe-when-date qe-when-date--input"
              value={dateText}
              inputMode="numeric"
              maxLength={10}
              placeholder="YYYY-MM-DD"
              title={t('qe_change_date')}
              aria-label={t('qe_change_date')}
              onChange={e => setDateText(e.target.value)}
              onFocus={e => e.target.select()}
              onBlur={() => {
                const parsed = parseCompactDate(dateText);
                if (parsed) {
                  setEventDate(parsed);
                } else {
                  setDateText(formatCompactDate(eventDate));
                }
              }}
              onKeyDown={e => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  (e.target as HTMLInputElement).blur();
                } else if (e.key === 'Escape') {
                  e.preventDefault();
                  setDateText(formatCompactDate(eventDate));
                  (e.target as HTMLInputElement).blur();
                }
              }}
            />
            <button
              ref={datePickerRef}
              type="button"
              className="qe-when-date-picker-btn"
              onClick={() => {
                setCalYear(eventDate.getFullYear());
                setCalMonth(eventDate.getMonth());
                setShowDatePicker(p => !p);
              }}
              title={t('qe_change_date')}
              aria-label={t('qe_open_picker', { defaultValue: 'Open calendar picker' })}
            >
              <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                <line x1="16" y1="2" x2="16" y2="6" />
                <line x1="8" y1="2" x2="8" y2="6" />
                <line x1="3" y1="10" x2="21" y2="10" />
              </svg>
            </button>
          </div>
          {showDatePicker && (() => {
            const rect = datePickerRef.current?.getBoundingClientRect();
            const dpTop = rect ? rect.bottom + 6 : 100;
            const dpLeft = rect ? rect.left : 100;
            return createPortal(
            <>
              <div className="qe-dp-backdrop" onMouseDown={() => setShowDatePicker(false)} />
              <div className="qe-date-picker" style={{ top: dpTop, left: dpLeft }}>
                <div className="qe-dp-header">
                  <button type="button" className="qe-dp-nav" onClick={() => {
                    if (calMonth === 0) { setCalMonth(11); setCalYear(y => y - 1); }
                    else setCalMonth(m => m - 1);
                  }} aria-label={t('prev_month')}><ChevronLeftIcon size={16} /></button>
                  <span className="qe-dp-month">{QE_MONTH_NAMES[calMonth]} {calYear}</span>
                  <button type="button" className="qe-dp-nav" onClick={() => {
                    if (calMonth === 11) { setCalMonth(0); setCalYear(y => y + 1); }
                    else setCalMonth(m => m + 1);
                  }} aria-label={t('next_month')}><ChevronRightIcon size={16} /></button>
                </div>
                <div className="qe-dp-grid">
                  {QE_DAY_LABELS.map((d, i) => (
                    <span key={i} className="qe-dp-dow">{d}</span>
                  ))}
                  {qeCalDays.map((day, i) => {
                    if (!day) return <span key={`e-${i}`} />;
                    const isSelected = eventDate.getFullYear() === calYear && eventDate.getMonth() === calMonth && eventDate.getDate() === day;
                    const isToday = today.getFullYear() === calYear && today.getMonth() === calMonth && today.getDate() === day;
                    return (
                      <button
                        key={day}
                        type="button"
                        className={['qe-dp-day', isToday ? 'today' : '', isSelected ? 'selected' : ''].filter(Boolean).join(' ')}
                        onClick={() => {
                          const next = new Date(eventDate);
                          next.setFullYear(calYear, calMonth, day);
                          setEventDate(next);
                          setShowDatePicker(false);
                        }}
                      >
                        {day}
                      </button>
                    );
                  })}
                </div>
              </div>
            </>,
            document.body
          ); })()}
          {!allDay && (
            <span className="qe-when-times">
              <span className="qe-time-inputs">
                <input
                  className="qe-time-digit"
                  value={hourText}
                  inputMode="numeric"
                  maxLength={2}
                  title={t('qe_change_time')}
                  onWheel={e => {
                    e.preventDefault();
                    const nh = (startHour + (e.deltaY < 0 ? 1 : -1) + 24) % 24;
                    setStartHour(nh);
                    setHourText(String(nh).padStart(2, '0'));
                  }}
                  onChange={e => {
                    const raw = e.target.value.replace(/\D/g, '').slice(0, 2);
                    setHourText(raw);
                  }}
                  onBlur={() => {
                    const nh = Math.min(23, Math.max(0, parseInt(hourText) || 0));
                    setStartHour(nh);
                    setHourText(String(nh).padStart(2, '0'));
                  }}
                  onFocus={e => e.target.select()}
                />
                <span className="qe-time-colon">:</span>
                <div className="qe-minute-wrap">
                  <input
                    className="qe-time-digit"
                    value={minuteText}
                    inputMode="numeric"
                    maxLength={2}
                    onClick={() => setShowMinutePicker(p => !p)}
                    onWheel={e => {
                      e.preventDefault();
                      const nm = (startMinute + (e.deltaY < 0 ? 5 : -5) + 60) % 60;
                      setStartMinute(nm);
                      setMinuteText(String(nm).padStart(2, '0'));
                    }}
                    onChange={e => {
                      const raw = e.target.value.replace(/\D/g, '').slice(0, 2);
                      setMinuteText(raw);
                    }}
                    onBlur={() => {
                      const nm = Math.min(59, Math.max(0, parseInt(minuteText) || 0));
                      setStartMinute(nm);
                      setMinuteText(String(nm).padStart(2, '0'));
                      setShowMinutePicker(false);
                    }}
                    onFocus={e => e.target.select()}
                  />
                  {showMinutePicker && (
                    <div className="qe-minute-picker">
                      {['00', '15', '30', '45'].map(v => (
                        <button
                          key={v}
                          type="button"
                          className={`qe-minute-opt${startMinute === Number(v) ? ' active' : ''}`}
                          onMouseDown={e => {
                            e.preventDefault();
                            setStartMinute(Number(v));
                            setMinuteText(v);
                            setShowMinutePicker(false);
                          }}
                        >
                          {v}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </span>
              <span className="qe-when-dash">&ndash;</span>
              {/* End time — editable, styled exactly like the start inputs
                  (it used to be plain text, which read as non-editable). */}
              <span className="qe-time-inputs">
                <input
                  className="qe-time-digit"
                  value={endHourText}
                  inputMode="numeric"
                  maxLength={2}
                  title={t('qe_change_time')}
                  aria-label={t('qe_end_time_label', { defaultValue: 'End time' })}
                  onWheel={e => {
                    e.preventDefault();
                    const nd = duration + (e.deltaY < 0 ? 60 : -60);
                    if (nd >= 15 && nd <= 1440) setDuration(nd);
                  }}
                  onChange={e => setEndHourText(e.target.value.replace(/\D/g, '').slice(0, 2))}
                  onBlur={commitEndTime}
                  onFocus={e => e.target.select()}
                />
                <span className="qe-time-colon">:</span>
                <input
                  className="qe-time-digit"
                  value={endMinuteText}
                  inputMode="numeric"
                  maxLength={2}
                  title={t('qe_change_time')}
                  aria-label={t('qe_end_time_label', { defaultValue: 'End time' })}
                  onWheel={e => {
                    e.preventDefault();
                    const nd = duration + (e.deltaY < 0 ? 5 : -5);
                    if (nd >= 15 && nd <= 1440) setDuration(nd);
                  }}
                  onChange={e => setEndMinuteText(e.target.value.replace(/\D/g, '').slice(0, 2))}
                  onBlur={commitEndTime}
                  onFocus={e => e.target.select()}
                />
              </span>
            </span>
          )}
        </div>

        {/* Duration — quick preset chips right under the time row. Any other
            duration is set by editing the end time directly. */}
        {!allDay && (
          <div
            className="qe-duration-presets"
            role="group"
            aria-label={t('qe_duration_label', { defaultValue: 'Duration' })}
            style={{ '--row-delay': `${++rowIdx}` } as React.CSSProperties}
          >
            {DURATION_PRESETS.map(mins => (
              <button
                key={mins}
                type="button"
                className={`qe-duration-preset${duration === mins ? ' active' : ''}`}
                aria-pressed={duration === mins}
                onClick={() => setDuration(mins)}
              >
                {formatDurationLabel(mins)}
              </button>
            ))}
            {!DURATION_PRESETS.includes(duration) && (
              <span className="qe-duration-custom-label">{formatDurationLabel(duration)}</span>
            )}
          </div>
        )}

        {/* Toggle buttons row for optional fields. Positioned below the
            When-row so the primary path (title → time → create) reads
            top-to-bottom uninterrupted; the toggles + their expanded
            bodies (Location, Notes, Reminder, Recurrence) cluster at the
            bottom as a single "additional details" zone. */}
        <div className="qe-toggles-row" style={{ '--row-delay': `${++rowIdx}` } as React.CSSProperties}>
          <button
            type="button"
            className={`qe-toggle-btn${showLocation ? ' active' : ''}`}
            onClick={() => setShowLocation(!showLocation)}
          >
            <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" /><circle cx="12" cy="10" r="3" />
            </svg>
            {t('qe_location_toggle')}
          </button>
          <button
            type="button"
            className={`qe-toggle-btn${showNotes ? ' active' : ''}`}
            onClick={() => setShowNotes(!showNotes)}
          >
            <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="17" x2="7" y1="10" y2="10" /><line x1="17" x2="7" y1="14" y2="14" /><line x1="14" x2="7" y1="18" y2="18" />
              <path d="M3 6h18" />
            </svg>
            {t('qe_notes_toggle')}
          </button>
          <button
            type="button"
            className={`qe-toggle-btn${showReminder ? ' active' : ''}`}
            onClick={() => setShowReminder(!showReminder)}
          >
            <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
            </svg>
            {t('qe_reminder_toggle')}
          </button>
          <button
            type="button"
            className={`qe-toggle-btn${showRecurrence ? ' active' : ''}`}
            onClick={() => setShowRecurrence(!showRecurrence)}
          >
            <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="17 1 21 5 17 9" /><path d="M3 11V9a4 4 0 0 1 4-4h14" />
              <polyline points="7 23 3 19 7 15" /><path d="M21 13v2a4 4 0 0 1-4 4H3" />
            </svg>
            {t('qe_recurrence_toggle')}
          </button>
          <button
            type="button"
            className={`qe-toggle-btn${conference ? ' active' : ''}`}
            onClick={() => setConference(!conference)}
          >
            <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="m22 8-6 4 6 4V8Z" /><rect width="14" height="12" x="2" y="6" rx="2" ry="2" />
            </svg>
            {calendarProvider === 'gmail' ? 'Google Meet' : calendarProvider === 'outlook' ? 'Teams' : t('qe_video_toggle')}
            {conference && <CheckIcon size={11} className="qe-toggle-check" />}
          </button>

          {/* Pièce jointe */}
          <input
            ref={fileInputRef}
            type="file"
            style={{ display: 'none' }}
            onChange={e => {
              const file = e.target.files?.[0];
              if (file) setAttachmentName(file.name);
            }}
          />
          <button
            type="button"
            className={`qe-toggle-btn${attachmentName ? ' active' : ''}`}
            onClick={() => fileInputRef.current?.click()}
          >
            <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
            </svg>
            {attachmentName ?? t('qe_attachment')}
          </button>
        </div>

        {showLocation && (
          <div className="qe-field-row" style={{ '--row-delay': `${++rowIdx}` } as React.CSSProperties}>
            <svg aria-hidden="true" className="qe-field-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" /><circle cx="12" cy="10" r="3" />
            </svg>
            <input
              type="text"
              className="qe-field-input"
              placeholder={t('qe_add_location')}
              value={location}
              onChange={e => setLocation(e.target.value)}
              onKeyDown={handleKeyDown}
              aria-label={t('qe_location_label')}
            />
          </div>
        )}

        {showNotes && (
          <div className="qe-field-row qe-field-row--notes" style={{ '--row-delay': `${++rowIdx}` } as React.CSSProperties}>
            <div className="qe-field-rte-wrap">
              <RichTextEditor
                value={notes}
                onChange={setNotes}
                placeholder={t('qe_add_notes')}
                ariaLabel={t('qe_notes_label')}
                minHeight={70}
                enableSnippets={false}
              />
            </div>
          </div>
        )}

        {showReminder && (
          <div className="qe-field-row" style={{ '--row-delay': `${++rowIdx}` } as React.CSSProperties}>
            <svg aria-hidden="true" className="qe-field-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
            </svg>
            <div className="qe-reminder-track">
              {REMINDER_OPTIONS.map(opt => (
                <button
                  key={opt.value}
                  type="button"
                  className={`qe-reminder-seg${reminder === opt.value ? ' active' : ''}`}
                  onClick={() => setReminder(opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {showRecurrence && (
          <div className="qe-field-row qe-field-row--recurrence" style={{ '--row-delay': `${++rowIdx}` } as React.CSSProperties}>
            <RecurrencePicker
              value={recurrence}
              onChange={setRecurrence}
              date={eventDate}
            />
          </div>
        )}

        {/* Save error */}
        {saveError && (
          <div className="qe-slot-error">{saveError}</div>
        )}

        {/* Footer */}
        <div className="qe-footer" style={{ '--row-delay': `${rowIdx + 1}` } as React.CSSProperties}>
          <button
            type="button"
            className="qe-cancel-btn"
            onClick={() => { if (!saving) onClose(); }}
            disabled={saving}
          >
            {t('qe_cancel_btn', { defaultValue: 'Cancel' })}
          </button>
          <button
            className={`qe-save-btn${saving ? ' saving' : ''}`}
            onClick={handleSave}
            disabled={!title.trim() || saving}
            type="button"
          >
            {saving ? (
              <div className="qe-save-spinner" />
            ) : (
              t('qe_save_btn')
            )}
          </button>
        </div>
      </div>

      {showScheduler && (
        <PickATimePicker
          attendees={attendeesList}
          onSelectSlot={handleSchedulerSelect}
          onBack={() => setShowScheduler(false)}
          localEvents={localEvents}
          defaultDuration={duration}
          defaultWorkStart={workStart}
          defaultWorkEnd={workEnd}
        />
      )}
    </>
  );
}
