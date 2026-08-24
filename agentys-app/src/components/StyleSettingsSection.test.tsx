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

import { render } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { StyleSettingsSection } from './StyleSettingsSection'
import type { DefaultStyleSettings } from '../types/training'

// i18n is initialised to `fr` by src/__tests__/setup.ts.

const defaultStyle: DefaultStyleSettings = {
  formality_level: 'mixed',
  preferred_greetings: ['Bonjour {first_name},', 'Salut'],
  preferred_closings: ['Cordialement', 'A+'],
  typical_signature: null,
}

describe('StyleSettingsSection — greeting/closing block layout', () => {
  it('renders the formality explanation as the lead-in ABOVE the greeting/closing rows', () => {
    const { container } = render(
      <StyleSettingsSection
        defaultStyle={defaultStyle}
        onUpdateDefaultStyle={vi.fn()}
      />,
    )

    const block = container.querySelector('.style-greetings-block')
    expect(block).toBeInTheDocument()

    // The first child is the formality hint, not a greeting field.
    const lead = block!.firstElementChild!
    expect(lead).toHaveClass('pillar-field-hint')
    expect(lead).toHaveTextContent(/Agentys choisit automatiquement la formule/)

    // …and it precedes the first greeting/closing row in DOM order.
    const firstRow = block!.querySelector('.pillar-field-row')!
    expect(
      lead.compareDocumentPosition(firstRow) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })

  it('only renders the greeting block when the default-style updater is provided', () => {
    const { container } = render(
      <StyleSettingsSection />,
    )
    expect(container.querySelector('.style-greetings-block')).toBeNull()
  })
})
