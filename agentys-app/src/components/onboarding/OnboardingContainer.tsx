import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useOnboardingState } from '../../hooks/useOnboardingState'
import { useLearningProgress } from '../../hooks/useLearningProgress'
import { LearningProgressScreen } from './LearningProgressScreen'
import { LearningInsights } from './LearningInsights'
import { FaqSourceStep } from './FaqSourceStep'
import { API_URL } from '../../config'
import { getAuthHeaders } from '../../services/authToken'
import './OnboardingContainer.css'

interface OnboardingContainerProps {
  accountId: number
  accountEmail: string
  onComplete: () => void
  onSkip: () => void
}

interface FaqEntry {
  question: string
  answer: string
  source?: string
}

export function OnboardingContainer({ accountId, accountEmail, onComplete, onSkip }: OnboardingContainerProps) {
  const { t } = useTranslation('onboarding')
  const { step, setStep, completeOnboarding } = useOnboardingState()
  const { progress, insights, startLearning, fetchInsights } = useLearningProgress()
  // OB-04: skip-confirmation modal — without this, the user clicks "Skip"
  // and silently gets a Drafter that has no profile/contacts/style. We make
  // the consequences explicit AND persist a "skipped" state so we can later
  // tell the user why drafts feel generic.
  const [showSkipConfirm, setShowSkipConfirm] = useState(false)
  // OB-01: cancel state — drives the confirm modal + the in-flight POST.
  const [showCancelConfirm, setShowCancelConfirm] = useState(false)
  const [cancelInFlight, setCancelInFlight] = useState(false)
  // OB-H-3 (audit 2026-04-25 onboarding-flawless): track cancel failure so
  // the modal can stay open with a retry button instead of silently
  // dismissing — pre-fix the user thought they had cancelled but the
  // backend pipeline kept running.
  const [cancelError, setCancelError] = useState<string | null>(null)
  // OB-residual-1 (Codex audit 2026-04-26 prep): cap retry attempts so
  // a network outage doesn't let the user spam the cancel endpoint and
  // a buggy frontend can't loop. After 3 failures we disable the retry
  // path and tell the user to wait — the backend pipeline has its own
  // safeguards and will end on its own.
  const [cancelRetryCount, setCancelRetryCount] = useState(0)
  const cancelRetryExhausted = cancelRetryCount >= 3
  // OB-residual-2: remember whether the user has explicitly navigated
  // out of "welcome" since mount. The async hydration effect (C-6) used
  // to override that step if the backend reported "running" mid-click,
  // which yanked the user off the step they had just chosen.
  // `_userNavigated` est utilisé via setUserNavigated(prev => …) — la valeur
  // destructurée elle-même n'est jamais lue directement, prefix `_` pour
  // satisfaire `noUnusedLocals`.
  const [_userNavigated, setUserNavigated] = useState(false)

  // Auto-transition to insights when learning completes
  useEffect(() => {
    if (!progress.isActive && progress.confidenceScore >= 100 && !progress.error) {
      fetchInsights(accountId)
    }
  }, [progress.isActive, progress.confidenceScore, progress.error, fetchInsights, accountId])

  // OB-C-6 (audit 2026-04-25 onboarding-flawless): on mount, hydrate the
  // wizard step from the backend's onboarding status. If a pipeline is
  // already running for this account (user refreshed mid-pipeline, opened
  // a second tab), we resume directly into the "learning" step and let
  // the WebSocket events update progress — instead of showing "Welcome"
  // again, which lured users into clicking Start a second time and
  // racing the existing pipeline (the start() dedupe blocks the row but
  // the cost of the duplicate request is paid).
  useEffect(() => {
    let cancelled = false
    const hydrate = async () => {
      try {
        const res = await fetch(`${API_URL}/api/onboarding/status?account_id=${accountId}`, {
          headers: { ...getAuthHeaders() },
        })
        if (cancelled || !res.ok) return
        const data = await res.json().catch(() => ({}))
        const status = (data?.status as string) || 'not_started'
        // OB-residual-2 (audit prep 2026-04-26): only override the step
        // if the user hasn't explicitly navigated since mount. Without
        // this guard a slow network /status response yanked the user
        // back to "learning" right after they clicked into "faq_source",
        // which felt like a UI glitch.
        if (status === 'running' || status === 'waiting_for_sync') {
          setUserNavigated(prev => {
            if (!prev) setStep('learning')
            return prev
          })
        } else if (status === 'completed' && data?.has_insights) {
          fetchInsights(accountId)
        }
      } catch {
        // Best-effort hydration — fall through to the default welcome
        // step if /status is unreachable. The user can still click Start.
      }
    }
    hydrate()
    return () => { cancelled = true }
    // accountId is the only stable identity here. We deliberately don't
    // re-run on setStep / fetchInsights changes — those are stable hook
    // returns but listing them would create infinite re-runs in dev.

  }, [accountId])

  useEffect(() => {
    if (insights.ready) {
      setStep('insights')
    }
  }, [insights.ready, setStep])

  const handleGoToFaqSource = useCallback(() => {
    setUserNavigated(true)
    setStep('faq_source')
  }, [setStep])

  const handleFaqConfirm = useCallback((entries: FaqEntry[]) => {
    setUserNavigated(true)
    setStep('learning')
    startLearning(accountId, accountEmail, entries)
  }, [setStep, startLearning, accountId, accountEmail])

  const handleFaqSkip = useCallback(() => {
    setUserNavigated(true)
    setStep('learning')
    startLearning(accountId, accountEmail)
  }, [setStep, startLearning, accountId, accountEmail])

  const handleRetry = useCallback(() => {
    setStep('welcome')
  }, [setStep])

  const handleComplete = useCallback(() => {
    completeOnboarding()
    onComplete()
  }, [completeOnboarding, onComplete])

  const handleConfirmProfession = useCallback(async (profession: string) => {
    const res = await fetch(`${API_URL}/api/onboarding/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body: JSON.stringify({
        account_id: accountId,
        approved: true,
        corrections: { profile: { profession } },
      }),
    })
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}))
      throw new Error(payload?.error || 'Failed to save profession')
    }
  }, [accountId])

  // OB-04: skip flow — show modal first, only call onSkip() after user
  // explicitly confirms they understand the AI will be untrained.
  const handleRequestSkip = useCallback(() => {
    setShowSkipConfirm(true)
  }, [])

  const handleConfirmSkip = useCallback(() => {
    setShowSkipConfirm(false)
    // Persist a marker so the rest of the app knows training was skipped
    // (used by Drafter fallback messages, settings banners, etc.).
    try {
      localStorage.setItem('agentys_onboarding_skipped', String(Date.now()))
    } catch {
      // localStorage unavailable in some environments — non-fatal.
    }
    onSkip()
  }, [onSkip])

  const handleCancelSkip = useCallback(() => {
    setShowSkipConfirm(false)
  }, [])

  // OB-01: cancel flow — confirm, then POST to /api/onboarding/cancel,
  // then return user to the welcome step (where they can restart later).
  const handleRequestCancel = useCallback(() => {
    setShowCancelConfirm(true)
  }, [])

  const handleConfirmCancel = useCallback(async () => {
    setCancelInFlight(true)
    setCancelError(null)
    try {
      const res = await fetch(`${API_URL}/api/onboarding/cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ account_id: accountId, user_email: accountEmail }),
      })
      if (!res.ok) {
        // OB-H-3: keep the modal open and surface the error so the user
        // can retry. Pre-fix we always returned to "welcome" even when the
        // POST failed, so the user thought they had cancelled while the
        // backend pipeline kept burning LLM calls.
        setCancelError(t('cancel_error_retry', 'Échec de l\'annulation. Réessayer ?'))
        setCancelInFlight(false)
        setCancelRetryCount(c => c + 1)
        return
      }
      setCancelInFlight(false)
      setShowCancelConfirm(false)
      setCancelError(null)
      setCancelRetryCount(0)
      setStep('welcome')
    } catch {
      setCancelError(t('cancel_error_network', 'Réseau indisponible. Réessayer ?'))
      setCancelInFlight(false)
      setCancelRetryCount(c => c + 1)
    }
  }, [accountId, accountEmail, setStep, t])

  const handleDismissCancel = useCallback(() => {
    setShowCancelConfirm(false)
    setCancelError(null)
  }, [])

  // Escape key closes whichever confirm modal is open — skip when typing in
  // fields so inner popups handle Escape themselves first.
  useEffect(() => {
    if (!showSkipConfirm && !showCancelConfirm) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      const tgt = e.target as HTMLElement | null
      if (tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA' || tgt.isContentEditable)) {
        return
      }
      if (showSkipConfirm) {
        handleCancelSkip()
      } else if (showCancelConfirm && !cancelInFlight) {
        handleDismissCancel()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [showSkipConfirm, showCancelConfirm, cancelInFlight, handleCancelSkip, handleDismissCancel])

  return (
    <div className="onboarding-container">
      <div className="onboarding-card">
        {/* Step indicator */}
        <div className="onboarding-steps">
          <div className={`onboarding-step-dot ${step === 'welcome' ? 'active' : ''}`} />
          <div className={`onboarding-step-dot ${step === 'faq_source' ? 'active' : ''}`} />
          <div className={`onboarding-step-dot ${step === 'learning' ? 'active' : ''}`} />
          <div className={`onboarding-step-dot ${step === 'insights' ? 'active' : ''}`} />
        </div>

        {step === 'welcome' && (
          <div className="onboarding-welcome">
            <div className="onboarding-welcome-icon">
              <svg aria-hidden="true" width="56" height="56" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M16 2.5L1.5 29.5h29z" stroke="var(--accent-primary)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" fill="none" opacity="0.7"/>
                <path d="M16 12L8.5 25h15L16 12z" fill="var(--accent-primary)"/>
                <path d="M16 16.5L11.5 23.5h9L16 16.5z" fill="var(--surface-primary)"/>
              </svg>
            </div>
            <h3>{t('welcome_title')}</h3>
            <p className="onboarding-welcome-desc">
              {t('welcome_desc')}
            </p>
            <p className="onboarding-welcome-detail">
              {t('welcome_detail')}
            </p>
            <div className="onboarding-welcome-actions">
              <button
                type="button"
                className="onboarding-btn onboarding-btn-skip"
                onClick={handleRequestSkip}
              >
                {t('skip')}
              </button>
              <button
                type="button"
                className="onboarding-btn onboarding-btn-primary"
                onClick={handleGoToFaqSource}
              >
                {t('start_analysis')}
              </button>
            </div>
          </div>
        )}

        {step === 'faq_source' && (
          <FaqSourceStep
            onConfirm={handleFaqConfirm}
            onSkip={handleFaqSkip}
          />
        )}

        {step === 'learning' && (
          <LearningProgressScreen
            progress={progress}
            onRetry={handleRetry}
            onCancel={progress.isActive && !progress.error ? handleRequestCancel : undefined}
          />
        )}

        {step === 'insights' && (
          <LearningInsights
            insights={insights}
            onComplete={handleComplete}
            onConfirmProfession={handleConfirmProfession}
          />
        )}
      </div>

      {/* OB-04: skip confirmation modal — explicitly tell the user that
          skipping training means a generic AI until they run training again. */}
      {showSkipConfirm && (
        <div
          className="onboarding-modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-labelledby="onboarding-skip-modal-title"
        >
          <div className="onboarding-modal">
            <h3 id="onboarding-skip-modal-title">{t('skip_confirm_title', 'Passer l\'entraînement ?')}</h3>
            <p>
              {t(
                'skip_confirm_desc',
                'Sans entraînement, votre IA répondra avec un style générique : pas d\'apprentissage de votre ton, de vos signatures ou de vos contacts.',
              )}
            </p>
            <p>
              {t(
                'skip_confirm_hint',
                'Vous pourrez toujours lancer l\'entraînement plus tard depuis les Réglages.',
              )}
            </p>
            <div className="onboarding-modal-actions">
              <button
                type="button"
                className="onboarding-btn onboarding-btn-skip"
                onClick={handleCancelSkip}
              >
                {t('skip_confirm_back', 'Retour')}
              </button>
              <button
                type="button"
                className="onboarding-btn onboarding-btn-primary"
                onClick={handleConfirmSkip}
              >
                {t('skip_confirm_proceed', 'Passer quand même')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* OB-01: cancel confirmation modal — visible during the standard
          learning step. Calls /api/onboarding/cancel before bouncing back. */}
      {showCancelConfirm && (
        <div
          className="onboarding-modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-labelledby="onboarding-cancel-modal-title"
        >
          <div className="onboarding-modal">
            <h3 id="onboarding-cancel-modal-title">
              {t('cancel_confirm_title', 'Annuler l\'entraînement ?')}
            </h3>
            <p>
              {t(
                'cancel_confirm_desc',
                'L\'analyse en cours sera interrompue. Les résultats partiels déjà calculés seront conservés.',
              )}
            </p>
            {cancelError && (
              <p className="onboarding-cancel-error" role="alert" style={{ color: '#c0392b', marginTop: 8 }}>
                {cancelError}
              </p>
            )}
            <div className="onboarding-modal-actions">
              <button
                type="button"
                className="onboarding-btn onboarding-btn-skip"
                disabled={cancelInFlight}
                onClick={handleDismissCancel}
              >
                {t('cancel_confirm_keep', 'Continuer')}
              </button>
              <button
                type="button"
                className="onboarding-btn onboarding-btn-primary"
                disabled={cancelInFlight || cancelRetryExhausted}
                onClick={handleConfirmCancel}
              >
                {cancelInFlight
                  ? t('cancel_confirm_in_flight', 'Annulation...')
                  : cancelRetryExhausted
                    ? t('cancel_retry_exhausted', 'Réessayez plus tard')
                    : cancelError
                      ? t('cancel_retry_label', 'Réessayer')
                      : t('cancel_confirm_proceed', 'Annuler l\'entraînement')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
