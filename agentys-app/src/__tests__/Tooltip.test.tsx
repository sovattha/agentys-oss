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

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { Tooltip } from '../components/Tooltip'

describe('Tooltip', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders children correctly', () => {
    render(
      <Tooltip content="Test tooltip">
        <button>Hover me</button>
      </Tooltip>
    )
    expect(screen.getByRole('button', { name: 'Hover me' })).toBeInTheDocument()
  })

  it('does not show tooltip initially', () => {
    render(
      <Tooltip content="Test tooltip">
        <button>Hover me</button>
      </Tooltip>
    )
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('shows tooltip on mouse enter after delay', () => {
    render(
      <Tooltip content="Test tooltip">
        <button>Hover me</button>
      </Tooltip>
    )

    // Fire on the wrapper (parent of button)
    const wrapper = screen.getByRole('button').parentElement!
    fireEvent.mouseEnter(wrapper)

    act(() => {
      vi.advanceTimersByTime(500) // Default delay is now 500ms per AC3
    })

    expect(screen.getByRole('tooltip')).toBeInTheDocument()
    expect(screen.getByText('Test tooltip')).toBeInTheDocument()
  })

  it('hides tooltip on mouse leave', () => {
    render(
      <Tooltip content="Test tooltip">
        <button>Hover me</button>
      </Tooltip>
    )

    const wrapper = screen.getByRole('button').parentElement!
    fireEvent.mouseEnter(wrapper)

    act(() => {
      vi.advanceTimersByTime(500) // Default delay is now 500ms per AC3
    })

    expect(screen.getByRole('tooltip')).toBeInTheDocument()

    fireEvent.mouseLeave(wrapper)

    act(() => {
      vi.advanceTimersByTime(100)
    })

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('shows tooltip on focus for accessibility', () => {
    render(
      <Tooltip content="Test tooltip">
        <button>Hover me</button>
      </Tooltip>
    )

    const wrapper = screen.getByRole('button').parentElement!
    fireEvent.focus(wrapper)

    act(() => {
      vi.advanceTimersByTime(500) // Default delay is now 500ms per AC3
    })

    expect(screen.getByRole('tooltip')).toBeInTheDocument()
  })

  it('hides tooltip on blur', () => {
    render(
      <Tooltip content="Test tooltip">
        <button>Hover me</button>
      </Tooltip>
    )

    const wrapper = screen.getByRole('button').parentElement!
    fireEvent.focus(wrapper)

    act(() => {
      vi.advanceTimersByTime(500) // Default delay is now 500ms per AC3
    })

    expect(screen.getByRole('tooltip')).toBeInTheDocument()

    fireEvent.blur(wrapper)

    act(() => {
      vi.advanceTimersByTime(100)
    })

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('applies correct position class', () => {
    render(
      <Tooltip content="Test tooltip" position="bottom">
        <button>Hover me</button>
      </Tooltip>
    )

    const wrapper = screen.getByRole('button').parentElement!
    fireEvent.mouseEnter(wrapper)

    act(() => {
      vi.advanceTimersByTime(500) // Default delay is now 500ms per AC3
    })

    const tooltip = screen.getByRole('tooltip')
    expect(tooltip).toHaveClass('tooltip-bottom')
  })

  it('defaults to top position', () => {
    render(
      <Tooltip content="Test tooltip">
        <button>Hover me</button>
      </Tooltip>
    )

    const wrapper = screen.getByRole('button').parentElement!
    fireEvent.mouseEnter(wrapper)

    act(() => {
      vi.advanceTimersByTime(500) // Default delay is now 500ms per AC3
    })

    const tooltip = screen.getByRole('tooltip')
    expect(tooltip).toHaveClass('tooltip-top')
  })

  it('does not show tooltip if disabled', () => {
    render(
      <Tooltip content="Test tooltip" disabled>
        <button>Hover me</button>
      </Tooltip>
    )

    const wrapper = screen.getByRole('button').parentElement!
    fireEvent.mouseEnter(wrapper)

    act(() => {
      vi.advanceTimersByTime(500) // Default delay is now 500ms per AC3
    })

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('supports custom delay', () => {
    render(
      <Tooltip content="Test tooltip" delay={800}>
        <button>Hover me</button>
      </Tooltip>
    )

    const wrapper = screen.getByRole('button').parentElement!
    fireEvent.mouseEnter(wrapper)

    act(() => {
      vi.advanceTimersByTime(500) // Default delay (500ms) has passed, but custom is 800ms
    })

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(300) // Now 800ms total
    })

    expect(screen.getByRole('tooltip')).toBeInTheDocument()
  })
})
