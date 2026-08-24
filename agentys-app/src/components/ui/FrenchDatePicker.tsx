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

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import "./FrenchDatePicker.css";

// Legacy filename — the picker is now locale-aware. Month names, weekday
// initials and the human-readable date are all derived from the current
// i18next language via Intl.DateTimeFormat. The export name is preserved
// to avoid touching every call site; rename in a follow-up if needed.

interface FrenchDatePickerProps {
  value: string; // YYYY-MM-DD
  onChange: (value: string) => void;
  min?: string;
  placeholder?: string;
  ariaLabel?: string;
}

function toISO(year: number, month: number, day: number): string {
  return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function getCalendarDays(year: number, month: number, weekStartsOn: number): (number | null)[] {
  const firstDay = new Date(year, month, 1).getDay();
  // Shift so weekStartsOn maps to column 0 (Mon-first: 1 → Sun=6, Sat=5…).
  const startOffset = (firstDay - weekStartsOn + 7) % 7;
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const cells: (number | null)[] = [];
  for (let i = 0; i < startOffset; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  return cells;
}

const EN_ORDINAL_SUFFIX: Record<Intl.LDMLPluralRule, string> = {
  one: "st",
  two: "nd",
  few: "rd",
  other: "th",
  zero: "th",
  many: "th",
};

function englishOrdinalSuffix(day: number): string {
  return EN_ORDINAL_SUFFIX[new Intl.PluralRules("en", { type: "ordinal" }).select(day)] ?? "th";
}

export function FrenchDatePicker({
  value,
  onChange,
  min,
  placeholder = "Select a date",
  ariaLabel,
}: FrenchDatePickerProps) {
  const { i18n } = useTranslation();
  const locale = i18n.language || "en";

  const monthsLong = useMemo(() => {
    const fmt = new Intl.DateTimeFormat(locale, { month: "long" });
    return Array.from({ length: 12 }, (_, m) => fmt.format(new Date(2026, m, 1)));
  }, [locale]);

  // Weekday initials for the header. Week starts Monday (international
  // convention; en-US technically starts Sunday but most users have moved on).
  const weekStartsOn = 1; // Monday
  const daysShort = useMemo(() => {
    const fmt = new Intl.DateTimeFormat(locale, { weekday: "narrow" });
    // 2026-01-05 is a Monday — anchor week starts there.
    return Array.from({ length: 7 }, (_, i) =>
      fmt.format(new Date(2026, 0, 5 + i))
    );
  }, [locale]);

  const formatLongDate = useCallback(
    (iso: string): string => {
      if (!iso) return "";
      const [y, m, d] = iso.split("-").map(Number);
      if (!y || !m || !d) return "";
      const fmt = new Intl.DateTimeFormat(locale, {
        day: "numeric",
        month: "long",
        year: "numeric",
      });
      if (!fmt.resolvedOptions().locale.toLowerCase().startsWith("en")) {
        return fmt.format(new Date(y, m - 1, d));
      }
      const month = new Intl.DateTimeFormat(locale, { month: "long" }).format(new Date(y, m - 1, d));
      return `${month} ${d}${englishOrdinalSuffix(d)} ${y}`;
    },
    [locale],
  );

  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [dropdownStyle, setDropdownStyle] = useState<React.CSSProperties>({});

  const initial = value ? new Date(value) : new Date();
  const [viewYear, setViewYear] = useState(initial.getFullYear());
  const [viewMonth, setViewMonth] = useState(initial.getMonth());

  useEffect(() => {
    if (value) {
      const d = new Date(value);
      setViewYear(d.getFullYear());
      setViewMonth(d.getMonth());
    }
  }, [value]);

  useEffect(() => {
    if (open && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setDropdownStyle({
        position: "fixed",
        top: rect.bottom + 4,
        left: rect.left,
        zIndex: "var(--z-modal)" as never,
      });
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    // Capture-phase mousedown: when the picker is mounted inside a modal that
    // stops native mousedown propagation (e.g. AutoReplyModal nested in the
    // Settings modal), a bubble-phase document listener never fires and the
    // calendar can't be dismissed by clicking outside. Capture runs on the way
    // down from document, before any parent stopPropagation can swallow it.
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    // Capture-phase Escape so the calendar closes *before* any parent modal
    // also bound to Escape (stopImmediatePropagation keeps the parent open).
    const keyHandler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopImmediatePropagation();
        e.preventDefault();
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", handler, { capture: true });
    document.addEventListener("keydown", keyHandler, { capture: true });
    return () => {
      document.removeEventListener("mousedown", handler, { capture: true });
      document.removeEventListener("keydown", keyHandler, { capture: true });
    };
  }, [open]);

  const prevMonth = useCallback(() => {
    setViewMonth((m) => {
      if (m === 0) {
        setViewYear((y) => y - 1);
        return 11;
      }
      return m - 1;
    });
  }, []);

  const nextMonth = useCallback(() => {
    setViewMonth((m) => {
      if (m === 11) {
        setViewYear((y) => y + 1);
        return 0;
      }
      return m + 1;
    });
  }, []);

  const handleSelect = useCallback(
    (day: number) => {
      onChange(toISO(viewYear, viewMonth, day));
      setOpen(false);
    },
    [viewYear, viewMonth, onChange],
  );

  const today = new Date();
  const todayISO = toISO(today.getFullYear(), today.getMonth(), today.getDate());
  const cells = getCalendarDays(viewYear, viewMonth, weekStartsOn);

  const isDisabled = (day: number): boolean => {
    if (!min) return false;
    return toISO(viewYear, viewMonth, day) < min;
  };

  return (
    <div className="fdp-container" ref={containerRef}>
      <button
        type="button"
        ref={triggerRef}
        className={`fdp-trigger ${open ? "fdp-trigger-open" : ""}`}
        onClick={() => setOpen((o) => !o)}
        aria-label={ariaLabel || placeholder}
        aria-expanded={open}
      >
        <span className={value ? "fdp-trigger-value" : "fdp-trigger-placeholder"}>
          {value ? formatLongDate(value) : placeholder}
        </span>
        <svg aria-hidden="true" className="fdp-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
          <line x1="16" y1="2" x2="16" y2="6" />
          <line x1="8" y1="2" x2="8" y2="6" />
          <line x1="3" y1="10" x2="21" y2="10" />
        </svg>
      </button>

      {open && (
        <div className="fdp-dropdown" style={dropdownStyle}>
          <div className="fdp-header">
            <button type="button" className="fdp-nav" onClick={prevMonth} aria-label="Previous month">‹</button>
            <span className="fdp-month-label">{monthsLong[viewMonth]} {viewYear}</span>
            <button type="button" className="fdp-nav" onClick={nextMonth} aria-label="Next month">›</button>
          </div>

          <div className="fdp-weekdays">
            {daysShort.map((d, i) => (
              <span key={i} className="fdp-weekday">{d}</span>
            ))}
          </div>

          <div className="fdp-grid">
            {cells.map((day, i) => {
              if (day === null) return <span key={`empty-${i}`} className="fdp-cell fdp-empty" />;
              const iso = toISO(viewYear, viewMonth, day);
              const selected = iso === value;
              const isToday = iso === todayISO;
              const disabled = isDisabled(day);
              return (
                <button
                  key={day}
                  type="button"
                  className={[
                    "fdp-cell",
                    selected && "fdp-selected",
                    isToday && "fdp-today",
                    disabled && "fdp-disabled",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onClick={() => !disabled && handleSelect(day)}
                  disabled={disabled}
                  aria-label={`${day} ${monthsLong[viewMonth]} ${viewYear}`}
                  aria-pressed={selected}
                >
                  {day}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
