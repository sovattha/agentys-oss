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

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  _resetFiredStore,
  hasFired,
  markFired,
  markFiredUntil,
} from '../services/draftWakeStore'

describe('draftWakeStore', () => {
  beforeEach(() => {
    _resetFiredStore()
    vi.useRealTimers()
  })

  afterEach(() => {
    _resetFiredStore()
    vi.useRealTimers()
  })

  it('returns false for unknown draftId', () => {
    expect(hasFired('never-seen')).toBe(false)
  })

  it('returns false for empty/missing draftId', () => {
    expect(hasFired('')).toBe(false)
    // No throw on empty markFired call.
    markFired('')
    expect(hasFired('')).toBe(false)
  })

  it('markFired persists permanently — survives a faux time jump', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-19T09:00:00Z'))
    markFired('draft-permanent')
    expect(hasFired('draft-permanent')).toBe(true)

    // Jump 365 days — still suppressed because the entry has no expiry.
    vi.setSystemTime(new Date('2027-05-19T09:00:00Z'))
    expect(hasFired('draft-permanent')).toBe(true)
  })

  it('markFiredUntil suppresses until expiry, then re-allows', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-19T09:00:00Z'))
    const expiresAt = Date.now() + 60_000 // +60s
    markFiredUntil('draft-snooze', expiresAt)
    expect(hasFired('draft-snooze')).toBe(true)

    vi.setSystemTime(new Date('2026-05-19T09:00:30Z'))
    expect(hasFired('draft-snooze')).toBe(true)

    vi.setSystemTime(new Date('2026-05-19T09:01:01Z'))
    expect(hasFired('draft-snooze')).toBe(false)
  })

  it('markFiredUntil with past timestamp clears any existing entry', () => {
    markFired('to-clear')
    expect(hasFired('to-clear')).toBe(true)
    markFiredUntil('to-clear', Date.now() - 1000)
    // Past timestamp = delete branch.
    expect(hasFired('to-clear')).toBe(false)
  })

  it('writing a new entry prunes other expired entries', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-19T09:00:00Z'))
    markFiredUntil('old', Date.now() + 1000)

    // Past expiry — but no write has happened yet so it's still in store.
    vi.setSystemTime(new Date('2026-05-19T10:00:00Z'))
    expect(hasFired('old')).toBe(false) // read-time check ignores expired

    // Trigger a write — the expired entry should be pruned out of storage.
    markFired('new')
    const raw = JSON.parse(localStorage.getItem('agentys_draft_wake_fired_v1') || '{}')
    expect(raw.new).toBeDefined()
    expect(raw.old).toBeUndefined()
  })

  it('_resetFiredStore clears the whole namespace', () => {
    markFired('a')
    markFiredUntil('b', Date.now() + 60_000)
    _resetFiredStore()
    expect(hasFired('a')).toBe(false)
    expect(hasFired('b')).toBe(false)
    expect(localStorage.getItem('agentys_draft_wake_fired_v1')).toBeNull()
  })

  it('survives corrupted localStorage entries without throwing', () => {
    localStorage.setItem('agentys_draft_wake_fired_v1', 'not-json{{{')
    expect(hasFired('any')).toBe(false)
    // Subsequent writes recover from the corruption.
    markFired('after-corrupt')
    expect(hasFired('after-corrupt')).toBe(true)
  })

  it('replaces an existing entry rather than appending', () => {
    markFired('replace-me')
    markFiredUntil('replace-me', Date.now() + 60_000)
    const raw = JSON.parse(localStorage.getItem('agentys_draft_wake_fired_v1') || '{}')
    expect(Object.keys(raw)).toEqual(['replace-me'])
    expect(raw['replace-me'].until).toBeGreaterThan(0)
  })
})
