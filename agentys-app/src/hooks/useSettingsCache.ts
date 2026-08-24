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
 * Settings cache — backward-compat shim over TanStack queryClient.
 *
 * Phase 1 migration: the singleton dedup + 30 s TTL is now provided by the
 * queryClient (`staleTime: 30_000`, in-flight dedup is automatic). This
 * module preserves the public surface (`fetchSettingsCached`,
 * `invalidateSettingsCache`, `patchSettingsCache`) so existing non-hook
 * callers (App.tsx, CalendarView.tsx, useAutoReplySetting.ts, …) do not
 * need a touch in this phase.
 *
 * The actual storage is `queryClient.getQueryCache()` under
 * `qk.settings(accountId)`. Hooks using `useQuery(qk.settings(...))` share
 * the same cache entry as this shim, so a fetch through either path
 * deduplicates the other.
 */
import { getQueryClient } from "../lib/queryClient";
import { qk } from "../lib/queryKeys";
import { fetchAllSettings, type SettingsPayload } from "../api/settings";

export async function fetchSettingsCached(
  accountId?: number,
): Promise<SettingsPayload> {
  const client = getQueryClient();
  // fetchQuery handles: in-flight dedup, staleTime freshness, retry, gcTime.
  // All 25 boot-mounted setting hooks calling this within `staleTime`
  // collapse to a single network request.
  return client.fetchQuery({
    queryKey: qk.settings(accountId),
    queryFn: fetchAllSettings,
  });
}

export function invalidateSettingsCache(accountId?: number): void {
  const client = getQueryClient();
  void client.invalidateQueries({ queryKey: qk.settings(accountId) });
}

/**
 * Optimistically merge fields into the cached settings for an account.
 * Equivalent to the old in-memory merge — now backed by queryClient so a
 * concurrent `useQuery(qk.settings(...))` subscriber re-renders.
 */
export function patchSettingsCache(
  fields: SettingsPayload,
  accountId?: number,
): void {
  const client = getQueryClient();
  client.setQueryData<SettingsPayload>(qk.settings(accountId), (prev) => ({
    ...(prev ?? {}),
    ...fields,
  }));
}
