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
 * QuickStepsBar — invisible hotkey listener for the open email detail.
 *
 * Earlier versions rendered a visible chip bar in the action footer. Per
 * design feedback (the chip was visual noise next to Reply/Reply-all/
 * Forward), the chips are gone. The component now exists purely to bind
 * keyboard shortcuts while the detail modal is open and run them on the
 * currently-open email. The list-level surface is handled by
 * {@link QuickStepsListHotkeys}; the body dataset flag they coordinate
 * through (`document.body.dataset.emailDetailOpen`) is set by
 * {@link EmailDetailModal} so only one listener fires per keydown.
 *
 * Confirmation modal still renders here so it doesn't blink when the
 * detail modal closes during a confirm.
 */
import { useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import { useQuickSteps } from '../hooks/useQuickSteps'
import { useQuickStepRunner } from '../hooks/useQuickStepRunner'
import type { QuickStep, QuickStepExecutionReport } from '../types/quickStep'
import './QuickStepsBar.css'

interface QuickStepsBarProps {
  emailId: string | null
  /** Called on successful execution so the parent can advance to the next email. */
  onExecuted?: (report: QuickStepExecutionReport) => void
}

export function QuickStepsBar({ emailId, onExecuted }: QuickStepsBarProps) {
  const { steps } = useQuickSteps()
  const runner = useQuickStepRunner(onExecuted)

  const enabledSteps = useMemo(
    () => steps.filter(s => s.enabled),
    [steps],
  )

  useEffect(() => {
    if (!emailId || enabledSteps.length === 0) return
    const handler = (event: KeyboardEvent) => {
      // Don't fire while another app-level modal is layered on top of the
      // email detail (Settings / Quick Actions / etc.). The detail modal
      // can remain mounted underneath, but its hotkeys should defer.
      if (document.body.dataset.modalOpen === 'true') return
      if (isTypingTarget(event.target)) return
      const pressed = serializeKeyEvent(event)
      const shortcutKey = event.shiftKey
        ? pressed.split('+').filter(p => p !== 'shift').join('+')
        : pressed
      const match = enabledSteps.find(s => s.shortcut && s.shortcut === shortcutKey)
      if (!match) return
      event.preventDefault()
      event.stopPropagation()
      void runner.run(match, emailId, { bypassConfirm: event.shiftKey })
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [emailId, enabledSteps, runner])

  if (!runner.pendingConfirm) return null

  return (
    <ConfirmRunModal
      step={runner.pendingConfirm}
      onCancel={runner.cancelConfirm}
      onConfirm={runner.confirm}
    />
  )
}

interface ConfirmRunModalProps {
  step: QuickStep
  onCancel: () => void
  onConfirm: () => void
}

function ConfirmRunModal({ step, onCancel, onConfirm }: ConfirmRunModalProps) {
  const { t } = useTranslation('settings')
  const { t: tCommon } = useTranslation('common')
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
      if (e.key === 'Enter') onConfirm()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onCancel, onConfirm])

  return (
    <div className="quicksteps-confirm" role="dialog" aria-modal="true">
      <div className="quicksteps-confirm__panel">
        <h4>{t('quicksteps_confirm_title', { name: step.name })}</h4>
        <p>{t('quicksteps_confirm_chain_hint')}</p>
        <ul className="quicksteps-confirm__chain">
          {step.actions.map((a, i) => (
            <li key={i}>{i + 1}. {actionSummary(a, t)}</li>
          ))}
        </ul>
        <div className="quicksteps-confirm__cta">
          <button type="button" onClick={onCancel}>{tCommon('cancel')}</button>
          <button type="button" className="primary" onClick={onConfirm} autoFocus>
            {tCommon('confirm')}
          </button>
        </div>
        <p className="quicksteps-confirm__hint">
          {t('quicksteps_confirm_shift_hint')}
        </p>
      </div>
    </div>
  )
}

type TFn = (k: string, opts?: Record<string, unknown>) => string
function actionSummary(action: QuickStep['actions'][number], t: TFn): string {
  switch (action.type) {
    case 'archive': return t('quicksteps_action_archive')
    case 'delete': return t('quicksteps_action_delete')
    case 'mark_read': return action.payload.value
      ? t('quicksteps_chain_mark_read')
      : t('quicksteps_chain_mark_unread')
    case 'move_to_spam': return t('quicksteps_action_move_to_spam')
    case 'reply_template': return t('quicksteps_chain_reply_template')
    case 'forward': return t('quicksteps_chain_forward_to', { to: action.payload.to.join(', ') })
    default: return (action as { type: string }).type
  }
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
  if (target.isContentEditable) return true
  return false
}

function serializeKeyEvent(event: KeyboardEvent): string {
  const parts: string[] = []
  if (event.ctrlKey) parts.push('ctrl')
  if (event.shiftKey) parts.push('shift')
  if (event.altKey) parts.push('alt')
  if (event.metaKey) parts.push('meta')
  const key = event.key.length === 1 ? event.key.toLowerCase() : event.key.toLowerCase()
  if (parts.includes(key)) return ''
  parts.push(key)
  return parts.join('+')
}

