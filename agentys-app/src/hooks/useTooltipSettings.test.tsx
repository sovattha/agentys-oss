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
