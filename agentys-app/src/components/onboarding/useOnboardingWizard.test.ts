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

import { renderHook } from '@testing-library/react'
import { describe, it, expect, beforeEach } from 'vitest'
import { useOnboardingWizard } from './useOnboardingWizard'

describe('useOnboardingWizard persistence', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('restores the Step 1 OAuth recovery state instead of resetting to Step 0', () => {
    localStorage.setItem('agentys_premium_onboarding', JSON.stringify({
      step: 1,
      direction: 'forward',
      connected: false,
      llmConfigured: false,
      scanData: null,
      cleanupData: null,
      trainingData: null,
      labelData: null,
      startedAt: '2026-06-03T10:00:00.000Z',
      completedAt: null,
    }))

    const { result } = renderHook(() => useOnboardingWizard())

    expect(result.current.state.step).toBe(1)
    expect(result.current.state.startedAt).toBe('2026-06-03T10:00:00.000Z')
  })
})
