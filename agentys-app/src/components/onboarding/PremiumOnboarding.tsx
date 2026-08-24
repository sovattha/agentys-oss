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

import { Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { lazyWithRetry as lazy } from '../../utils/lazyWithRetry'
import { useTranslation } from 'react-i18next'
import { useOnboardingWizard, type OnboardingStep } from './useOnboardingWizard'
import { useLearningProgress } from '../../hooks/useLearningProgress'
import { OnboardingLanguageSwitch } from './OnboardingLanguageSwitch'
import { ChevronLeftIcon } from '../icons/ActionIcons'
import { stripeService } from '../../services/subscription'
import './PremiumOnboarding.css'

/* Lazy-load steps for code-splitting */
const Step0Welcome = lazy(() => import('./steps/Step0Welcome').then(m => ({ default: m.Step0Welcome })))
const Step1Connect = lazy(() => import('./steps/Step1Connect').then(m => ({ default: m.Step1Connect })))
const Step3TrainAI = lazy(() => import('./steps/Step3TrainAI').then(m => ({ default: m.Step3TrainAI })))
const Step4SmartOrg = lazy(() => import('./steps/Step4SmartOrg').then(m => ({ default: m.Step4SmartOrg })))
const FinalScorecard = lazy(() => import('./steps/FinalScorecard').then(m => ({ default: m.FinalScorecard })))

interface PremiumOnboardingProps {
  onComplete: () => void
  onAccountConnected?: () => void
  accountId?: number
  accountEmail?: string
}

export function PremiumOnboarding({ onComplete, onAccountConnected, accountId, accountEmail }: PremiumOnboardingProps) {
  const { t } = useTranslation('onboarding')
  const wizard = useOnboardingWizard()
  const { step, direction, progress, setConnected, setLlmConfigured, goTo } = wizard

  const alreadyConnected = !!(accountId && accountId > 0)

  // Mark as connected since user already authenticated via OAuth on LoginPage
  useEffect(() => {
    if (alreadyConnected) {
      setConnected()
      setLlmConfigured()
    }
  }, [alreadyConnected, setConnected, setLlmConfigured])

  // Step 1 is a recovery path (not in STEP_ORDER) used when Step 3 lands
  // without an accountId. Once OAuth resolves the missing account, snap
  // forward to Step 3 so the user doesn't stall on the spinner.
  const [forceConnectStep, setForceConnectStep] = useState(false)
  useEffect(() => {
    if (alreadyConnected && step === 1 && !forceConnectStep) {
      goTo(3)
    }
  }, [alreadyConnected, step, forceConnectStep, goTo])

  // ── Eager learning: start analysis during Step 0 to reduce wait at Step 3 ──
  const { startLearning: startEagerLearning } = useLearningProgress()
  const [learningEagerStarted, setLearningEagerStarted] = useState(false)
  const [billingAiEnabled, setBillingAiEnabled] = useState<boolean | null>(null)
  const eagerStartFired = useRef(false)

  useEffect(() => {
    if (!alreadyConnected) {
      setBillingAiEnabled(null)
      return
    }
    let cancelled = false
    stripeService.getBilling()
      .then(billing => {
        if (!cancelled) setBillingAiEnabled(billing.ai_enabled)
      })
      .catch(() => {
        if (!cancelled) setBillingAiEnabled(true)
      })
    return () => { cancelled = true }
  }, [alreadyConnected])

  useEffect(() => {
    if (billingAiEnabled !== true) return
    if (!alreadyConnected || !accountId || accountId <= 0 || eagerStartFired.current) return
    eagerStartFired.current = true
    setLearningEagerStarted(true)
    void startEagerLearning(accountId, accountEmail ?? '')
  }, [alreadyConnected, accountId, accountEmail, billingAiEnabled, startEagerLearning])

  const handleSkipToMain = useCallback(() => {
    wizard.complete()
    onComplete()
  }, [wizard, onComplete])

  const [exiting, setExiting] = useState(false)

  const handleFinish = useCallback(() => {
    wizard.complete()
    setExiting(true)
    // Let the shell fade-out animation play before unmounting, then ask the V2
    // tour to start. useOnboardingV2's auto-start effect has empty deps and
    // already ran at app boot with kb_complete=false — without this dispatch,
    // a fresh user never sees the quick tour until next app relaunch.
    setTimeout(() => {
      onComplete()
      // Audit 2026-05-11: `replay` resets V2_COMPLETE_KEY and forces the
      // tour back to 'welcome'. Only dispatch when the user has not
      // already completed v2 — otherwise re-mounts of PremiumOnboarding
      // (e.g. after sign-out / sign-in cycles) would resurrect the
      // overlay despite the persisted completion flag.
      if (localStorage.getItem('agentys_onboarding_v2_complete') !== 'true') {
        window.dispatchEvent(new CustomEvent('onboarding-v2:replay'))
      }
    }, 300)
  }, [wizard, onComplete])

  const stepKey = String(step)
  const animClass = direction === 'forward' ? 'slide-left' : 'slide-right'
  const handleGoToConnect = useCallback(() => {
    setForceConnectStep(true)
    goTo(1)
  }, [goTo])
  const handleOAuthComplete = useCallback(() => {
    setForceConnectStep(false)
    onAccountConnected?.()
  }, [onAccountConnected])

  return (
    <div className={`po-shell${exiting ? ' exiting' : ''}`} role="main" aria-label={t('po_aria_label')}>
      <OnboardingLanguageSwitch />
      {/* Progress bar — hidden on final celebration */}
      {step !== 'final' && (
        <div className="po-progress" role="progressbar" aria-valuenow={Math.round(progress * 100)} aria-valuemin={0} aria-valuemax={100}>
          <div className="po-progress-fill" style={{ width: `${progress * 100}%` }} />
        </div>
      )}

      <div className="po-card-region">
        {/* Back arrow — hidden on step 0 and final */}
        {step !== 0 && step !== 'final' && (
          <button className="po-back-btn" onClick={wizard.prev} type="button" aria-label={t('wizard_back')}>
            <ChevronLeftIcon size={14} />
          </button>
        )}

        <div className="po-card">
          {/* Step content */}
          <div className="po-step-wrapper">
            <Suspense fallback={
              <div className="po-loading-center">
                <div className="po-spinner po-spinner-large" />
              </div>
            }>
              <div key={stepKey} className={`po-step ${animClass}`}>
                {renderStep(step, wizard, accountId, accountEmail, handleOAuthComplete, handleSkipToMain, handleFinish, learningEagerStarted, handleGoToConnect, forceConnectStep)}
              </div>
            </Suspense>
          </div>
        </div>
      </div>
    </div>
  )
}

function renderStep(
  step: OnboardingStep,
  wizard: ReturnType<typeof useOnboardingWizard>,
  accountId: number | undefined,
  accountEmail: string | undefined,
  onAccountConnected: (() => void) | undefined,
  onSkipToMain: () => void,
  onFinish: () => void,
  learningEagerStarted: boolean,
  onGoToConnect: () => void,
  forceConnectStep: boolean,
) {
  switch (step) {
    case 0:
      return (
        <Step0Welcome
          onNext={wizard.next}
          onSkip={onSkipToMain}
        />
      )
    case 1:
      // Skip rendering if account already connected (useEffect will auto-advance)
      if (accountId && accountId > 0 && !forceConnectStep) {
        return (
          <div className="po-loading-center">
            <div className="po-spinner po-spinner-large" />
          </div>
        )
      }
      return (
        <Step1Connect
          onNext={wizard.next}
          onBack={wizard.prev}
          onConnected={wizard.setConnected}
          onOAuthComplete={() => {
            wizard.setConnected()
            onAccountConnected?.()
          }}
          onLlmConfigured={wizard.setLlmConfigured}
          forceOAuthReconnect={forceConnectStep}
        />
      )
    case 3:
      return (
        <Step3TrainAI
          accountId={accountId ?? 0}
          accountEmail={accountEmail ?? ''}
          onNext={wizard.next}
          onBack={wizard.prev}
          onGoToConnect={onGoToConnect}
          onTrainingDone={wizard.setTrainingData}
          onContinueFree={onSkipToMain}
          learningAlreadyStarted={learningEagerStarted}
        />
      )
    case 4:
      return (
        <Step4SmartOrg
          onNext={wizard.next}
          onBack={wizard.prev}
          onLabelData={wizard.setLabelData}
        />
      )
    case 'final':
      return (
        <FinalScorecard
          state={wizard.state}
          onFinish={onFinish}
        />
      )
    default:
      return null
  }
}
