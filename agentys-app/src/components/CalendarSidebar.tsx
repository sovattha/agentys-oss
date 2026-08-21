import { useState, useEffect, useLayoutEffect, useMemo, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { apiClient } from '../services/api';
import type { Calendar } from '../services/api';
import { formatCompactDate } from '../utils/dateFormat';
import { ChevronLeftIcon, ChevronRightIcon } from './icons/ActionIcons';

/** Month keys in order (Jan..Dec) for i18n lookup */
const MONTH_KEYS = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'] as const;
/** Day-of-week single-letter keys in Mon..Sun order for i18n lookup */
const MINI_DAY_KEYS = ['mon','tue','wed','thu','fri','sat','sun'] as const;

interface CalendarSidebarProps {
  currentWeekStart: Date;
  onNavigateToDate: (date: Date) => void;
  visibleCalendarIds: Set<string> | null;
  onToggleCalendar: (calendarId: string) => void;
  onCalendarsLoaded?: (ids: string[], calendars?: Calendar[]) => void;
  /** Email address of the connected calendar account */
  userEmail?: string;
  /** Country name for tz2 holidays (e.g. "France"), empty if no tz2 */
  tz2Country?: string;
  /** Accent color for the tz2 holiday toggle */
  tz2Color?: string;
  /** Whether tz2 holidays are currently visible */
  showTz2Holidays?: boolean;
  /** Toggle tz2 holidays visibility */
  onToggleTz2Holidays?: () => void;
  /** Country name for primary timezone holidays (e.g. "Canada"), empty if not mapped */
  primaryTzCountry?: string;
  /** Whether primary timezone holidays are currently visible */
  showPrimaryHolidays?: boolean;
  /** Toggle primary timezone holidays visibility */
  onTogglePrimaryHolidays?: () => void;
}


// MINI_DAY_NAMES removed — now using i18n common:days_short via MINI_DAY_KEYS

/** Check if a calendar is a holiday calendar */
function isHolidayCalendar(cal: Calendar): boolean {
  return cal.id.includes('#holiday@') ||
    cal.name.toLowerCase().includes('fériés') ||
    cal.name.toLowerCase().includes('holiday');
}

export function CalendarSidebar({
  currentWeekStart,
  onNavigateToDate,
  visibleCalendarIds,
  onToggleCalendar,
  onCalendarsLoaded,
  userEmail,
  tz2Country,
  tz2Color,
  showTz2Holidays,
  onToggleTz2Holidays,
  primaryTzCountry,
  showPrimaryHolidays,
  onTogglePrimaryHolidays,
}: CalendarSidebarProps) {
  const { t } = useTranslation('calendar');
  const { t: tc } = useTranslation('common');
  const [miniMonth, setMiniMonth] = useState(() => {
    const d = new Date(currentWeekStart);
    return { year: d.getFullYear(), month: d.getMonth() };
  });
  const [calendars, setCalendars] = useState<Calendar[]>([]);

  // Month/year picker state
  const [miniMonthPickerOpen, setMiniMonthPickerOpen] = useState(false);
  const [miniYearPickerOpen,  setMiniYearPickerOpen]  = useState(false);
  const [miniMonthPickerPos,  setMiniMonthPickerPos]  = useState<{ top: number; left: number } | null>(null);
  const [miniYearPickerPos,   setMiniYearPickerPos]   = useState<{ top: number; left: number } | null>(null);
  const miniMonthBtnRef    = useRef<HTMLButtonElement>(null);
  const miniYearBtnRef     = useRef<HTMLButtonElement>(null);
  const miniMonthPickerRef = useRef<HTMLDivElement>(null);
  const miniYearPickerRef  = useRef<HTMLDivElement>(null);

  // Fetch calendars list
  // BUG-J003 fix: AbortController prevents the StrictMode double-mount from firing
  // two concurrent listCalendars requests and applying both responses.
  useEffect(() => {
    const controller = new AbortController();
    apiClient.listCalendars().then(res => {
      if (controller.signal.aborted) return;
      if (res.calendars) {
        setCalendars(res.calendars);
        onCalendarsLoaded?.(res.calendars.map(c => c.id), res.calendars);
      }
    }).catch(err => {
      if (controller.signal.aborted) return;
      console.error('[CalendarSidebar] fetch calendars failed:', err);
    });
    return () => controller.abort();
  }, []);

  // Sync mini month with current week when navigating
  useEffect(() => {
    const mid = new Date(currentWeekStart);
    mid.setDate(mid.getDate() + 3); // Mid-week
    setMiniMonth({ year: mid.getFullYear(), month: mid.getMonth() });
  }, [currentWeekStart]);

  // Mini calendar grid
  const miniCalendarDays = useMemo(() => {
    const { year, month } = miniMonth;
    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);

    // Day of week for first day (0=Sun, convert to Mon-start)
    let startDow = firstDay.getDay() - 1;
    if (startDow < 0) startDow = 6;

    const days: Array<{ date: Date; inMonth: boolean }> = [];

    // Previous month fill
    for (let i = startDow - 1; i >= 0; i--) {
      const d = new Date(year, month, -i);
      days.push({ date: d, inMonth: false });
    }

    // Current month
    for (let i = 1; i <= lastDay.getDate(); i++) {
      days.push({ date: new Date(year, month, i), inMonth: true });
    }

    // Next month fill (to complete 6 rows)
    const remaining = 42 - days.length;
    for (let i = 1; i <= remaining; i++) {
      days.push({ date: new Date(year, month + 1, i), inMonth: false });
    }

    return days;
  }, [miniMonth]);

  const today = useMemo(() => new Date(), []);
  const todayStr = today.toDateString();

  const goToPrevMonth = () => {
    setMiniMonth(prev => {
      const m = prev.month - 1;
      return m < 0 ? { year: prev.year - 1, month: 11 } : { year: prev.year, month: m };
    });
  };

  const goToNextMonth = () => {
    setMiniMonth(prev => {
      const m = prev.month + 1;
      return m > 11 ? { year: prev.year + 1, month: 0 } : { year: prev.year, month: m };
    });
  };

  const closeAllMiniPickers = useCallback(() => {
    setMiniMonthPickerOpen(false);
    setMiniYearPickerOpen(false);
  }, []);

  const openMiniMonthPicker = () => {
    setMiniYearPickerOpen(false);
    setMiniMonthPickerOpen(v => !v);
  };

  const openMiniYearPicker = () => {
    setMiniMonthPickerOpen(false);
    setMiniYearPickerOpen(v => !v);
  };

  const goToMiniMonthYear = useCallback((month: number, year: number) => {
    setMiniMonth({ year, month });
    closeAllMiniPickers();
  }, [closeAllMiniPickers]);

  // Compute picker positions (useLayoutEffect = sync after DOM update, before paint → no flicker)
  useLayoutEffect(() => {
    if (miniMonthPickerOpen && miniMonthBtnRef.current) {
      const r = miniMonthBtnRef.current.getBoundingClientRect();
      const dropdownW = 220;
      const left = r.left + dropdownW > window.innerWidth
        ? r.right - dropdownW
        : r.left;
      setMiniMonthPickerPos({ top: r.bottom + 4, left });
    }
  }, [miniMonthPickerOpen]);

  useLayoutEffect(() => {
    if (miniYearPickerOpen && miniYearBtnRef.current) {
      const r = miniYearBtnRef.current.getBoundingClientRect();
      const dropdownW = 100;
      const left = r.left + dropdownW > window.innerWidth
        ? r.right - dropdownW
        : r.left;
      setMiniYearPickerPos({ top: r.bottom + 4, left });
    }
  }, [miniYearPickerOpen]);

  // Close mini month picker on outside click
  useEffect(() => {
    if (!miniMonthPickerOpen) return;
    const handler = (e: MouseEvent) => {
      if (
        miniMonthPickerRef.current && !miniMonthPickerRef.current.contains(e.target as Node) &&
        miniMonthBtnRef.current && !miniMonthBtnRef.current.contains(e.target as Node)
      ) setMiniMonthPickerOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [miniMonthPickerOpen]);

  // Close mini year picker on outside click
  useEffect(() => {
    if (!miniYearPickerOpen) return;
    const handler = (e: MouseEvent) => {
      if (
        miniYearPickerRef.current && !miniYearPickerRef.current.contains(e.target as Node) &&
        miniYearBtnRef.current && !miniYearBtnRef.current.contains(e.target as Node)
      ) setMiniYearPickerOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [miniYearPickerOpen]);

  // Escape closes whichever mini picker is open
  useEffect(() => {
    if (!miniMonthPickerOpen && !miniYearPickerOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); closeAllMiniPickers(); }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [miniMonthPickerOpen, miniYearPickerOpen, closeAllMiniPickers]);

  // Auto-scroll year picker to current year
  useEffect(() => {
    if (!miniYearPickerOpen || !miniYearPickerRef.current) return;
    const active = miniYearPickerRef.current.querySelector('.cal-picker-active');
    active?.scrollIntoView({ block: 'center', behavior: 'instant' });
  }, [miniYearPickerOpen]);

  // Split calendars into user calendars and holiday calendars
  const userCals = useMemo(() =>
    calendars.filter(c => !isHolidayCalendar(c)).sort((a, b) => a.isPrimary ? -1 : b.isPrimary ? 1 : 0),
    [calendars]
  );
  const holidayCals = useMemo(() => calendars.filter(isHolidayCalendar), [calendars]);

  // Suppress the primary holidays toggle if a synced holiday calendar already covers that country
  const primaryAlreadySynced = useMemo(() => {
    if (!primaryTzCountry) return false;
    return holidayCals.some(cal => cal.name.toLowerCase().includes(primaryTzCountry.toLowerCase()));
  }, [holidayCals, primaryTzCountry]);

  return (
    <div className="calendar-sidebar">
      {/* Mini calendar */}
      <div className="cal-sidebar-mini">
        <div className="cal-sidebar-mini-header">
          <button className="cal-sidebar-mini-nav" onClick={goToPrevMonth} aria-label={t('prev_month')}>
            <ChevronLeftIcon size={14} />
          </button>
          <span className="cal-sidebar-mini-title">
            <span className="cal-picker-wrapper">
              <button ref={miniMonthBtnRef} className="cal-picker-btn cal-sidebar-mini-picker-btn"
                onClick={openMiniMonthPicker} aria-label={t('choose_month')} aria-expanded={miniMonthPickerOpen}>
                {tc(`months.${MONTH_KEYS[miniMonth.month]}`)}
              </button>
              {miniMonthPickerOpen && miniMonthPickerPos && createPortal(
                <div ref={miniMonthPickerRef} className="cal-picker-dropdown cal-month-picker"
                  style={{ top: miniMonthPickerPos.top, left: miniMonthPickerPos.left }}>
                  {MONTH_KEYS.map((key, i) => (
                    <button key={i}
                      className={`cal-picker-month-cell${i === miniMonth.month ? ' cal-picker-active' : ''}`}
                      onClick={() => goToMiniMonthYear(i, miniMonth.year)}>
                      {tc(`months.${key}`)}
                    </button>
                  ))}
                </div>,
                document.body
              )}
            </span>
            {' '}
            <span className="cal-picker-wrapper">
              <button ref={miniYearBtnRef} className="cal-picker-btn cal-sidebar-mini-picker-btn"
                onClick={openMiniYearPicker} aria-label={t('choose_year')} aria-expanded={miniYearPickerOpen}>
                {miniMonth.year}
              </button>
              {miniYearPickerOpen && miniYearPickerPos && createPortal(
                <div ref={miniYearPickerRef} className="cal-picker-dropdown cal-year-picker"
                  style={{ top: miniYearPickerPos.top, left: miniYearPickerPos.left }}>
                  {Array.from({ length: 21 }, (_, i) => miniMonth.year - 10 + i).map(y => (
                    <button key={y}
                      className={`cal-picker-year-item${y === miniMonth.year ? ' cal-picker-active' : ''}`}
                      onClick={() => goToMiniMonthYear(miniMonth.month, y)}>
                      {y}
                    </button>
                  ))}
                </div>,
                document.body
              )}
            </span>
          </span>
          <button className="cal-sidebar-mini-nav" onClick={goToNextMonth} aria-label={t('next_month')}>
            <ChevronRightIcon size={14} />
          </button>
        </div>

        {/* Day of week headers */}
        <div className="cal-sidebar-mini-grid">
          {MINI_DAY_KEYS.map((key, i) => (
            <div key={`h-${i}`} className="cal-sidebar-mini-dow">{tc(`days_short.${key}`).charAt(0)}</div>
          ))}

          {/* Day cells */}
          {miniCalendarDays.map((day, i) => {
            const isToday = day.date.toDateString() === todayStr;
            const classes = [
              'cal-sidebar-mini-day',
              !day.inMonth && 'out-of-month',
              isToday && 'is-today',
            ].filter(Boolean).join(' ');

            return (
              <button
                key={i}
                className={classes}
                onClick={() => onNavigateToDate(day.date)}
                title={formatCompactDate(day.date)}
              >
                {day.date.getDate()}
              </button>
            );
          })}
        </div>
      </div>

      {/* Calendar list */}
      {(calendars.length > 0 || tz2Country) && (
        <div className="cal-sidebar-calendars">
          <div className="cal-sidebar-section-title">{t('calendars')}</div>

          {/* User calendars (non-holiday) */}
          {userCals.map(cal => {
            const isVisible = visibleCalendarIds === null || visibleCalendarIds.has(cal.id);
            const calDisplayName = (cal.name === 'Calendrier' || cal.name === userEmail) ? t('default_calendar_name') : cal.name;
            return (
              <label key={cal.id} className="cal-sidebar-calendar-item cal-sidebar-holidays-toggle">
                <button
                  type="button"
                  role="switch"
                  aria-checked={isVisible}
                  aria-label={t('toggle_calendar_aria', { name: calDisplayName, defaultValue: `Afficher/masquer ${calDisplayName}` })}
                  className={`cal-sidebar-toggle ${isVisible ? 'on' : ''}`}
                  onClick={() => onToggleCalendar(cal.id)}
                  style={{ '--toggle-color': cal.color || 'var(--accent-primary)' } as React.CSSProperties}
                />
                <span className="cal-sidebar-calendar-name">
                  {calDisplayName}
                  {userEmail && <span className="cal-sidebar-calendar-email">{userEmail}</span>}
                </span>
              </label>
            );
          })}

          {/* Holiday calendars — each with its own toggle */}
          {holidayCals.map(cal => {
            const isVisible = visibleCalendarIds === null || visibleCalendarIds.has(cal.id);
            const holidayName = t('holidays_label', { country: cal.name.replace(/^(?:Calendrier\s+des\s+jours\s+f[ée]ri[ée]s\s*[-·:]?\s*|Jours\s+f[ée]ri[ée]s(?:\s+(?:au|en|aux|du|de|des))?\s*[-·]?\s*|Holidays(?:\s+in)?\s*[-·]?\s*|Feiertage(?:\s+in)?\s*[-·]?\s*|D[ií]as\s+festivos(?:\s+(?:en|de))?\s*[-·]?\s*)/i, '').replace(/^(?:au|en|aux|du|de|des|in)\s+/i, '') });
            return (
              <label key={cal.id} className="cal-sidebar-calendar-item cal-sidebar-holidays-toggle">
                <button
                  type="button"
                  role="switch"
                  aria-checked={isVisible}
                  aria-label={t('toggle_calendar_aria', { name: holidayName, defaultValue: `Afficher/masquer ${holidayName}` })}
                  className={`cal-sidebar-toggle ${isVisible ? 'on' : ''}`}
                  onClick={() => onToggleCalendar(cal.id)}
                  style={{ '--toggle-color': cal.color || 'var(--accent-primary)' } as React.CSSProperties}
                />
                <span className="cal-sidebar-calendar-name">{holidayName}</span>
              </label>
            );
          })}

          {/* Primary timezone holidays toggle — hidden if already synced via Google Calendar */}
          {primaryTzCountry && onTogglePrimaryHolidays && !primaryAlreadySynced && (
            <label className="cal-sidebar-calendar-item cal-sidebar-holidays-toggle">
              <button
                type="button"
                role="switch"
                aria-checked={showPrimaryHolidays ?? true}
                aria-label={t('toggle_calendar_aria', { name: t('holidays_label', { country: primaryTzCountry }), defaultValue: `Afficher/masquer ${t('holidays_label', { country: primaryTzCountry })}` })}
                className={`cal-sidebar-toggle ${showPrimaryHolidays ?? true ? 'on' : ''}`}
                onClick={onTogglePrimaryHolidays}
                style={{ '--toggle-color': '#16a34a' } as React.CSSProperties}
              />
              <span className="cal-sidebar-calendar-name">{t('holidays_label', { country: primaryTzCountry })}</span>
            </label>
          )}

          {/* Tz2 holidays toggle */}
          {tz2Country && onToggleTz2Holidays && (
            <label className="cal-sidebar-calendar-item cal-sidebar-holidays-toggle">
              <button
                type="button"
                role="switch"
                aria-checked={showTz2Holidays ?? true}
                aria-label={t('toggle_calendar_aria', { name: t('holidays_label', { country: tz2Country }), defaultValue: `Afficher/masquer ${t('holidays_label', { country: tz2Country })}` })}
                className={`cal-sidebar-toggle ${showTz2Holidays ?? true ? 'on' : ''}`}
                onClick={onToggleTz2Holidays}
                style={{ '--toggle-color': tz2Color || '#d97706' } as React.CSSProperties}
              />
              <span className="cal-sidebar-calendar-name">{t('holidays_label', { country: tz2Country })}</span>
            </label>
          )}
        </div>
      )}
    </div>
  );
}
