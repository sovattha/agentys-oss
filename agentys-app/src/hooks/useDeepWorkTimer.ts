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

import { useState, useEffect, useCallback, useRef } from "react";
import { API_URL } from "../config";
import { getAuthHeaders, getStoredToken } from "../services/authToken";
import { useDeepWorkSetting, type DeepWorkSettings, type CheckSlot, type WorkBlock } from "./useDeepWorkSetting";
import { formatHourMinute } from "../utils/dateFormat";
import i18n from "../i18n";

function timeToMinutes(hhmm: string): number {
  const [h, m] = hhmm.split(":").map(Number);
  return (h || 0) * 60 + (m || 0);
}

/** ISO weekday: 1=Mon, 7=Sun (JS getDay: 0=Sun → convert) */
function jsToIsoWeekday(jsDay: number): number {
  return jsDay === 0 ? 7 : jsDay;
}

/** Minutes-since-midnight → locale-aware clock (FR "9h00", EN/ES "09:00"). */
function fmtMinClock(mins: number): string {
  return formatHourMinute(new Date(2000, 0, 1, Math.floor(mins / 60), mins % 60), i18n.language);
}

/**
 * INVERTED logic: Deep Work is ON when NOT in a check slot.
 * Returns the current check slot info if user is in one, or null if in deep work.
 */
function findCurrentCheckSlot(
  s: DeepWorkSettings,
  now: Date
): { inCheckSlot: boolean; slotLabel: string; slotEnd: number; slotStart: number } {
  // Check weekday first
  const isoDay = jsToIsoWeekday(now.getDay());
  if (!s.weekdays.includes(isoDay)) {
    return { inCheckSlot: false, slotLabel: "", slotEnd: 0, slotStart: 0 };
  }

  const mins = now.getHours() * 60 + now.getMinutes();
  for (let i = 0; i < s.checkSlots.length; i++) {
    const slot = s.checkSlots[i];
    const start = timeToMinutes(slot.start);
    const end = start + slot.duration;
    if (mins >= start && mins < end) {
      return {
        inCheckSlot: true,
        slotLabel: `Consultation ${i + 1} \u00b7 ${fmtMinClock(start)} \u2013 ${fmtMinClock(end)}`,
        slotEnd: end,
        slotStart: start,
      };
    }
  }
  return { inCheckSlot: false, slotLabel: "", slotEnd: 0, slotStart: 0 };
}

/** Find next check slot from now (wraps around to next workday if needed) */
function findNextCheckSlot(
  slots: CheckSlot[],
  nowMins: number,
  weekdays?: number[],
  now?: Date
): { start: number; startStr: string; label: string; wrapAround?: boolean } | null {
  const sorted = slots
    .map((s, i) => ({ start: timeToMinutes(s.start), duration: s.duration, idx: i }))
    .sort((a, b) => a.start - b.start);
  for (const s of sorted) {
    if (s.start > nowMins) {
      const endMin = s.start + s.duration;
      const startStr = fmtMinClock(s.start);
      return {
        start: s.start,
        startStr,
        label: `Emails \u00b7 ${startStr} \u2192 ${fmtMinClock(endMin)}`,
      };
    }
  }
  // No more slots today — wrap around to next workday
  if (weekdays && weekdays.length > 0 && now && sorted.length > 0) {
    const firstSlot = sorted[0];
    const endMin = firstSlot.start + firstSlot.duration;
    const startStr = fmtMinClock(firstSlot.start);
    const todayIso = jsToIsoWeekday(now.getDay());
    for (let offset = 1; offset <= 7; offset++) {
      const nextDay = ((todayIso - 1 + offset) % 7) + 1;
      if (weekdays.includes(nextDay)) {
        return {
          start: firstSlot.start,
          startStr,
          label: `Emails \u00b7 ${startStr} \u2192 ${fmtMinClock(endMin)}`,
          wrapAround: true,
        };
      }
    }
  }
  return null;
}

// ── Snooze for day ──
const SNOOZE_DAY_KEY = "agentys_dw_snooze_day";

export function recordDeepWorkFeature(feature: string, count: number): void {
  if (!getStoredToken()) return;
  fetch(`${API_URL}/api/stats/feature`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify({ feature, count }),
  }).catch(() => { /* fire-and-forget */ });
}

function isSnoozedToday(): boolean {
  try {
    const stored = localStorage.getItem(SNOOZE_DAY_KEY);
    const today = new Date().toISOString().slice(0, 10);
    return stored === today;
  } catch { return false; }
}

function setSnoozeToday(): void {
  const today = new Date().toISOString().slice(0, 10);
  localStorage.setItem(SNOOZE_DAY_KEY, today);
}

// ── Streak persistence ──
const STREAK_KEY = "agentys_dw_streak_dates";

function getStreakDates(): string[] {
  try {
    const raw = localStorage.getItem(STREAK_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

function saveStreakDates(dates: string[]): void {
  localStorage.setItem(STREAK_KEY, JSON.stringify(dates));
}

function computeStreak(dates: string[]): number {
  if (dates.length === 0) return 0;
  const today = new Date().toISOString().slice(0, 10);
  const sorted = [...new Set(dates)].sort().reverse();
  if (sorted[0] !== today) return 0;
  let streak = 1;
  for (let i = 1; i < sorted.length; i++) {
    const prev = new Date(sorted[i - 1]);
    prev.setDate(prev.getDate() - 1);
    if (sorted[i] === prev.toISOString().slice(0, 10)) {
      streak++;
    } else {
      break;
    }
  }
  return streak;
}

// ── VIP summary ──
interface VipSummary {
  vipCount: number
  vipSenders: string[]
  totalCount: number
}

export interface UseDeepWorkTimerReturn {
  /** True = overlay should block inbox (user is in deep work) */
  isActive: boolean
  isManualOverride: boolean
  focusMinutes: number
  slotProgress: number
  slotLabel: string
  nextCheckLabel: string
  emailsSummary: number
  streakDays: number
  vipSummary: VipSummary | null
  activate: () => void
  deactivate: () => void
  bypassOverlay: () => void
  snoozeForDay: () => void
  settings: DeepWorkSettings
  setEnabled: (val: boolean) => void
  setEmailsEnabled: (val: boolean) => void
  setWorkEnabled: (val: boolean) => void
  setCheckSlots: (val: CheckSlot[]) => void
  setVipContacts: (val: string[]) => void
  setWeekdays: (val: number[]) => void
  setPersonalBlocks: (val: WorkBlock[]) => void
}

export interface UseDeepWorkTimerOptions {
  onSlotEnd?: () => void
  accountId?: number
}

export function useDeepWorkTimer(options?: UseDeepWorkTimerOptions): UseDeepWorkTimerReturn {
  const {
    settings, isLoaded, setEnabled, setEmailsEnabled, setWorkEnabled, setCheckSlots, setVipContacts, setWeekdays, setPersonalBlocks,
  } = useDeepWorkSetting(options?.accountId);

  const [isManualActive, setIsManualActive] = useState(false);
  const [isManualOverride, setIsManualOverride] = useState(false);
  const [isSnoozedDay, setIsSnoozedDay] = useState(() => isSnoozedToday());
  const [isInDeepWork, setIsInDeepWork] = useState(false);
  const [slotLabel, setSlotLabel] = useState("");
  const [nextCheckLabel, setNextCheckLabel] = useState("");
  const [focusMinutes, setFocusMinutes] = useState(0);
  const [slotProgress, setSlotProgress] = useState(0);
  const [emailsSummary, setEmailsSummary] = useState(0);
  const [streakDays, setStreakDays] = useState(() => computeStreak(getStreakDates()));
  const [vipSummary, setVipSummary] = useState<VipSummary | null>(null);

  const prevInDeepWorkRef = useRef(false);
  const deepWorkStartRef = useRef<string>("");
  const timeSavedTrackedRef = useRef(0);
  const onSlotEndRef = useRef(options?.onSlotEnd);
  onSlotEndRef.current = options?.onSlotEnd;

  // Check slot every 30s
  useEffect(() => {
    const check = () => {
      if (!isLoaded) return;

      // Deep Work disabled (master switch off, email-blocking off, or snoozed
      // for the day) — no tracking, no side effects. Without this guard, the
      // background tracker silently accumulates "focus" time during working
      // hours and fires a "Session terminée" recap card the moment a check
      // slot begins — even though the user never activated the mode.
      if (!settings.enabled || !settings.emailsEnabled || isSnoozedDay) {
        if (prevInDeepWorkRef.current) {
          prevInDeepWorkRef.current = false;
          setIsInDeepWork(false);
        }
        return;
      }

      const now = new Date();
      const result = findCurrentCheckSlot(settings, now);
      const nowMins = now.getHours() * 60 + now.getMinutes();

      // Inverted: deep work when NOT in check slot AND on a weekday
      const isoDay = jsToIsoWeekday(now.getDay());
      const isWeekday = settings.weekdays.includes(isoDay);
      const inDeepWork = isWeekday && !result.inCheckSlot;

      setIsInDeepWork(inDeepWork);

      if (inDeepWork) {
        // Find which check slot we came out of
        const sortedSlots = settings.checkSlots
          .map(s => timeToMinutes(s.start) + s.duration)
          .sort((a, b) => a - b);
        const lastCheckEnd = sortedSlots.filter(end => end <= nowMins).pop();
        const beforeFirstSlot = lastCheckEnd === undefined;
        const elapsed = beforeFirstSlot ? 0 : nowMins - lastCheckEnd;
        setFocusMinutes(Math.max(0, elapsed));

        // Next check slot info (with wrap-around to next workday)
        const nextSlot = findNextCheckSlot(settings.checkSlots, nowMins, settings.weekdays, now);
        if (nextSlot) {
          setNextCheckLabel(nextSlot.label);
          if (nextSlot.wrapAround) {
            // Day's slots are done, concentration continues until midnight
            setSlotLabel(i18n.t('deepfocus:dw_focus_end_of_day'));
            const totalGap = 1440 - (lastCheckEnd ?? nowMins);
            if (totalGap > 0) {
              const elapsedGap = nowMins - (lastCheckEnd ?? nowMins);
              setSlotProgress(Math.min(100, Math.round((elapsedGap / totalGap) * 100)));
            } else {
              setSlotProgress(100);
            }
          } else if (beforeFirstSlot) {
            // Before first slot — progress at 0
            setSlotProgress(0);
            setSlotLabel(i18n.t('deepfocus:dw_focus_until', { time: nextSlot.startStr }));
          } else {
            // Normal: between two slots
            const totalGap = nextSlot.start - lastCheckEnd;
            if (totalGap > 0) {
              setSlotProgress(Math.min(100, Math.round((elapsed / totalGap) * 100)));
            }
            setSlotLabel(i18n.t('deepfocus:dw_focus_until', { time: nextSlot.startStr }));
          }
        } else {
          setNextCheckLabel(i18n.t('deepfocus:dw_checks_done_today'));
          setSlotLabel(i18n.t('deepfocus:dw_focus_day_done'));
          // Progress toward end of day (midnight)
          const totalGapEod = 1440 - (lastCheckEnd ?? nowMins);
          if (totalGapEod > 0) {
            const elapsedEod = nowMins - (lastCheckEnd ?? nowMins);
            setSlotProgress(Math.min(100, Math.round((elapsedEod / totalGapEod) * 100)));
          } else {
            setSlotProgress(100);
          }
        }

        if (!prevInDeepWorkRef.current) {
          deepWorkStartRef.current = now.toISOString();
          // Sync tracker to current elapsed to avoid re-sending past batches on remount
          timeSavedTrackedRef.current = Math.floor(elapsed / 30);
        }

        // Track time saved every 30 minutes of focus (only send delta)
        const batchesToReport = Math.floor(elapsed / 30);
        if (batchesToReport > timeSavedTrackedRef.current) {
          const newBatches = batchesToReport - timeSavedTrackedRef.current;
          // Cap at 1 batch per tick (30s interval) to prevent massive dumps on remount
          const safeBatches = Math.min(newBatches, 1);
          timeSavedTrackedRef.current = batchesToReport;
          recordDeepWorkFeature("deep_work_min", safeBatches * 30);
        }
      } else {
        if (prevInDeepWorkRef.current) {
          // Just entered a check slot (deep work ended temporarily)
          setIsManualOverride(false);

          // Record streak (deep work session without bypass)
          if (!isManualOverride) {
            const today = new Date().toISOString().slice(0, 10);
            const dates = getStreakDates();
            if (!dates.includes(today)) {
              dates.push(today);
              saveStreakDates(dates);
              setStreakDays(computeStreak(dates));
            }
          }

          onSlotEndRef.current?.();
        }

        // Show check slot info when in a check window
        if (result.inCheckSlot) {
          setSlotLabel(result.slotLabel);
        }
      }
      prevInDeepWorkRef.current = inDeepWork;
    };

    check();
    const interval = setInterval(check, 30_000);
    return () => clearInterval(interval);
  }, [settings, isManualOverride, isLoaded, isSnoozedDay]);

  // Track emails via WebSocket new_email events
  const isActiveRef = useRef(false);
  isActiveRef.current = settings.enabled && settings.emailsEnabled && (isInDeepWork || isManualActive) && !isManualOverride;

  useEffect(() => {
    const handler = () => {
      setEmailsSummary((prev) => prev + 1);
      // Report blocked interruption to backend (only when concentration mode respected)
      if (isActiveRef.current) {
        recordDeepWorkFeature("deep_work_emails", 1);
      }
    };
    window.addEventListener("agentys:new_email", handler);
    return () => window.removeEventListener("agentys:new_email", handler);
  }, []);

  // Fetch VIP summary when active.
  // F10 (MEDIUM): AbortController gates each in-flight request to the lifetime
  // of the effect. Without it, deactivating Deep Work mid-flight let a stale
  // `setVipSummary` land on a hook that should have already cleared its panel.
  useEffect(() => {
    const isActive = settings.enabled && settings.emailsEnabled && (isInDeepWork || isManualActive) && !isManualOverride;
    if (!isActive || settings.vipContacts.length === 0) {
      setVipSummary(null);
      return;
    }
    const since = deepWorkStartRef.current || new Date().toISOString();
    const controller = new AbortController();
    const fetchVip = () => {
      fetch(`${API_URL}/api/deep-work/summary?since=${encodeURIComponent(since)}`, {
        headers: { ...getAuthHeaders() },
        signal: controller.signal,
      })
        .then((r) => r.ok ? r.json() : null)
        .then((data) => {
          if (controller.signal.aborted) return;
          if (data) {
            setVipSummary({
              vipCount: data.vip_count || 0,
              vipSenders: data.vip_senders || [],
              totalCount: data.total_count || 0,
            });
          }
        })
        .catch(err => {
          if (err?.name === 'AbortError') return;
          console.error('[useDeepWorkTimer] fetch VIP summary failed:', err);
        });
    };
    fetchVip();
    const interval = setInterval(fetchVip, 120_000);
    return () => {
      clearInterval(interval);
      controller.abort();
    };
  }, [settings.enabled, settings.emailsEnabled, isInDeepWork, isManualActive, isManualOverride, settings.vipContacts.length]);

  // isActive = should block inbox (requires both master switch AND email-blocking sub-feature enabled)
  const isActive = settings.enabled && settings.emailsEnabled && (isInDeepWork || isManualActive) && !isManualOverride && !isSnoozedDay;

  const activate = useCallback(() => {
    if (!settings.enabled) {
      setEnabled(true);
    }
    setIsManualActive(true);
    setIsManualOverride(false);
    deepWorkStartRef.current = new Date().toISOString();
    timeSavedTrackedRef.current = 0;
    setFocusMinutes(0);
    setSlotProgress(0);
    setEmailsSummary(0);
    if (!slotLabel) {
      setSlotLabel("Session manuelle");
    }
  }, [settings.enabled, setEnabled, slotLabel]);

  const deactivate = useCallback(() => {
    setIsManualActive(false);
    setIsManualOverride(false);
  }, []);

  const bypassOverlay = useCallback(() => {
    setIsManualOverride(true);
    // Bypass breaks streak
    const today = new Date().toISOString().slice(0, 10);
    const dates = getStreakDates().filter((d) => d !== today);
    saveStreakDates(dates);
    setStreakDays(computeStreak(dates));
  }, []);

  const snoozeForDay = useCallback(() => {
    setSnoozeToday();
    setIsSnoozedDay(true);
    // Snooze breaks streak
    const today = new Date().toISOString().slice(0, 10);
    const dates = getStreakDates().filter((d) => d !== today);
    saveStreakDates(dates);
    setStreakDays(computeStreak(dates));
  }, []);

  return {
    isActive,
    isManualOverride,
    focusMinutes,
    slotProgress,
    slotLabel,
    nextCheckLabel,
    emailsSummary,
    streakDays,
    vipSummary,
    activate,
    deactivate,
    bypassOverlay,
    snoozeForDay,
    settings,
    setEnabled,
    setEmailsEnabled,
    setWorkEnabled,
    setCheckSlots,
    setVipContacts,
    setWeekdays,
    setPersonalBlocks,
  };
}
