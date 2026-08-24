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
 * Singleton TanStack Query client.
 *
 * Defaults are tuned for an inbox app, not a generic SPA:
 *   - `staleTime: 30s` matches the prior `useSettingsCache` TTL — so first
 *     wave of subscribers within 30 s share one fetch (the issue's core win).
 *   - `gcTime: 30 min` keeps recently-viewed data hot for tab switches.
 *   - `refetchOnWindowFocus: false` — the WebSocket is the canonical
 *     invalidation bus (Phase 5). Focus-refetch would race with WS events.
 *   - `retry: 1` for queries — the lazy-body 3/7/14s pattern lives on
 *     specific email queries (Phase 3), not as a global retry.
 */
import { QueryClient } from "@tanstack/react-query";

let _client: QueryClient | null = null;

export function getQueryClient(): QueryClient {
  if (_client === null) {
    _client = new QueryClient({
      defaultOptions: {
        queries: {
          staleTime: 30_000,
          gcTime: 30 * 60_000,
          refetchOnWindowFocus: false,
          refetchOnReconnect: false,
          retry: 1,
        },
        mutations: {
          retry: 0,
        },
      },
    });
  }
  return _client;
}

/**
 * Test-only reset. Allows vitest to start each test with a fresh client and
 * prevents accidental cross-test pollution. Never call from production code.
 */
export function __resetQueryClientForTests(): void {
  _client = null;
}
