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
import { useTranslation } from 'react-i18next';
import i18n from '../i18n';
import { formatLongDateFromDate } from '../utils/dateFormat';
import { createPortal } from 'react-dom';
import { useAnimatedUnmount } from '../hooks/useAnimatedUnmount';
import { ChevronLeftIcon } from './icons/ActionIcons';
import './FollowupDatePicker.css';

interface FollowupDatePickerProps {
  position: { x: number; y: number; buttonTop?: number };
  emailBody?: string;
  onSelect: (date: Date) => void;
  onClose: () => void;
  forceCalendar?: boolean;
  /** Override the picker header — defaults to t('followup_picker_title'). */
  title?: string;
}

// Multilingual month/day dictionaries (FR + EN, full + abbreviated)
const MONTHS_MAP: Record<string, number> = {
  // FR
  janvier: 0, février: 1, fevrier: 1, mars: 2, avril: 3, mai: 4,
  juin: 5, juillet: 6, août: 7, aout: 7, septembre: 8, octobre: 9,
  novembre: 10, décembre: 11, decembre: 11,
  // EN full
  january: 0, february: 1, march: 2, april: 3, may: 4, june: 5,
  july: 6, august: 7, september: 8, october: 9, november: 10, december: 11,
  // EN abbreviated
  jan: 0, feb: 1, mar: 2, apr: 3, jun: 5, jul: 6, aug: 7,
  sept: 8, sep: 8, oct: 9, nov: 10, dec: 11,
};

const DAYS_MAP: Record<string, number> = {
  dimanche: 0, lundi: 1, mardi: 2, mercredi: 3, jeudi: 4, vendredi: 5, samedi: 6,
  sunday: 0, monday: 1, tuesday: 2, wednesday: 3, thursday: 4, friday: 5, saturday: 6,
};

// Build alternation strings, longest-first so e.g. "mars" wins over "mar"
const MONTH_ALT = Object.keys(MONTHS_MAP).sort((a, b) => b.length - a.length).join('|');
const DAY_ALT = Object.keys(DAYS_MAP).sort((a, b) => b.length - a.length).join('|');
const ORDINAL = '(?:st|nd|rd|th)?';

// "5 mai", "5th of May", "1st March"
const DAY_THEN_MONTH = new RegExp(`\\b(\\d{1,2})${ORDINAL}\\s+(?:of\\s+)?(${MONTH_ALT})\\b`, 'i');
// "May 5th", "mai 5", "Mar 21"
const MONTH_THEN_DAY = new RegExp(`\\b(${MONTH_ALT})\\s+(\\d{1,2})${ORDINAL}\\b`, 'i');
const DAY_NAME_PATTERN = new RegExp(`\\b(${DAY_ALT})\\b`, 'i');

// Phrases d'indisponibilité — une date dans ce contexte n'est PAS un engagement.
// Exemple : « je serai en vacances du 6 au 10 mai » → pas de rappel à programmer.
// FR + EN. NB: \b ne reconnaît PAS les lettres accentuées en regex JS — \b après
// « congé » ne matche jamais. On utilise donc des lookarounds Unicode-aware
// (Latin-1 Supplement + Latin Extended-A) pour les frontières de mot.
const _LETTER = '[A-Za-z\\u00C0-\\u024F]';
const NON_COMMITMENT_PATTERN = new RegExp(
  `(?<!${_LETTER})(?:` +
    // FR
    'vacances?|congés?|en\\s+vacances|en\\s+congé|absent[es]?|absence|férié[es]?|' +
    'fermé[es]?|fermeture|indisponibles?|hors\\s+ligne|hors\\s+bureau|' +
    'je\\s+serai\\s+(?:absent|en\\s+vacances|en\\s+congé|en\\s+déplacement|fermé)|' +
    'je\\s+suis\\s+(?:absent|en\\s+vacances|en\\s+congé|fermé)|' +
    'je\\s+ne\\s+serai\\s+pas|je\\s+ne\\s+suis\\s+pas\\s+(?:disponible|là|ici)|' +
    // EN
    'vacation|holiday|holidays|on\\s+leave|on\\s+pto|on\\s+annual\\s+leave|' +
    'out\\s+of\\s+office|ooo|away|unavailable|day\\s+off|days\\s+off|off\\s+work|' +
    'closed|closure|sick\\s+leave|business\\s+trip|travelling|traveling|' +
    'won[\'’]t\\s+be(?:\\s+(?:there|here|available|in))?|' +
    'will\\s+not\\s+be(?:\\s+(?:there|here|available|in))?|' +
    'i\\s+am\\s+off|i[\'’]m\\s+off|i\\s+am\\s+away|i[\'’]m\\s+away' +
  `)(?!${_LETTER})`,
  'i'
);

function getMonthNames(): string[] {
  return Array.from({ length: 12 }, (_, m) =>
    new Date(2000, m, 1).toLocaleString(i18n.language, { month: 'long' })
      .replace(/^./, c => c.toUpperCase())
  );
}

const DAY_LABELS = ['L', 'M', 'M', 'J', 'V', 'S', 'D'];

export function detectDateFromBody(body?: string): { date: Date; label: string } | null {
  if (!body) return null;

  // Decode HTML entities + strip tags via DOM (gère é, è, à, ù, ô, etc.)
  let text: string;
  try {
    const tmp = document.createElement('div');
    tmp.innerHTML = body;
    // Drop blocks tagged as availability proposals — those dates are
    // offered to the recipient, not commitments we owe ourselves a
    // reminder about. See formatAvailability's `agentys-availability`
    // wrapper.
    tmp.querySelectorAll('.agentys-availability').forEach(el => el.remove());
    text = tmp.textContent || tmp.innerText || '';
  } catch {
    // Fallback regex strip — also drops the availability wrapper.
    text = body
      .replace(/<div[^>]*class="[^"]*agentys-availability[^"]*"[^>]*>[\s\S]*?<\/div>/gi, ' ')
      .replace(/<[^>]+>/g, ' ');
  }
  // Normaliser les espaces insécables (\u00A0) produits par les éditeurs rich text
  text = text.replace(/\u00A0/g, ' ');

  // Indisponibilite (vacances, OOO, conges...) -> la date n'est pas un engagement
  if (NON_COMMITMENT_PATTERN.test(text)) return null;

  const now = new Date();

  // Date explicite — gère les deux ordres ("5 mai" et "May 5th") + suffixes ordinaux
  const dm = DAY_THEN_MONTH.exec(text);
  const md = MONTH_THEN_DAY.exec(text);
  let parsed: { day: number; month: number; index: number } | null = null;
  if (dm) {
    const m = MONTHS_MAP[dm[2].toLowerCase()];
    if (m !== undefined) parsed = { day: parseInt(dm[1]), month: m, index: dm.index };
  }
  if (md) {
    const m = MONTHS_MAP[md[1].toLowerCase()];
    if (m !== undefined && (!parsed || md.index < parsed.index)) {
      parsed = { day: parseInt(md[2]), month: m, index: md.index };
    }
  }
  if (parsed && parsed.day >= 1 && parsed.day <= 31) {
    const year = (parsed.month < now.getMonth() ||
      (parsed.month === now.getMonth() && parsed.day < now.getDate()))
      ? now.getFullYear() + 1
      : now.getFullYear();
    const target = new Date(year, parsed.month, parsed.day, 6, 0, 0, 0);
    if (target > now) {
      const label = formatLongDateFromDate(target, i18n.language || 'en');
      return { date: target, label };
    }
  }

  // Nom de jour vague (ex: "samedi", "monday") — fallback
  const dayMatch = DAY_NAME_PATTERN.exec(text);
  if (dayMatch) {
    const targetDay = DAYS_MAP[dayMatch[1].toLowerCase()];
    if (targetDay !== undefined) {
      const currentDay = now.getDay();
      let daysAhead = targetDay - currentDay;
      if (daysAhead <= 0) daysAhead += 7;
      const target = new Date(now);
      target.setDate(target.getDate() + daysAhead);
      target.setHours(6, 0, 0, 0);
      const label = target.toLocaleDateString(i18n.language || undefined, { weekday: 'long' });
      return { date: target, label: label.charAt(0).toUpperCase() + label.slice(1) };
    }
  }

  return null;
}

function buildCalendarDays(year: number, month: number): (number | null)[] {
  const firstDay = new Date(year, month, 1).getDay();
  const offset = (firstDay + 6) % 7;
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells: (number | null)[] = [];
  for (let i = 0; i < offset; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  return cells;
}

export function FollowupDatePicker({ position, emailBody, onSelect, onClose, forceCalendar, title }: FollowupDatePickerProps) {
  const { t } = useTranslation('common');

  const MONTH_NAMES = useMemo(() => getMonthNames(), [i18n.language]);
  const ref = useRef<HTMLDivElement>(null);
  const [adjustedPos, setAdjustedPos] = useState(position);
  const { isClosing, handleClose } = useAnimatedUnmount(true, onClose);
  const [showCalendar, setShowCalendar] = useState(() => forceCalendar || !detectDateFromBody(emailBody));
  // true si l'utilisateur a explicitement cliqué "Choisir une autre date"
  const [userNavigatedToCalendar, setUserNavigatedToCalendar] = useState(false);

  const today = new Date();
  const [calYear, setCalYear] = useState(today.getFullYear());
  const [calMonth, setCalMonth] = useState(today.getMonth());
  const [selectedDay, setSelectedDay] = useState<number | null>(null);
  const [timeValue, setTimeValue] = useState('09:00');

  const smartDate = useMemo(() => detectDateFromBody(emailBody), [emailBody]);

  // Si emailBody arrive après le mount (éditeur rich text chargé en différé),
  // basculer vers la vue suggestion dès qu'une date est détectée — sauf si
  // l'utilisateur a explicitement choisi le calendrier ou forceCalendar est actif.
  useEffect(() => {
    if (!forceCalendar && !userNavigatedToCalendar && smartDate) {
      setShowCalendar(false);
    }
  }, [smartDate, forceCalendar, userNavigatedToCalendar]);

  // Adjust position to stay within viewport, flipping above the button if needed
  useEffect(() => {
    if (!ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const x = Math.min(position.x, window.innerWidth - rect.width - 8);
    let y = position.y;
    // If the picker would overflow below the viewport and we know the button's top, flip above
    if (y + rect.height > window.innerHeight - 8 && position.buttonTop !== undefined) {
      y = position.buttonTop - rect.height - 4;
    }
    setAdjustedPos({ x: Math.max(8, x), y: Math.max(8, Math.min(y, window.innerHeight - rect.height - 8)) });
  }, [position, showCalendar]);

  // Close on outside click or Escape
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        handleClose();
      }
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') handleClose();
    };
    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [handleClose]);

  const calDays = useMemo(() => buildCalendarDays(calYear, calMonth), [calYear, calMonth]);

  const prevMonth = useCallback(() => {
    if (calMonth === 0) { setCalMonth(11); setCalYear(y => y - 1); }
    else setCalMonth(m => m - 1);
    setSelectedDay(null);
  }, [calMonth]);

  const nextMonth = useCallback(() => {
    if (calMonth === 11) { setCalMonth(0); setCalYear(y => y + 1); }
    else setCalMonth(m => m + 1);
    setSelectedDay(null);
  }, [calMonth]);

  const isPast = useCallback((day: number) => {
    // Aujourd'hui est sélectionnable : on compare uniquement la date (sans l'heure)
    const d = new Date(calYear, calMonth, day);
    const todayDate = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    return d < todayDate;
  }, [calYear, calMonth, today]);

  const isToday = useCallback((day: number) => {
    return calYear === today.getFullYear() && calMonth === today.getMonth() && day === today.getDate();
  }, [calYear, calMonth, today]);

  const handleDayClick = useCallback((day: number) => {
    if (isPast(day)) return;
    setSelectedDay(day);
  }, [isPast]);

  const handleConfirm = useCallback(() => {
    if (!selectedDay) return;
    const [h, m] = timeValue.split(':').map(Number);
    const date = new Date(calYear, calMonth, selectedDay, h, m, 0, 0);
    onSelect(date);
  }, [selectedDay, timeValue, calYear, calMonth, onSelect]);

  return createPortal(
    <div
      ref={ref}
      className={`followup-picker${isClosing ? ' closing' : ''}`}
      style={{ left: adjustedPos.x, top: adjustedPos.y }}
      data-escape-owner=""
    >
      <div className="followup-picker-title">{title ?? t('followup_picker_title')}</div>

      {!showCalendar ? (
        <>
          {smartDate && (
            <button className="followup-picker-option smart" onClick={() => onSelect(smartDate.date)}>
              <span className="followup-picker-icon">&#9889;</span>
              <span className="followup-picker-label">{smartDate.label}</span>
              <span className="followup-picker-badge">{t('followup_picker_detected')}</span>
            </button>
          )}

          <div className="followup-picker-divider" />

          <button className="followup-picker-option followup-picker-calendar-trigger" onClick={() => { setShowCalendar(true); setUserNavigatedToCalendar(true); }}>
            <span className="followup-picker-icon">📅</span>
            <span className="followup-picker-label">{t('followup_picker_choose_date')}</span>
          </button>
        </>
      ) : (
        <div className="followup-picker-calendar">
          <div className="followup-cal-header">
            <button className="followup-cal-nav" onClick={prevMonth} aria-label={t('prev_month')}>‹</button>
            <span className="followup-cal-month">{MONTH_NAMES[calMonth]} {calYear}</span>
            <button className="followup-cal-nav" onClick={nextMonth} aria-label={t('next_month')}>›</button>
          </div>

          <div className="followup-cal-grid">
            {DAY_LABELS.map((d, i) => (
              <span key={i} className="followup-cal-dow">{d}</span>
            ))}

            {calDays.map((day, i) => {
              if (!day) return <span key={`empty-${i}`} />;
              const past = isPast(day);
              const tod = isToday(day);
              const sel = selectedDay === day;
              return (
                <button
                  key={day}
                  className={[
                    'followup-cal-day',
                    past ? 'past' : '',
                    tod ? 'today' : '',
                    sel ? 'selected' : '',
                  ].filter(Boolean).join(' ')}
                  onClick={() => handleDayClick(day)}
                  disabled={past}
                  aria-label={`${day} ${MONTH_NAMES[calMonth]}`}
                  aria-pressed={sel}
                >
                  {day}
                </button>
              );
            })}
          </div>

          <div className="followup-cal-footer">
            <div className="followup-cal-time-row">
              <span className="followup-cal-time-label">{t('followup_picker_time')}</span>
              <input
                type="time"
                className="followup-cal-time-input"
                value={timeValue}
                onChange={(e) => setTimeValue(e.target.value || '09:00')}
                aria-label={t('followup_picker_time')}
              />
            </div>
            <div className="followup-cal-actions">
              {smartDate && (
                <button className="followup-cal-back" onClick={() => { setShowCalendar(false); setSelectedDay(null); }}>
                  <ChevronLeftIcon size={14} /> {t('back')}
                </button>
              )}
              <button
                className="followup-cal-confirm"
                disabled={!selectedDay}
                onClick={handleConfirm}
              >
                {t('confirm')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>,
    document.body
  );
}
