import { describe, it, expect } from 'vitest'
import { derivePlanBanner } from './planBanner'

const NOW = new Date('2026-06-25T12:00:00Z').getTime()

describe('derivePlanBanner', () => {
  it('masque la bannière pour un abonné payant actif', () => {
    const r = derivePlanBanner(
      { plan: 'professional', subscription_status: 'active', ai_enabled: true },
      NOW,
    )
    expect(r.show).toBe(false)
  })

  it('affiche la variante essai avec les jours restants (trialing)', () => {
    const r = derivePlanBanner(
      {
        plan: 'starter',
        subscription_status: 'trialing',
        ai_enabled: true,
        current_period_end: '2026-06-30T12:00:00Z', // +5 jours
      },
      NOW,
    )
    expect(r.show).toBe(true)
    expect(r.variant).toBe('trial')
    expect(r.daysRemaining).toBe(5)
  })

  it('affiche la variante gratuite quand aucun abonnement actif', () => {
    const r = derivePlanBanner(
      { plan: 'free', subscription_status: 'none', ai_enabled: false },
      NOW,
    )
    expect(r.show).toBe(true)
    expect(r.variant).toBe('free')
    expect(r.daysRemaining).toBeNull()
  })

  it('traite un statut inactif (past_due/canceled) comme gratuit', () => {
    const r = derivePlanBanner(
      { plan: 'professional', subscription_status: 'canceled', ai_enabled: false },
      NOW,
    )
    expect(r.show).toBe(true)
    expect(r.variant).toBe('free')
  })

  it('borne les jours restants à 0 minimum (essai expiré)', () => {
    const r = derivePlanBanner(
      {
        plan: 'starter',
        subscription_status: 'trialing',
        ai_enabled: true,
        current_period_end: '2026-06-24T12:00:00Z', // passé
      },
      NOW,
    )
    expect(r.variant).toBe('trial')
    expect(r.daysRemaining).toBe(0)
  })

  it('ne montre rien si le billing est absent (évite un flash avant chargement)', () => {
    expect(derivePlanBanner(null, NOW).show).toBe(false)
    expect(derivePlanBanner(undefined, NOW).show).toBe(false)
  })
})
