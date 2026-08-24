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
 * Cross-browser UUID v4 generator.
 *
 * `crypto.randomUUID()` is unsupported on Safari <15.4 and Firefox <96 — calling
 * it there throws TypeError, which crashes the calling component. This helper
 * tries the native API first and falls back to a `crypto.getRandomValues`-based
 * generator that's been available since Safari 11 / Firefox 21.
 *
 * If both are missing (extremely old browsers, jsdom without crypto, ancient
 * mobile WebViews), we fall back to `Math.random` — not cryptographically
 * strong, but never throws so the UI stays functional.
 *
 * Cryptographic strength only matters for security-sensitive IDs. The current
 * call sites (`AccountManager.tsx` form-state IDs) just need uniqueness
 * within a session, so degraded entropy on the last fallback is fine.
 */
export function safeRandomUUID(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    try {
      return crypto.randomUUID()
    } catch {
      // Some sandboxed contexts expose crypto but throw — fall through.
    }
  }

  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    const bytes = new Uint8Array(16)
    crypto.getRandomValues(bytes)
    // RFC 4122 v4: set version (4) and variant (10xx) bits.
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0'))
    return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex.slice(6, 8).join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10, 16).join('')}`
  }

  // Last-resort non-crypto fallback. Never reached on any browser shipped
  // since 2013, but guarantees the UI doesn't crash on exotic environments.
  const r = () => Math.floor(Math.random() * 0xffffffff).toString(16).padStart(8, '0')
  return `${r().slice(0, 8)}-${r().slice(0, 4)}-4${r().slice(0, 3)}-${r().slice(0, 4)}-${r()}${r().slice(0, 4)}`
}
