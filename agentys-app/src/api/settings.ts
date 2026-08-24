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
 * Raw HTTP for /api/settings.
 *
 * No caching, no dedup — those concerns live in the queryClient layer
 * (`src/hooks/useSettingsCache.ts` shim) and the `useQuery` factory inside
 * `createSettingHook`. This module is intentionally small: a typed fetch
 * and a typed PATCH, both signed with the active session auth headers.
 *
 * `accountId` is not passed in the URL — the backend resolves the active
 * account from the session header `X-Account-Id` (injected by
 * `getAuthHeaders()`). We thread `accountId` through the public API only
 * so the query-key segment stays scoped per-account on the client side.
 */
import { API_URL } from "../config";
import { getAuthHeaders, handleAuthResponse } from "../services/authToken";

const API_BASE = `${API_URL}/api`;

export type SettingsPayload = Record<string, unknown>;

export async function fetchAllSettings(): Promise<SettingsPayload> {
  const res = await fetch(`${API_BASE}/settings`, { headers: getAuthHeaders() });
  await handleAuthResponse(res);
  if (!res.ok) {
    // Don't return an error body shape (e.g. 401 `{error: "..."}`) as if it
    // were settings — the 30 s TTL would poison every downstream read.
    throw new Error(`GET /api/settings failed: ${res.status}`);
  }
  return res.json();
}

export async function patchSettingsHttp(fields: SettingsPayload): Promise<void> {
  const res = await fetch(`${API_BASE}/settings`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify(fields),
  });
  await handleAuthResponse(res);
  if (!res.ok) {
    throw new Error(`PATCH /api/settings returned ${res.status}`);
  }
}
