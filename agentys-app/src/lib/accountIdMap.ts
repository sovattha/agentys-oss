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
 * Hex ↔ int account-id resolver.
 *
 * Audit F-03 (2026-05-17 deep-audit): the backend exposes account ids in
 * two shapes — `/api/init` returns numeric ints (`{ id: 6, hash_id: "ca85…" }`)
 * while `/api/accounts` returns hex hashes only (`{ id: "ca85…" }`). The
 * active-account store (`api/emails.ts`) holds whichever form the most
 * recent caller passed: `useBackendConnection` plants the int-string
 * (`String(active.id)`) on initial login, but `AccountManager.handleActivate`
 * plants the hex (because `Account.id` from `/api/accounts` is hex).
 *
 * Backend WebSocket events always carry the int form. To keep the
 * cross-account guard in `useWebSocketSync` comparing apples to apples
 * regardless of which UI path produced the active id, callers can resolve
 * either form to its counterpart via this map.
 *
 * The map is populated by `useBackendConnection` once `/api/init` returns
 * the accounts payload (both forms present). It is intentionally a
 * module-level singleton so background hooks can read it without React
 * context.
 *
 * The functions are pure and total — they never throw, return null when
 * resolution fails, and the calling code must fall back to the raw form
 * in that case (preserves the pre-fix behaviour at worst).
 */
type AccountIdPair = { intId: number; hashId: string }

let _pairs: AccountIdPair[] = []

/** Register the int↔hex pairs from `/api/init`. Replaces any previous map. */
export function setAccountIdMap(
  accounts: ReadonlyArray<{ id: number; hash_id?: string | null }>,
): void {
  _pairs = accounts
    .filter((a): a is { id: number; hash_id: string } =>
      typeof a.hash_id === 'string' && a.hash_id.length > 0,
    )
    .map((a) => ({ intId: a.id, hashId: a.hash_id }))
}

/** Reset for tests. */
export function __resetAccountIdMapForTests(): void {
  _pairs = []
}

/**
 * Resolve any account-id form (int, int-as-string, or hex) to its int
 * counterpart as a string. Returns null when:
 *   - input is null / undefined / empty / "default"
 *   - input is a hex form not present in the registered pairs
 */
export function resolveToIntString(
  rawId: string | number | null | undefined,
): string | null {
  if (rawId === null || rawId === undefined) return null
  const s = typeof rawId === 'number' ? String(rawId) : rawId.trim()
  if (!s || s === 'default') return null
  // Already an int / int-string — return canonical decimal form.
  // Audit regressions (2026-05-18 batch5) F-02: the prior `n !== 0` guard
  // conflated "non-zero account id" with "valid id". `0` is a syntactically
  // valid INTEGER PRIMARY KEY value (test seeds, manual SQL, migration
  // backfills) — rejecting it silently dropped every WS event for the first
  // account. The "no account" sentinel is already filtered at line 57
  // (`s === 'default'`); we don't need an additional zero-check here.
  if (/^-?\d+$/.test(s)) {
    const n = Number(s)
    return Number.isFinite(n) ? String(Math.trunc(n)) : null
  }
  // Hex form — look up the matching int.
  const lower = s.toLowerCase()
  const pair = _pairs.find((p) => p.hashId.toLowerCase() === lower)
  return pair ? String(pair.intId) : null
}
