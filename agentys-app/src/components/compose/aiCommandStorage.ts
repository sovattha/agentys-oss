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
 * AI command menu — saved instructions storage layer.
 *
 * Saved commands are scoped per-account so that switching accounts (or sharing
 * the same device with different profiles) doesn't leak custom instructions.
 * The active account id is fetched once on mount and cached at the module level.
 */

import { fetchAccounts } from '../../api/accounts'
import i18n from '../../i18n'

let cachedAccountId: string | null = null
let accountIdPromise: Promise<string | null> | null = null

export function getCurrentAccountId(): Promise<string | null> {
  if (cachedAccountId) return Promise.resolve(cachedAccountId)
  if (accountIdPromise) return accountIdPromise
  accountIdPromise = fetchAccounts()
    .then(({ current_account_id }) => {
      cachedAccountId = current_account_id ?? null
      return cachedAccountId
    })
    .catch(() => null)
    .finally(() => { accountIdPromise = null })
  return accountIdPromise
}

export function getCachedAccountId(): string | null {
  return cachedAccountId
}

// Listen for account switches dispatched elsewhere in the app
if (typeof window !== 'undefined') {
  window.addEventListener('agentys:account-changed', () => {
    cachedAccountId = null
    accountIdPromise = null
  })
}

/** Test-only: resets the module-level account id cache. */
export function _resetAccountIdCacheForTests(): void {
  cachedAccountId = null
  accountIdPromise = null
}

export function savedCmdsKey(accountId: string | null): string {
  return accountId ? `ai-cmd-saved:${accountId}` : 'ai-cmd-saved'
}

export interface SavedCmd { id: number; label: string; instruction: string }

/**
 * Audit 2026-05-18: first-time-user seed for the AI command palette.
 *
 * The previous Ctrl+J popover was an empty box with one preset row plus a
 * free-text input — first-time users had nothing to click and bounced. Seed
 * four high-leverage instructions on first open so the popover always has
 * scannable affordances. Stored as regular saved commands, so the user can
 * delete or rename them like any other chip; the seed only runs on the
 * very first open per account (sentinel key tracks it).
 */
const SEEDED_FLAG_PREFIX = 'ai-cmd-seeded:'
// Labels (chip text) and instructions (LLM payload) are resolved through i18n
// at SEED time — first open per account — so a new user gets chips in their UI
// language. Once seeded they become regular user data (renamable/deletable)
// and intentionally do NOT re-localize on a later language switch, same
// contract as user-created chips. The literal strings are the fr fallbacks
// used when i18n isn't initialized yet.
const SEEDED_DEFAULTS: ReadonlyArray<{ labelKey: string; label: string; instructionKey: string; instruction: string }> = [
  {
    labelKey: 'compose:ai_cmd_seed_shorten_label', label: 'Raccourcir',
    instructionKey: 'compose:ai_cmd_seed_shorten_instruction', instruction: 'Raccourcis ce message tout en gardant les points clés.',
  },
  {
    labelKey: 'compose:ai_cmd_seed_formal_label', label: 'Plus formel',
    instructionKey: 'compose:ai_cmd_seed_formal_instruction', instruction: 'Réécris ce message dans un registre plus formel et professionnel.',
  },
  {
    labelKey: 'compose:ai_cmd_seed_translate_label', label: 'Traduire en anglais',
    instructionKey: 'compose:ai_cmd_seed_translate_instruction', instruction: 'Traduis ce message en anglais en gardant le ton de l\'auteur.',
  },
  {
    labelKey: 'compose:ai_cmd_seed_spelling_label', label: "Corriger l'orthographe",
    instructionKey: 'compose:ai_cmd_seed_spelling_instruction', instruction: "Corrige uniquement l'orthographe et la grammaire, sans changer le sens.",
  },
]

function seededFlagKey(accountId: string | null): string {
  return accountId ? `${SEEDED_FLAG_PREFIX}${accountId}` : SEEDED_FLAG_PREFIX
}

export function loadSaved(accountId: string | null): SavedCmd[] {
  let stored: SavedCmd[]
  try { stored = JSON.parse(localStorage.getItem(savedCmdsKey(accountId)) ?? '[]') } catch { stored = [] }
  // Seed defaults exactly once per account. The sentinel persists across
  // reloads so re-deleting them sticks.
  try {
    if (stored.length === 0 && !localStorage.getItem(seededFlagKey(accountId))) {
      stored = SEEDED_DEFAULTS.map((d, i) => ({
        id: Date.now() + i,
        label: i18n.t(d.labelKey, d.label),
        instruction: i18n.t(d.instructionKey, d.instruction),
      }))
      localStorage.setItem(savedCmdsKey(accountId), JSON.stringify(stored))
      localStorage.setItem(seededFlagKey(accountId), '1')
    }
  } catch {
    // localStorage unavailable (private mode, quota) — ignore and return
    // whatever we managed to parse. The popover renders fine with [].
  }
  return stored
}

export function persistSaved(accountId: string | null, cmds: SavedCmd[]) {
  // Persisting (even an empty list) marks the account as seeded so we
  // never re-seed after the user explicitly cleared the chips.
  localStorage.setItem(savedCmdsKey(accountId), JSON.stringify(cmds))
  if (!localStorage.getItem(seededFlagKey(accountId))) {
    localStorage.setItem(seededFlagKey(accountId), '1')
  }
}
