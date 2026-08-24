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
import { renderHook } from '@testing-library/react'

import { useVoiceDictationAccess } from './useVoiceDictationAccess'
import { stripeService } from '../services/subscription'
import { useAuth } from './useAuth'

vi.mock('./useAuth', () => ({ useAuth: vi.fn() }))

describe('useVoiceDictationAccess', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    // Auth user SANS signal billing (cas réel : le billing est fetché à part).
    vi.mocked(useAuth).mockReturnValue({
      user: { id: 1, email: 'free@test.local' },
      isLoading: false,
    } as unknown as ReturnType<typeof useAuth>)
  })

  it('verrouille la dictée quand le billing live est gratuit (ai_enabled false)', () => {
    vi.spyOn(stripeService, 'getCachedBilling').mockReturnValue({
      plan: 'free',
      subscription_status: 'none',
      ai_enabled: false,
      reason: 'no_active_subscription',
    } as ReturnType<typeof stripeService.getCachedBilling>)

    const { result } = renderHook(() => useVoiceDictationAccess())
    expect(result.current).toBe(false)
  })

  it('autorise la dictée quand le billing live est actif (ai_enabled true)', () => {
    vi.spyOn(stripeService, 'getCachedBilling').mockReturnValue({
      plan: 'professional',
      subscription_status: 'active',
      ai_enabled: true,
      reason: 'active',
    } as ReturnType<typeof stripeService.getCachedBilling>)

    const { result } = renderHook(() => useVoiceDictationAccess())
    expect(result.current).toBe(true)
  })

  it('ne verrouille pas pendant le chargement (billing pas encore en cache)', () => {
    vi.spyOn(stripeService, 'getCachedBilling').mockReturnValue(null)
    const { result } = renderHook(() => useVoiceDictationAccess())
    // Pas de signal billing → comportement historique fail-open (pas de flash-lock).
    expect(result.current).toBe(true)
  })
})
