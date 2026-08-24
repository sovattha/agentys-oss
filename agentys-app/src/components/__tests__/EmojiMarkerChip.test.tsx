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

import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'

import { EmojiMarkerChip } from '../SwipeableEmailItem'

function chipEl(container: HTMLElement): HTMLElement {
  return container.querySelector('.emoji-marker-chip') as HTMLElement
}

describe('EmojiMarkerChip', () => {
  it('renders a plain quiet chip by default — no color/bare variant', () => {
    const { container } = render(<EmojiMarkerChip emoji="💰" text="Stripe" />)
    const el = chipEl(container)
    expect(el).toBeInTheDocument()
    expect(el.className).toContain('emoji-marker-chip')
    expect(el.className).not.toContain('emoji-marker-chip--colored')
    expect(el.className).not.toContain('emoji-marker-chip--bare')
    expect(container.querySelector('.emoji-marker-chip__emoji')?.textContent).toBe('💰')
  })

  it('applies the colored variant + --marker-color custom property', () => {
    const { container } = render(<EmojiMarkerChip emoji="💰" color="#dc2626" />)
    const el = chipEl(container)
    expect(el.className).toContain('emoji-marker-chip--colored')
    expect(el.style.getPropertyValue('--marker-color')).toBe('#dc2626')
  })

  it('ignores a non-hex color (FE anti-injection lock)', () => {
    // A malformed color must never reach the style attribute as a raw value.
    const { container } = render(<EmojiMarkerChip emoji="💰" color="red; position:fixed" />)
    const el = chipEl(container)
    expect(el.className).not.toContain('emoji-marker-chip--colored')
    expect(el.style.getPropertyValue('--marker-color')).toBe('')
  })

  it('renders bare (no pill) when chip is false', () => {
    const { container } = render(<EmojiMarkerChip emoji="💰" chip={false} />)
    expect(chipEl(container).className).toContain('emoji-marker-chip--bare')
  })

  it('keeps the pill when chip is true or omitted (regression lock)', () => {
    const { container: withTrue } = render(<EmojiMarkerChip emoji="💰" chip={true} />)
    expect(chipEl(withTrue).className).not.toContain('emoji-marker-chip--bare')
    const { container: omitted } = render(<EmojiMarkerChip emoji="💰" />)
    expect(chipEl(omitted).className).not.toContain('emoji-marker-chip--bare')
  })

  it('omits the emoji span for a text-only marker', () => {
    const { container } = render(<EmojiMarkerChip text="VIP" />)
    expect(container.querySelector('.emoji-marker-chip__emoji')).toBeNull()
    expect(container.querySelector('.emoji-marker-chip__text')?.textContent).toBe('VIP')
  })

  it('combines colored + bare', () => {
    const { container } = render(<EmojiMarkerChip emoji="💰" color="#3b82f6" chip={false} />)
    const el = chipEl(container)
    expect(el.className).toContain('emoji-marker-chip--colored')
    expect(el.className).toContain('emoji-marker-chip--bare')
  })

  it('renders the follow-up marker (🔁) as the FollowUpIcon, not the emoji glyph', () => {
    const { container } = render(<EmojiMarkerChip emoji={'\u{1F501}'} text="Nathan" />)
    const emojiSpan = container.querySelector('.emoji-marker-chip__emoji') as HTMLElement
    expect(emojiSpan).toBeInTheDocument()
    // The 🔁 glyph is swapped for an inline SVG icon…
    expect(emojiSpan.querySelector('svg')).toBeInTheDocument()
    // …so no literal emoji text leaks through.
    expect(emojiSpan.textContent).toBe('')
    // The accompanying text still renders alongside it.
    expect(container.querySelector('.emoji-marker-chip__text')?.textContent).toBe('Nathan')
  })

  it('leaves non-follow-up emojis as literal glyphs (no icon swap)', () => {
    const { container } = render(<EmojiMarkerChip emoji="⭐" />)
    const emojiSpan = container.querySelector('.emoji-marker-chip__emoji') as HTMLElement
    expect(emojiSpan.querySelector('svg')).toBeNull()
    expect(emojiSpan.textContent).toBe('⭐')
  })
})
