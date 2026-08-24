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

import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import i18n from 'i18next'
import { Step3TrainAI } from './Step3TrainAI'

const learningMocks = vi.hoisted(() => ({
  progress: {
    isActive: false,
    emailsProcessed: 0,
    emailsTotal: 0,
    patterns: [],
    confidenceScore: 0,
    currentPhase: '',
    agentSteps: {
      profile: 'failed',
      style: 'failed',
      knowledge: 'failed',
      label: 'failed',
    },
    error: 'scan_partial_insufficient_data',
    currentStep: null,
    discoveries: [],
  },
  startLearning: vi.fn(),
  fetchInsights: vi.fn(),
  startStatusPolling: vi.fn(),
}))

vi.mock('../../../api/accounts', () => ({
  fetchAccounts: vi.fn().mockResolvedValue({ accounts: [] }),
}))

vi.mock('../../../hooks/useLearningProgress', () => ({
  useLearningProgress: vi.fn(() => ({
    progress: learningMocks.progress,
    insights: {
      ready: false,
      emailsAnalysed: 0,
      profile: null,
      knowledge: null,
      style: null,
      labels: null,
    },
    isStalled: false,
    startLearning: learningMocks.startLearning,
    fetchInsights: learningMocks.fetchInsights,
    startStatusPolling: learningMocks.startStatusPolling,
  })),
}))

describe('Step3TrainAI partial skip', () => {
  beforeEach(async () => {
    await act(async () => { await i18n.changeLanguage('en') })
    learningMocks.progress.error = 'scan_partial_insufficient_data'
    learningMocks.startLearning.mockResolvedValue({ ok: true })
    learningMocks.startStatusPolling.mockReturnValue(vi.fn())
    vi.clearAllMocks()
  })

  it('stores minimal training data and advances to the next onboarding step', async () => {
    const onTrainingDone = vi.fn()
    const onNext = vi.fn()

    render(
      <Step3TrainAI
        accountId={1}
        accountEmail="new@example.com"
        onNext={onNext}
        onBack={vi.fn()}
        onTrainingDone={onTrainingDone}
        onGoToConnect={vi.fn()}
      />,
    )

    fireEvent.click(await screen.findByRole('button', { name: /continue anyway/i }))

    await waitFor(() => {
      expect(onTrainingDone).toHaveBeenCalledWith({
        emailsAnalysed: 0,
        tone: 'professionnel',
        contactsCount: 0,
      })
      expect(onNext).toHaveBeenCalledTimes(1)
    })
  })

  it('lets billing-required users continue in free mode', async () => {
    learningMocks.progress.error = 'billing_required'
    const onContinueFree = vi.fn()

    render(
      <Step3TrainAI
        accountId={1}
        accountEmail="free@example.com"
        onNext={vi.fn()}
        onBack={vi.fn()}
        onTrainingDone={vi.fn()}
        onGoToConnect={vi.fn()}
        onContinueFree={onContinueFree}
      />,
    )

    fireEvent.click(await screen.findByRole('button', { name: /continue in free mode|continuer en mode gratuit/i }))

    expect(onContinueFree).toHaveBeenCalledTimes(1)
  })
})
