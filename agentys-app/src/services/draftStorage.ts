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
 * Local storage service for saving compose/reply drafts when modals are closed.
 * Drafts are stored in localStorage and capped at MAX_DRAFTS.
 *
 * Clé scopée par compte actif (`agentys_saved_drafts:<accountId>`) pour éviter
 * toute fuite de contenu d'emails entre comptes.
 */

import {
  getCurrentAccountId,
  isCurrentAccountLoaded,
  ensureCurrentAccountId,
  subscribeCurrentAccountId,
} from '../lib/currentAccountId'

const STORAGE_KEY_BASE = 'agentys_saved_drafts'
const MAX_DRAFTS = 20

// Fallback key used while the active account id is still loading (it resolves
// asynchronously from /api/accounts, so `getCurrentAccountId()` returns null
// for the first moments after a reload).
const NULL_ACCOUNT_KEY = `${STORAGE_KEY_BASE}:__none`
// Pre-account-scoping builds (before 2026-04-17) stored drafts under the bare,
// unscoped base key. Still migrated so drafts from an old build resurface.
const LEGACY_UNSCOPED_KEY = STORAGE_KEY_BASE

function getStorageKey(): string {
  const accountId = getCurrentAccountId()
  return `${STORAGE_KEY_BASE}:${accountId ?? '__none'}`
}

/**
 * Pull drafts stranded under the null-account fallback (`:__none`) or the
 * pre-scoping legacy key into the resolved per-account key, then delete the
 * strays.
 *
 * Why this exists: the active account id loads asynchronously. If a draft is
 * autosaved (or simply read) during the brief window after a reload when the
 * id is still null, it lands on / is read from `:__none`. Once the real id
 * arrives the list reads `:<id>` and the draft appears to have vanished — it is
 * still in localStorage, just under the wrong key. This consolidation makes the
 * first read under a real key reclaim those strays. Id-deduped (target wins on
 * collision — it is the account-owned source), TTL-filtered, capped.
 */
function _consolidateStrandedDrafts(targetKey: string): void {
  // Only consolidate INTO a real per-account key. While the id is null the
  // target IS `:__none`, so there is nothing to pull in yet.
  if (targetKey === NULL_ACCOUNT_KEY) return

  const merged: SavedDraft[] = []
  const seen = new Set<string>()
  const absorb = (raw: string | null): number => {
    if (!raw) return 0
    let added = 0
    try {
      const arr = JSON.parse(raw) as SavedDraft[]
      if (!Array.isArray(arr)) return 0
      for (const d of arr) {
        if (d && d.id && !seen.has(d.id) && !_isExpired(d)) {
          seen.add(d.id)
          merged.push(d)
          added++
        }
      }
    } catch {
      /* corrupt entry — skip */
    }
    return added
  }

  // Target first so its entries win on id collision; strays only fill gaps.
  absorb(localStorage.getItem(targetKey))

  const straysPresent: string[] = []
  let recovered = false
  for (const strayKey of [NULL_ACCOUNT_KEY, LEGACY_UNSCOPED_KEY]) {
    if (strayKey === targetKey) continue
    if (localStorage.getItem(strayKey) === null) continue
    const added = absorb(localStorage.getItem(strayKey))
    straysPresent.push(strayKey)
    if (added > 0) recovered = true
  }

  if (straysPresent.length === 0) return

  // Persist the merged set FIRST. Only clear the strays once the write lands —
  // otherwise a quota failure here would delete the strays and lose the drafts.
  if (recovered) {
    merged.sort((a, b) => (Date.parse(b.savedAt) || 0) - (Date.parse(a.savedAt) || 0))
    try {
      localStorage.setItem(targetKey, JSON.stringify(merged.slice(0, MAX_DRAFTS)))
    } catch {
      return // write failed — keep strays intact; recovery retries next read
    }
  }
  // Safe now: either the merge persisted, or the strays carried nothing fresh
  // (all expired/duplicate) so dropping them loses nothing.
  for (const strayKey of straysPresent) {
    localStorage.removeItem(strayKey)
  }
}

// Pub/sub for draft changes — lets components react in real-time
const _listeners = new Set<() => void>()

function _notifyListeners(): void {
  _listeners.forEach(cb => cb())
}

// Quand le compte actif change, notifier les composants : ils doivent relire
// les drafts du nouveau compte (le jeu de clés localStorage change).
subscribeCurrentAccountId(() => {
  _notifyListeners()
})

export function subscribeDraftChange(cb: () => void): () => void {
  _listeners.add(cb)
  return () => { _listeners.delete(cb) }
}

export interface SavedComposeDraft {
  type: 'compose'
  id: string
  to: string
  cc: string
  bcc: string
  subject: string
  body: string
  savedAt: string
}

export interface SavedReplyDraft {
  type: 'reply'
  id: string
  emailId: string
  emailSubject: string
  emailSender: string
  body: string
  savedAt: string
}

export type SavedDraft = SavedComposeDraft | SavedReplyDraft

function generateId(): string {
  return `draft_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

// Silent-failure fix (issue #312) : purger les brouillons > 7 jours pour
// honorer le message UI « Les brouillons sont supprimés après 7 jours. »
// Sans ça les compose drafts en localStorage vivaient pour toujours et le
// wording UI mentait sur l'existence d'un nettoyage automatique.
const DRAFT_TTL_MS = 7 * 24 * 60 * 60 * 1000

function _isExpired(draft: SavedDraft): boolean {
  const saved = Date.parse(draft.savedAt)
  if (Number.isNaN(saved)) return false // date corrompue : on garde, un fix manuel ou l'écriture suivante corrigera
  return Date.now() - saved > DRAFT_TTL_MS
}

export function getSavedDrafts(): SavedDraft[] {
  // The active account id loads asynchronously. If it is not ready yet, kick
  // the load so the subscribeCurrentAccountId → _notifyListeners chain re-runs
  // this read under the real key once it arrives — otherwise the list can stay
  // stuck on the empty `:__none` fallback after a reload.
  if (!isCurrentAccountLoaded()) {
    void ensureCurrentAccountId()
  }
  const key = getStorageKey()
  // Reclaim drafts stranded under `:__none` / the legacy key before reading.
  _consolidateStrandedDrafts(key)
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return []
    const all = JSON.parse(raw) as SavedDraft[]
    const fresh = all.filter((d) => !_isExpired(d))
    if (fresh.length !== all.length) {
      // Un ou plusieurs drafts ont été purgés — persister immédiatement pour
      // qu'ils ne réapparaissent pas au prochain getSavedDrafts.
      try {
        localStorage.setItem(key, JSON.stringify(fresh))
      } catch {
        // Quota / storage indisponible : on retourne quand même la version purgée
        // en mémoire. La purge sera réessayée au prochain appel.
      }
    }
    return fresh
  } catch {
    return []
  }
}

function writeDrafts(drafts: SavedDraft[]): void {
  const key = getStorageKey()
  try {
    localStorage.setItem(key, JSON.stringify(drafts.slice(0, MAX_DRAFTS)))
  } catch (e) {
    // localStorage quota exceeded — evict oldest drafts and retry
    console.warn('[draftStorage] Quota exceeded, evicting oldest drafts:', e)
    const reduced = drafts.slice(0, Math.max(1, Math.floor(MAX_DRAFTS / 2)))
    try {
      localStorage.setItem(key, JSON.stringify(reduced))
    } catch {
      // Still full — clear draft storage entirely
      localStorage.removeItem(key)
    }
  }
}

/**
 * Returns true if there is meaningful content worth saving.
 * Ignores signature-only bodies AND HTML-wrapped empty bodies — TipTap émet
 * `<p></p>` pour un éditeur vide, et `hasContent` retournait true pour ces 7
 * chars, déclenchant un autosave qui écrasait le vrai draft au reload (R2-U-02).
 */
export function hasContent(fields: { to?: string; subject?: string; body?: string }): boolean {
  const { to = '', subject = '', body = '' } = fields
  if (to.trim()) return true
  if (subject.trim()) return true
  // Strip HTML tags (TipTap wraps in <p>…</p>), nbsp, then signature block
  const bodyText = body
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/\n--\n[\s\S]*$/, '')
    .trim()
  return bodyText.length > 0
}

export function saveComposeDraft(
  draft: Omit<SavedComposeDraft, 'type' | 'id' | 'savedAt'> & { id?: string }
): SavedComposeDraft {
  const drafts = getSavedDrafts()
  // Upsert by id: each compose session generates a stable id (passed in by
  // NewMessageModal). Re-saving with the same id updates that entry in place;
  // a different id leaves earlier compose drafts untouched. This is what lets
  // multiple closed compose drafts coexist in the Drafts tab.
  const sessionId = draft.id ?? generateId()
  const filtered = drafts.filter(d => d.id !== sessionId)
  const saved: SavedComposeDraft = {
    type: 'compose',
    id: sessionId,
    savedAt: new Date().toISOString(),
    to: draft.to,
    cc: draft.cc,
    bcc: draft.bcc,
    subject: draft.subject,
    body: draft.body,
  }
  filtered.unshift(saved)
  writeDrafts(filtered)
  _notifyListeners()
  return saved
}

export function saveReplyDraft(draft: Omit<SavedReplyDraft, 'type' | 'id' | 'savedAt'>): SavedReplyDraft {
  const drafts = getSavedDrafts()
  // One reply draft per emailId — replace if exists
  const filtered = drafts.filter(d => !(d.type === 'reply' && d.emailId === draft.emailId))
  const saved: SavedReplyDraft = {
    type: 'reply',
    id: generateId(),
    savedAt: new Date().toISOString(),
    ...draft,
  }
  filtered.unshift(saved)
  writeDrafts(filtered)
  _notifyListeners()
  return saved
}

export function deleteSavedDraft(draftId: string): void {
  const drafts = getSavedDrafts()
  writeDrafts(drafts.filter(d => d.id !== draftId))
  _notifyListeners()
}

export function getReplyDraftForEmail(emailId: string): SavedReplyDraft | undefined {
  return getSavedDrafts().find(
    (d): d is SavedReplyDraft => d.type === 'reply' && d.emailId === emailId
  )
}

export function getLatestComposeDraft(): SavedComposeDraft | undefined {
  return getSavedDrafts().find(
    (d): d is SavedComposeDraft => d.type === 'compose'
  )
}

export function deleteReplyDraftForEmail(emailId: string): void {
  const drafts = getSavedDrafts()
  writeDrafts(drafts.filter(d => !(d.type === 'reply' && d.emailId === emailId)))
  _notifyListeners()
}

export function deleteAllSavedDrafts(): void {
  writeDrafts([])
  _notifyListeners()
}
