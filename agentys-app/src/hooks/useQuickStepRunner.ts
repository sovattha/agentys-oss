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
 * useQuickStepRunner — shared execution logic for any UI that fires Quick
 * Steps (chip bar, hover strip, Cmd+K palette).
 *
 * Responsibilities:
 *  - Coalesce double-runs (per-step in-flight guard).
 *  - Surface a confirmation request when the step is flagged irreversible
 *    (the consumer renders the actual modal).
 *  - Track the last execution report per step so consumers can paint
 *    per-action ✓/✗ feedback for ~1s after the call returns.
 *  - Emit a single global toast on success/failure.
 */
import { useCallback, useRef, useState } from 'react'

import i18n from '../i18n'
import { executeQuickStep } from '../services/api'
import type {
  QuickStep,
  QuickStepExecutionReport,
} from '../types/quickStep'

const FEEDBACK_DURATION_MS = 1100

interface RunOptions {
  bypassConfirm?: boolean
}

export interface QuickStepRunnerState {
  /** id of the step currently in flight, if any. */
  runningStepId: string | null
  /** Step awaiting user confirmation (consumer renders the modal). */
  pendingConfirm: QuickStep | null
  /** Last report keyed by step id — UI paints checkmarks until cleared. */
  lastReports: Record<string, QuickStepExecutionReport>
}

export interface UseQuickStepRunner extends QuickStepRunnerState {
  run: (step: QuickStep, emailId: string, options?: RunOptions) => Promise<void>
  confirm: () => void
  cancelConfirm: () => void
}

export function useQuickStepRunner(
  onExecuted?: (report: QuickStepExecutionReport) => void,
): UseQuickStepRunner {
  const [runningStepId, setRunningStepId] = useState<string | null>(null)
  const [pendingConfirm, setPendingConfirm] = useState<QuickStep | null>(null)
  const [lastReports, setLastReports] = useState<Record<string, QuickStepExecutionReport>>({})
  const pendingEmailRef = useRef<string | null>(null)
  const inFlightKey = useRef<string | null>(null)
  const feedbackTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({})

  const dispatchExecution = useCallback(
    async (step: QuickStep, emailId: string) => {
      if (inFlightKey.current === step.id) return
      inFlightKey.current = step.id
      setRunningStepId(step.id)
      try {
        const idemKey =
          typeof crypto !== 'undefined' && 'randomUUID' in crypto
            ? crypto.randomUUID()
            : `${Date.now()}-${Math.random().toString(36).slice(2)}`
        const report = await executeQuickStep(step.id, emailId, idemKey)
        setLastReports(prev => ({ ...prev, [step.id]: report }))
        scheduleFeedbackClear(step.id, feedbackTimers, setLastReports)
        if (report.success) {
          emitToast(`✓ ${step.name}`, 'success')
          onExecuted?.(report)
        } else {
          emitToast(formatExecutionError(step, report), 'error')
        }
      } catch (err) {
        emitToast(`${step.name}: ${(err as Error).message}`, 'error')
      } finally {
        inFlightKey.current = null
        setRunningStepId(null)
      }
    },
    [onExecuted],
  )

  const run = useCallback(
    async (step: QuickStep, emailId: string, options: RunOptions = {}) => {
      if (!emailId) return
      if (step.confirmBeforeRun && !options.bypassConfirm) {
        pendingEmailRef.current = emailId
        setPendingConfirm(step)
        return
      }
      await dispatchExecution(step, emailId)
    },
    [dispatchExecution],
  )

  const confirm = useCallback(() => {
    const step = pendingConfirm
    const emailId = pendingEmailRef.current
    setPendingConfirm(null)
    pendingEmailRef.current = null
    if (step && emailId) void dispatchExecution(step, emailId)
  }, [pendingConfirm, dispatchExecution])

  const cancelConfirm = useCallback(() => {
    setPendingConfirm(null)
    pendingEmailRef.current = null
  }, [])

  return {
    runningStepId,
    pendingConfirm,
    lastReports,
    run,
    confirm,
    cancelConfirm,
  }
}

function scheduleFeedbackClear(
  stepId: string,
  timers: React.MutableRefObject<Record<string, ReturnType<typeof setTimeout>>>,
  setLastReports: React.Dispatch<React.SetStateAction<Record<string, QuickStepExecutionReport>>>,
) {
  if (timers.current[stepId]) clearTimeout(timers.current[stepId])
  timers.current[stepId] = setTimeout(() => {
    setLastReports(prev => {
      if (!(stepId in prev)) return prev
      const { [stepId]: _drop, ...rest } = prev
      return rest
    })
    delete timers.current[stepId]
  }, FEEDBACK_DURATION_MS)
}

function formatExecutionError(step: QuickStep, report: QuickStepExecutionReport): string {
  const error = report.error || i18n.t('common:unknown_error')
  if (report.executed > 0 && report.executed < report.actions.length) {
    return i18n.t('common:toasts.quickstep_partial_failure', {
      name: step.name,
      executed: report.executed,
      total: report.actions.length,
      error,
    })
  }
  return i18n.t('common:toasts.quickstep_failure', { name: step.name, error })
}

function emitToast(message: string, type: 'success' | 'error' | 'info' = 'info') {
  // Audit Cluster D (2026-05-17) F-01: GlobalToastHost reads `detail.type`, so
  // emitting `{ level }` silently fell back to 'info' — error toasts looked
  // like neutral notices and users thought failed Quick Steps had succeeded.
  window.dispatchEvent(
    new CustomEvent('agentys:toast', { detail: { message, type } }),
  )
}
