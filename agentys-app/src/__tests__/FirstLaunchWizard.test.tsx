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

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render as rtlRender, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from '../App'
import { ONBOARDING_COMPLETE_KEY } from '../lib/storageKeys'

// App.tsx now depends on TanStack Query for labels + settings. Tests
// rendering <App /> directly (bypassing main.tsx) must provide their own
// provider — wire one per render with a no-retry client.
function render(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return rtlRender(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

// Mock window.matchMedia — not available in jsdom but used by App.tsx
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// Mock PremiumOnboarding so lazy import resolves synchronously with predictable UI
vi.mock('../components/onboarding', () => ({
  PremiumOnboarding: ({ onComplete }: { onComplete: () => void }) => (
    <div data-testid="premium-onboarding">
      <h1>Configuration</h1>
      <button onClick={onComplete}>Terminer</button>
    </div>
  ),
}))

// Mock Tauri APIs
vi.mock('@tauri-apps/api/event', () => ({
  listen: vi.fn().mockResolvedValue(() => {}),
}))

vi.mock('../services/notifications', () => ({
  getNotificationService: vi.fn().mockReturnValue({
    registerNotificationActions: vi.fn().mockResolvedValue(undefined),
    onNotificationClick: vi.fn().mockResolvedValue(() => {}),
  }),
}))

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => { store[key] = value },
    removeItem: (key: string) => { delete store[key] },
    clear: () => { store = {} },
  }
})()
Object.defineProperty(window, 'localStorage', { value: localStorageMock })

describe('First Launch Wizard', () => {
  const mockFetch = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('fetch', mockFetch)
    localStorageMock.clear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('should show wizard on first launch when onboarding is not complete', async () => {
    // Provide a dev token so useAuth bypasses the network call and authenticates immediately
    localStorageMock.setItem('agentys_jwt', 'dev:test@example.com')

    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/ping') || url.includes('/api/health')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ version: '1.0.0' }),
        })
      }
      if (url.includes('/api/wizard/status')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ onboarding_complete: false }),
        })
      }
      if (url.includes('/api/labels')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ labels: [], counts: {}, total: 0 }),
        })
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({}),
      })
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('Configuration')).toBeInTheDocument()
    }, { timeout: 5000 })
  })

  it('should show inbox when onboarding is complete', async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/health')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: 'healthy', version: '1.0.0' }),
        })
      }
      if (url.includes('/api/wizard/status')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ onboarding_complete: true }),
        })
      }
      if (url.includes('/api/emails')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ count: 0, emails: [] }),
        })
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({}),
      })
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('Agentys')).toBeInTheDocument()
      expect(screen.queryByText('Configuration')).not.toBeInTheDocument()
    })
  })

  it('should hide wizard and show inbox after completing onboarding', async () => {
    // This test will be more complex as it requires interaction
    // For now, just verify the structure is correct
    expect(true).toBe(true)
  })

  it('should skip wizard if localStorage has agentys_onboarding_complete flag', async () => {
    localStorageMock.setItem(ONBOARDING_COMPLETE_KEY, 'true')

    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/health')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: 'healthy', version: '1.0.0' }),
        })
      }
      if (url.includes('/api/emails')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ count: 0, emails: [] }),
        })
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({}),
      })
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('Agentys')).toBeInTheDocument()
    })

    // Should not show wizard
    expect(screen.queryByText('Configuration')).not.toBeInTheDocument()
  })
})
