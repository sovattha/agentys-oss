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
import { renderHook, act, waitFor } from '@testing-library/react'

import { useQuickStepRunner } from './useQuickStepRunner'
import type { QuickStep, QuickStepExecutionReport } from '../types/quickStep'

// Mock the API call the hook dispatches. Indirection keeps the spy resettable.
const executeQuickStep = vi.fn()
vi.mock('../services/api', () => ({
  executeQuickStep: (...args: unknown[]) => executeQuickStep(...args),
}))

const BASE_STEP = {
  id: 'step-1',
  name: 'Archive',
  icon: null,
  shortcut: null,
  actions: [],
  enabled: true,
  confirmBeforeRun: false,
  autoEnabled: false,
  showAutoBadge: true,
  triggerOperator: 'OR',
  triggers: [],
  firesOn: 'received',
} as unknown as QuickStep

function step(over: Partial<QuickStep> = {}): QuickStep {
  return { ...BASE_STEP, ...over }
}

function okReport(over: Partial<QuickStepExecutionReport> = {}): QuickStepExecutionReport {
  return {
    success: true,
    step_id: 'step-1',
    email_id: 'email-1',
    executed: 1,
    actions: [{ type: 'archive', ok: true, error: null }],
    error: null,
    idempotent_replay: false,
    ...over,
  }
}

// Capture the global toast events the hook emits.
let toasts: Array<{ message: string; type: string }>
const onToast = (e: Event) => {
  toasts.push((e as CustomEvent).detail)
}

beforeEach(() => {
  executeQuickStep.mockReset()
  toasts = []
  window.addEventListener('agentys:toast', onToast as EventListener)
})

afterEach(() => {
  window.removeEventListener('agentys:toast', onToast as EventListener)
  vi.useRealTimers()
})

describe('useQuickStepRunner', () => {
  it('executes immediately + emits a success toast when confirmBeforeRun is false', async () => {
    executeQuickStep.mockResolvedValue(okReport())
    const onExecuted = vi.fn()
    const { result } = renderHook(() => useQuickStepRunner(onExecuted))

    await act(async () => {
      await result.current.run(step(), 'email-1')
    })

    expect(executeQuickStep).toHaveBeenCalledTimes(1)
    const [stepId, emailId, idemKey] = executeQuickStep.mock.calls[0]
    expect(stepId).toBe('step-1')
    expect(emailId).toBe('email-1')
    // A fresh idempotency key is generated per call.
    expect(typeof idemKey).toBe('string')
    expect((idemKey as string).length).toBeGreaterThan(0)
    expect(onExecuted).toHaveBeenCalledTimes(1)
    expect(toasts).toEqual([{ message: '✓ Archive', type: 'success' }])
    expect(result.current.lastReports['step-1']?.success).toBe(true)
    expect(result.current.runningStepId).toBeNull()
  })

  it('surfaces pendingConfirm (and does not execute) when confirmBeforeRun is true', async () => {
    executeQuickStep.mockResolvedValue(okReport())
    const { result } = renderHook(() => useQuickStepRunner())

    await act(async () => {
      await result.current.run(step({ confirmBeforeRun: true }), 'email-1')
    })

    expect(executeQuickStep).not.toHaveBeenCalled()
    expect(result.current.pendingConfirm?.id).toBe('step-1')

    // Confirm runs it and clears the pending state.
    await act(async () => {
      result.current.confirm()
    })
    await waitFor(() => expect(executeQuickStep).toHaveBeenCalledTimes(1))
    expect(result.current.pendingConfirm).toBeNull()
  })

  it('cancelConfirm clears the pending step without executing', async () => {
    const { result } = renderHook(() => useQuickStepRunner())
    await act(async () => {
      await result.current.run(step({ confirmBeforeRun: true }), 'email-1')
    })
    act(() => {
      result.current.cancelConfirm()
    })
    expect(result.current.pendingConfirm).toBeNull()
    expect(executeQuickStep).not.toHaveBeenCalled()
  })

  it('bypassConfirm skips the confirmation gate', async () => {
    executeQuickStep.mockResolvedValue(okReport())
    const { result } = renderHook(() => useQuickStepRunner())
    await act(async () => {
      await result.current.run(step({ confirmBeforeRun: true }), 'email-1', { bypassConfirm: true })
    })
    expect(executeQuickStep).toHaveBeenCalledTimes(1)
    expect(result.current.pendingConfirm).toBeNull()
  })

  it('coalesces concurrent runs of the same step (single in-flight call)', async () => {
    let resolveExec!: (r: QuickStepExecutionReport) => void
    executeQuickStep.mockReturnValue(
      new Promise<QuickStepExecutionReport>((res) => {
        resolveExec = res
      }),
    )
    const { result } = renderHook(() => useQuickStepRunner())

    await act(async () => {
      const p1 = result.current.run(step(), 'email-1')
      const p2 = result.current.run(step(), 'email-1') // fired before the first resolves
      resolveExec(okReport())
      await Promise.all([p1, p2])
    })

    expect(executeQuickStep).toHaveBeenCalledTimes(1)
  })

  it('emits an error toast when the report is unsuccessful (and skips onExecuted)', async () => {
    executeQuickStep.mockResolvedValue(
      okReport({ success: false, executed: 0, error: 'provider_unavailable' }),
    )
    const onExecuted = vi.fn()
    const { result } = renderHook(() => useQuickStepRunner(onExecuted))

    await act(async () => {
      await result.current.run(step(), 'email-1')
    })

    expect(onExecuted).not.toHaveBeenCalled()
    expect(toasts).toHaveLength(1)
    expect(toasts[0].type).toBe('error')
    expect(toasts[0].message).toContain('provider_unavailable')
  })

  it('emits an error toast when executeQuickStep throws', async () => {
    executeQuickStep.mockRejectedValue(new Error('network down'))
    const { result } = renderHook(() => useQuickStepRunner())

    await act(async () => {
      await result.current.run(step(), 'email-1')
    })

    expect(toasts).toHaveLength(1)
    expect(toasts[0].type).toBe('error')
    expect(toasts[0].message).toContain('network down')
  })

  it('no-ops on an empty emailId', async () => {
    const { result } = renderHook(() => useQuickStepRunner())
    await act(async () => {
      await result.current.run(step(), '')
    })
    expect(executeQuickStep).not.toHaveBeenCalled()
    expect(result.current.pendingConfirm).toBeNull()
  })

  it('clears per-step feedback after the feedback window elapses', async () => {
    vi.useFakeTimers()
    executeQuickStep.mockResolvedValue(okReport())
    const { result } = renderHook(() => useQuickStepRunner())

    await act(async () => {
      await result.current.run(step(), 'email-1')
    })
    expect(result.current.lastReports['step-1']).toBeTruthy()

    await act(async () => {
      vi.advanceTimersByTime(1200)
    })
    expect(result.current.lastReports['step-1']).toBeUndefined()
  })
})
