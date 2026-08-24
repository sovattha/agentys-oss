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

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { LabelEditor } from './LabelEditor'

// i18n: return the key verbatim so we can assert on stable identifiers.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('../../hooks/useContactGroups', () => ({
  useContactGroups: () => ({ groups: [], loading: false }),
}))

const createLabel = vi.fn()
const createRule = vi.fn()
vi.mock('../../api/labels', () => ({
  createLabel: (...args: unknown[]) => createLabel(...args),
  updateLabel: vi.fn(),
  deleteLabel: vi.fn(),
  createRule: (...args: unknown[]) => createRule(...args),
  deleteRule: vi.fn(),
  fetchRules: vi.fn().mockResolvedValue({ rules: [] }),
}))

/**
 * Audit e2e 2026-06-10 F-01 : un label-projet dont les règles d'auto-tri
 * échouent à l'enregistrement affichait quand même le toast succès
 * « Libellé créé » — l'utilisateur croyait son tri automatique actif alors
 * que 100 % des règles étaient perdues (chemin déterministe : sentinel -1
 * → /api/rules 401). Le toast doit devenir un warning avec le compte des
 * règles perdues, et rester un succès quand tout passe.
 */
describe('LabelEditor — échec partiel des règles au save', () => {
  const toastEvents: CustomEvent[] = []
  const onToast = (evt: Event) => toastEvents.push(evt as CustomEvent)

  beforeEach(() => {
    toastEvents.length = 0
    createLabel.mockReset().mockResolvedValue({ success: true })
    createRule.mockReset()
    window.addEventListener('agentys:toast', onToast)
    return () => window.removeEventListener('agentys:toast', onToast)
  })

  async function createProjectLabel() {
    render(<LabelEditor label={null} isOpen onClose={vi.fn()} onSave={vi.fn()} />)
    fireEvent.change(screen.getByPlaceholderText('label_name_placeholder'), {
      target: { value: 'Projet Phoenix' },
    })
    // Activer le mode projet : le nom de projet est auto-rempli depuis le nom,
    // ce qui dérive des règles subject/body à enregistrer via createRule.
    const projectToggle = screen.getByText('label_project').closest('label')!
      .querySelector('input[type="checkbox"]')!
    fireEvent.click(projectToggle)
    fireEvent.click(screen.getByText('label_save'))
    await waitFor(() => expect(createLabel).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(toastEvents.length).toBeGreaterThan(0))
  }

  it('toast warning avec le compte quand des règles échouent', async () => {
    createRule.mockRejectedValue(Object.assign(new Error('Unauthorized'), { status: 401 }))

    await createProjectLabel()

    expect(createRule).toHaveBeenCalled()
    const detail = toastEvents[0].detail
    expect(detail.type).toBe('warning')
    expect(detail.message).toBe('toasts.label_saved_rules_failed')
  })

  it('toast succès inchangé quand toutes les règles passent', async () => {
    createRule.mockResolvedValue({ success: true })

    await createProjectLabel()

    expect(createRule).toHaveBeenCalled()
    const detail = toastEvents[0].detail
    expect(detail.type).toBe('success')
    expect(detail.message).toBe('toasts.label_created')
  })
})
