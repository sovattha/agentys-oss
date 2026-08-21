import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { LearningInsights } from './LearningInsights'
import type { LearningInsights as LearningInsightsType } from '../../types/onboarding'

const baseInsights = (profession = 'avocate') : LearningInsightsType => ({
  profile: {
    user_email: 'sophie@example.com',
    user_name: 'Sophie Martin',
    preferred_name: 'Sophie',
    profession,
    profession_confirmed: false,
    signature: { title: 'Associée', company: 'Cabinet Martin' },
    tone: { default_tone: 'semi-formal' },
    languages: ['fr'],
  },
  knowledge: { contacts: [] },
  rules: { contact_rules: [], general_rules: [], forbidden_phrases: [] },
  categories: null,
  emailsAnalysed: 12,
  ready: true,
})

describe('LearningInsights profession confirmation', () => {
  it('blocks the final button when profession is empty', () => {
    const onConfirmProfession = vi.fn()
    const onComplete = vi.fn()

    render(
      <LearningInsights
        insights={baseInsights('')}
        onConfirmProfession={onConfirmProfession}
        onComplete={onComplete}
      />,
    )

    expect(screen.getByLabelText(/Métier détecté/i)).toHaveValue('')
    expect(screen.getByRole('button', { name: /Commencer à utiliser Agentys/i })).toBeDisabled()
    expect(onConfirmProfession).not.toHaveBeenCalled()
    expect(onComplete).not.toHaveBeenCalled()
  })

  it('sends the edited profession before completing onboarding', async () => {
    const onConfirmProfession = vi.fn().mockResolvedValue(undefined)
    const onComplete = vi.fn()

    render(
      <LearningInsights
        insights={baseInsights('avocate')}
        onConfirmProfession={onConfirmProfession}
        onComplete={onComplete}
      />,
    )

    fireEvent.change(screen.getByLabelText(/Métier détecté/i), {
      target: { value: ' courtier immobilier ' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Commencer à utiliser Agentys/i }))

    await waitFor(() => {
      expect(onConfirmProfession).toHaveBeenCalledWith('courtier immobilier')
    })
    expect(onComplete).toHaveBeenCalledTimes(1)
  })

  it('shows an error and does not complete when saving fails', async () => {
    const onConfirmProfession = vi.fn().mockRejectedValue(new Error('boom'))
    const onComplete = vi.fn()

    render(
      <LearningInsights
        insights={baseInsights('avocate')}
        onConfirmProfession={onConfirmProfession}
        onComplete={onComplete}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Commencer à utiliser Agentys/i }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/Impossible de sauvegarder votre métier/i)
    })
    expect(onComplete).not.toHaveBeenCalled()
  })
})
