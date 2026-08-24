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

/**
 * Module-level state de l'ID du compte actif côté backend.
 *
 * Pattern : cache + listener + invalidation sur `ACCOUNT_CHANGED`.
 * Utilisé à la fois par le hook React `useCurrentAccountId` et par les
 * services non-React (draftStorage, crossChannelRules, workHours) pour
 * scoper leurs clés localStorage par compte.
 *
 * Convention : `null` = pas encore chargé ou pas de compte courant.
 */

import { fetchAccounts } from "../api/accounts";
import { appEvents, ACCOUNT_CHANGED } from "./appEvents";
import { getStoredToken } from "../services/authToken";

let cached: string | null = null;
let cacheLoaded = false;
let fetchPromise: Promise<string | null> | null = null;
const listeners = new Set<(id: string | null) => void>();

export function getCurrentAccountId(): string | null {
  return cached;
}

export function isCurrentAccountLoaded(): boolean {
  return cacheLoaded;
}

export function ensureCurrentAccountId(): Promise<string | null> {
  if (fetchPromise) return fetchPromise;
  if (cacheLoaded) return Promise.resolve(cached);
  // No JWT → user is on the login page. Skip the /api/accounts fetch which
  // would 401 and pollute the console (audit 2026-05-01 P1 finding #5). The
  // `auth:login_success` listener below invalidates this cache once a JWT
  // is in hand, triggering a fresh fetch.
  if (!getStoredToken()) {
    cached = null;
    cacheLoaded = true;
    return Promise.resolve(null);
  }
  fetchPromise = fetchAccounts()
    .then(({ current_account_id }) => {
      cached = current_account_id;
      cacheLoaded = true;
      listeners.forEach((fn) => fn(cached));
      return cached;
    })
    .catch((err) => {
      const msg = err instanceof Error ? err.message : String(err);
      if (!/\b401\b/.test(msg)) {
        console.warn("[currentAccountId] fetch failed:", err);
      }
      fetchPromise = null;
      return null;
    });
  return fetchPromise;
}

export function subscribeCurrentAccountId(
  fn: (id: string | null) => void
): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

function invalidate(): void {
  cached = null;
  cacheLoaded = false;
  fetchPromise = null;
  // Re-fetch en arrière-plan — les abonnés seront notifiés au succès
  ensureCurrentAccountId();
}

appEvents.addEventListener(ACCOUNT_CHANGED, invalidate);
// After OAuth completes (`auth:login_success` event from useAuth), the cache
// loaded a "no token" state — invalidate so the next consumer triggers a real
// /api/accounts fetch with the fresh JWT.
if (typeof window !== "undefined") {
  window.addEventListener("auth:login_success", invalidate);
}
