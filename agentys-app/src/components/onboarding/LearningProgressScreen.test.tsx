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

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { LearningProgress } from '../../types/onboarding'
import { LearningProgressScreen } from './LearningProgressScreen'

const baseProgress: LearningProgress = {
  isActive: false,
  emailsProcessed: 0,
  emailsTotal: 0,
  patterns: [],
  confidenceScore: 0,
  currentPhase: '',
  currentPhaseKey: null,
  currentPhaseParams: null,
  agentSteps: {
    profile: 'failed',
    style: 'failed',
    knowledge: 'failed',
    label: 'failed',
  },
  error: null,
  currentStep: null,
  batchCurrent: 0,
  batchTotal: 0,
  newContacts: 0,
  newRules: 0,
  discoveries: [],
}

describe('LearningProgressScreen OAuth guidance', () => {
  it('replaces raw insufficient-scope errors with guided recovery choices', async () => {
    const onReconnectEmail = vi.fn()
    const onRetry = vi.fn()

    render(
      <LearningProgressScreen
        progress={{
          ...baseProgress,
          error: 'HttpError 403: Request had insufficient authentication scopes.',
        }}
        onReconnectEmail={onReconnectEmail}
        onRetry={onRetry}
      />,
    )

    expect(screen.getByRole('heading', { name: 'Connexion Gmail à finaliser' })).toBeInTheDocument()
    expect(screen.getByText('Problème détecté automatiquement')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'J’ai refusé certaines autorisations' })).toHaveAttribute('aria-checked', 'true')

    await userEvent.click(screen.getByRole('radio', { name: 'Je reviens toujours au login' }))
    expect(screen.getByRole('radio', { name: 'Je reviens toujours au login' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByText(/résultat OAuth complet/i)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Relancer la connexion' }))
    expect(onReconnectEmail).toHaveBeenCalledOnce()
    expect(onRetry).not.toHaveBeenCalled()
  })

  it('keeps the generic retry UI for non-OAuth failures', () => {
    render(
      <LearningProgressScreen
        progress={{
          ...baseProgress,
          error: 'database is locked',
        }}
        onRetry={vi.fn()}
      />,
    )

    expect(screen.getByText('database is locked')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Recommencer' })).toBeInTheDocument()
    expect(screen.queryByText('Connexion Gmail à finaliser')).not.toBeInTheDocument()
  })
})
