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

import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { FrenchDatePicker } from '../ui/FrenchDatePicker';

interface RecurrencePickerProps {
  value: string | null;
  onChange: (rrule: string | null) => void;
  date: Date;
}

type Frequency = 'DAILY' | 'WEEKLY' | 'MONTHLY' | 'YEARLY';
type EndType = 'never' | 'count' | 'until';

// DAY_LABELS removed — now derived from i18n common:days_short via DAY_KEYS
const DAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const;
const DAY_CODES = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'];

// FREQ_LABELS moved inside component for i18n — see useFreqLabels below
const FREQ_LABEL_KEYS: { value: Frequency; key: string }[] = [
  { value: 'DAILY', key: 'recurrence_day' },
  { value: 'WEEKLY', key: 'recurrence_week' },
  { value: 'MONTHLY', key: 'recurrence_month' },
  { value: 'YEARLY', key: 'recurrence_year' },
];

function getDayCode(date: Date): string {
  const jsDay = date.getDay(); // 0=Sun
  const idx = jsDay === 0 ? 6 : jsDay - 1;
  return DAY_CODES[idx];
}

function buildRrule(
  freq: Frequency,
  interval: number,
  byDay: string[],
  byMonthDay: number | null,
  endType: EndType,
  endCount: number,
  endDate: string,
): string {
  let rule = `RRULE:FREQ=${freq}`;
  if (interval > 1) rule += `;INTERVAL=${interval}`;
  if (freq === 'WEEKLY' && byDay.length > 0) {
    rule += `;BYDAY=${byDay.join(',')}`;
  }
  if (freq === 'MONTHLY' && byMonthDay) {
    rule += `;BYMONTHDAY=${byMonthDay}`;
  }
  if (endType === 'count') {
    rule += `;COUNT=${endCount}`;
  } else if (endType === 'until' && endDate) {
    rule += `;UNTIL=${endDate.replace(/-/g, '')}T235959Z`;
  }
  return rule;
}

export function RecurrencePicker({ value, onChange, date }: RecurrencePickerProps) {
  const { t } = useTranslation('calendar');
  const { t: tc } = useTranslation('common');

  const FREQ_LABELS = useMemo(() =>
    FREQ_LABEL_KEYS.map(f => ({ value: f.value, label: t(f.key) })),
    [t]
  );

  // Derive single-letter day labels from i18n (e.g. "Mon" → "M", "Lun" → "L")
  const dayLabels = useMemo(() =>
    DAY_KEYS.map(key => tc(`days_short.${key}`).charAt(0)),
    [tc]
  );

  const [showCustom, setShowCustom] = useState(false);
  const [freq, setFreq] = useState<Frequency>('WEEKLY');
  const [interval, setInterval] = useState(1);
  const [byDay, setByDay] = useState<string[]>([getDayCode(date)]);
  const [endType, setEndType] = useState<EndType>('never');
  const [endCount, setEndCount] = useState(10);
  const [endDate, setEndDate] = useState('');

  const byMonthDay = date.getDate();
  const currentDayCode = getDayCode(date);

  const presets = useMemo(() => [
    { label: t('recurrence_none'), value: null },
    { label: t('recurrence_daily'), value: 'RRULE:FREQ=DAILY' },
    { label: t('recurrence_weekly'), value: `RRULE:FREQ=WEEKLY;BYDAY=${currentDayCode}` },
    { label: t('recurrence_monthly'), value: `RRULE:FREQ=MONTHLY;BYMONTHDAY=${byMonthDay}` },
  ], [currentDayCode, byMonthDay, t]);

  const activePreset = presets.find(p => p.value === value);
  const isCustom = value && !activePreset;

  const handlePresetClick = (preset: typeof presets[0]) => {
    setShowCustom(false);
    onChange(preset.value);
  };

  const handleCustomToggle = () => {
    if (showCustom) {
      setShowCustom(false);
    } else {
      setShowCustom(true);
      // Initialize custom from current value or defaults
      if (!value) {
        const rule = buildRrule(freq, interval, byDay, byMonthDay, endType, endCount, endDate);
        onChange(rule);
      }
    }
  };

  const updateCustomRule = (
    newFreq?: Frequency,
    newInterval?: number,
    newByDay?: string[],
    newEndType?: EndType,
    newEndCount?: number,
    newEndDate?: string,
  ) => {
    const f = newFreq ?? freq;
    const i = newInterval ?? interval;
    const d = newByDay ?? byDay;
    const et = newEndType ?? endType;
    const ec = newEndCount ?? endCount;
    const ed = newEndDate ?? endDate;
    if (newFreq !== undefined) setFreq(f);
    if (newInterval !== undefined) setInterval(i);
    if (newByDay !== undefined) setByDay(d);
    if (newEndType !== undefined) setEndType(et);
    if (newEndCount !== undefined) setEndCount(ec);
    if (newEndDate !== undefined) setEndDate(ed);
    onChange(buildRrule(f, i, d, byMonthDay, et, ec, ed));
  };

  const toggleDay = (dayCode: string) => {
    const next = byDay.includes(dayCode)
      ? byDay.filter(d => d !== dayCode)
      : [...byDay, dayCode];
    if (next.length === 0) return; // At least 1 day required
    updateCustomRule(undefined, undefined, next);
  };


  return (
    <div className="qe-recurrence">
      {/* Preset pills */}
      <div className="qe-recurrence-presets">
        {presets.map(p => (
          <button
            key={p.label}
            type="button"
            className={`qe-recurrence-pill${value === p.value ? ' active' : ''}`}
            onClick={() => handlePresetClick(p)}
          >
            {p.label}
          </button>
        ))}
        <button
          type="button"
          className={`qe-recurrence-pill${isCustom || showCustom ? ' active' : ''}`}
          onClick={handleCustomToggle}
        >
          {t('recurrence_custom')}
        </button>
      </div>

      {/* Custom config (inline) */}
      {showCustom && (
        <div className="qe-recurrence-custom">
          {/* Frequency */}
          <div className="qe-recurrence-row">
            <span className="qe-recurrence-label">{t('recurrence_every')}</span>
            <input
              type="number"
              min={1}
              max={99}
              value={interval}
              onChange={e => updateCustomRule(undefined, Math.max(1, parseInt(e.target.value) || 1))}
              className="qe-recurrence-number"
              aria-label={t('recurrence_interval_label')}
            />
            <div className="qe-recurrence-freq-pills">
              {FREQ_LABELS.map(f => (
                <button
                  key={f.value}
                  type="button"
                  className={`qe-recurrence-freq-pill${freq === f.value ? ' active' : ''}`}
                  onClick={() => updateCustomRule(f.value)}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </div>

          {/* Weekday selector (only for WEEKLY) */}
          {freq === 'WEEKLY' && (
            <div className="qe-recurrence-row">
              <div className="qe-recurrence-days">
                {dayLabels.map((label, i) => (
                  <button
                    key={DAY_CODES[i]}
                    type="button"
                    className={`qe-recurrence-day${byDay.includes(DAY_CODES[i]) ? ' active' : ''}`}
                    onClick={() => toggleDay(DAY_CODES[i])}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* End condition */}
          <div className="qe-recurrence-row">
            <span className="qe-recurrence-label">{t('recurrence_end')}</span>
            <div className="qe-recurrence-end-pills">
              <button
                type="button"
                className={`qe-recurrence-freq-pill${endType === 'never' ? ' active' : ''}`}
                onClick={() => updateCustomRule(undefined, undefined, undefined, 'never')}
              >
                {t('recurrence_never')}
              </button>
              <button
                type="button"
                className={`qe-recurrence-freq-pill${endType === 'count' ? ' active' : ''}`}
                onClick={() => updateCustomRule(undefined, undefined, undefined, 'count')}
              >
                {t('recurrence_after')}
              </button>
              <button
                type="button"
                className={`qe-recurrence-freq-pill${endType === 'until' ? ' active' : ''}`}
                onClick={() => updateCustomRule(undefined, undefined, undefined, 'until')}
              >
                {t('recurrence_until')}
              </button>
            </div>
          </div>

          {endType === 'count' && (
            <div className="qe-recurrence-row">
              <input
                type="number"
                min={1}
                max={999}
                value={endCount}
                onChange={e => updateCustomRule(undefined, undefined, undefined, undefined, Math.max(1, parseInt(e.target.value) || 1))}
                className="qe-recurrence-number"
                aria-label={t('recurrence_count_label')}
              />
              <span className="qe-recurrence-label">{t('recurrence_times')}</span>
            </div>
          )}

          {endType === 'until' && (
            <div className="qe-recurrence-row">
              <FrenchDatePicker
                value={endDate}
                onChange={v => updateCustomRule(undefined, undefined, undefined, undefined, undefined, v)}
                min={(() => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; })()}
                ariaLabel={t('recurrence_end_date_label')}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
