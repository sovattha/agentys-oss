import { render, screen, act } from '@testing-library/react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import i18n from 'i18next'
import { FinalScorecard } from './FinalScorecard'
import type { OnboardingState } from '../useOnboardingWizard'

const BASE_STATE: OnboardingState = {
  step: 'final',
  direction: 'forward',
  connected: true,
  llmConfigured: true,
  scanData: null,
  cleanupData: null,
  trainingData: null,
  labelData: null,
  startedAt: null,
  completedAt: null,
}

describe('FinalScorecard', () => {
  beforeEach(async () => {
    await act(async () => { await i18n.changeLanguage('en') })
  })

  it('localizes raw backend tone values', () => {
    render(
      <FinalScorecard
        state={{
          ...BASE_STATE,
          trainingData: {
            emailsAnalysed: 12,
            tone: 'professionnel',
            contactsCount: 0,
          },
        }}
        onFinish={vi.fn()}
      />,
    )

    expect(screen.getByText('Semi-formal')).toBeInTheDocument()
    expect(screen.queryByText('professionnel')).not.toBeInTheDocument()
  })
})
