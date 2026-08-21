/**
 * QuickStepEditor — Auto mode is the default (2026-06-09).
 *
 * Product decision: every Quick Action that CAN auto-fire defaults to
 * Automatique; the user opts into Manuel, not the other way around. The
 * schema rejects autoEnabled without triggers, so the editor flips the mode
 * the moment the rule gains its first condition (0 → 1 transition only —
 * an explicit Manuel choice survives later edits), and downgrades back to
 * Manuel when the last condition is removed so the rule stays saveable.
 */
import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, fireEvent } from '@testing-library/react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? key,
    i18n: { language: 'fr', changeLanguage: () => Promise.resolve() },
  }),
  Trans: ({ children }: { children?: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => undefined },
}))

// ConditionsSection fetches labels + contact groups on mount; keep the
// editor offline (mirrors QuickStepEditor.reorderHandle.test.tsx).
vi.mock('../../../api/labels', () => ({ fetchLabels: () => Promise.resolve({ labels: [] }) }))
vi.mock('../../../hooks/useContactGroups', () => ({ useContactGroups: () => ({ groups: [] }) }))

import { QuickStepEditor } from '../QuickStepsManager'
import { normalizeQuickStep } from '../../../types/quickStep'

type RawDraft = Partial<Parameters<typeof normalizeQuickStep>[0]>

function draftWith(overrides: RawDraft) {
  return normalizeQuickStep({
    id: '11111111-1111-1111-1111-111111111111',
    name: 'Test step',
    description: '',
    triggers: [],
    actions: [{ type: 'archive', payload: {} }],
    firesOn: 'received',
    ...overrides,
  } as Parameters<typeof normalizeQuickStep>[0])
}

function renderEditor(overrides: RawDraft = {}) {
  return render(
    <QuickStepEditor
      draft={draftWith(overrides)}
      siblings={[]}
      onCancel={vi.fn()}
      onSave={vi.fn()}
    />,
  )
}

/** The two mode cards, in DOM order: [Manuel, Automatique]. */
function modeCards(container: HTMLElement) {
  const cards = container.querySelectorAll<HTMLButtonElement>('.qs-mode-card')
  expect(cards).toHaveLength(2)
  return { manual: cards[0], auto: cards[1] }
}

function addCondition(container: HTMLElement) {
  const add = container.querySelector<HTMLButtonElement>('.qs-trigger-add')
  expect(add).not.toBeNull()
  fireEvent.click(add!)
}

describe('QuickStepEditor — auto mode default', () => {
  it('starts a trigger-less rule in Manuel with Auto disabled', () => {
    const { container } = renderEditor()
    const { manual, auto } = modeCards(container)
    expect(manual.getAttribute('aria-checked')).toBe('true')
    expect(auto.getAttribute('aria-checked')).toBe('false')
    expect(auto.disabled).toBe(true)
  })

  it('flips to Automatique when the first condition is added', () => {
    const { container } = renderEditor()
    addCondition(container)
    const { manual, auto } = modeCards(container)
    expect(auto.getAttribute('aria-checked')).toBe('true')
    expect(auto.disabled).toBe(false)
    expect(manual.getAttribute('aria-checked')).toBe('false')
  })

  it('respects an explicit Manuel choice when more conditions are added', () => {
    const { container } = renderEditor()
    addCondition(container)
    fireEvent.click(modeCards(container).manual)
    addCondition(container)
    const { manual, auto } = modeCards(container)
    expect(manual.getAttribute('aria-checked')).toBe('true')
    expect(auto.getAttribute('aria-checked')).toBe('false')
  })

  it('does not re-flip an existing rule saved as Manuel when a condition is added', () => {
    const { container } = renderEditor({
      triggers: [{ type: 'is_read', value: 'true' }],
      autoEnabled: false,
    })
    addCondition(container)
    const { manual, auto } = modeCards(container)
    expect(manual.getAttribute('aria-checked')).toBe('true')
    expect(auto.getAttribute('aria-checked')).toBe('false')
  })

  it('downgrades to Manuel when the last condition of an auto rule is removed', () => {
    const { container } = renderEditor({
      triggers: [{ type: 'is_read', value: 'true' }],
      autoEnabled: true,
    })
    const remove = container.querySelector<HTMLButtonElement>('.qs-trigger-row__remove')
    expect(remove).not.toBeNull()
    fireEvent.click(remove!)
    const { manual, auto } = modeCards(container)
    expect(manual.getAttribute('aria-checked')).toBe('true')
    expect(auto.getAttribute('aria-checked')).toBe('false')
    expect(auto.disabled).toBe(true)
  })
})
