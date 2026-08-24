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
 * Regression test — F-06
 *
 * useSnooze.dismissSnoozed() fires a best-effort backend DELETE
 * (apiClient.deleteReminder) when dismissing a follow-up entry.
 *
 * Previously the rejection was swallowed by an EMPTY `.catch(() => {})`,
 * so a failed backend cleanup left a phantom reminder that fired later
 * with NO trace. The fix logs the failure via console.warn (no user toast
 * — backend cleanup failure must not nag the user).
 *
 * Guard:
 *  - a rejecting deleteReminder no longer throws out of dismissSnoozed
 *  - the failure is logged with console.warn including the reminderId
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const { deleteReminderMock, getStoredTokenMock } = vi.hoisted(() => ({
  deleteReminderMock: vi.fn(),
  // null token -> the hook's polling useEffect early-returns (no timers/fetch)
  getStoredTokenMock: vi.fn().mockReturnValue(null),
}))

vi.mock('../services/api', () => ({
  apiClient: {
    deleteReminder: deleteReminderMock,
  },
}))

vi.mock('../services/authToken', () => ({
  getStoredToken: getStoredTokenMock,
  registerActiveAccountProvider: vi.fn(),
}))

import { renderHook, act } from '@testing-library/react'
import { useSnooze } from '../hooks/useSnooze'

const STORAGE_KEY = 'agentys_snoozed:default'

describe('useSnooze.dismissSnoozed — F-06 deleteReminder failure is logged, not swallowed', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    // Seed a follow-up entry with a backend reminderId so dismiss triggers the DELETE
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify([
        {
          emailId: 'email-1',
          date: new Date().toISOString(),
          subject: 'Re: contract',
          type: 'followup',
          reminderId: 'rem-42',
        },
      ])
    )
  })

  afterEach(() => {
    localStorage.clear()
  })

  it('logs a console.warn when the best-effort deleteReminder rejects (no throw)', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    deleteReminderMock.mockRejectedValueOnce(new Error('backend down'))

    const { result } = renderHook(() => useSnooze())

    // dismissSnoozed must not throw even though the backend DELETE rejects
    await act(async () => {
      result.current.dismissSnoozed('email-1')
      // let the rejected promise settle so the .catch handler runs
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(deleteReminderMock).toHaveBeenCalledWith('rem-42')
    expect(warnSpy).toHaveBeenCalled()
    // The log carries context: the reminderId that failed to clean up
    const loggedArgs = warnSpy.mock.calls.flat()
    expect(loggedArgs).toContain('rem-42')

    warnSpy.mockRestore()
  })
})
