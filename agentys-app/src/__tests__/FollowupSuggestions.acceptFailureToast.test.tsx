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
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { FollowupSuggestions } from '../components/FollowupSuggestions'

const mockGetSuggestions = vi.fn()
const mockAcceptSuggestion = vi.fn()
const mockRejectSuggestion = vi.fn()

vi.mock('../services/api', () => ({
  apiClient: {
    getSuggestions: (...args: unknown[]) => mockGetSuggestions(...args),
    acceptSuggestion: (...args: unknown[]) => mockAcceptSuggestion(...args),
    rejectSuggestion: (...args: unknown[]) => mockRejectSuggestion(...args),
  },
}))

// i18n: return the key so we can assert the message deterministically.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => `T:${k}` }),
}))

interface ToastDetail { message: string; type: string; duration: number }

const pendingSuggestion = {
  id: 'sug-1',
  email_id: 'email-1',
  account_id: 'acc-1',
  description: 'Send the contract by Friday',
  deadline: null,
  status: 'pending' as const,
}

describe('FollowupSuggestions accept failure feedback (silent-failure fix)', () => {
  let dispatched: CustomEvent[] = []

  beforeEach(() => {
    vi.clearAllMocks()
    dispatched = []
    vi.spyOn(window, 'dispatchEvent').mockImplementation((evt) => {
      if (evt instanceof CustomEvent) dispatched.push(evt)
      return true
    })
    mockGetSuggestions.mockResolvedValue({ count: 1, suggestions: [pendingSuggestion] })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('dispatches an error toast when acceptSuggestion rejects', async () => {
    mockAcceptSuggestion.mockRejectedValue(new Error('network down'))

    render(<FollowupSuggestions emailId="email-1" />)

    const acceptBtn = await screen.findByText('T:accept')
    fireEvent.click(acceptBtn)

    await waitFor(() => {
      const toast = dispatched.find(e => e.type === 'agentys:toast')
      expect(toast).toBeDefined()
    })

    const toast = dispatched.find(e => e.type === 'agentys:toast') as CustomEvent<ToastDetail>
    expect(toast.detail.message).toBe('T:toasts.action_failed')
    expect(toast.detail.type).toBe('error')
  })

  it('dispatches an error toast when acceptSuggestion returns success=false', async () => {
    mockAcceptSuggestion.mockResolvedValue({ success: false, suggestion_id: 'sug-1' })

    render(<FollowupSuggestions emailId="email-1" />)

    const acceptBtn = await screen.findByText('T:accept')
    fireEvent.click(acceptBtn)

    await waitFor(() => {
      const toast = dispatched.find(e => e.type === 'agentys:toast')
      expect(toast).toBeDefined()
    })

    const toast = dispatched.find(e => e.type === 'agentys:toast') as CustomEvent<ToastDetail>
    expect(toast.detail.message).toBe('T:toasts.action_failed')
    expect(toast.detail.type).toBe('error')
  })
})
