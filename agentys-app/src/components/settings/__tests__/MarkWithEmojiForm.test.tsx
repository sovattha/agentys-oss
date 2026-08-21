import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import { MarkWithEmojiForm } from '../QuickStepsManager'
import { LABEL_COLORS } from '../../../types/labels'
import type { MarkWithEmojiPayload } from '../../../types/quickStep'

function setup(payload: Partial<MarkWithEmojiPayload> = {}) {
  const onChange = vi.fn()
  const full: MarkWithEmojiPayload = {
    emoji: '💰', text: '', include_deadline: false, chip: true, ...payload,
  }
  render(<MarkWithEmojiForm payload={full} onChange={onChange} />)
  return { onChange }
}

describe('MarkWithEmojiForm — color swatches', () => {
  it('renders one swatch per LABEL_COLORS member plus a "no color" tile', () => {
    setup()
    for (const color of LABEL_COLORS) {
      expect(screen.getByRole('radio', { name: color })).toBeInTheDocument()
    }
    expect(screen.getByTestId('qs-marker-color-none')).toBeInTheDocument()
  })

  it('clicking a swatch sends that color to onChange', () => {
    const { onChange } = setup()
    fireEvent.click(screen.getByRole('radio', { name: '#dc2626' }))
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ color: '#dc2626' }))
  })

  it('clicking the "no color" tile clears the color', () => {
    const { onChange } = setup({ color: '#dc2626' })
    fireEvent.click(screen.getByTestId('qs-marker-color-none'))
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ color: undefined }))
  })

  it('marks the active color swatch as checked', () => {
    setup({ color: '#3b82f6' })
    expect(screen.getByRole('radio', { name: '#3b82f6' })).toBeChecked()
    expect(screen.getByTestId('qs-marker-color-none')).not.toBeChecked()
  })
})

describe('MarkWithEmojiForm — no-emoji (text-only) tile', () => {
  it('renders a "no emoji" tile in the emoji grid', () => {
    setup()
    expect(screen.getByTestId('qs-marker-emoji-none')).toBeInTheDocument()
  })

  it('clicking it selects the text-only marker (emoji="")', () => {
    const { onChange } = setup({ emoji: '💰' })
    fireEvent.click(screen.getByTestId('qs-marker-emoji-none'))
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ emoji: '' }))
  })

  it('is checked when the marker has no emoji', () => {
    setup({ emoji: '' })
    expect(screen.getByTestId('qs-marker-emoji-none')).toBeChecked()
    // and no whitelisted swatch is checked
    expect(screen.getByRole('radio', { name: '💰' })).not.toBeChecked()
  })
})

describe('MarkWithEmojiForm — chip toggle', () => {
  it('is checked when chip is true (default)', () => {
    setup({ chip: true })
    expect(screen.getByTestId('qs-marker-chip-toggle')).toBeChecked()
  })

  it('unchecking the toggle sends chip:false', () => {
    const { onChange } = setup({ chip: true })
    fireEvent.click(screen.getByTestId('qs-marker-chip-toggle'))
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ chip: false }))
  })

  it('treats an absent chip flag as on (default true)', () => {
    setup({ chip: undefined })
    expect(screen.getByTestId('qs-marker-chip-toggle')).toBeChecked()
  })
})
