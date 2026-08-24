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

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useSnooze, writeSnoozeEntry, type SnoozedEntry } from './useSnooze'

// ============================================================================
// MOCKS
// ============================================================================

vi.mock('../services/api', () => ({
  apiClient: {
    getReminders: vi.fn(() => Promise.resolve([])),
  },
}))

// MA-01: the snooze store is account-scoped (`agentys_snoozed:${accountId}`).
// Pin the active account so the hook's storageKey() is deterministic and the
// assertions below target the same scoped key the hook reads/writes.
const TEST_ACCOUNT_ID = 'test-acct'
vi.mock('../api/emails', () => ({
  getActiveAccountId: () => TEST_ACCOUNT_ID,
}))

// ============================================================================
// HELPERS
// ============================================================================

const STORAGE_KEY = `agentys_snoozed:${TEST_ACCOUNT_ID}`

function setStorageEntries(entries: SnoozedEntry[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(entries))
}

function clearStorage() {
  localStorage.removeItem(STORAGE_KEY)
}

function makeFutureDate(hoursFromNow = 24): string {
  const d = new Date()
  d.setHours(d.getHours() + hoursFromNow)
  return d.toISOString()
}

function makePastDate(hoursAgo = 2): string {
  const d = new Date()
  d.setHours(d.getHours() - hoursAgo)
  return d.toISOString()
}

// ============================================================================
// TESTS
// ============================================================================

describe('useSnooze', () => {
  beforeEach(() => {
    clearStorage()
    vi.clearAllMocks()
  })

  afterEach(() => {
    clearStorage()
  })

  // --------------------------------------------------------------------------
  // État initial vide
  // --------------------------------------------------------------------------

  it('retourne des sets vides si localStorage est vide', () => {
    const { result } = renderHook(() => useSnooze())

    expect(result.current.snoozedMap.size).toBe(0)
    expect(result.current.sleepingIds.size).toBe(0)
    expect(result.current.wokeIds.size).toBe(0)
    expect(result.current.wokeSnoozeIds.size).toBe(0)
    expect(result.current.wokeFollowupIds.size).toBe(0)
  })

  it('retourne des sets vides si localStorage contient du JSON invalide', () => {
    localStorage.setItem(STORAGE_KEY, 'INVALID_JSON_[[[')
    const { result } = renderHook(() => useSnooze())

    expect(result.current.snoozedMap.size).toBe(0)
    expect(result.current.sleepingIds.size).toBe(0)
  })

  // --------------------------------------------------------------------------
  // Classification par date
  // --------------------------------------------------------------------------

  it('email avec date passée → wokeIds et wokeSnoozeIds', () => {
    const entries: SnoozedEntry[] = [
      { emailId: 'email-past', date: makePastDate(3), subject: 'Test passé', type: 'snooze' },
    ]
    setStorageEntries(entries)

    const { result } = renderHook(() => useSnooze())

    expect(result.current.wokeIds.has('email-past')).toBe(true)
    expect(result.current.wokeSnoozeIds.has('email-past')).toBe(true)
    expect(result.current.sleepingIds.has('email-past')).toBe(false)
    expect(result.current.wokeFollowupIds.has('email-past')).toBe(false)
  })

  it('email avec date future → sleepingIds', () => {
    const entries: SnoozedEntry[] = [
      { emailId: 'email-future', date: makeFutureDate(24), subject: 'Test futur', type: 'snooze' },
    ]
    setStorageEntries(entries)

    const { result } = renderHook(() => useSnooze())

    expect(result.current.sleepingIds.has('email-future')).toBe(true)
    expect(result.current.wokeIds.has('email-future')).toBe(false)
  })

  it('type followup + date passée → wokeFollowupIds, pas wokeSnoozeIds', () => {
    const entries: SnoozedEntry[] = [
      { emailId: 'followup-1', date: makePastDate(1), subject: 'Suivi projet', type: 'followup' },
    ]
    setStorageEntries(entries)

    const { result } = renderHook(() => useSnooze())

    expect(result.current.wokeFollowupIds.has('followup-1')).toBe(true)
    expect(result.current.wokeSnoozeIds.has('followup-1')).toBe(false)
    expect(result.current.wokeIds.has('followup-1')).toBe(true)
  })

  it('type absent (rétrocompat) → traité comme snooze', () => {
    const entries = [
      { emailId: 'old-email', date: makePastDate(5), subject: 'Ancien format' },
      // pas de champ 'type'
    ] as SnoozedEntry[]
    setStorageEntries(entries)

    const { result } = renderHook(() => useSnooze())

    expect(result.current.wokeSnoozeIds.has('old-email')).toBe(true)
    expect(result.current.wokeFollowupIds.has('old-email')).toBe(false)
  })

  it('plusieurs emails avec dates mixtes → classifiés correctement', () => {
    const entries: SnoozedEntry[] = [
      { emailId: 'past-snooze', date: makePastDate(2), subject: 'Passé snooze', type: 'snooze' },
      { emailId: 'past-followup', date: makePastDate(1), subject: 'Passé followup', type: 'followup' },
      { emailId: 'future-snooze', date: makeFutureDate(6), subject: 'Futur snooze', type: 'snooze' },
    ]
    setStorageEntries(entries)

    const { result } = renderHook(() => useSnooze())

    expect(result.current.wokeSnoozeIds.has('past-snooze')).toBe(true)
    expect(result.current.wokeFollowupIds.has('past-followup')).toBe(true)
    expect(result.current.sleepingIds.has('future-snooze')).toBe(true)
    expect(result.current.wokeIds.size).toBe(2)
    expect(result.current.sleepingIds.size).toBe(1)
  })

  // --------------------------------------------------------------------------
  // snoozedMap
  // --------------------------------------------------------------------------

  it('snoozedMap contient toutes les entrées indexées par emailId', () => {
    const entries: SnoozedEntry[] = [
      { emailId: 'e1', date: makeFutureDate(), subject: 'Sujet 1', type: 'snooze' },
      { emailId: 'e2', date: makePastDate(), subject: 'Sujet 2', type: 'followup' },
    ]
    setStorageEntries(entries)

    const { result } = renderHook(() => useSnooze())

    expect(result.current.snoozedMap.get('e1')?.subject).toBe('Sujet 1')
    expect(result.current.snoozedMap.get('e2')?.type).toBe('followup')
    expect(result.current.snoozedMap.size).toBe(2)
  })

  // --------------------------------------------------------------------------
  // dismissSnoozed
  // --------------------------------------------------------------------------

  it('dismissSnoozed retire l\'entrée du state', () => {
    const entries: SnoozedEntry[] = [
      { emailId: 'dismiss-me', date: makePastDate(), subject: 'À dismisser', type: 'snooze' },
      { emailId: 'keep-me', date: makePastDate(), subject: 'À garder', type: 'snooze' },
    ]
    setStorageEntries(entries)

    const { result } = renderHook(() => useSnooze())

    // Vérifier que les deux sont présents au départ
    expect(result.current.wokeIds.has('dismiss-me')).toBe(true)
    expect(result.current.wokeIds.has('keep-me')).toBe(true)

    // Dismisser le premier
    act(() => {
      result.current.dismissSnoozed('dismiss-me')
    })

    expect(result.current.snoozedMap.has('dismiss-me')).toBe(false)
    expect(result.current.snoozedMap.has('keep-me')).toBe(true)
  })

  it('dismissSnoozed supprime l\'entrée du localStorage', () => {
    const entries: SnoozedEntry[] = [
      { emailId: 'remove-from-storage', date: makePastDate(), subject: 'Test', type: 'snooze' },
    ]
    setStorageEntries(entries)

    const { result } = renderHook(() => useSnooze())

    act(() => {
      result.current.dismissSnoozed('remove-from-storage')
    })

    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]') as SnoozedEntry[]
    const found = stored.find((e) => e.emailId === 'remove-from-storage')
    expect(found).toBeUndefined()
  })

  it('dismissSnoozed sur emailId inexistant ne crash pas', () => {
    const { result } = renderHook(() => useSnooze())

    expect(() => {
      act(() => {
        result.current.dismissSnoozed('nonexistent-id')
      })
    }).not.toThrow()
  })

  // --------------------------------------------------------------------------
  // Réaction aux StorageEvent
  // --------------------------------------------------------------------------

  it('réagit aux StorageEvent — re-calcule les sets', async () => {
    const { result } = renderHook(() => useSnooze())

    // État initial vide
    expect(result.current.snoozedMap.size).toBe(0)

    // Simuler une écriture depuis un autre onglet
    const newEntry: SnoozedEntry = {
      emailId: 'storage-event-email',
      date: makePastDate(1),
      subject: 'Via storage event',
      type: 'snooze',
    }

    act(() => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify([newEntry]))
      window.dispatchEvent(new StorageEvent('storage', { key: STORAGE_KEY }))
    })

    expect(result.current.snoozedMap.has('storage-event-email')).toBe(true)
    expect(result.current.wokeSnoozeIds.has('storage-event-email')).toBe(true)
  })

  it('ignore les StorageEvent sur d\'autres clés', () => {
    const { result } = renderHook(() => useSnooze())

    act(() => {
      localStorage.setItem('other_key', 'some-value')
      window.dispatchEvent(new StorageEvent('storage', { key: 'other_key' }))
    })

    // Doit rester vide — pas de re-calcul sur autre clé
    expect(result.current.snoozedMap.size).toBe(0)
  })
})

// ============================================================================
// TESTS writeSnoozeEntry (fonction utilitaire)
// ============================================================================

describe('writeSnoozeEntry', () => {
  beforeEach(() => {
    clearStorage()
  })

  afterEach(() => {
    clearStorage()
  })

  it('écrit une entrée dans localStorage', () => {
    const date = new Date(Date.now() + 3600_000) // +1h
    writeSnoozeEntry('email-write-1', date, 'Sujet test', 'snooze')

    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]') as SnoozedEntry[]
    expect(stored).toHaveLength(1)
    expect(stored[0].emailId).toBe('email-write-1')
    expect(stored[0].type).toBe('snooze')
  })

  it('remplace une entrée existante pour le même emailId', () => {
    const date1 = new Date(Date.now() + 3600_000)
    const date2 = new Date(Date.now() + 7200_000)

    writeSnoozeEntry('dup-email', date1, 'Premier sujet', 'snooze')
    writeSnoozeEntry('dup-email', date2, 'Deuxième sujet', 'snooze')

    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]') as SnoozedEntry[]
    const entries = stored.filter((e) => e.emailId === 'dup-email')
    expect(entries).toHaveLength(1)
    expect(entries[0].subject).toBe('Deuxième sujet')
  })

  it('dispatche un StorageEvent après l\'écriture', () => {
    const events: StorageEvent[] = []
    const handler = (e: StorageEvent) => events.push(e)
    window.addEventListener('storage', handler)

    writeSnoozeEntry('event-email', new Date(), 'Test event', 'followup')

    window.removeEventListener('storage', handler)
    expect(events.length).toBeGreaterThan(0)
    expect(events[0].key).toBe(STORAGE_KEY)
  })
})
