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
