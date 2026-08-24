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

import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { TooltipSettingsProvider, useTooltipSettings } from './useTooltipSettings.js'

function TestComponent() {
  const { tooltipsEnabled, setTooltipsEnabled } = useTooltipSettings()
  return (
    <div>
      <span data-testid="status">{tooltipsEnabled ? 'enabled' : 'disabled'}</span>
      <button onClick={() => setTooltipsEnabled(!tooltipsEnabled)}>Toggle</button>
    </div>
  )
}

describe('useTooltipSettings', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('defaults to tooltips enabled when no stored value', () => {
    render(
      <TooltipSettingsProvider>
        <TestComponent />
      </TooltipSettingsProvider>
    )

    expect(screen.getByTestId('status')).toHaveTextContent('enabled')
  })

  it('reads stored value from localStorage', () => {
    localStorage.setItem('agentys_tooltips_enabled', 'false')

    render(
      <TooltipSettingsProvider>
        <TestComponent />
      </TooltipSettingsProvider>
    )

    expect(screen.getByTestId('status')).toHaveTextContent('disabled')
  })

  it('persists changes to localStorage', () => {
    render(
      <TooltipSettingsProvider>
        <TestComponent />
      </TooltipSettingsProvider>
    )

    expect(screen.getByTestId('status')).toHaveTextContent('enabled')

    fireEvent.click(screen.getByRole('button', { name: 'Toggle' }))

    expect(screen.getByTestId('status')).toHaveTextContent('disabled')
    expect(localStorage.getItem('agentys_tooltips_enabled')).toBe('false')
  })

  it('returns default values when not wrapped in provider', () => {
    // Render without provider to test fallback
    render(<TestComponent />)

    // Should default to enabled
    expect(screen.getByTestId('status')).toHaveTextContent('enabled')
  })
})
