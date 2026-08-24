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
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react'

// Mock the i18n singleton used for the toast message so we can assert the
// exact key without depending on locale JSON. react-i18next's own instance
// (initialized in setup.ts) is a different module and stays intact, so the
// component's `useTranslation('agents')` calls still resolve real text.
vi.mock('../i18n', () => ({
  default: { t: (k: string) => `T:${k}` },
}))

// The fix under test: when this rejects, handleSave must surface a warning
// toast instead of swallowing the SQLite KnowledgeEntry write failure.
const syncSpy = vi.fn((..._args: unknown[]) => Promise.reject(new Error('SQLite write failed')))
vi.mock('../utils/savoirSync', () => ({
  syncSavoirToKnowledgeEntries: (...args: unknown[]) => syncSpy(...args),
}))

vi.mock('../services/api', () => ({
  getKnowledgeEntries: vi.fn(() => Promise.resolve([])),
  createKnowledgeEntry: vi.fn(() => Promise.resolve({})),
}))

vi.mock('../api/learning', () => ({
  fetchUserLearningCategories: vi.fn(() => Promise.resolve([])),
}))

vi.mock('../services/websocket', () => ({
  getWebSocketClient: () => ({ subscribe: () => () => {} }),
}))

vi.mock('../hooks/useLearningProgress', () => ({
  useLearningProgress: () => ({
    // The real hook always returns an object (never null); the component reads
    // learningActivity.lastRefreshAt directly, so mirror that shape here.
    learningActivity: { lastRefreshAt: null },
    fetchLearningStatus: vi.fn(),
  }),
}))

import { TrainingPage } from '../components/TrainingPage'

interface ToastDetail { message: string; type: string; duration: number }

function mockFetch() {
  return vi.fn((url: string, opts?: { method?: string }) => {
    if (url.includes('/api/memory')) {
      // PUT save succeeds so handleSave proceeds to the sync call.
      if (opts?.method === 'PUT') {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
      }
      // GET initial load returns minimal markdown.
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ content: '' }) })
    }
    if (url.includes('/api/writing-style')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
  })
}

describe('TrainingPage save — savoir sync failure feedback', () => {
  let dispatched: CustomEvent[]
  const onClose = vi.fn()

  beforeEach(() => {
    dispatched = []
    syncSpy.mockClear()
    onClose.mockClear()
    vi.stubGlobal('fetch', mockFetch())
    vi.spyOn(window, 'dispatchEvent').mockImplementation((evt: Event) => {
      if (evt instanceof CustomEvent) dispatched.push(evt)
      return true
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('dispatches a warning toast when KnowledgeEntry sync rejects', async () => {
    render(<TrainingPage onClose={onClose} />)

    // Wait for initial load to finish (full-name field is on the default pillar).
    const nameInput = await screen.findByPlaceholderText('Votre nom complet')

    // Edit a profile field so `hasChanges` is true and Save becomes enabled.
    await act(async () => {
      fireEvent.change(nameInput, { target: { value: 'Alex Tester' } })
    })

    const saveBtn = await screen.findByRole('button', { name: /enregistrer|save/i })
    await waitFor(() => expect(saveBtn).not.toBeDisabled())

    await act(async () => {
      fireEvent.click(saveBtn)
    })

    // The sync was invoked and rejected — assert the warning toast surfaced.
    await waitFor(() => expect(syncSpy).toHaveBeenCalled())
    await waitFor(() => {
      const toast = dispatched.find(
        e => e.type === 'agentys:toast' &&
          (e.detail as ToastDetail).message === 'T:common:toasts.faq_sync_partial',
      )
      expect(toast).toBeDefined()
      expect((toast as CustomEvent<ToastDetail>).detail.type).toBe('warning')
    })
  })
})
