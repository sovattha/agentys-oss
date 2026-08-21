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
