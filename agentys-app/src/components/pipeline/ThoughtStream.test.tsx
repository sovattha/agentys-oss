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

import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import i18n from 'i18next'
import { ThoughtStream } from './ThoughtStream'

beforeEach(async () => {
  await i18n.changeLanguage('fr')
})

describe('ThoughtStream', () => {
  it('contextualise le chargement du corps email avant la génération', () => {
    render(
      <ThoughtStream
        stageName={null}
        versionIndex={1}
        accumulatedText=""
        waitingForEmailBody
        isComplete={false}
      />,
    )

    expect(screen.getByText('Je récupère le contenu complet de l’email…')).toBeInTheDocument()
  })

  it('affiche le vrai statut quand le critic travaille', () => {
    render(
      <ThoughtStream
        stageName="optimisation"
        versionIndex={1}
        accumulatedText="Oui, je suis disponible demain à 14h."
        isComplete={false}
      />,
    )

    expect(screen.getByText('Je vérifie le ton, les faits et les consignes…')).toBeInTheDocument()
  })
})
