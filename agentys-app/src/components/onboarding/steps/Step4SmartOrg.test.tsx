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

/**
 * Step4SmartOrg — VIP suggestion chips
 *
 * Covers the onboarding "one-click VIP" affordance:
 *  1. Bidirectional contacts returned by the API render as toggle chips.
 *  2. Clicking a chip selects it (aria-pressed) and clicking again deselects.
 *  3. Empty API result → no suggestions block, manual autocomplete remains
 *     (graceful fallback when the scan produced no legitimate contacts yet).
 *  4. A selected chip flows into the VIP creation POST on Continue.
 */

import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import i18n from 'i18next'
import { Step4SmartOrg } from './Step4SmartOrg'

vi.mock('../../../services/api', () => ({
  apiClient: {
    getSuggestedVipContacts: vi.fn().mockResolvedValue([]),
    searchContacts: vi.fn().mockResolvedValue([]),
  },
}))

vi.mock('../../../api/labels', () => ({
  fetchLabelCounts: vi.fn().mockResolvedValue({ counts: {} }),
  createLabel: vi.fn().mockResolvedValue({}),
  updateLabel: vi.fn().mockResolvedValue({}),
}))

import { apiClient } from '../../../services/api'

const ALICE = { name: 'Alice', email: 'alice@acme.test', sent_count: 4, received_count: 6 }
const BOB = { name: 'Bob', email: 'bob@acme.test', sent_count: 2, received_count: 3 }

function renderStep4() {
  return render(
    <Step4SmartOrg onNext={vi.fn()} onBack={vi.fn()} onLabelData={vi.fn()} />,
  )
}

beforeEach(async () => {
  await act(async () => { await i18n.changeLanguage('en') })
  vi.mocked(apiClient.getSuggestedVipContacts).mockResolvedValue([])
})

describe('Step4SmartOrg — VIP suggestion chips', () => {
  it('localizes the default Noise label card', async () => {
    await act(async () => { await i18n.changeLanguage('es') })
    renderStep4()

    expect(await screen.findByText('Ruido')).toBeInTheDocument()
    expect(screen.queryByText('Bruit')).not.toBeInTheDocument()
  })

  it('renders suggested contacts as toggle chips', async () => {
    vi.mocked(apiClient.getSuggestedVipContacts).mockResolvedValue([ALICE, BOB])
    renderStep4()

    const aliceChip = await screen.findByRole('button', { name: 'Alice' }, { timeout: 5000 })
    expect(aliceChip).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: 'Bob' })).toBeInTheDocument()
  })

  it('toggles selection on click and back off on a second click', async () => {
    vi.mocked(apiClient.getSuggestedVipContacts).mockResolvedValue([ALICE])
    renderStep4()

    const aliceChip = await screen.findByRole('button', { name: 'Alice' }, { timeout: 5000 })
    expect(aliceChip).toHaveAttribute('aria-pressed', 'false')

    fireEvent.click(aliceChip)
    expect(aliceChip).toHaveAttribute('aria-pressed', 'true')

    fireEvent.click(aliceChip)
    expect(aliceChip).toHaveAttribute('aria-pressed', 'false')
  })

  it('renders no suggestions block when the API returns an empty list', async () => {
    vi.mocked(apiClient.getSuggestedVipContacts).mockResolvedValue([])
    renderStep4()

    // Wait for the label area to finish loading (spinner → content).
    await waitFor(() =>
      expect(document.querySelector('.po-vip-box')).toBeInTheDocument(),
    )
    // The manual autocomplete fallback is present, the chips block is not.
    expect(document.querySelector('.po-vip-autocomplete')).toBeInTheDocument()
    expect(document.querySelector('.po-vip-suggestions')).not.toBeInTheDocument()
  })

  it('promotes a selected chip into the VIP creation POST on Continue', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)
    vi.mocked(apiClient.getSuggestedVipContacts).mockResolvedValue([ALICE])

    renderStep4()
    const aliceChip = await screen.findByRole('button', { name: 'Alice' }, { timeout: 5000 })
    fireEvent.click(aliceChip)

    fireEvent.click(screen.getByRole('button', { name: /Continue/ }))

    await waitFor(() => {
      const calledVip = fetchMock.mock.calls.some(
        ([url, opts]) =>
          typeof url === 'string' &&
          url.includes('/api/labels/vip') &&
          typeof opts?.body === 'string' &&
          opts.body.includes('alice@acme.test'),
      )
      expect(calledVip).toBe(true)
    })

    vi.unstubAllGlobals()
  })
})
