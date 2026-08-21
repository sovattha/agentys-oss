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
