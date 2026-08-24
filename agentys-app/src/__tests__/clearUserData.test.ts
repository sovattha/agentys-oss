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

import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock the cache module before importing clearUserData
vi.mock('../api/cache', () => ({
  cacheInvalidatePrefix: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('../api/emailBodyCache', () => ({
  clearEmailBodyCache: vi.fn().mockResolvedValue(undefined),
}))

// Mock config
vi.mock('../config', () => ({
  API_URL: 'http://localhost:5050',
}))

import { clearLocalData } from '../services/clearUserData'
import { cacheInvalidatePrefix } from '../api/cache'
import { clearEmailBodyCache } from '../api/emailBodyCache'

describe('clearLocalData', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    vi.clearAllMocks()
  })

  it('should clear localStorage user keys', async () => {
    localStorage.setItem('agentys_jwt', 'token123')
    localStorage.setItem('agentys_theme', 'dark')
    localStorage.setItem('agentys_language', 'fr')
    localStorage.setItem('agentys_onboarding_v2_complete', 'true')

    await clearLocalData()

    expect(localStorage.getItem('agentys_jwt')).toBeNull()
    expect(localStorage.getItem('agentys_theme')).toBeNull()
    expect(localStorage.getItem('agentys_language')).toBeNull()
    expect(localStorage.getItem('agentys_onboarding_v2_complete')).toBeNull()
  })

  it('should clear the saved-draft local pin set', async () => {
    localStorage.setItem('agentys:pinned-saved-drafts', JSON.stringify(['saved-1']))

    await clearLocalData()

    expect(localStorage.getItem('agentys:pinned-saved-drafts')).toBeNull()
  })

  it('should clear dynamic prefix keys', async () => {
    localStorage.setItem('pkce_verifier_abc', 'val')
    localStorage.setItem('draft-backup-123', 'val')

    await clearLocalData()

    expect(localStorage.getItem('pkce_verifier_abc')).toBeNull()
    expect(localStorage.getItem('draft-backup-123')).toBeNull()
  })

  it('should clear AI command menu legacy global saved key', async () => {
    localStorage.setItem('ai-cmd-saved', JSON.stringify([{ id: 1, label: 'old', instruction: 'old' }]))

    await clearLocalData()

    expect(localStorage.getItem('ai-cmd-saved')).toBeNull()
  })

  it('should clear ALL AI command menu per-account scoped saved keys', async () => {
    localStorage.setItem('ai-cmd-saved:account-1', JSON.stringify([{ id: 1, label: 'A', instruction: 'A' }]))
    localStorage.setItem('ai-cmd-saved:account-2', JSON.stringify([{ id: 2, label: 'B', instruction: 'B' }]))
    localStorage.setItem('ai-cmd-saved:f9057edfed0d4574', JSON.stringify([{ id: 3, label: 'C', instruction: 'C' }]))

    await clearLocalData()

    expect(localStorage.getItem('ai-cmd-saved:account-1')).toBeNull()
    expect(localStorage.getItem('ai-cmd-saved:account-2')).toBeNull()
    expect(localStorage.getItem('ai-cmd-saved:f9057edfed0d4574')).toBeNull()
  })

  it('should NOT touch unrelated keys when clearing AI command menu data', async () => {
    localStorage.setItem('ai-cmd-saved:account-1', JSON.stringify([{ id: 1, label: 'A', instruction: 'A' }]))
    localStorage.setItem('some_third_party_key', 'preserved')
    // A key that *contains* 'ai-cmd-saved' but doesn't match the prefix shouldn't be touched
    localStorage.setItem('not-ai-cmd-saved', 'preserved')

    await clearLocalData()

    expect(localStorage.getItem('ai-cmd-saved:account-1')).toBeNull()
    expect(localStorage.getItem('some_third_party_key')).toBe('preserved')
    expect(localStorage.getItem('not-ai-cmd-saved')).toBe('preserved')
  })

  it('should clear ALL contact group caches (legacy global + per-account scoped)', async () => {
    localStorage.setItem('agentys_contact_groups', JSON.stringify([{ id: 'old' }]))
    localStorage.setItem('agentys_contact_groups_acc-1', JSON.stringify([{ id: 'g1' }]))
    localStorage.setItem('agentys_contact_groups_acc-2', JSON.stringify([{ id: 'g2' }]))
    localStorage.setItem('agentys_contact_groups_f9057edfed0d4574', JSON.stringify([{ id: 'g3' }]))

    await clearLocalData()

    expect(localStorage.getItem('agentys_contact_groups')).toBeNull()
    expect(localStorage.getItem('agentys_contact_groups_acc-1')).toBeNull()
    expect(localStorage.getItem('agentys_contact_groups_acc-2')).toBeNull()
    expect(localStorage.getItem('agentys_contact_groups_f9057edfed0d4574')).toBeNull()
  })

  it('should clear ALL snippets fallback caches (legacy global + per-account scoped)', async () => {
    localStorage.setItem('agentys_snippets', JSON.stringify([{ id: 'old' }]))
    localStorage.setItem('agentys_snippets:acc-1', JSON.stringify([{ id: 's1' }]))
    localStorage.setItem('agentys_snippets:acc-2', JSON.stringify([{ id: 's2' }]))

    await clearLocalData()

    expect(localStorage.getItem('agentys_snippets')).toBeNull()
    expect(localStorage.getItem('agentys_snippets:acc-1')).toBeNull()
    expect(localStorage.getItem('agentys_snippets:acc-2')).toBeNull()
  })

  it('should clear ALL approval audit logs (legacy global + per-account scoped)', async () => {
    localStorage.setItem('agentys-approval-audit', JSON.stringify([{ id: 'old' }]))
    localStorage.setItem('agentys-approval-audit:acc-1', JSON.stringify([{ id: 'a1' }]))
    localStorage.setItem('agentys-approval-audit:acc-2', JSON.stringify([{ id: 'a2' }]))

    await clearLocalData()

    expect(localStorage.getItem('agentys-approval-audit')).toBeNull()
    expect(localStorage.getItem('agentys-approval-audit:acc-1')).toBeNull()
    expect(localStorage.getItem('agentys-approval-audit:acc-2')).toBeNull()
  })

  it('should clear sessionStorage', async () => {
    sessionStorage.setItem('someKey', 'val')

    await clearLocalData()

    expect(sessionStorage.length).toBe(0)
  })

  it('should clear IndexedDB cache', async () => {
    await clearLocalData()

    expect(cacheInvalidatePrefix).toHaveBeenCalledWith('')
    expect(clearEmailBodyCache).toHaveBeenCalled()
  })

  it('should NOT call any backend API (no fetch)', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')

    await clearLocalData()

    expect(fetchSpy).not.toHaveBeenCalled()
    fetchSpy.mockRestore()
  })
})
