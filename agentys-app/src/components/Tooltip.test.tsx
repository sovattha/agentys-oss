import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { Tooltip } from './Tooltip'
import { TooltipSettingsProvider, useTooltipSettings } from '../hooks/useTooltipSettings.js'

// Mock the settings hook for testing disabled state
vi.mock('../hooks/useTooltipSettings.js', async () => {
  const actual = await vi.importActual('../hooks/useTooltipSettings.js')
  return {
    ...actual,
    useTooltipSettings: vi.fn(() => ({
      tooltipsEnabled: true,
      setTooltipsEnabled: vi.fn(),
    })),
  }
})

const mockedUseTooltipSettings = vi.mocked(useTooltipSettings)

function TestWrapper({ children }: { children: React.ReactNode }) {
  return (
    <TooltipSettingsProvider>
      {children}
    </TooltipSettingsProvider>
  )
}

describe('Tooltip', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mockedUseTooltipSettings.mockReturnValue({
      tooltipsEnabled: true,
      setTooltipsEnabled: vi.fn(),
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  describe('Basic rendering', () => {
    it('renders children correctly', () => {
      render(
        <TestWrapper>
          <Tooltip content="Test tooltip">
            <button>Hover me</button>
          </Tooltip>
        </TestWrapper>
      )

      expect(screen.getByRole('button', { name: 'Hover me' })).toBeInTheDocument()
    })

    it('does not show tooltip initially', () => {
      render(
        <TestWrapper>
          <Tooltip content="Test tooltip">
            <button>Hover me</button>
          </Tooltip>
        </TestWrapper>
      )

      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
    })
  })

  describe('Delay behavior (AC3)', () => {
    it('shows tooltip after default 500ms delay', () => {
      render(
        <TestWrapper>
          <Tooltip content="Test tooltip">
            <button>Hover me</button>
          </Tooltip>
        </TestWrapper>
      )

      const wrapper = screen.getByRole('button', { name: 'Hover me' }).parentElement!
      fireEvent.mouseEnter(wrapper)

      // Should not be visible immediately
      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()

      // Should not be visible at 400ms
      act(() => {
        vi.advanceTimersByTime(400)
      })
      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()

      // Should be visible at 500ms
      act(() => {
        vi.advanceTimersByTime(100)
      })
      expect(screen.getByRole('tooltip')).toBeInTheDocument()
    })

    it('respects custom delay prop', () => {
      render(
        <TestWrapper>
          <Tooltip content="Test tooltip" delay={300}>
            <button>Hover me</button>
          </Tooltip>
        </TestWrapper>
      )

      const wrapper = screen.getByRole('button', { name: 'Hover me' }).parentElement!
      fireEvent.mouseEnter(wrapper)

      // Should not be visible at 200ms
      act(() => {
        vi.advanceTimersByTime(200)
      })
      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()

      // Should be visible at 300ms
      act(() => {
        vi.advanceTimersByTime(100)
      })
      expect(screen.getByRole('tooltip')).toBeInTheDocument()
    })

    it('cancels show timeout on mouse leave', () => {
      render(
        <TestWrapper>
          <Tooltip content="Test tooltip">
            <button>Hover me</button>
          </Tooltip>
        </TestWrapper>
      )

      const wrapper = screen.getByRole('button', { name: 'Hover me' }).parentElement!
      fireEvent.mouseEnter(wrapper)

      act(() => {
        vi.advanceTimersByTime(200)
      })
      fireEvent.mouseLeave(wrapper)

      act(() => {
        vi.advanceTimersByTime(500)
      })
      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
    })
  })

  describe('Keyboard shortcut display (AC2)', () => {
    it('displays keyboard shortcut when provided', () => {
      render(
        <TestWrapper>
          <Tooltip content="Synchroniser" shortcut="Cmd+Shift+S">
            <button>Sync</button>
          </Tooltip>
        </TestWrapper>
      )

      const wrapper = screen.getByRole('button', { name: 'Sync' }).parentElement!
      fireEvent.mouseEnter(wrapper)

      act(() => {
        vi.advanceTimersByTime(500)
      })

      const tooltip = screen.getByRole('tooltip')
      expect(tooltip).toHaveTextContent('Synchroniser')
      expect(tooltip).toHaveTextContent('Cmd+Shift+S')
    })

    it('shows shortcut in a kbd element', () => {
      render(
        <TestWrapper>
          <Tooltip content="Nouveau message" shortcut="Cmd+N">
            <button>Compose</button>
          </Tooltip>
        </TestWrapper>
      )

      const wrapper = screen.getByRole('button', { name: 'Compose' }).parentElement!
      fireEvent.mouseEnter(wrapper)

      act(() => {
        vi.advanceTimersByTime(500)
      })

      const tooltip = screen.getByRole('tooltip')
      const kbd = tooltip.querySelector('.tooltip-shortcut')
      expect(kbd).toBeInTheDocument()
      expect(kbd?.tagName).toBe('KBD')
      expect(kbd).toHaveTextContent('Cmd+N')
    })

    it('renders tooltip without shortcut when not provided', () => {
      render(
        <TestWrapper>
          <Tooltip content="Régénérer le brouillon">
            <button>Regenerate</button>
          </Tooltip>
        </TestWrapper>
      )

      const wrapper = screen.getByRole('button', { name: 'Regenerate' }).parentElement!
      fireEvent.mouseEnter(wrapper)

      act(() => {
        vi.advanceTimersByTime(500)
      })

      const tooltip = screen.getByRole('tooltip')
      expect(tooltip).toHaveTextContent('Régénérer le brouillon')
      expect(tooltip.querySelector('.tooltip-shortcut')).not.toBeInTheDocument()
    })
  })

  describe('Positioning (AC1)', () => {
    const positions = ['top', 'bottom', 'left', 'right'] as const

    positions.forEach(position => {
      it(`applies correct class for ${position} position`, () => {
        render(
          <TestWrapper>
            <Tooltip content="Test" position={position}>
              <button>Target</button>
            </Tooltip>
          </TestWrapper>
        )

        const wrapper = screen.getByRole('button', { name: 'Target' }).parentElement!
        fireEvent.mouseEnter(wrapper)

        act(() => {
          vi.advanceTimersByTime(500)
        })

        expect(screen.getByRole('tooltip')).toHaveClass(`tooltip-${position}`)
      })
    })

    it('defaults to top position', () => {
      render(
        <TestWrapper>
          <Tooltip content="Test">
            <button>Target</button>
          </Tooltip>
        </TestWrapper>
      )

      const wrapper = screen.getByRole('button', { name: 'Target' }).parentElement!
      fireEvent.mouseEnter(wrapper)

      act(() => {
        vi.advanceTimersByTime(500)
      })

      expect(screen.getByRole('tooltip')).toHaveClass('tooltip-top')
    })
  })

  describe('Accessibility (AC5)', () => {
    it('has role="tooltip"', () => {
      render(
        <TestWrapper>
          <Tooltip content="Test tooltip">
            <button>Hover me</button>
          </Tooltip>
        </TestWrapper>
      )

      const wrapper = screen.getByRole('button', { name: 'Hover me' }).parentElement!
      fireEvent.mouseEnter(wrapper)

      act(() => {
        vi.advanceTimersByTime(500)
      })

      expect(screen.getByRole('tooltip')).toBeInTheDocument()
    })

    it('provides aria-describedby linking wrapper to tooltip', () => {
      render(
        <TestWrapper>
          <Tooltip content="Test tooltip">
            <button>Hover me</button>
          </Tooltip>
        </TestWrapper>
      )

      const button = screen.getByRole('button', { name: 'Hover me' })
      const wrapper = button.parentElement!
      fireEvent.mouseEnter(wrapper)

      act(() => {
        vi.advanceTimersByTime(500)
      })

      const tooltip = screen.getByRole('tooltip')
      const tooltipId = tooltip.getAttribute('id')
      expect(tooltipId).toBeTruthy()
      expect(wrapper.getAttribute('aria-describedby')).toBe(tooltipId)
    })

    it('shows tooltip on focus for keyboard navigation', () => {
      render(
        <TestWrapper>
          <Tooltip content="Test tooltip">
            <button>Hover me</button>
          </Tooltip>
        </TestWrapper>
      )

      const wrapper = screen.getByRole('button', { name: 'Hover me' }).parentElement!
      fireEvent.focus(wrapper)

      act(() => {
        vi.advanceTimersByTime(500)
      })

      expect(screen.getByRole('tooltip')).toBeInTheDocument()
    })

    it('hides tooltip on blur', () => {
      render(
        <TestWrapper>
          <Tooltip content="Test tooltip">
            <button>Hover me</button>
          </Tooltip>
        </TestWrapper>
      )

      const wrapper = screen.getByRole('button', { name: 'Hover me' }).parentElement!
      fireEvent.focus(wrapper)

      act(() => {
        vi.advanceTimersByTime(500)
      })

      expect(screen.getByRole('tooltip')).toBeInTheDocument()

      fireEvent.blur(wrapper)

      act(() => {
        vi.advanceTimersByTime(200)
      })

      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
    })
  })

  describe('Disabled state', () => {
    it('does not show tooltip when disabled prop is true', () => {
      render(
        <TestWrapper>
          <Tooltip content="Test tooltip" disabled>
            <button>Hover me</button>
          </Tooltip>
        </TestWrapper>
      )

      const wrapper = screen.getByRole('button', { name: 'Hover me' }).parentElement!
      fireEvent.mouseEnter(wrapper)

      act(() => {
        vi.advanceTimersByTime(500)
      })

      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
    })
  })

  describe('Global settings integration (AC4)', () => {
    it('does not show tooltip when global setting is disabled', () => {
      mockedUseTooltipSettings.mockReturnValue({
        tooltipsEnabled: false,
        setTooltipsEnabled: vi.fn(),
      })

      render(
        <TestWrapper>
          <Tooltip content="Test tooltip">
            <button>Hover me</button>
          </Tooltip>
        </TestWrapper>
      )

      const wrapper = screen.getByRole('button', { name: 'Hover me' }).parentElement!
      fireEvent.mouseEnter(wrapper)

      act(() => {
        vi.advanceTimersByTime(500)
      })

      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
    })

    it('shows tooltip when global setting is enabled', () => {
      mockedUseTooltipSettings.mockReturnValue({
        tooltipsEnabled: true,
        setTooltipsEnabled: vi.fn(),
      })

      render(
        <TestWrapper>
          <Tooltip content="Test tooltip">
            <button>Hover me</button>
          </Tooltip>
        </TestWrapper>
      )

      const wrapper = screen.getByRole('button', { name: 'Hover me' }).parentElement!
      fireEvent.mouseEnter(wrapper)

      act(() => {
        vi.advanceTimersByTime(500)
      })

      expect(screen.getByRole('tooltip')).toBeInTheDocument()
    })
  })
})
