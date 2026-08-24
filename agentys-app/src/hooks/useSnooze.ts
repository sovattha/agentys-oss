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

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { apiClient } from '../services/api';
import { getStoredToken } from '../services/authToken';
import { getActiveAccountId } from '../api/emails';
import i18n from '../i18n';

export interface SnoozedEntry {
  emailId: string;
  date: string;   // ISO
  subject: string;
  type?: 'snooze' | 'followup';  // absent = 'snooze' (rétrocompat)
  labels?: Array<{ name: string; color: string }> | string[];
  reminderId?: string;  // backend reminder id — used to DELETE on dismiss
  sender?: string;      // email address of the original sender
  senderName?: string;  // display name of the original sender
}

export interface SnoozeHook {
  snoozedMap: Map<string, SnoozedEntry>;
  sleepingIds: Set<string>;
  wokeIds: Set<string>;
  wokeSnoozeIds: Set<string>;
  wokeFollowupIds: Set<string>;
  dismissSnoozed: (emailId: string) => void;
}

// MA-01: the snooze store is scoped per active account. A bare global key let
// one account's snoozes surface in another account's "Later" list (manual
// snooze entries are never auto-removed). The key uses the same id that scopes
// the backend reminder fetch (X-Account-Id) so the two stay in sync.
const STORAGE_PREFIX = 'agentys_snoozed';
const LEGACY_KEY = 'agentys_snoozed';

function storageKey(): string {
  return `${STORAGE_PREFIX}:${getActiveAccountId() || 'default'}`;
}

function isSnoozeKey(key: string | null): boolean {
  return !!key && (key === LEGACY_KEY || key.startsWith(`${STORAGE_PREFIX}:`));
}

function readEntries(): SnoozedEntry[] {
  try {
    const key = storageKey();
    const rawScoped = localStorage.getItem(key);
    if (rawScoped !== null) {
      const parsed = JSON.parse(rawScoped || '[]');
      return Array.isArray(parsed) ? parsed : [];
    }
    // One-time migration into the active account's scoped key. Claim BOTH the
    // pre-scoping global key AND the ':default' boot-window bucket: a snooze
    // written before setActiveAccountId() resolves lands under ':default' and
    // would otherwise be stranded there forever once a real account loads.
    // Only persist the fold once a real account is active (not the 'default'
    // placeholder) so the entries land under the right account.
    const activeId = getActiveAccountId();
    const onRealAccount = !!activeId && activeId !== 'default';
    const defaultKey = `${STORAGE_PREFIX}:default`;
    const sources = onRealAccount && key !== defaultKey ? [LEGACY_KEY, defaultKey] : [LEGACY_KEY];
    const byId = new Map<string, SnoozedEntry>();
    let found = false;
    for (const src of sources) {
      const raw = localStorage.getItem(src);
      if (raw === null) continue;
      found = true;
      const parsed = JSON.parse(raw || '[]');
      if (Array.isArray(parsed)) for (const e of parsed) byId.set(e.emailId, e);
    }
    if (!found) return [];
    const entries = Array.from(byId.values());
    if (onRealAccount) {
      localStorage.setItem(key, JSON.stringify(entries));
      for (const src of sources) localStorage.removeItem(src);
    }
    return entries;
  } catch {
    return [];
  }
}

function buildMaps(entries: SnoozedEntry[], now: string) {
  const snoozedMap = new Map<string, SnoozedEntry>();
  const sleepingIds = new Set<string>();
  const wokeIds = new Set<string>();
  const wokeSnoozeIds = new Set<string>();
  const wokeFollowupIds = new Set<string>();

  for (const entry of entries) {
    snoozedMap.set(entry.emailId, entry);
    if (entry.date > now) {
      sleepingIds.add(entry.emailId);
    } else {
      wokeIds.add(entry.emailId);
      if (entry.type === 'followup') {
        wokeFollowupIds.add(entry.emailId);
      } else {
        wokeSnoozeIds.add(entry.emailId);
      }
    }
  }

  return { snoozedMap, sleepingIds, wokeIds, wokeSnoozeIds, wokeFollowupIds };
}

export function writeSnoozeEntry(
  emailId: string,
  date: Date,
  subject: string,
  type: 'snooze' | 'followup' = 'snooze',
  labels?: Array<{ name: string; color: string }> | string[],
  sender?: string,
  senderName?: string,
): void {
  try {
    const entries = readEntries().filter(e => e.emailId !== emailId);
    entries.push({ emailId, date: date.toISOString(), subject, type, labels: labels?.length ? labels : undefined, sender: sender || undefined, senderName: senderName || undefined });
    const key = storageKey();
    localStorage.setItem(key, JSON.stringify(entries));
    window.dispatchEvent(new StorageEvent('storage', { key }));
  } catch {
    // ignore
  }
}

/** Sync backend reminders → localStorage on startup (résout la perte d'entrée après redémarrage).
 *
 *  Two-way sync: adds missing entries AND removes followup entries that no
 *  longer exist server-side. The removal half matters when the backend
 *  starts filtering a reminder kind out of /api/reminders (e.g. the
 *  ``draft_followup`` type, which moved to its own endpoint at
 *  /api/pending-drafts/snoozed) — without it, stale entries linger in
 *  localStorage and double-render in the Later view forever. Manual
 *  snooze entries (type='snooze' or absent) are NEVER auto-removed since
 *  they're written client-side and have no backend record.
 */
async function syncRemindersFromBackend(): Promise<void> {
  try {
    const reminders = await apiClient.getReminders();
    const current = readEntries();
    const backendIds = new Set(reminders.map(r => r.email_id));
    const currentIds = new Set(current.map(e => e.emailId));
    let changed = false;

    // Add entries the backend knows about but localStorage doesn't.
    for (const r of reminders) {
      if (!currentIds.has(r.email_id)) {
        current.push({
          emailId: r.email_id,
          date: r.reminder_date,
          subject: r.subject,
          type: 'followup',
          reminderId: r.id,
        });
        changed = true;
      }
    }

    // Remove server-backed followup entries the backend no longer returns
    // (deleted, dismissed, or filtered out — e.g. draft_followup type).
    const filtered = current.filter(e => {
      if (e.type === 'followup' && !backendIds.has(e.emailId)) {
        changed = true;
        return false;
      }
      return true;
    });

    if (changed) {
      const key = storageKey();
      localStorage.setItem(key, JSON.stringify(filtered));
      window.dispatchEvent(new StorageEvent('storage', { key }));
    }
  } catch {
    // Non-bloquant
  }
}

export function useSnooze(): SnoozeHook {
  const [entries, setEntries] = useState<SnoozedEntry[]>(() => readEntries());
  const syncedRef = useRef(false);

  // Sync backend → localStorage une seule fois au montage. Skip when no JWT
  // is present — login page would otherwise hit /api/reminders with 401
  // (audit 2026-05-01 P1 finding #5).
  useEffect(() => {
    if (syncedRef.current) return;
    if (!getStoredToken()) return;
    syncedRef.current = true;
    syncRemindersFromBackend();
  }, []);

  // Poll every 60s to detect newly woken emails
  useEffect(() => {
    const id = setInterval(() => {
      setEntries(readEntries());
    }, 60_000);
    return () => clearInterval(id);
  }, []);

  // Also listen to storage events (other tabs / same-tab writes)
  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (isSnoozeKey(e.key)) {
        setEntries(readEntries());
      }
    };
    window.addEventListener('storage', handler);
    return () => window.removeEventListener('storage', handler);
  }, []);

  // Re-read (and re-sync) when the active account changes so account A's snoozes
  // never bleed into account B's Later list (MA-01).
  useEffect(() => {
    const onAccountChanged = () => {
      setEntries(readEntries());
      if (getStoredToken()) {
        syncedRef.current = true;
        syncRemindersFromBackend();
      }
    };
    window.addEventListener('agentys:account-changed', onAccountChanged);
    return () => window.removeEventListener('agentys:account-changed', onAccountChanged);
  }, []);

  const dismissSnoozed = useCallback((emailId: string) => {
    let entryToDelete: SnoozedEntry | undefined;
    try {
      const current = readEntries();
      entryToDelete = current.find(e => e.emailId === emailId);
      const filtered = current.filter(e => e.emailId !== emailId);
      localStorage.setItem(storageKey(), JSON.stringify(filtered));
    } catch {
      // ignore
    }
    setEntries(prev => prev.filter(e => e.emailId !== emailId));
    // Supprimer le reminder backend en arrière-plan si nécessaire
    if (entryToDelete?.reminderId && entryToDelete.type === 'followup') {
      apiClient.deleteReminder(entryToDelete.reminderId).catch(err => {
        console.warn('[useSnooze] dismissSnoozed deleteReminder failed:', entryToDelete?.reminderId, err);
        // TC-04: the backend reminder DELETE failed, so syncRemindersFromBackend
        // re-injects this entry on next mount and the woken email reappears.
        // Tell the user instead of failing silently.
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: { message: i18n.t('common:toasts.reminder_delete_failed'), type: 'warning', duration: 5000 },
        }));
      });
    }
  }, []);

  const { snoozedMap, sleepingIds, wokeIds, wokeSnoozeIds, wokeFollowupIds } = useMemo(
    () => buildMaps(entries, new Date().toISOString()),
    [entries]
  );

  return { snoozedMap, sleepingIds, wokeIds, wokeSnoozeIds, wokeFollowupIds, dismissSnoozed };
}
