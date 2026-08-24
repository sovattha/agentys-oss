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
 * QuickStepsListHotkeys — invisible component that fires Quick Action
 * shortcuts on whichever email row the user is currently "on" (hovered,
 * else selected).
 *
 * Mounts at the EmailList level. The chip overlay was removed per design
 * feedback (too noisy on hover); shortcuts still need to work when the
 * user is in the inbox without an open detail modal. When the detail
 * modal IS open, ``QuickStepsBar`` already owns shortcut handling — we
 * read ``document.body.dataset.emailDetailOpen`` to defer to it. We also
 * read ``document.body.dataset.modalOpen`` (set by App.tsx) so a Quick
 * Step hotkey doesn't fire from inside Settings / Quick Actions / etc.
 *
 * Renders nothing visible except the run-confirmation modal (when a Quick
 * Action with ``confirmBeforeRun`` fires).
 */
import { useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import { useQuickSteps } from '../hooks/useQuickSteps'
import { useQuickStepRunner } from '../hooks/useQuickStepRunner'

interface QuickStepsListHotkeysProps {
  /** Email row the cursor is on (hovered). Falls back to `selectedEmailId`. */
  hoveredEmailId: string | null
  /** Currently-selected row (last clicked). Used as fallback target. */
  selectedEmailId: string | null
}

export function QuickStepsListHotkeys({
  hoveredEmailId,
  selectedEmailId,
}: QuickStepsListHotkeysProps) {
  const { steps } = useQuickSteps()
  const runner = useQuickStepRunner()
  const enabled = useMemo(() => steps.filter(s => s.enabled), [steps])

  useEffect(() => {
    if (enabled.length === 0) return
    const handler = (event: KeyboardEvent) => {
      // Defer to the in-modal QuickStepsBar listener when the detail
      // modal is open — running the same shortcut twice would target
      // possibly different emails (modal email vs. hovered list row).
      if (document.body.dataset.emailDetailOpen === 'true') return
      // Don't fire Quick Step hotkeys while any app-level modal is open
      // (Settings / Quick Actions / etc.) — pressing a letter on a
      // settings list item should not action an email behind the modal.
      if (document.body.dataset.modalOpen === 'true') return
      if (isTypingTarget(event.target)) return
      const pressed = serializeKeyEvent(event)
      if (!pressed) return
      const shortcutKey = event.shiftKey
        ? pressed.split('+').filter(p => p !== 'shift').join('+')
        : pressed
      const match = enabled.find(s => s.shortcut && s.shortcut === shortcutKey)
      if (!match) return
      const targetId = hoveredEmailId || selectedEmailId
      if (!targetId) return
      event.preventDefault()
      event.stopPropagation()
      void runner.run(match, targetId, { bypassConfirm: event.shiftKey })
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [enabled, hoveredEmailId, selectedEmailId, runner])

  if (!runner.pendingConfirm) return null
  return (
    <RunConfirmation
      stepName={runner.pendingConfirm.name}
      onConfirm={runner.confirm}
      onCancel={runner.cancelConfirm}
    />
  )
}

interface RunConfirmationProps {
  stepName: string
  onConfirm: () => void
  onCancel: () => void
}

function RunConfirmation({ stepName, onConfirm, onCancel }: RunConfirmationProps) {
  const { t } = useTranslation('settings')
  const { t: tCommon } = useTranslation('common')
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
      if (e.key === 'Enter') onConfirm()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onConfirm, onCancel])

  return (
    <div className="quicksteps-confirm" role="dialog" aria-modal="true">
      <div className="quicksteps-confirm__panel">
        <h4>{t('quicksteps_confirm_title', { name: stepName })}</h4>
        <p>{t('quicksteps_confirm_chain_hint')}</p>
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
  const key = event.key.toLowerCase()
  if (parts.includes(key)) return ''
  if (MODIFIER_KEY_NAMES.has(key)) return ''
  parts.push(key)
  return parts.join('+')
}

const MODIFIER_KEY_NAMES = new Set([
  'control', 'ctrl', 'shift', 'alt', 'meta', 'os', 'altgraph',
])
