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
 * Canonical account-id normalizer.
 *
 * The backend exposes account ids in two shapes:
 *   - `/api/init` returns numeric ints (1, 2, …)
 *   - `/api/accounts` returns hex hashes ("a3f9c1d2…")
 *
 * The frontend has historically stored either form in different places. To
 * use account-id as a stable cache-key segment we need ONE function that
 * folds both forms (plus `null` / `undefined` / "default" / 0) into a single
 * canonical string. That string is opaque — it is never sent to the server,
 * only used as a query-key segment.
 *
 * Rules:
 *  - `null` / `undefined` / `""` / `"default"` / `0` / `"0"` → `"anon"`
 *    (the "no account bound yet" bucket; safe to share across pre-auth UI)
 *  - integers → `"i:<int>"` (e.g. `i:1`)
 *  - decimal-only strings → `"i:<int>"` after parseInt (so `"1"` and `1` map together)
 *  - hex-like strings → `"h:<lowercased>"` (so case noise doesn't fragment caches)
 *  - anything else → `"s:<str>"` (defensive — shouldn't happen, but never throws)
 *
 * The `i:` / `h:` / `s:` prefixes prevent collisions between an integer `1`
 * and a hex string `"1"`. The function is pure, total, never throws.
 */
export type AccountIdInput = string | number | null | undefined;

const HEX_RE = /^[0-9a-f]+$/i;

export function canonicalAccountId(input: AccountIdInput): string {
  if (input === null || input === undefined) return "anon";

  if (typeof input === "number") {
    if (!Number.isFinite(input) || input === 0) return "anon";
    return `i:${Math.trunc(input)}`;
  }

  // Defensive: TS will block non-string/number callers, but JS at runtime
  // can still pass through arrays/objects (e.g. accidental JSON.parse result).
  // Stay total — never throw.
  if (typeof input !== "string") return "anon";

  // string path
  const trimmed = input.trim();
  if (trimmed === "" || trimmed === "default" || trimmed === "0") return "anon";

  // Decimal-only (no leading zero strings except "0" which is handled above)
  if (/^-?\d+$/.test(trimmed)) {
    const n = Number(trimmed);
    if (Number.isFinite(n) && n !== 0) return `i:${Math.trunc(n)}`;
  }

  // Hex-like (mixed digits and a-f). Length check guards against treating
  // pure-decimal as hex — pure decimals are caught above.
  if (HEX_RE.test(trimmed) && /[a-f]/i.test(trimmed)) {
    return `h:${trimmed.toLowerCase()}`;
  }

  return `s:${trimmed}`;
}
