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

vi.mock('../config', () => ({
  API_URL: 'https://api.agentys.io',
  IS_CLOUD: true,
}))

import { resolveOAuthRedirectUri } from '../hooks/useOAuth'

describe('resolveOAuthRedirectUri', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('utilise le callback backend Outlook quand le client ID env existe sans redirect URI env', () => {
    vi.stubEnv('VITE_MICROSOFT_REDIRECT_URI', '')

    expect(resolveOAuthRedirectUri('outlook')).toBe(
      'https://api.agentys.io/api/oauth/outlook/callback',
    )
  })

  it('garde la redirect URI explicite du backend config quand elle existe', () => {
    vi.stubEnv('VITE_MICROSOFT_REDIRECT_URI', '')

    expect(
      resolveOAuthRedirectUri(
        'outlook',
        'https://api.agentys.io/api/oauth/outlook/callback',
      ),
    ).toBe('https://api.agentys.io/api/oauth/outlook/callback')
  })

  it('laisse une redirect URI env explicite surcharger le fallback backend', () => {
    vi.stubEnv(
      'VITE_MICROSOFT_REDIRECT_URI',
      'https://app.agentys.io/oauth/callback',
    )

    expect(resolveOAuthRedirectUri('outlook')).toBe(
      'https://app.agentys.io/oauth/callback',
    )
  })
})
