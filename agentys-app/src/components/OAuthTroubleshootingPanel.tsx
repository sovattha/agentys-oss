/**
 * OAuthTroubleshootingPanel
 *
 * Surfaces OAuth obstacles caused by browser settings (popup blocker,
 * third-party cookies, COOP, tracking prevention) and offers an actionable
 * path forward instead of letting the user stare at a silent spinner.
 *
 * Two states:
 *   1. popup blocked → brief "redirecting you directly…" notice
 *   2. polling stalled → compact card with a single primary CTA ("Use redirect")
 *      and a subtle text-link Cancel
 *
 * Lives inside the provider button column (Gmail / Outlook), so it has to
 * look tidy in a narrow ~210px slot.
 */

import { useTranslation } from 'react-i18next'
import './OAuthTroubleshootingPanel.css'

export interface OAuthTroubleshootingPanelProps {
  status: 'disconnected' | 'connecting' | 'connected' | 'error'
  popupBlocked: boolean
  pollingStalled: boolean
  onCancel: () => void
  onUseRedirect: () => void
}

export function OAuthTroubleshootingPanel({
  status,
  popupBlocked,
  pollingStalled,
  onCancel,
  onUseRedirect,
}: OAuthTroubleshootingPanelProps) {
  const { t } = useTranslation('inbox')

  if (status !== 'connecting') return null

  if (popupBlocked) {
    return (
      <div role="status" className="oauth-tip">
        <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M7 17 17 7" /><polyline points="7 7 17 7 17 17" />
        </svg>
        <span>{t('oauth_popup_blocked_redirecting')}</span>
      </div>
    )
  }

  if (pollingStalled) {
    return (
      <div role="alert" className="oauth-stalled">
        <div className="oauth-stalled__head">
          <svg className="oauth-stalled__icon" aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
          </svg>
          <span className="oauth-stalled__title">{t('oauth_polling_stalled_title')}</span>
        </div>
        <p className="oauth-stalled__hint">{t('oauth_polling_stalled_hint')}</p>
        <div className="oauth-stalled__actions">
          <button
            type="button"
            className="oauth-stalled__cta"
            onClick={onUseRedirect}
          >
            {t('oauth_polling_stalled_cta')}
          </button>
          <button
            type="button"
            className="oauth-stalled__cancel"
            onClick={onCancel}
          >
            {t('oauth_cancel')}
          </button>
        </div>
      </div>
    )
  }

  return null
}
