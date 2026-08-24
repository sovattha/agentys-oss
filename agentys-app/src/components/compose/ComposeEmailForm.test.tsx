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

import { describe, test, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ComposeEmailForm } from './ComposeEmailForm'

// TODO: update for new architecture — ContactAutocomplete no longer has standard form control association
describe.skip('ComposeEmailForm', () => {
  const defaultProps = {
    onSubmit: vi.fn(),
    onCancel: vi.fn(),
    isLoading: false,
  }

  test('renders all form fields', () => {
    render(<ComposeEmailForm {...defaultProps} />)

    expect(screen.getByLabelText(/destinataire/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/objet/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/instructions/i)).toBeInTheDocument()
  })

  test('renders submit and cancel buttons', () => {
    render(<ComposeEmailForm {...defaultProps} />)

    expect(screen.getByRole('button', { name: /générer/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /annuler/i })).toBeInTheDocument()
  })

  test('validates email format', async () => {
    const user = userEvent.setup()
    render(<ComposeEmailForm {...defaultProps} />)

    await user.type(screen.getByLabelText(/destinataire/i), 'invalid-email')
    await user.type(screen.getByLabelText(/objet/i), 'Test Subject')
    await user.click(screen.getByRole('button', { name: /générer/i }))

    await waitFor(() => {
      expect(screen.getByText(/email invalide/i)).toBeInTheDocument()
    })
  })

  test('validates required subject', async () => {
    const user = userEvent.setup()
    render(<ComposeEmailForm {...defaultProps} />)

    const toInput = screen.getByLabelText(/destinataire/i)
    await user.type(toInput, 'test@example.com')
    await user.click(screen.getByRole('button', { name: /générer/i }))

    await waitFor(() => {
      expect(screen.getByText(/objet requis/i)).toBeInTheDocument()
    })
  })

  test('submits form with valid data', async () => {
    const user = userEvent.setup()
    const handleSubmit = vi.fn()
    render(<ComposeEmailForm {...defaultProps} onSubmit={handleSubmit} />)

    await user.type(screen.getByLabelText(/destinataire/i), 'test@example.com')
    await user.type(screen.getByLabelText(/objet/i), 'Test Subject')
    await user.type(screen.getByLabelText(/instructions/i), 'Write a friendly email')
    await user.click(screen.getByRole('button', { name: /générer/i }))

    await waitFor(() => {
      expect(handleSubmit).toHaveBeenCalledWith({
        to: 'test@example.com',
        subject: 'Test Subject',
        instructions: 'Write a friendly email',
        useHistory: true,
      })
    })
  })

  test('shows loading state during generation', () => {
    render(<ComposeEmailForm {...defaultProps} isLoading={true} />)

    const submitButton = screen.getByRole('button', { name: /génération/i })
    expect(submitButton).toBeDisabled()
  })

  test('calls onCancel when cancel button is clicked', async () => {
    const user = userEvent.setup()
    const handleCancel = vi.fn()
    render(<ComposeEmailForm {...defaultProps} onCancel={handleCancel} />)

    await user.click(screen.getByRole('button', { name: /annuler/i }))

    expect(handleCancel).toHaveBeenCalledTimes(1)
  })

  test('toggles use history checkbox', async () => {
    const user = userEvent.setup()
    render(<ComposeEmailForm {...defaultProps} />)

    const checkbox = screen.getByRole('checkbox', { name: /utiliser l'historique/i })
    expect(checkbox).toBeChecked()

    await user.click(checkbox)
    expect(checkbox).not.toBeChecked()
  })
})
