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
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ComposeEmailButton } from './ComposeEmailButton'

describe('ComposeEmailButton', () => {
  test('renders button with correct text', () => {
    render(<ComposeEmailButton onClick={() => {}} />)

    expect(screen.getByRole('button', { name: /nouveau message/i })).toBeInTheDocument()
  })

  test('renders button with text', () => {
    render(<ComposeEmailButton onClick={() => {}} />)

    const button = screen.getByRole('button')
    expect(button.textContent).toContain('Nouveau message')
  })

  test('calls onClick when clicked', async () => {
    const user = userEvent.setup()
    const handleClick = vi.fn()

    render(<ComposeEmailButton onClick={handleClick} />)

    await user.click(screen.getByRole('button'))

    expect(handleClick).toHaveBeenCalledTimes(1)
  })

  test('applies hover and active styles', () => {
    render(<ComposeEmailButton onClick={() => {}} />)

    const button = screen.getByRole('button')
    expect(button).toHaveClass('compose-email-button')
  })

  test('can be disabled', () => {
    render(<ComposeEmailButton onClick={() => {}} disabled />)

    const button = screen.getByRole('button')
    expect(button).toBeDisabled()
  })

  test('does not call onClick when disabled', async () => {
    const user = userEvent.setup()
    const handleClick = vi.fn()

    render(<ComposeEmailButton onClick={handleClick} disabled />)

    await user.click(screen.getByRole('button'))

    expect(handleClick).not.toHaveBeenCalled()
  })
})
