/* eslint-disable react-refresh/only-export-components */
/**
 * TimezoneUtils - Timezone hooks and components extracted from CalendarView
 *
 * Decoupled so that Sidebar can import timezone utilities without pulling
 * in FullCalendar (~200KB+) via the CalendarView dependency chain.
 */

import { useState, useEffect, useLayoutEffect, useMemo, useRef, useSyncExternalStore } from 'react';
import { useTranslation } from 'react-i18next';
import { createPortal } from 'react-dom';
import { CheckIcon } from './icons/ActionIcons';

// ── Storage keys ──

const TIMEZONE_STORAGE_KEY = 'agentys-calendar-tz2';
const TZ2_COLOR_STORAGE_KEY = 'agentys-calendar-tz2-color';

// ── Timezone presets ──

/** Popular timezone presets with short labels */
export const TIMEZONE_PRESETS: { tz: string; label: string; city: string; region?: string }[] = [
  { tz: '', label: '', city: 'tz_none' },
  // Americas
  { tz: 'Pacific/Honolulu', label: 'HNL', city: 'Honolulu', region: 'tz_americas' },
  { tz: 'America/Anchorage', label: 'ANC', city: 'Anchorage' },
  { tz: 'America/Los_Angeles', label: 'LA', city: 'Los Angeles' },
  { tz: 'America/Denver', label: 'DEN', city: 'Denver' },
  { tz: 'America/Chicago', label: 'CHI', city: 'Chicago' },
  { tz: 'America/New_York', label: 'NYC', city: 'New York' },
  { tz: 'America/Toronto', label: 'TOR', city: 'Toronto' },
  { tz: 'America/Mexico_City', label: 'MEX', city: 'Mexico' },
  { tz: 'America/Bogota', label: 'BOG', city: 'Bogota' },
  { tz: 'America/Sao_Paulo', label: 'SAO', city: 'São Paulo' },
  { tz: 'America/Argentina/Buenos_Aires', label: 'BUE', city: 'Buenos Aires' },
  // Europe & Africa
  { tz: 'Europe/London', label: 'LON', city: 'London', region: 'tz_europe_africa' },
  { tz: 'Europe/Paris', label: 'PAR', city: 'Paris' },
  { tz: 'Europe/Berlin', label: 'BER', city: 'Berlin' },
  { tz: 'Europe/Istanbul', label: 'IST', city: 'Istanbul' },
  { tz: 'Europe/Moscow', label: 'MSK', city: 'Moscow' },
  { tz: 'Africa/Cairo', label: 'CAI', city: 'Cairo' },
  { tz: 'Africa/Johannesburg', label: 'JNB', city: 'Johannesburg' },
  // Asia & Oceania
  { tz: 'Asia/Dubai', label: 'DXB', city: 'Dubai', region: 'tz_asia_oceania' },
  { tz: 'Asia/Kolkata', label: 'DEL', city: 'Delhi' },
  { tz: 'Asia/Bangkok', label: 'BKK', city: 'Bangkok' },
  { tz: 'Asia/Singapore', label: 'SIN', city: 'Singapore' },
  { tz: 'Asia/Hong_Kong', label: 'HKG', city: 'Hong Kong' },
  { tz: 'Asia/Shanghai', label: 'SHA', city: 'Shanghai' },
  { tz: 'Asia/Seoul', label: 'SEL', city: 'Seoul' },
  { tz: 'Asia/Tokyo', label: 'TYO', city: 'Tokyo' },
  { tz: 'Australia/Sydney', label: 'SYD', city: 'Sydney' },
  { tz: 'Pacific/Auckland', label: 'AKL', city: 'Auckland' },
];

/** Color presets for the secondary timezone column */
export const TZ2_COLOR_PRESETS = [
  { name: 'Orange', hue: '#d97706', dark: '#b45309' },
  { name: 'Blue', hue: '#2563eb', dark: '#1d4ed8' },
  { name: 'Purple', hue: '#7c3aed', dark: '#6d28d9' },
  { name: 'Pink', hue: '#db2777', dark: '#be185d' },
  { name: 'Green', hue: '#059669', dark: '#047857' },
  { name: 'Red', hue: '#dc2626', dark: '#b91c1c' },
];

// ── Helper functions ──

/** Get short label for a timezone IANA string */
export function getTzLabel(tz: string): string {
  const preset = TIMEZONE_PRESETS.find(p => p.tz === tz);
  if (preset) return preset.label;
  // Fallback: last part of IANA string
  const parts = tz.split('/');
  return parts[parts.length - 1].slice(0, 3).toUpperCase();
}

// ── Shared module-level stores (singleton — survives re-renders across components) ──

// Secondary timezone store
let _tz2Value = (() => { try { return localStorage.getItem(TIMEZONE_STORAGE_KEY) || ''; } catch { return ''; } })();
const _tz2Listeners = new Set<() => void>();
const _getTz2 = () => _tz2Value;
const _subscribeTz2 = (fn: () => void) => { _tz2Listeners.add(fn); return () => { _tz2Listeners.delete(fn); }; };
function _setTz2(newTz: string) {
  _tz2Value = newTz;
  try { localStorage.setItem(TIMEZONE_STORAGE_KEY, newTz); } catch { /* noop */ }
  _tz2Listeners.forEach(fn => fn());
}

// Tz2 color store
let _tz2ColorValue: typeof TZ2_COLOR_PRESETS[0] = (() => {
  try {
    const stored = localStorage.getItem(TZ2_COLOR_STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      return TZ2_COLOR_PRESETS.find(c => c.hue === parsed.hue) || TZ2_COLOR_PRESETS[0];
    }
  } catch { /* noop */ }
  return TZ2_COLOR_PRESETS[0];
})();
const _tz2ColorListeners = new Set<() => void>();
const _getTz2Color = () => _tz2ColorValue;
const _subscribeTz2Color = (fn: () => void) => { _tz2ColorListeners.add(fn); return () => { _tz2ColorListeners.delete(fn); }; };
function _setTz2Color(c: typeof TZ2_COLOR_PRESETS[0]) {
  _tz2ColorValue = c;
  try { localStorage.setItem(TZ2_COLOR_STORAGE_KEY, JSON.stringify(c)); } catch { /* noop */ }
  _tz2ColorListeners.forEach(fn => fn());
}

// ── Hooks ──

/** Hook to persist secondary timezone — shared across all instances via module-level store */
export function useSecondaryTimezone(): [string, (tz: string) => void] {
  const tz = useSyncExternalStore(_subscribeTz2, _getTz2, _getTz2);
  return [tz, _setTz2];
}

/** Hook to persist tz2 color — shared across all instances via module-level store */
export function useTz2Color(): [typeof TZ2_COLOR_PRESETS[0], (color: typeof TZ2_COLOR_PRESETS[0]) => void] {
  const color = useSyncExternalStore(_subscribeTz2Color, _getTz2Color, _getTz2Color);
  // Apply CSS custom properties whenever color changes
  useEffect(() => {
    document.documentElement.style.setProperty('--tz2-color', color.hue);
    document.documentElement.style.setProperty('--tz2-color-dark', color.dark);
  }, [color]);
  return [color, _setTz2Color];
}

// ── Components ──

/** Timezone picker dropdown */
export function TimezonePicker({
  value, onChange, tz2Color, onColorChange,
}: {
  value: string;
  onChange: (tz: string) => void;
  tz2Color: typeof TZ2_COLOR_PRESETS[0];
  onColorChange: (c: typeof TZ2_COLOR_PRESETS[0]) => void;
}) {
  const { t } = useTranslation('common');
  const [open, setOpen] = useState(false);
  const [dropdownMaxHeight, setDropdownMaxHeight] = useState(360);
  const [dropdownPos, setDropdownPos] = useState<{ left: number; top: number }>({ left: 0, top: 0 });
  const ref = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Adapt dropdown height and compute fixed position for portal
  useLayoutEffect(() => {
    if (!buttonRef.current || !open) return;
    const btnRect = buttonRef.current.getBoundingClientRect();
    const spaceBelow = window.innerHeight - btnRect.bottom - 10;
    setDropdownMaxHeight(Math.max(120, Math.min(360, spaceBelow)));
    let left = btnRect.left;
    const top = btnRect.bottom + 6;
    if (left + 220 > window.innerWidth - 8) left = window.innerWidth - 220 - 8;
    setDropdownPos({ left, top });
  }, [open]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const inTrigger = ref.current?.contains(e.target as Node);
      const inDropdown = dropdownRef.current?.contains(e.target as Node);
      if (!inTrigger && !inDropdown) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  // Group presets by region
  const groups = useMemo(() => {
    const result: { region: string; items: typeof TIMEZONE_PRESETS }[] = [];
    let currentGroup: typeof TIMEZONE_PRESETS = [];
    let currentRegion = '';
    for (const p of TIMEZONE_PRESETS.slice(1)) {
      if (p.region) {
        if (currentGroup.length > 0) result.push({ region: currentRegion, items: currentGroup });
        currentRegion = p.region;
        currentGroup = [p];
      } else {
        currentGroup.push(p);
      }
    }
    if (currentGroup.length > 0) result.push({ region: currentRegion, items: currentGroup });
    return result;
  }, []);

  // "None" option is always first, separate from groups
  const nonePreset = TIMEZONE_PRESETS[0];

  return (
    <div className="calendar-tz-picker" ref={ref}>
      <button
        ref={buttonRef}
        className={`calendar-tz-picker-btn ${value ? 'has-value' : ''}`}
        onClick={() => setOpen(!open)}
        title="Secondary timezone"
      >
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <line x1="2" x2="22" y1="12" y2="12" />
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
        </svg>
        <span>{value ? getTzLabel(value) : 'TZ'}</span>
      </button>
      {open && createPortal(
        <div
          ref={dropdownRef}
          className="calendar-tz-dropdown"
          style={{ position: 'fixed', left: dropdownPos.left, top: dropdownPos.top, maxHeight: dropdownMaxHeight }}
        >
          {/* Color picker row */}
          {value && (
            <div className="calendar-tz-color-row">
              <span className="calendar-tz-color-label">Color</span>
              <div className="calendar-tz-color-swatches">
                {TZ2_COLOR_PRESETS.map(c => (
                  <button
                    key={c.hue}
                    className={`calendar-tz-color-swatch ${tz2Color.hue === c.hue ? 'active' : ''}`}
                    style={{ background: c.hue }}
                    onClick={() => onColorChange(c)}
                    title={c.name}
                  />
                ))}
              </div>
            </div>
          )}

          {/* "Aucun" option */}
          <button
            className={`calendar-tz-option ${value === nonePreset.tz ? 'active' : ''}`}
            onClick={() => { onChange(nonePreset.tz); setOpen(false); }}
          >
            <span className="calendar-tz-option-label">—</span>
            <span className="calendar-tz-option-city">{t(nonePreset.city)}</span>
            {value === nonePreset.tz && (
              <CheckIcon size={14} className="calendar-tz-option-check" />
            )}
          </button>

          {/* Grouped timezone options */}
          {groups.map(group => (
            <div key={group.region}>
              {group.region && (
                <div className="calendar-tz-region-header">{t(group.region)}</div>
              )}
              {group.items.map(p => (
                <button
                  key={p.tz || '__none'}
                  className={`calendar-tz-option ${value === p.tz ? 'active' : ''}`}
                  onClick={() => { onChange(p.tz); setOpen(false); }}
                >
                  <span className="calendar-tz-option-label">{p.label}</span>
                  <span className="calendar-tz-option-city">{p.city}</span>
                  {value === p.tz && (
                    <CheckIcon size={14} className="calendar-tz-option-check" />
                  )}
                </button>
              ))}
            </div>
          ))}
        </div>,
        document.body
      )}
    </div>
  );
}
