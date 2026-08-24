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

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../config', () => ({
  API_URL: 'https://api.agentys.io',
}))

vi.mock('../services/authToken', () => ({
  getAuthHeaders: () => ({ Authorization: 'Bearer test-token' }),
  getStoredToken: () => 'test-token',
}))

vi.mock('../lib/appEvents', () => ({
  ACCOUNT_CHANGED: 'account-changed',
  appEvents: { dispatchEvent: vi.fn() },
}))

import { importAccountAvatar, uploadAccountAvatar } from './accounts'

describe('account avatar API', () => {
  beforeEach(() => {
    vi.spyOn(Date, 'now').mockReturnValue(12345)
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ url: '/api/accounts/avatars/f905_avatar.jpg' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    )
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('cache-busts imported avatar URLs so React retries the image', async () => {
    await expect(importAccountAvatar('f905')).resolves.toBe(
      'https://api.agentys.io/api/accounts/avatars/f905_avatar.jpg?v=12345'
    )
  })

  it('cache-busts uploaded avatar URLs so a replaced file is visible immediately', async () => {
    const file = new File(['avatar'], 'avatar.jpg', { type: 'image/jpeg' })

    await expect(uploadAccountAvatar('f905', file)).resolves.toBe(
      'https://api.agentys.io/api/accounts/avatars/f905_avatar.jpg?v=12345'
    )
  })
})
