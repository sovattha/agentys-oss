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
 * QuickStepEditor — action reorder handle visibility (2026-05-21).
 *
 * The drag-to-reorder grip on an action row only makes sense when there are
 * 2+ actions to reorder. A single-action step must NOT show it — it's a dead
 * affordance (drag is a no-op with one item). The grip is now gated on the
 * same `actions.length > 1` as the up/down/remove controls beside it, and the
 * row is only `draggable` under the same condition.
 */
import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? key,
    i18n: { language: 'fr', changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => undefined },
}))

// Action bodies / ConditionsSection fetch labels + contact groups on mount;
// keep the editor offline (mirrors QuickStepEditor.i18n.test.tsx).
vi.mock('../../../api/labels', () => ({ fetchLabels: () => Promise.resolve({ labels: [] }) }))
vi.mock('../../../hooks/useContactGroups', () => ({ useContactGroups: () => ({ groups: [] }) }))

import { QuickStepEditor } from '../QuickStepsManager'
import { normalizeQuickStep } from '../../../types/quickStep'

type ActionInput = { type: string; payload?: Record<string, unknown> }

function draftWith(actions: ActionInput[]) {
  return normalizeQuickStep({
    id: '11111111-1111-1111-1111-111111111111',
    name: 'Test step',
    description: '',
    triggers: [{ type: 'is_read', value: 'true' }],
    actions,
    firesOn: 'received',
  } as Parameters<typeof normalizeQuickStep>[0])
}

function renderEditor(actions: ActionInput[]) {
  return render(
    <QuickStepEditor draft={draftWith(actions)} siblings={[]} onCancel={vi.fn()} onSave={vi.fn()} />,
  )
}

describe('QuickStepEditor — action reorder handle', () => {
  it('hides the reorder grip and disables row drag for a single action', () => {
    const { container } = renderEditor([{ type: 'archive', payload: {} }])
    expect(container.querySelector('.quickstep-actions__handle')).toBeNull()
    expect(container.querySelector('.quickstep-actions__item')?.getAttribute('draggable')).toBe('false')
  })

  it('shows a grip per row and enables drag when there are 2+ actions', () => {
    const { container } = renderEditor([
      { type: 'archive', payload: {} },
      { type: 'archive', payload: {} },
    ])
    expect(container.querySelectorAll('.quickstep-actions__handle')).toHaveLength(2)
    const rows = container.querySelectorAll('.quickstep-actions__item')
    expect(rows).toHaveLength(2)
    rows.forEach(r => expect(r.getAttribute('draggable')).toBe('true'))
  })
})
