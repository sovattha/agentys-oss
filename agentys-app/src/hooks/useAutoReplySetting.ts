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

import { useState, useCallback, useEffect, useRef } from "react";
import i18n from "../i18n";
import { API_URL } from "../config";
import { getAuthHeaders } from "../services/authToken";
import { fetchSettingsCached, invalidateSettingsCache, patchSettingsCache } from "./useSettingsCache";

const API_BASE = `${API_URL}/api`;
const LS_CAL_EVENT_KEY = 'agentys-auto-reply-event-id';

interface AutoReplyState {
  enabled: boolean;
  message: string;
  start: string;
  end: string;
  transferEnabled: boolean;
  transferEmail: string;
}

function authJson(): Record<string, string> {
  return { "Content-Type": "application/json", ...getAuthHeaders() };
}

export function useAutoReplySetting(accountId?: number) {
  const [autoReply, setAutoReplyState] = useState<AutoReplyState>({
    enabled: false,
    message: "",
    start: "",
    end: "",
    transferEnabled: false,
    transferEmail: "",
  });

  const [calendarSynced, setCalendarSynced] = useState(false);
  const [calendarSyncError, setCalendarSyncError] = useState<string | null>(null);
  // Flips true once the mount-time settings load resolves. Consumers use it to
  // distinguish "loaded, message is empty" from "not loaded yet" before acting
  // on the message (e.g. the suggested-message pre-fill in AutoReplyModal).
  const [loaded, setLoaded] = useState(false);

  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const pendingPatchRef = useRef<Record<string, unknown>>({});
  const syncInFlightRef = useRef(false);
  const latestStateRef = useRef<AutoReplyState>(autoReply);

  // Keep latestStateRef in sync so flushPending can access current state
  useEffect(() => {
    latestStateRef.current = autoReply;
  }, [autoReply]);

  const syncCalendarEvent = useCallback(async (state: AutoReplyState) => {
    // Guard against concurrent calls (React StrictMode double-invoke)
    if (syncInFlightRef.current) return;
    syncInFlightRef.current = true;
    setCalendarSyncError(null);

    // Audit Cluster D (2026-05-17) F-11 / regressions batch4 F-04: previously
    // the dedup/cleanup DELETEs were `.catch(() => {})` so partial failures
    // left phantom "Absence" events in the provider with zero user signal.
    // F-11's first pass switched to `setTimeout(check failures, 1500)` —
    // batch4 found that any provider responding slower than 1500 ms reported
    // 0 failures even when DELETEs eventually returned 4xx. Replace the
    // magic deadline with an awaited `Promise.allSettled` of every queued
    // DELETE so the toast reflects real outcomes regardless of latency.
    let cleanupFailures = 0;
    const pendingCleanups: Promise<unknown>[] = [];
    const deleteCalendarEvent = (id: string) => {
      const p = fetch(`${API_BASE}/calendar/events/${id}`, { method: "DELETE", headers: getAuthHeaders() })
        .then((r) => {
          if (!r.ok) cleanupFailures += 1;
        })
        .catch(() => {
          cleanupFailures += 1;
        });
      pendingCleanups.push(p);
      return p;
    };

    try {
      const storedId = localStorage.getItem(LS_CAL_EVENT_KEY);

      if (state.enabled && state.start && state.end) {
        const payload = {
          title: "Absence",
          start_time: state.start + "T00:00:00",
          end_time: state.end + "T23:59:59",
          all_day: true,
          description: state.message || "",
        };

        if (storedId) {
          const res = await fetch(`${API_BASE}/calendar/events/${storedId}`, {
            method: "PATCH",
            headers: authJson(),
            body: JSON.stringify(payload),
          });
          if (res.ok) {
            // Fire-and-forget: delete any orphaned "Absence" duplicates in this period
            fetch(
              `${API_BASE}/calendar/events?start=${encodeURIComponent(state.start + "T00:00:00")}&end=${encodeURIComponent(state.end + "T23:59:59")}&limit=50`,
              { headers: getAuthHeaders() }
            )
              .then(r => r.ok ? r.json() : null)
              .then((data) => {
                if (!data) return;
                const dupes = (data.events || []).filter(
                  (e: { title?: string; id?: string }) => e.title === "Absence" && e.id && e.id !== storedId
                );
                for (const d of dupes) {
                  void deleteCalendarEvent(d.id);
                }
              })
              .catch(() => {});
            setCalendarSynced(true);
            window.dispatchEvent(new CustomEvent('agentys:calendar-synced'));
            return;
          }
          if (res.status !== 404) {
            const errData = await res.json().catch(() => ({}));
            throw new Error((errData as { message?: string }).message || i18n.t('common:toasts.calendar_event_update_failed'));
          }
          // 404 → event deleted externally → fallthrough to dedup search
          localStorage.removeItem(LS_CAL_EVENT_KEY);
        }

        // Dedup: find ALL existing "Absence" events in this period
        try {
          const searchRes = await fetch(
            `${API_BASE}/calendar/events?start=${encodeURIComponent(state.start + "T00:00:00")}&end=${encodeURIComponent(state.end + "T23:59:59")}&limit=50`,
            { headers: getAuthHeaders() }
          );
          if (searchRes.ok) {
            const searchData = await searchRes.json();
            const absences: { title?: string; id?: string }[] = (searchData.events || []).filter(
              (e: { title?: string; id?: string }) => e.title === "Absence" && e.id
            );
            if (absences.length > 0) {
              const keepId = absences[0].id!;
              localStorage.setItem(LS_CAL_EVENT_KEY, keepId);
              // Delete all duplicates (tracked — F-11)
              for (const dup of absences.slice(1)) {
                void deleteCalendarEvent(dup.id!);
              }
              // Update the kept event with latest description.
              // Site 2 (audit toast-coverage 2026-06-11) : ce PATCH était
              // `.catch(() => {})` puis synced=true inconditionnel — en échec,
              // l'événement gardait l'ANCIENNE description mais l'UI affichait
              // « synchronisé ». Même contrat que la branche storedId : !ok →
              // throw → le catch global remet calendarSynced=false.
              const keepRes = await fetch(`${API_BASE}/calendar/events/${keepId}`, {
                method: "PATCH",
                headers: authJson(),
                body: JSON.stringify(payload),
              });
              if (!keepRes.ok) {
                const errData = await keepRes.json().catch(() => ({}));
                throw new Error((errData as { message?: string }).message || i18n.t('common:toasts.calendar_event_update_failed'));
              }
              setCalendarSynced(true);
              window.dispatchEvent(new CustomEvent('agentys:calendar-synced'));
              return;
            }
          }
        } catch {
          /* best-effort dedup, fall through to POST */
        }

        const res = await fetch(`${API_BASE}/calendar/events`, {
          method: "POST",
          headers: authJson(),
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error((errData as { message?: string }).message || i18n.t('common:toasts.calendar_event_create_failed'));
        }
        const data = await res.json();
        localStorage.setItem(LS_CAL_EVENT_KEY, data.event_id);
        setCalendarSynced(true);
        window.dispatchEvent(new CustomEvent('agentys:calendar-synced'));
      } else {
        // Delete the stored event (tracked — F-11)
        if (storedId) {
          void deleteCalendarEvent(storedId);
          localStorage.removeItem(LS_CAL_EVENT_KEY);
        }
        // Cleanup orphaned "Absence" events (e.g. localStorage lost the ID)
        // Search a wide range (±6 months) and delete all "Absence" events we created
        const now = new Date();
        const searchStart = new Date(now);
        searchStart.setMonth(searchStart.getMonth() - 1);
        const searchEnd = new Date(now);
        searchEnd.setMonth(searchEnd.getMonth() + 6);
        fetch(
          `${API_BASE}/calendar/events?start=${encodeURIComponent(searchStart.toISOString())}&end=${encodeURIComponent(searchEnd.toISOString())}&limit=100`,
          { headers: getAuthHeaders() }
        )
          .then(r => r.ok ? r.json() : null)
          .then((data) => {
            if (!data) return;
            const orphans = (data.events || []).filter(
              (e: { title?: string; id?: string }) => e.title === "Absence" && e.id && e.id !== storedId
            );
            for (const o of orphans) {
              void deleteCalendarEvent(o.id!);
            }
            if (orphans.length > 0) {
              window.dispatchEvent(new CustomEvent('agentys:calendar-synced'));
            }
          })
          .catch(() => {});
        setCalendarSynced(false);
        window.dispatchEvent(new CustomEvent('agentys:calendar-synced'));
      }
    } catch {
      // Calendar sync is a best-effort feature — silently fail if calendar is not configured
      setCalendarSynced(false);
    } finally {
      syncInFlightRef.current = false;
      // F-04 (audit regressions 2026-05-17 batch4): wait for ALL queued
      // cleanup DELETEs before checking the failure count, instead of the
      // previous setTimeout(1500) magic deadline that silently dropped any
      // DELETE slower than 1.5 s. `Promise.allSettled` never rejects, so
      // the catch above is unaffected; if no DELETEs were queued the array
      // is empty and the chain resolves synchronously.
      void Promise.allSettled(pendingCleanups).then(() => {
        if (cleanupFailures > 0 && typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('agentys:toast', {
            detail: {
              message: i18n.t('common:toasts.autoreply_calendar_cleanup_partial'),
              type: 'warning',
              duration: 6000,
            },
          }));
        }
      });
    }
  }, []);

  useEffect(() => {
    fetchSettingsCached(accountId)
      .then((data) => {
        const state: AutoReplyState = {
          enabled: !!data.auto_reply_enabled,
          message: (data.auto_reply_message as string) ?? "",
          start: (data.auto_reply_start as string) ?? "",
          end: (data.auto_reply_end as string) ?? "",
          transferEnabled: !!data.auto_transfer_enabled,
          transferEmail: (data.auto_transfer_email as string) ?? "",
        };
        setAutoReplyState(state);
        setLoaded(true);
        // Always sync: if enabled → create/dedup events; if disabled → cleanup orphans
        syncCalendarEvent(state);
      })
      .catch(err => console.error('[useAutoReplySetting] load settings failed:', err));
  }, [accountId, syncCalendarEvent]);

  /** Flush any pending debounced changes immediately. Call before closing. */
  const flushPending = useCallback(() => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
      debounceRef.current = undefined;
    }
    const pending = { ...pendingPatchRef.current };
    if (Object.keys(pending).length === 0) return;
    pendingPatchRef.current = {};
    patchSettingsCache(pending, accountId);
    fetch(`${API_BASE}/settings`, {
      keepalive: true,
      method: "PATCH",
      headers: authJson(),
      body: JSON.stringify(pending),
    }).then(() => {
      invalidateSettingsCache(accountId);
      syncCalendarEvent(latestStateRef.current);
    }).catch(err => {
      // A-3 (audit 2026-05-29): the unmount flush silently swallowed save
      // failures with only a console.error — same risk as the debounced
      // patch (F-12), so surface the same toast here.
      console.error('[useAutoReplySetting] flush patch failed:', err);
      invalidateSettingsCache(accountId);
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: {
            message: i18n.t('common:toasts.autoreply_save_failed'),
            type: 'error',
            duration: 8000,
          },
        }));
      }
    });
  }, [syncCalendarEvent, accountId]);

  // Flush pending patch on unmount (fermeture du modal)
  useEffect(() => {
    return () => {
      flushPending();
    };
  }, [flushPending]);

  const debouncedPatch = useCallback((fields: Record<string, unknown>, stateSnapshot?: AutoReplyState) => {
    // Accumule les changements en attente
    Object.assign(pendingPatchRef.current, fields);

    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }
    debounceRef.current = setTimeout(async () => {
      const pending = { ...pendingPatchRef.current };
      pendingPatchRef.current = {};
      try {
        patchSettingsCache(pending, accountId);
        const res = await fetch(`${API_BASE}/settings`, {
          method: "PATCH",
          headers: authJson(),
          body: JSON.stringify(pending),
        });
        if (!res.ok) {
          throw new Error(`PATCH /api/settings returned ${res.status}`);
        }
        invalidateSettingsCache(accountId);
        if (stateSnapshot) {
          syncCalendarEvent(stateSnapshot);
        }
      } catch (err) {
        // Audit F-12 (2026-05-12): without a toast the user could set up
        // vacation dates / auto-reply text and walk away thinking it was
        // saved, while the PATCH silently failed. Invalidate the cache so
        // the next read reflects server state, then alert the user.
        console.error('[useAutoReplySetting] debounced patch failed:', err);
        invalidateSettingsCache(accountId);
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('agentys:toast', {
            detail: {
              message: i18n.t('common:toasts.autoreply_save_failed'),
              type: 'error',
              duration: 8000,
            },
          }));
        }
      }
    }, 400);
  }, [syncCalendarEvent, accountId]);

  const toggleAutoReply = useCallback(() => {
    const newValue = !autoReply.enabled;
    setAutoReplyState((prev) => ({ ...prev, enabled: newValue }));
    patchSettingsCache({ auto_reply_enabled: newValue }, accountId);
    fetch(`${API_BASE}/settings`, {
      method: "PATCH",
      headers: authJson(),
      body: JSON.stringify({ auto_reply_enabled: newValue }),
    }).then(async (res) => {
      if (res && !res.ok) {
        const body = await res.json().catch(() => ({}));
        console.error('[useAutoReplySetting] toggle patch rejected:', res.status, body);
        setAutoReplyState((prev) => ({ ...prev, enabled: !newValue }));
        invalidateSettingsCache(accountId);
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('agentys:toast', {
            detail: {
              message: i18n.t('common:toasts.autoreply_save_failed'),
              type: 'error',
              duration: 6000,
            },
          }));
        }
        return;
      }
      invalidateSettingsCache(accountId);
      syncCalendarEvent({ ...autoReply, enabled: newValue });
    }).catch(err => {
      console.error('[useAutoReplySetting] toggle patch network error:', err);
      setAutoReplyState((prev) => ({ ...prev, enabled: !newValue }));
      invalidateSettingsCache(accountId);
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: {
            message: i18n.t('common:toasts.autoreply_save_failed'),
            type: 'error',
            duration: 6000,
          },
        }));
      }
    });
  }, [autoReply, syncCalendarEvent, accountId]);

  const toggleTransfer = useCallback(() => {
    const newValue = !autoReply.transferEnabled;
    setAutoReplyState((prev) => ({ ...prev, transferEnabled: newValue }));
    patchSettingsCache({ auto_transfer_enabled: newValue }, accountId);
    fetch(`${API_BASE}/settings`, {
      method: "PATCH",
      headers: authJson(),
      body: JSON.stringify({ auto_transfer_enabled: newValue }),
    }).then(async (res) => {
      if (res && !res.ok) {
        throw new Error(`PATCH /api/settings returned ${res.status}`);
      }
      invalidateSettingsCache(accountId);
    }).catch(err => {
      // Audit F-09 (2026-05-12): the rollback was already happening but the
      // user saw no toast — the toggle just "snapped back" with no
      // explanation. Surface a global toast on the rollback.
      console.error('[useAutoReplySetting] transfer toggle patch failed:', err);
      setAutoReplyState((prev) => ({ ...prev, transferEnabled: !newValue }));
      invalidateSettingsCache(accountId);
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: {
            message: i18n.t('common:toasts.autoforward_save_failed'),
            type: 'error',
            duration: 6000,
          },
        }));
      }
    });
  }, [autoReply, accountId]);

  const setAutoReply = useCallback(
    (fields: Partial<AutoReplyState>) => {
      setAutoReplyState((prev) => {
        const next = { ...prev, ...fields };
        // Build the API patch outside setState to avoid side effects in the callback
        // We schedule the patch via queueMicrotask so it runs after setState commits.
        const patch: Record<string, unknown> = {};
        if ("enabled" in fields) patch.auto_reply_enabled = next.enabled;
        if ("message" in fields) patch.auto_reply_message = next.message;
        if ("start" in fields) patch.auto_reply_start = next.start;
        if ("end" in fields) patch.auto_reply_end = next.end;
        if ("transferEnabled" in fields) patch.auto_transfer_enabled = next.transferEnabled;
        if ("transferEmail" in fields) patch.auto_transfer_email = next.transferEmail;
        queueMicrotask(() => debouncedPatch(patch, next));
        return next;
      });
    },
    [debouncedPatch]
  );

  return {
    autoReplyEnabled: autoReply.enabled,
    autoReplyMessage: autoReply.message,
    autoReplyStart: autoReply.start,
    autoReplyEnd: autoReply.end,
    autoTransferEnabled: autoReply.transferEnabled,
    autoTransferEmail: autoReply.transferEmail,
    calendarSynced,
    calendarSyncError,
    loaded,
    toggleAutoReply,
    toggleTransfer,
    setAutoReply,
    flushPending,
  };
}
