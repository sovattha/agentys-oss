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
 * AICommandMenu — badge cadenas sur le déclencheur verrouillé (2026-06-11).
 *
 * Quand le menu IA est désactivé pour une raison « plan » (disabledReason,
 * ex. IA réservée aux abonnements payants), la baguette grisée seule ne dit
 * pas pourquoi — la raison n'existe qu'au survol (title). Un mini-cadenas
 * sur l'icône rend l'état lisible sans hover. Un disabled purement
 * opérationnel (génération en cours, sans disabledReason) ne doit PAS
 * afficher le cadenas.
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

function renderMenu(props: { disabled?: boolean; disabledReason?: string }) {
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
      {...props}
    />,
  )
}

describe('AICommandMenu — badge cadenas (verrou plan payant)', () => {
  it('affiche le cadenas quand disabled avec disabledReason', () => {
    const { container } = renderMenu({ disabled: true, disabledReason: 'IA payante requise' })
    expect(container.querySelector('[data-testid="ai-cmd-lock"]')).not.toBeNull()
  })

  it('pas de cadenas quand disabled sans raison (désactivation opérationnelle)', () => {
    const { container } = renderMenu({ disabled: true })
    expect(container.querySelector('[data-testid="ai-cmd-lock"]')).toBeNull()
  })

  it('pas de cadenas quand le menu est actif', () => {
    const { container } = renderMenu({})
    expect(container.querySelector('[data-testid="ai-cmd-lock"]')).toBeNull()
  })

  it('le spinner busy prime : pas de cadenas pendant une exécution, même verrouillé', () => {
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
    expect(container.querySelector('[data-testid="ai-command-busy"]')).not.toBeNull()
    expect(container.querySelector('[data-testid="ai-cmd-lock"]')).toBeNull()
  })
})
