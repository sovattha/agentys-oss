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

import { afterEach, describe, expect, it, vi } from 'vitest'
import { recordDeepWorkFeature } from './useDeepWorkTimer'
import { getStoredToken } from '../services/authToken'

vi.mock('../config', () => ({
  API_URL: 'https://api.agentys.test',
}))

vi.mock('../services/authToken', () => ({
  getStoredToken: vi.fn(),
  getAuthHeaders: vi.fn(() => ({ Authorization: 'Bearer test-token' })),
}))

describe('recordDeepWorkFeature', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('does not send telemetry when no auth token is stored', () => {
    vi.mocked(getStoredToken).mockReturnValue(null)
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    recordDeepWorkFeature('deep_work_min', 30)

    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('sends auth headers when telemetry is recorded', () => {
    vi.mocked(getStoredToken).mockReturnValue('test-token')
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)

    recordDeepWorkFeature('deep_work_emails', 1)

    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.agentys.test/api/stats/feature',
      expect.objectContaining({
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer test-token',
        },
        body: JSON.stringify({ feature: 'deep_work_emails', count: 1 }),
      }),
    )
  })
})
