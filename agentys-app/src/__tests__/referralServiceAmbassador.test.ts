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

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { referralService } from '../services/subscription'

/**
 * Lot 5 — câblage du programme ambassadeur sur l'API réelle.
 * Le MVP localStorage (base64) est remplacé par le code/lien serveur.
 */
describe('ReferralService.activateAmbassador (programme ambassadeur)', () => {
  beforeEach(() => {
    localStorage.clear()
    referralService.resetReferral()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('POST /api/ambassador/activate et renvoie le code + lien du serveur', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        code: 'MARIE42',
        referral_link: 'https://agentys.app/signup?ref=MARIE42',
        status: 'active',
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const stats = await referralService.activateAmbassador()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, opts] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/api/ambassador/activate')
    expect(opts.method).toBe('POST')
    expect(stats.code).toBe('MARIE42')
    expect(stats.link).toBe('https://agentys.app/signup?ref=MARIE42')
  })

  it('persiste le code serveur pour l’affichage hors-ligne', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        code: 'MARIE42',
        referral_link: 'https://agentys.app/signup?ref=MARIE42',
        status: 'active',
      }),
    }))

    await referralService.activateAmbassador()
    expect(localStorage.getItem('agentys_referral_code')).toBe('MARIE42')
  })

  it('lève une erreur si la réponse est en échec', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({ error: 'Stripe is temporarily unavailable' }),
    }))

    await expect(referralService.activateAmbassador()).rejects.toThrow(
      'Stripe is temporarily unavailable',
    )
  })
})
