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

// Mirror useOptimisticMutation.test.ts: stub i18n so the toast message is
// deterministic, and spy on window.dispatchEvent to capture agentys:toast.
vi.mock('../i18n', () => ({
  default: { t: (k: string) => `T:${k}` },
}))

import i18n from '../i18n'

interface ToastDetail {
  message: string
  type: 'warning' | 'error' | 'info' | 'success'
  duration: number
}

// Faithful reproduction of SnoozedView.handleRowPickerSelect after the fix.
// The followup branch's `apply` calls apiClient.updateFollowup raw (throws on
// non-ok). Before the fix there was no try/catch, so a failed reschedule threw
// out of `await rowPicker.apply(date)` and `setRowPicker(null)` never ran — the
// picker stayed open and nothing was updated silently. This mirrors the safe
// scheduled branch by toasting on failure and still closing the picker.
function makeHandleRowPickerSelect(
  rowPicker: { apply: (d: Date) => Promise<void> } | null,
  setRowPicker: (v: null) => void,
) {
  return async (date: Date) => {
    if (!rowPicker) return
    try {
      await rowPicker.apply(date)
    } catch {
      window.dispatchEvent(new CustomEvent('agentys:toast', {
        detail: { message: i18n.t('common:toasts.followup_reschedule_failed'), type: 'error', duration: 6000 },
      }))
    } finally {
      setRowPicker(null)
    }
  }
}

describe('SnoozedView handleRowPickerSelect — followup reschedule failure', () => {
  let dispatched: CustomEvent<ToastDetail>[] = []

  beforeEach(() => {
    dispatched = []
    vi.spyOn(window, 'dispatchEvent').mockImplementation((evt) => {
      if (evt instanceof CustomEvent && evt.type === 'agentys:toast') {
        dispatched.push(evt as CustomEvent<ToastDetail>)
      }
      return true
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('dispatches an error toast AND closes the picker when apply (updateFollowup) throws', async () => {
    const setRowPicker = vi.fn()
    const rowPicker = {
      apply: vi.fn(async () => {
        // Simulates apiClient.updateFollowup raising on a non-ok response.
        throw new Error('HTTP 500')
      }),
    }
    const handleRowPickerSelect = makeHandleRowPickerSelect(rowPicker, setRowPicker)

    await handleRowPickerSelect(new Date('2026-06-01T10:00:00Z'))

    // User feedback now happens on the failure path.
    expect(dispatched).toHaveLength(1)
    expect(dispatched[0].detail.message).toBe('T:common:toasts.followup_reschedule_failed')
    expect(dispatched[0].detail.type).toBe('error')
    expect(dispatched[0].detail.duration).toBe(6000)

    // The picker no longer stays open on failure (the silent-failure bug).
    expect(setRowPicker).toHaveBeenCalledOnce()
    expect(setRowPicker).toHaveBeenCalledWith(null)
  })

  it('closes the picker and dispatches no toast on success', async () => {
    const setRowPicker = vi.fn()
    const rowPicker = { apply: vi.fn(async () => {}) }
    const handleRowPickerSelect = makeHandleRowPickerSelect(rowPicker, setRowPicker)

    await handleRowPickerSelect(new Date('2026-06-01T10:00:00Z'))

    expect(dispatched).toHaveLength(0)
    expect(setRowPicker).toHaveBeenCalledWith(null)
  })
})
