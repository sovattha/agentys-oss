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

import { describe, it, expect, vi, beforeEach } from 'vitest'

// Must use vi.hoisted for variables referenced in vi.mock factories
const { mockClearLocalData } = vi.hoisted(() => ({
  mockClearLocalData: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('../services/clearUserData', () => ({
  clearLocalData: mockClearLocalData,
  clearAllUserData: vi.fn(),
}))

vi.mock('../services/authToken', () => ({
  getStoredToken: vi.fn(() => 'fake-jwt'),
  setStoredToken: vi.fn(),
  clearStoredToken: vi.fn(),
}))

vi.mock('../config', () => ({
  API_URL: 'http://localhost:5050',
}))

import { renderHook, act } from '@testing-library/react'
import { useAuth } from '../hooks/useAuth'

describe('useAuth.logout', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ user: { id: 1, email: 'test@test.com' } }), { status: 200 })
    )
  })

  it('should call clearLocalData (not clearAllUserData) on logout', async () => {
    const { result } = renderHook(() => useAuth())

    await vi.waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    fetchSpy.mockClear()

    act(() => {
      result.current.logout()
    })

    expect(mockClearLocalData).toHaveBeenCalled()
    expect(fetchSpy).not.toHaveBeenCalled()

    fetchSpy.mockRestore()
  })

  it('should set isAuthenticated to false after logout', async () => {
    const { result } = renderHook(() => useAuth())

    await vi.waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    act(() => {
      result.current.logout()
    })

    expect(result.current.isAuthenticated).toBe(false)
    expect(result.current.user).toBeNull()
    expect(result.current.token).toBeNull()
  })
})
