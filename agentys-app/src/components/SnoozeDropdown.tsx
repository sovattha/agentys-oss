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

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import i18n from '../i18n';
import { createPortal } from 'react-dom';
import { useAnimatedUnmount } from '../hooks/useAnimatedUnmount';
import './SnoozeDropdown.css';

interface SnoozeDropdownProps {
  position: { x: number; y: number };
  emailBody?: string;
  onSnooze: (date: Date) => void;
  onClose: () => void;
}

function getMonthNames(): string[] {
  return Array.from({ length: 12 }, (_, m) =>
    new Date(2000, m, 1).toLocaleString(i18n.language, { month: 'long' })
      .replace(/^./, c => c.toUpperCase())
  );
}

const DAY_LABELS = ['L', 'M', 'M', 'J', 'V', 'S', 'D'];

/** Build the calendar grid for a given year/month (Mon-first weeks). */
function buildCalendarDays(year: number, month: number): (number | null)[] {
  const firstDay = new Date(year, month, 1).getDay(); // 0=Sun
  // Convert to Mon-first: Sun→6, Mon→0, …
  const offset = (firstDay + 6) % 7;
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells: (number | null)[] = [];
  for (let i = 0; i < offset; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  return cells;
}

export function SnoozeDropdown({ position, onSnooze, onClose }: SnoozeDropdownProps) {
  const { t } = useTranslation('inbox');
  const ref = useRef<HTMLDivElement>(null);
  const [adjustedPos, setAdjustedPos] = useState(position);
  const { isClosing, handleClose } = useAnimatedUnmount(true, onClose);
  const today = new Date();
  const [calYear, setCalYear] = useState(today.getFullYear());
  const [calMonth, setCalMonth] = useState(today.getMonth());
  const [selectedDay, setSelectedDay] = useState<number | null>(null);
  const [timeHour, setTimeHour] = useState('09');
  const [timeMinute, setTimeMinute] = useState('00');
  const [showMinutePicker, setShowMinutePicker] = useState(false);

  // Adjust position to stay within viewport
  useEffect(() => {
    if (!ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const x = Math.min(position.x, window.innerWidth - rect.width - 8);
    const y = Math.min(position.y, window.innerHeight - rect.height - 8);
    setAdjustedPos({ x: Math.max(8, x), y: Math.max(8, y) });
  }, [position]);

  // Close on Escape
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') handleClose();
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [handleClose]);


  const MONTH_NAMES = useMemo(() => getMonthNames(), [i18n.language]);
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
    const d = new Date(calYear, calMonth, day);
    d.setHours(23, 59, 59);
    return d < today;
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
    const date = new Date(calYear, calMonth, selectedDay, Number(timeHour), Number(timeMinute), 0, 0);
    onSnooze(date);
  }, [selectedDay, timeHour, timeMinute, calYear, calMonth, onSnooze]);

  return createPortal(
    <>
    <div className="snooze-backdrop" onMouseDown={handleClose} />
    <div
      ref={ref}
      className={`snooze-dropdown${isClosing ? ' closing' : ''}`}
      style={{ left: adjustedPos.x, top: adjustedPos.y }}
      data-escape-owner=""
    >
      <div className="snooze-dropdown-title" role="heading" aria-level={3}>{t('snooze_title')}</div>

      <div className="snooze-calendar">
        {/* Month navigation */}
        <div className="snooze-cal-header">
          <button className="snooze-cal-nav" onClick={prevMonth} aria-label={t('snooze_prev_month')}>‹</button>
          <span className="snooze-cal-month">{MONTH_NAMES[calMonth]} {calYear}</span>
          <button className="snooze-cal-nav" onClick={nextMonth} aria-label={t('snooze_next_month')}>›</button>
        </div>

        {/* Day-of-week labels */}
        <div className="snooze-cal-grid">
          {DAY_LABELS.map((d, i) => (
            <span key={i} className="snooze-cal-dow">{d}</span>
          ))}

          {/* Day cells */}
          {calDays.map((day, i) => {
            if (!day) return <span key={`empty-${i}`} />;
            const past = isPast(day);
            const tod = isToday(day);
            const sel = selectedDay === day;
            return (
              <button
                key={day}
                className={[
                  'snooze-cal-day',
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

        {/* Time picker + confirm */}
        <div className="snooze-cal-footer">
          <div className="snooze-cal-time-row">
            <span className="snooze-cal-time-label">{t('snooze_time_label')}</span>
            <div className="snooze-cal-time-digits">
              <input
                type="text"
                inputMode="numeric"
                className="snooze-cal-time-digit"
                value={timeHour}
                maxLength={2}
                onWheel={e => {
                  e.preventDefault();
                  const h = Number(timeHour);
                  const nh = (h + (e.deltaY < 0 ? 1 : -1) + 24) % 24;
                  setTimeHour(String(nh).padStart(2, '0'));
                }}
                onChange={e => {
                  const raw = e.target.value.replace(/\D/g, '').slice(0, 2);
                  setTimeHour(raw);
                }}
                onBlur={() => {
                  const nh = Math.min(23, Math.max(0, parseInt(timeHour) || 0));
                  setTimeHour(String(nh).padStart(2, '0'));
                }}
                onFocus={e => e.target.select()}
              />
              <span className="snooze-cal-time-sep">:</span>
              <div className="snooze-cal-minute-wrap">
                <input
                  type="text"
                  inputMode="numeric"
                  className="snooze-cal-time-digit"
                  value={timeMinute}
                  maxLength={2}
                  onClick={() => setShowMinutePicker(p => !p)}
                  onWheel={e => {
                    e.preventDefault();
                    const m = Number(timeMinute);
                    const nm = (m + (e.deltaY < 0 ? 15 : -15) + 60) % 60;
                    setTimeMinute(String(nm).padStart(2, '0'));
                  }}
                  onChange={e => {
                    const raw = e.target.value.replace(/\D/g, '').slice(0, 2);
                    setTimeMinute(raw);
                    setShowMinutePicker(false);
                  }}
                  onBlur={() => {
                    const nm = Math.min(59, Math.max(0, parseInt(timeMinute) || 0));
                    setTimeMinute(String(nm).padStart(2, '0'));
                  }}
                  onFocus={e => e.target.select()}
                  readOnly={showMinutePicker}
                />
                {showMinutePicker && (
                  <div className="snooze-cal-minute-picker">
                    {['00', '15', '30', '45'].map(v => (
                      <button
                        key={v}
                        type="button"
                        className={`snooze-cal-minute-opt${timeMinute === v ? ' active' : ''}`}
                        onMouseDown={e => {
                          e.preventDefault();
                          setTimeMinute(v);
                          setShowMinutePicker(false);
                        }}
                      >
                        {v}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
          <button
            className="snooze-cal-confirm"
            disabled={!selectedDay}
            onClick={handleConfirm}
          >
            {t('snooze_confirm')}
          </button>
        </div>
      </div>
    </div>
    </>,
    document.body
  );
}
