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
 * Tests unitaires pour getAuthHeaders — isolation multi-compte.
 *
 * Garantit que :
 *  - Authorization: Bearer <JWT> est présent quand un token est stocké.
 *  - X-Account-Id est envoyé quand getActiveAccountId() != 'default'.
 *  - Pas de X-Account-Id quand le compte actif est 'default' (avant login).
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest'

// Mock localStorage avant tout import.
class MockStorage {
  private store: Record<string, string> = {}
  getItem(k: string): string | null { return this.store[k] ?? null }
  setItem(k: string, v: string): void { this.store[k] = v }
  removeItem(k: string): void { delete this.store[k] }
  clear(): void { this.store = {} }
}

const mockStorage = new MockStorage()
Object.defineProperty(globalThis, 'localStorage', {
  value: mockStorage,
  writable: true,
})

import {
  getAuthHeaders,
  registerActiveAccountProvider,
} from '../services/authToken'

describe('getAuthHeaders', () => {
  beforeEach(() => {
    mockStorage.clear()
    registerActiveAccountProvider(() => 'default')
  })

  afterEach(() => {
    registerActiveAccountProvider(() => 'default')
  })

  it('inclut Authorization: Bearer <jwt> si token présent', () => {
    mockStorage.setItem('agentys_jwt', 'test-token')
    expect(getAuthHeaders()).toMatchObject({
      Authorization: 'Bearer test-token',
    })
  })

  it('inclut X-Account-Id quand le compte actif n\'est pas "default"', () => {
    mockStorage.setItem('agentys_jwt', 'jwt-123')
    registerActiveAccountProvider(() => 'f9057edfed0d4574')
    expect(getAuthHeaders()).toEqual({
      Authorization: 'Bearer jwt-123',
      'X-Account-Id': 'f9057edfed0d4574',
    })
  })

  it('n\'envoie PAS X-Account-Id quand le compte est "default" (pré-login)', () => {
    mockStorage.setItem('agentys_jwt', 'jwt-123')
    const headers = getAuthHeaders()
    expect(headers).not.toHaveProperty('X-Account-Id')
    expect(headers.Authorization).toBe('Bearer jwt-123')
  })

  it('retourne un objet vide si aucun token n\'est stocké', () => {
    expect(getAuthHeaders()).toEqual({})
  })

  it('protège contre un provider qui throw (fail-safe)', () => {
    mockStorage.setItem('agentys_jwt', 'jwt-123')
    registerActiveAccountProvider(() => {
      throw new Error('boom')
    })
    const headers = getAuthHeaders()
    expect(headers).not.toHaveProperty('X-Account-Id')
    expect(headers.Authorization).toBe('Bearer jwt-123')
  })
})
