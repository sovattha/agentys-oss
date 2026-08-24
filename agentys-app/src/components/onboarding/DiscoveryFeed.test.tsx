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
import { describe, it, expect, beforeEach } from 'vitest'
import { act } from 'react'
import i18n from 'i18next'
import { DiscoveryFeed } from './DiscoveryFeed'

describe('DiscoveryFeed', () => {
  beforeEach(async () => {
    await act(async () => { await i18n.changeLanguage('en') })
  })

  it('translates backend keys that include the onboarding namespace prefix', () => {
    render(
      <DiscoveryFeed
        discoveries={[{
          id: 'd1',
          kind: 'finding',
          agent: 'profile',
          messageKey: 'onboarding.discovery_tone_casual',
          messageParams: {},
          fallbackMessage: 'Ton par défaut : décontracté',
          timestampMs: Date.now() - 1_000,
        }]}
      />,
    )

    expect(screen.getByText('Default tone: casual')).toBeInTheDocument()
    expect(screen.queryByText('Ton par défaut : décontracté')).not.toBeInTheDocument()
  })
})
