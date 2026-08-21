import { useTranslation } from 'react-i18next'
import { derivePlanBanner } from '../utils/planBanner'
import type { BillingEntitlement } from '../services/subscription'
import './PlanStatusBanner.css'

interface PlanStatusBannerProps {
  /** Entitlement billing courant (`/api/billing/me`). Null tant que non chargé. */
  billing: BillingEntitlement | null | undefined
  /** Ouvre la popup Facturation. */
  onOpenBilling: () => void
}

/**
 * Bandeau de conversion : indique clairement aux utilisateurs gratuits ou en
 * essai sur quel forfait ils sont, et ouvre la popup Facturation au clic.
 * Masqué pour les abonnés payants actifs (rien à convertir).
 */
export function PlanStatusBanner({ billing, onOpenBilling }: PlanStatusBannerProps) {
  const { t } = useTranslation('common')
  const state = derivePlanBanner(billing)

  if (!state.show || !state.variant) return null

  const isTrial = state.variant === 'trial'

  const label = isTrial
    ? t('plan_banner_trial_label', {
        defaultValue: 'Essai gratuit · {{days}} j restants',
        days: String(state.daysRemaining ?? 0),
      })
    : t('plan_banner_free_label', {
        defaultValue: 'Version gratuite · fonctions IA verrouillées',
      })

  const cta = isTrial
    ? t('plan_banner_trial_cta', { defaultValue: 'Activer mon forfait' })
    : t('plan_banner_free_cta', { defaultValue: 'Choisir un forfait' })

  return (
    <button
      type="button"
      className={`plan-banner plan-banner--${state.variant}`}
      onClick={onOpenBilling}
      data-testid="plan-status-banner"
      aria-label={`${label} — ${cta}`}
    >
      <span className="plan-banner__dot" aria-hidden="true" />
      <span className="plan-banner__label">{label}</span>
      <span className="plan-banner__cta">
        {cta}
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M5 12h14" />
          <path d="m12 5 7 7-7 7" />
        </svg>
      </span>
    </button>
  )
}

export default PlanStatusBanner
