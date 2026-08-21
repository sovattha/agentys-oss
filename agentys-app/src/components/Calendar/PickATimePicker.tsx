/**
 * PickATimePicker — full-screen "everyone-free" slot picker.
 *
 * Replaces the inline SmartSchedulerPanel for the QuickEventPopover "Browse
 * slots" flow. Portals to body so the popover stays mounted underneath;
 * back / Escape / × return to the popover with its draft state intact.
 *
 * Design model: pre-digested chip list (Calendly-style). The picker did the
 * work — the chips ARE the answer. No timeline, no scanning. One chip is
 * scored as Best (★) so the default focus already points at "the pick".
 *
 * Layout (handoff-fidelity):
 *   ┌─────────────────────────────────────────────────────────────┐
 *   │ [‹ Back] TODAY ‹›   May 2026  W20    [1h · 4 👥 ⌄]   [✕]    │
 *   ├─────────────────────────────────────────────────────────────┤
 *   │ Find a slot · everyone free       ←→ week  ↑↓ slot  ↵ pick │
 *   ├─────────────────────────────────────────────────────────────┤
 *   │  MON   TUE   WED   THU   FRI   SAT   SUN                    │
 *   │   11    12    13    14   (15)   16    17                    │
 *   │ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐                          │
 *   │ │..│ │★ │ │..│ │..│ │..│ │— │ │— │      ★ = recommended    │
 *   ├─────────────────────────────────────────────────────────────┤
 *   │ SELECTED · Mon May 11 · 09h00 – 09h30          [Schedule]  │
 *   └─────────────────────────────────────────────────────────────┘
 *
 * Keyboard:
 *   ← → → slide visible window by one day (focus reset)
 *   ↑ ↓ → cycle through the visible window's free slots column-major
 *   ↵   → commit focused slot
 *   Esc → close the duration menu if open, else back to popover
 *
 * Events: registers `keydown` in CAPTURE phase + stopPropagation so the
 * parent popover's Escape→close listener doesn't double-fire.
 */

import { useState, useEffect, useMemo, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import i18n from '../../i18n'
import { formatShortDateFromDate } from '../../utils/dateFormat'
import { apiClient, type CalendarEvent } from '../../services/api'
import { fmtClockTime, isSameDay } from '../../utils/availabilityFormatter'
import { Avatar } from '../Avatar'
import {
  CloseIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
} from '../icons/ActionIcons'

const MAX_AVATAR_BUBBLES = 4
const DURATION_OPTIONS: readonly number[] = [15, 30, 45, 60, 90, 120]

interface PickATimePickerProps {
  attendees: string[]
  onSelectSlot: (start: string, end: string) => void
  onBack: () => void
  /** Local-only events (Deep Work) invisible to freebusy API */
  localEvents?: CalendarEvent[]
  /** Initial duration in minutes — seeded from the popover's current value.
   *  The picker keeps its own state after mount; the parent re-syncs on
   *  slot select via `end - start`. */
  defaultDuration?: number
  /** Work-hours start (0-23) — inherits popover's setting */
  defaultWorkStart?: number
  /** Work-hours end (0-23) — inherits popover's setting */
  defaultWorkEnd?: number
}

interface SlotData {
  start: Date
  end: Date
  rawStart: string
  rawEnd: string
}

interface FlatSlot {
  key: string
  dayIdx: number
  slotIdx: number
  slot: SlotData
}

function mondayOf(d: Date): Date {
  const out = new Date(d)
  out.setHours(0, 0, 0, 0)
  const dow = out.getDay()
  const delta = dow === 0 ? -6 : 1 - dow
  out.setDate(out.getDate() + delta)
  return out
}

function addDays(d: Date, n: number): Date {
  const out = new Date(d)
  out.setDate(out.getDate() + n)
  return out
}

/** ISO week number per ISO-8601 — Thursday-anchored. */
function isoWeekNum(d: Date): number {
  const t = new Date(d)
  t.setHours(0, 0, 0, 0)
  t.setDate(t.getDate() + 3 - ((t.getDay() + 6) % 7))
  const jan4 = new Date(t.getFullYear(), 0, 4)
  return 1 + Math.round(
    ((t.getTime() - jan4.getTime()) / 86400000 - 3 + ((jan4.getDay() + 6) % 7)) / 7,
  )
}

function fmtMonthYear(d: Date, lang: string): string {
  const out = new Intl.DateTimeFormat(lang, { month: 'long', year: 'numeric' }).format(d)
  return out.charAt(0).toUpperCase() + out.slice(1)
}

function fmtDayOfWeekShort(d: Date, lang: string): string {
  const out = new Intl.DateTimeFormat(lang, { weekday: 'short' }).format(d)
  return out.replace(/\.$/, '').toUpperCase()
}

function fmtMonthDayShort(d: Date, lang: string): string {
  // "May 27th" (EN ordinal) / "27 mai" (FR day-first) via the shared helper.
  return formatShortDateFromDate(d, lang)
}

function durationLabel(mins: number): string {
  if (mins < 60) return `${mins}m`
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return m ? `${h}h${String(m).padStart(2, '0')}` : `${h}h`
}

/**
 * Heuristic slot score — higher is "better calendar etiquette". Pure function
 * over the slot's start instant; deterministic, side-effect-free, so the same
 * week always ranks the same way regardless of fetch order.
 *
 * Signals (calibrated so day-of-week dominates time-of-day, and lunch + edges
 * gently nudge rather than veto):
 *   • Tue/Wed/Thu mid-week boost
 *   • Mon penalty (people are slow / triage email)
 *   • Fri penalty (focus drift, especially PM)
 *   • Sweet hours 10:30 + 14:30 — distance-weighted falloff
 *   • Soft edges (< 9, ≥ 16)
 *   • Mild lunch zone penalty (12 – 13)
 *   • Hard penalty for Mon-AM (< 10) and Fri-late (≥ 15)
 */
function scoreSlot(start: Date): number {
  let score = 0
  const day = start.getDay()
  const hour = start.getHours() + start.getMinutes() / 60

  if (day === 2 || day === 3 || day === 4) score += 14
  else if (day === 1) score -= 8
  else if (day === 5) score -= 6

  const distFromMorning = Math.abs(hour - 10.5)
  const distFromAfternoon = Math.abs(hour - 14.5)
  score -= Math.min(distFromMorning, distFromAfternoon) * 4

  if (hour < 9) score -= 6
  if (hour >= 16) score -= 6
  if (hour >= 12 && hour < 13) score -= 4
  if (day === 1 && hour < 10) score -= 6
  if (day === 5 && hour >= 15) score -= 8

  return score
}

export function PickATimePicker({
  attendees,
  onSelectSlot,
  onBack,
  localEvents,
  defaultDuration = 60,
  defaultWorkStart = 8,
  defaultWorkEnd = 17,
}: PickATimePickerProps) {
  const { t } = useTranslation('calendar')
  const lang = i18n.language || 'en'
  const timezone = useMemo(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone,
    [],
  )

  // `today` must stay live: if the picker is left open across midnight or
  // unhidden after a long sleep, a frozen `new Date()` would highlight the
  // wrong column and send "Today" to yesterday. Refresh on visibilitychange
  // and every 5 minutes — enough to catch day rollovers without re-rendering
  // the grid on every tick.
  const [today, setToday] = useState<Date>(() => new Date())
  useEffect(() => {
    const refresh = () => setToday(new Date())
    const onVis = () => { if (document.visibilityState === 'visible') refresh() }
    document.addEventListener('visibilitychange', onVis)
    const id = setInterval(refresh, 5 * 60 * 1000)
    return () => {
      document.removeEventListener('visibilitychange', onVis)
      clearInterval(id)
    }
  }, [])
  const [weekStart, setWeekStart] = useState<Date>(() => mondayOf(today))
  // Fetch anchor — only moves in 7-day jumps as `weekStart` slides past
  // the edges of the current 21-day fetch window. Day-by-day arrow nav
  // within that window hits the cache instead of re-fetching. The visible
  // 7-day week initially sits in the middle of the 21-day window with a
  // 7-day buffer on each side.
  const [fetchAnchor, setFetchAnchor] = useState<Date>(
    () => addDays(mondayOf(today), -7),
  )
  // Short timezone label for the floating dock pill (e.g. "EDT", "CEST"),
  // matching AvailabilityPicker's tz chip.
  const tzLabel = useMemo(() => {
    try {
      const parts = new Intl.DateTimeFormat('en', {
        timeZone: timezone,
        timeZoneName: 'short',
      }).formatToParts(new Date())
      return parts.find(p => p.type === 'timeZoneName')?.value || timezone
    } catch {
      return timezone
    }
  }, [timezone])
  const [focusedKey, setFocusedKey] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [slots, setSlots] = useState<SlotData[]>([])
  const [duration, setDuration] = useState<number>(defaultDuration)
  const [showDurationMenu, setShowDurationMenu] = useState(false)

  // Slot cache keyed by fetchAnchor + search signature. LRU-capped so it
  // doesn't grow unbounded as the user scrubs across months.
  const cacheRef = useRef<Map<string, SlotData[]>>(new Map())
  const fetchTokenRef = useRef(0)
  const CACHE_MAX = 20

  const attendeesKey = useMemo(() => [...attendees].sort().join(','), [attendees])
  const localEventsKey = useMemo(
    () => (localEvents ?? []).map(e => `${e.id}:${e.start}:${e.end}`).join('|'),
    [localEvents],
  )
  const cacheKey = useMemo(
    () =>
      `${fetchAnchor.getTime()}|${attendeesKey}|${duration}|${defaultWorkStart}|${defaultWorkEnd}|${localEventsKey}`,
    [fetchAnchor, attendeesKey, duration, defaultWorkStart, defaultWorkEnd, localEventsKey],
  )

  const weekDays = useMemo(
    () => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)),
    [weekStart],
  )

  // Slots grouped by their day-of-week index (0..6 within the visible week).
  const slotsByDay = useMemo(
    () =>
      weekDays.map(day =>
        slots
          .filter(s => isSameDay(s.start, day, timezone))
          .sort((a, b) => a.start.getTime() - b.start.getTime()),
      ),
    [weekDays, slots, timezone],
  )

  // Flat list in column-major order for ↑/↓ navigation.
  const flatSlots: FlatSlot[] = useMemo(() => {
    const flat: FlatSlot[] = []
    slotsByDay.forEach((col, d) =>
      col.forEach((s, i) => flat.push({ key: `${d}-${i}`, dayIdx: d, slotIdx: i, slot: s })),
    )
    return flat
  }, [slotsByDay])

  // Best slot for the visible week — highest scoreSlot across flatSlots.
  // Stable tie-break: earliest slot wins (the loop keeps the first max).
  const bestKey = useMemo(() => {
    if (flatSlots.length === 0) return null
    let best: { key: string; score: number } | null = null
    for (const f of flatSlots) {
      const s = scoreSlot(f.slot.start)
      if (!best || s > best.score) best = { key: f.key, score: s }
    }
    return best?.key ?? null
  }, [flatSlots])

  const focusedSlot = useMemo(
    () => flatSlots.find(f => f.key === focusedKey)?.slot ?? null,
    [flatSlots, focusedKey],
  )

  // Fetch a 21-day window starting at fetchAnchor. Hit cache first; only
  // fire a real request when the (anchor + filters) signature is new.
  useEffect(() => {
    const cached = cacheRef.current.get(cacheKey)
    if (cached) {
      // LRU touch: re-insert so this key moves to the end of insertion
      // order (Map preserves order — keys().next() returns the oldest).
      cacheRef.current.delete(cacheKey)
      cacheRef.current.set(cacheKey, cached)
      setSlots(cached)
      setLoading(false)
      setError('')
      return
    }

    const token = ++fetchTokenRef.current
    setLoading(true)
    setError('')

    const fetchStart = fetchAnchor.toISOString()
    const fetchEnd = addDays(fetchAnchor, 21).toISOString()

    const winLo = fetchAnchor.getTime()
    const winHi = addDays(fetchAnchor, 21).getTime()
    const extraBusy = (localEvents ?? [])
      .filter(ev => {
        const evStart = new Date(ev.start).getTime()
        const evEnd = new Date(ev.end).getTime()
        return evEnd > winLo && evStart < winHi
      })
      .map(ev => ({ start: ev.start, end: ev.end }))

    apiClient
      .findFreeBusySlots({
        attendees,
        start: fetchStart,
        end: fetchEnd,
        duration_minutes: duration,
        work_hours_only: true,
        work_start: defaultWorkStart,
        work_end: defaultWorkEnd,
        extra_busy: extraBusy.length > 0 ? extraBusy : undefined,
      })
      .then(result => {
        if (token !== fetchTokenRef.current) return
        const now = new Date()
        const parsed: SlotData[] = (result.slots || [])
          .map(s => ({
            start: new Date(s.start),
            end: new Date(s.end),
            rawStart: s.start,
            rawEnd: s.end,
          }))
          .filter(s => s.start > now)
        cacheRef.current.set(cacheKey, parsed)
        if (cacheRef.current.size > CACHE_MAX) {
          const oldest = cacheRef.current.keys().next().value
          if (oldest !== undefined) cacheRef.current.delete(oldest)
        }
        setSlots(parsed)
      })
      .catch((err: unknown) => {
        if (token !== fetchTokenRef.current) return
        const msg = err instanceof Error ? err.message : String(err)
        setError(msg || t('scheduler_search_error'))
        cacheRef.current.set(cacheKey, [])
        setSlots([])
      })
      .finally(() => {
        if (token === fetchTokenRef.current) setLoading(false)
      })
    // NOTE: deps intentionally narrow. `cacheKey` already encodes the content
    // of `attendees` and `localEvents` (via attendeesKey/localEventsKey), so
    // we don't want raw array identity to re-fire the fetch on every parent
    // re-render. `fetchAnchor`/`duration`/`defaultWork*` are also reflected in
    // cacheKey but kept here because the request body reads them at call time.
  }, [cacheKey, fetchAnchor, duration, defaultWorkStart, defaultWorkEnd, t])

  // Slide fetchAnchor when the visible 7-day week leaves the 21-day fetch
  // window. We recenter so the visible week sits in the middle of the new
  // window — gives ~7 days of free day-by-day nav in either direction
  // before the next fetch.
  useEffect(() => {
    const visibleStart = weekStart.getTime()
    const visibleEnd = addDays(weekStart, 7).getTime()
    const windowStart = fetchAnchor.getTime()
    const windowEnd = addDays(fetchAnchor, 21).getTime()
    if (visibleStart < windowStart || visibleEnd > windowEnd) {
      setFetchAnchor(addDays(weekStart, -7))
    }
  }, [weekStart, fetchAnchor])

  // Default focus when slots load: prefer the Best slot (so the
  // recommendation is the first thing the eye and Enter key land on),
  // otherwise today's first slot, otherwise the very first slot.
  useEffect(() => {
    if (focusedKey || flatSlots.length === 0) return
    if (bestKey) {
      setFocusedKey(bestKey)
      return
    }
    const todayIdx = weekDays.findIndex(d => isSameDay(today, d, timezone))
    if (todayIdx >= 0) {
      const firstInToday = flatSlots.find(s => s.dayIdx === todayIdx)
      if (firstInToday) {
        setFocusedKey(firstInToday.key)
        return
      }
    }
    setFocusedKey(flatSlots[0].key)
  }, [flatSlots, weekDays, today, timezone, focusedKey, bestKey])

  // Global keyboard handler — capture phase + stopPropagation so the parent
  // popover's Escape→close listener doesn't fire alongside us.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const target = e.target as HTMLElement | null
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        if (showDurationMenu) {
          setShowDurationMenu(false)
        } else {
          onBack()
        }
        return
      }
      if (e.key === 'ArrowLeft') {
        e.preventDefault()
        e.stopPropagation()
        setWeekStart(prev => addDays(prev, -1))
        setFocusedKey(null)
        return
      }
      if (e.key === 'ArrowRight') {
        e.preventDefault()
        e.stopPropagation()
        setWeekStart(prev => addDays(prev, 1))
        setFocusedKey(null)
        return
      }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        if (flatSlots.length === 0) return
        e.preventDefault()
        e.stopPropagation()
        const idx = flatSlots.findIndex(s => s.key === focusedKey)
        const dir = e.key === 'ArrowDown' ? 1 : -1
        const next =
          idx === -1
            ? (dir === 1 ? 0 : flatSlots.length - 1)
            : (idx + dir + flatSlots.length) % flatSlots.length
        setFocusedKey(flatSlots[next].key)
        return
      }
      if (e.key === 'Enter' && focusedSlot) {
        e.preventDefault()
        e.stopPropagation()
        onSelectSlot(focusedSlot.rawStart, focusedSlot.rawEnd)
      }
    }
    document.addEventListener('keydown', handler, { capture: true })
    return () => document.removeEventListener('keydown', handler, { capture: true })
  }, [flatSlots, focusedKey, focusedSlot, onSelectSlot, onBack, showDurationMenu])

  // Close the duration menu on outside click. Defer registration by a tick
  // so the same click that opened the menu doesn't immediately close it.
  useEffect(() => {
    if (!showDurationMenu) return
    const handler = (e: MouseEvent) => {
      const target = e.target as Element | null
      if (!target?.closest('.pat-duration-wrap')) {
        setShowDurationMenu(false)
      }
    }
    const tid = window.setTimeout(() => document.addEventListener('click', handler), 0)
    return () => {
      window.clearTimeout(tid)
      document.removeEventListener('click', handler)
    }
  }, [showDurationMenu])

  // Auto-scroll focused chip into view inside its column.
  const chipRefs = useRef<Record<string, HTMLButtonElement | null>>({})
  useEffect(() => {
    if (!focusedKey) return
    const el = chipRefs.current[focusedKey]
    if (el && el.scrollIntoView) {
      el.scrollIntoView({ block: 'nearest', inline: 'nearest' })
    }
  }, [focusedKey])

  // Anchor header chrome to the Monday of the visible week so day-by-day
  // nav (which slides weekStart off Monday) doesn't drift the displayed
  // month/week number with every keystroke.
  const weekMonday = useMemo(() => mondayOf(weekStart), [weekStart])
  const monthYear = fmtMonthYear(weekMonday, lang)
  const weekNum = isoWeekNum(weekMonday)

  const gotoToday = () => {
    setWeekStart(mondayOf(today))
    setFocusedKey(null)
  }

  const navigateDays = (delta: number) => {
    setWeekStart(prev => addDays(prev, delta))
    setFocusedKey(null)
  }

  const visibleAttendees = attendees.slice(0, MAX_AVATAR_BUBBLES)
  const overflow = Math.max(0, attendees.length - MAX_AVATAR_BUBBLES)

  const footerLabel = focusedSlot
    ? `${fmtDayOfWeekShort(focusedSlot.start, lang)} ${fmtMonthDayShort(focusedSlot.start, lang)} · ${fmtClockTime(focusedSlot.start, lang, timezone)} – ${fmtClockTime(focusedSlot.end, lang, timezone)}`
    : ''

  return createPortal(
    <div
      className="pat-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="pat-title"
      onClick={onBack}
    >
      <div className="pat-shell" onClick={e => e.stopPropagation()}>
        {/* ── Header ───────────────────────────────────────────────────── */}
        <div className="pat-header">
          <div className="pat-header-left">
            <button
              type="button"
              className="pat-today-btn"
              onClick={gotoToday}
            >
              {t('picker_today')}
            </button>
            <div className="pat-nav-cluster">
              <button
                type="button"
                className="pat-nav-btn"
                onClick={() => navigateDays(-1)}
                aria-label={t('scheduler_prev_day')}
                title={`${t('scheduler_prev_day')} (←)`}
              >
                <ChevronLeftIcon size={12} />
              </button>
              <button
                type="button"
                className="pat-nav-btn"
                onClick={() => navigateDays(1)}
                aria-label={t('scheduler_next_day')}
                title={`${t('scheduler_next_day')} (→)`}
              >
                <ChevronRightIcon size={12} />
              </button>
            </div>
            <div className="pat-month-group">
              <span id="pat-title" className="pat-month-label">{monthYear}</span>
              <span className="pat-week-pill">W{weekNum}</span>
            </div>
          </div>

          <div className="pat-header-right">
            <span className="pat-find-label">{t('picker_subtitle')}</span>
            <span className="pat-attendees-pill" aria-label={t('picker_attendees_count', { count: attendees.length })}>
              <span className="pat-attendees-stack">
                {visibleAttendees.map((email, i) => (
                  <span
                    key={email}
                    className="pat-av-wrap"
                    style={{ marginLeft: i ? -7 : 0 }}
                    title={email}
                  >
                    <Avatar name={null} email={email} size="sm" />
                  </span>
                ))}
                {overflow > 0 && <span className="pat-av-overflow">+{overflow}</span>}
              </span>
              <span className="pat-attendees-meta">{attendees.length}</span>
            </span>
            <button
              type="button"
              className="pat-close-btn"
              onClick={onBack}
              aria-label={t('qe_close')}
              title={`${t('qe_close')} (Esc)`}
            >
              <CloseIcon size={18} />
            </button>
          </div>
        </div>

        {/* ── Grid ─────────────────────────────────────────────────────── */}
        <div className="pat-grid-wrap">
          {error && (
            <div className="pat-error" role="alert">{error}</div>
          )}
          <div className="pat-grid">
            {weekDays.map((date, d) => {
              const isToday = isSameDay(today, date, timezone)
              const isWknd = date.getDay() === 0 || date.getDay() === 6
              const daySlots = slotsByDay[d]
              // Saturday hosts the "jump forward a week" arrow when the
              // visible week is empty — break the weekend's dim opacity
              // for that column so the affordance reads at full strength.
              const hostsJumpArrow = date.getDay() === 6 && flatSlots.length === 0 && daySlots.length === 0
              return (
                <div
                  key={date.toISOString()}
                  className={`pat-col${isWknd ? ' is-weekend' : ''}${hostsJumpArrow ? ' has-jump' : ''}`}
                >
                  <div className="pat-col-head">
                    <span className={`pat-col-dow${isToday ? ' is-today' : ''}`}>
                      {fmtDayOfWeekShort(date, lang)}
                    </span>
                    <span className={`pat-col-num${isToday ? ' is-today' : ''}`}>
                      {date.getDate()}
                    </span>
                  </div>
                  <div className="pat-slot-list">
                    {loading && daySlots.length === 0 ? (
                      <div className="pat-slot-skeletons">
                        <span className="pat-slot-skel" />
                        <span className="pat-slot-skel" />
                        <span className="pat-slot-skel" />
                      </div>
                    ) : daySlots.length === 0 ? (
                      // Jump-forward arrow lives in the Saturday column when
                      // the whole week is empty — it's the natural "edge of
                      // the week" anchor, and matches the scroll-down pill
                      // used on long emails (filled teal surface).
                      date.getDay() === 6 && flatSlots.length === 0 ? (
                        <button
                          type="button"
                          className="pat-slot-jump"
                          onClick={() => navigateDays(7)}
                          aria-label={t('picker_jump_forward')}
                          title={t('picker_jump_forward')}
                        >
                          <ChevronRightIcon size={16} />
                        </button>
                      ) : isWknd ? (
                        <div className="pat-slot-none" aria-hidden="true">—</div>
                      ) : null
                    ) : (
                      daySlots.map((s, i) => {
                        const key = `${d}-${i}`
                        const focused = focusedKey === key
                        const isBest = bestKey === key
                        return (
                          <button
                            key={key}
                            ref={el => {
                              chipRefs.current[key] = el
                            }}
                            type="button"
                            className={`pat-chip${focused ? ' is-focused' : ''}${isBest ? ' is-best' : ''}`}
                            onClick={() => setFocusedKey(key)}
                            onDoubleClick={() => onSelectSlot(s.rawStart, s.rawEnd)}
                            aria-label={`${fmtDayOfWeekShort(date, lang)} ${date.getDate()} · ${fmtClockTime(s.start, lang, timezone)} – ${fmtClockTime(s.end, lang, timezone)}${isBest ? ` · ${t('picker_best')}` : ''}`}
                          >
                            <span className="pat-chip-time">
                              {fmtClockTime(s.start, lang, timezone)}
                              {' – '}
                              {fmtClockTime(s.end, lang, timezone)}
                            </span>
                            {isBest && (
                              <span className="pat-chip-best" title={t('picker_best')}>
                                <svg
                                  aria-hidden="true"
                                  width="9"
                                  height="9"
                                  viewBox="0 0 24 24"
                                  fill="currentColor"
                                >
                                  <path d="M12 2l2.94 7.36L23 10.27l-5.66 5.04L19 23l-7-4.47L5 23l1.66-7.69L1 10.27l8.06-.91L12 2z" />
                                </svg>
                              </span>
                            )}
                          </button>
                        )
                      })
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* ── Floating dock (matches AvailabilityPicker's av-dock) ─────── */}
        <div className="pat-dock-floating">
          {!focusedSlot && (
            <div className="pat-dock-hint" role="status">
              {t('picker_idle_hint')}
            </div>
          )}
          <div className="pat-dock">
            <div className="pat-duration-wrap">
              <button
                type="button"
                className="pat-dock-duration"
                onClick={() => setShowDurationMenu(v => !v)}
                aria-haspopup="menu"
                aria-expanded={showDurationMenu}
                aria-label={t('picker_change_duration')}
              >
                <svg
                  aria-hidden="true"
                  width="12"
                  height="12"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 16 14" />
                </svg>
                <span>{durationLabel(duration)}</span>
              </button>
              {showDurationMenu && (
                <div className="pat-duration-menu" role="menu">
                  <div className="pat-duration-menu-label">
                    {t('picker_duration_menu_label')}
                  </div>
                  <div className="pat-duration-options">
                    {DURATION_OPTIONS.map(d => {
                      const active = d === duration
                      return (
                        <button
                          key={d}
                          type="button"
                          role="menuitemradio"
                          aria-checked={active}
                          className={`pat-duration-opt${active ? ' is-active' : ''}`}
                          onClick={() => {
                            setDuration(d)
                            setShowDurationMenu(false)
                            setFocusedKey(null)
                          }}
                        >
                          {durationLabel(d)}
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
            <span className="pat-dock-tz" title={timezone}>{tzLabel}</span>
            {focusedSlot && (
              <span className="pat-dock-selected" aria-live="polite">
                {footerLabel}
              </span>
            )}
            <button
              type="button"
              className="pat-dock-cancel"
              onClick={onBack}
            >
              {t('picker_cancel')}
            </button>
            <button
              type="button"
              className="pat-dock-insert"
              disabled={!focusedSlot}
              onClick={() => focusedSlot && onSelectSlot(focusedSlot.rawStart, focusedSlot.rawEnd)}
              title={`${t('picker_schedule')} (↵)`}
            >
              {t('picker_schedule')}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}
