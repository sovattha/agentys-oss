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
 * AICommandMenu — état `busy` (2026-06-09).
 *
 * Quand le parent exécute la commande soumise (refine LLM, 8-15 s de latence
 * réelle), le bouton baguette doit montrer un spinner et se désactiver.
 * Sans ce feedback, l'utilisateur conclut que le prompt ne fait rien et
 * re-soumet la même instruction (rapport « can't use prompt in draft tab »).
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

import { AICommandMenu } from '../AICommandMenu'

function renderMenu(busy: boolean) {
  return render(
    <AICommandMenu
      commands={[]}
      onCommandSelect={vi.fn()}
      onCustomSubmit={vi.fn()}
      onDictate={vi.fn()}
      isRecording={false}
      isTranscribing={false}
      onStopRecording={vi.fn()}
      showDictateOption={false}
      transcriptionError={null}
      busy={busy}
    />,
  )
}

describe('AICommandMenu — busy state', () => {
  it('shows an accent spinner and disables the trigger while busy', () => {
    const { container } = renderMenu(true)
    const trigger = container.querySelector<HTMLButtonElement>('[data-testid="ai-command-trigger"]')
    expect(trigger).not.toBeNull()
    expect(trigger!.disabled).toBe(true)
    expect(container.querySelector('[data-testid="ai-command-busy"]')).not.toBeNull()
  })

  it('renders the normal enabled wand when not busy', () => {
    const { container } = renderMenu(false)
    const trigger = container.querySelector<HTMLButtonElement>('[data-testid="ai-command-trigger"]')
    expect(trigger!.disabled).toBe(false)
    expect(container.querySelector('[data-testid="ai-command-busy"]')).toBeNull()
  })

  it('keeps the disabled reason visible while showing busy feedback', () => {
    const { container } = render(
      <AICommandMenu
        commands={[]}
        onCommandSelect={vi.fn()}
        onCustomSubmit={vi.fn()}
        onDictate={vi.fn()}
        isRecording={false}
        isTranscribing={false}
        onStopRecording={vi.fn()}
        showDictateOption={false}
        transcriptionError={null}
        disabled
        disabledReason="IA payante requise"
        busy
      />,
    )

    const trigger = container.querySelector<HTMLButtonElement>('[data-testid="ai-command-trigger"]')
    expect(trigger!.disabled).toBe(true)
    expect(trigger).toHaveAttribute('title', 'IA payante requise')
    expect(container.querySelector('[data-testid="ai-command-busy"]')).not.toBeNull()
  })
})
