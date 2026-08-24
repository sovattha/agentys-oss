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
 * Factory for boolean setting hooks.
 *
 * Phase 1 migration: internals replaced by `useQuery` + `useMutation` over
 * the shared queryClient. The public signature is unchanged — every
 * existing call site (`useAutoReplyEnabled()`, `useDeepWorkEnabled()`, …)
 * keeps working without a diff.
 *
 * Wins vs the pre-migration implementation:
 *  - All boolean setting hooks share ONE cache entry per accountId
 *    (`qk.settings(accountId)`), so 25 hooks mounting in the same boot
 *    window collapse to a single `GET /api/settings`.
 *  - Cross-component reactivity is automatic (queryClient subscribers
 *    re-render on `setQueryData` / `invalidateQueries` without the manual
 *    `_listeners` registry).
 *  - Optimistic toggle + rollback now flows through `setQueryData`, so any
 *    `useQuery(qk.settings(...))` subscriber sees the optimistic value
 *    immediately instead of waiting for a manual store ping.
 *  - `useLocalStorage` config flag is preserved for API compat but is now
 *    a no-op (the queryClient `gcTime: 30 min` retains values across
 *    remounts, which is what the localStorage path was simulating).
 */
import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchAllSettings, patchSettingsHttp } from "../api/settings";
import { qk } from "../lib/queryKeys";
import type { SettingsPayload } from "../api/settings";

interface SettingHookConfig {
  /** Key used in the GET /api/settings response and PATCH body. */
  settingKey: string;
  /** Default value when not yet loaded from the server. */
  defaultValue?: boolean;
  /**
   * Preserved for backwards compatibility. Pre-Phase-1 this gated a
   * localStorage path with `useSyncExternalStore`; queryClient subsumes
   * both responsibilities so the flag no longer affects behaviour.
   */
  useLocalStorage?: boolean;
  /** Reserved for compat — see `useLocalStorage`. */
  localStorageKey?: string;
  /**
   * Pre-Phase-1 this gated auth headers on the PATCH; queryClient calls
   * `patchSettingsHttp` which always carries `getAuthHeaders()`, so this
   * flag is also a no-op now.
   */
  useAuthHeaders?: boolean;
  /** Name used in console.error messages for debugging. */
  hookName: string;
}

export function createSettingHook(config: SettingHookConfig) {
  const { settingKey, defaultValue = false, hookName } = config;

  return function useBooleanSetting(accountId?: number): {
    value: boolean;
    toggle: () => Promise<boolean>;
  } {
    const queryClient = useQueryClient();
    const queryKey = qk.settings(accountId);

    const { data: settings } = useQuery({
      queryKey,
      queryFn: fetchAllSettings,
      // staleTime/gcTime inherited from the client defaults (30 s / 30 min).
    });

    const rawValue = settings?.[settingKey];
    const value = typeof rawValue === "boolean" ? rawValue : defaultValue;

    const mutation = useMutation({
      mutationFn: async (next: boolean): Promise<void> => {
        await patchSettingsHttp({ [settingKey]: next });
      },
      // Optimistic: flip the cached settings entry before the PATCH lands.
      onMutate: async (next: boolean) => {
        await queryClient.cancelQueries({ queryKey });
        const snapshot = queryClient.getQueryData<SettingsPayload>(queryKey);
        queryClient.setQueryData<SettingsPayload>(queryKey, (prev) => ({
          ...(prev ?? {}),
          [settingKey]: next,
        }));
        return { snapshot };
      },
      // Rollback on failure — restore the exact snapshot, not just !next.
      onError: (err, _next, ctx) => {
        if (ctx?.snapshot !== undefined) {
          queryClient.setQueryData(queryKey, ctx.snapshot);
        }
        console.error(`[${hookName}] PATCH failed`, err);
      },
    });

    const toggle = useCallback(async (): Promise<boolean> => {
      const next = !value;
      try {
        await mutation.mutateAsync(next);
        return true;
      } catch {
        return false;
      }
    }, [value, mutation]);

    return { value, toggle };
  };
}
