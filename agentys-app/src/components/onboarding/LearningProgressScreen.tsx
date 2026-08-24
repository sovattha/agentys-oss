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

import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { LearningProgress, AgentStepStatus } from '../../types/onboarding'
import { CheckIcon, CloseIcon } from '../icons/ActionIcons'
import { detectOAuthErrorGuidance, type OAuthProblemKey } from '../../lib/oauthProblemGuidance'
import './LearningProgressScreen.css'

// Smooth interpolation pour éviter les sauts discrets du compteur
// emailsProcessed. 400ms avec ease-out cubic.
function useSmoothCount(target: number): number {
  const [value, setValue] = useState(target)
  const fromRef = useRef(target)
  const startRef = useRef<number | null>(null)
  const rafRef = useRef<number | null>(null)

  useEffect(() => {
    if (target === value) return
    fromRef.current = value
    startRef.current = null
    const duration = 400
    const from = value
    const to = target

    const tick = (now: number) => {
      if (startRef.current === null) startRef.current = now
      const t = Math.min((now - startRef.current) / duration, 1)
      const eased = 1 - Math.pow(1 - t, 3)
      const next = Math.round(from + (to - from) * eased)
      setValue(next)
      if (t < 1) rafRef.current = requestAnimationFrame(tick)
    }

    rafRef.current = requestAnimationFrame(tick)
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
    }

  }, [target])

  return value
}

export interface StepInfo {
  key: 'profile' | 'style' | 'knowledge' | 'label'
  title: string
  description: string
}

/* ── Progress Ring SVG — supporte un mode indéterminé pour les phases backend
      non-mesurables (sync Gmail, récupération sent cache). L'arc rotatif
      signale "vivant, ça avance" sans fausser les % comme le faisait le 0% fixe. */
function ProgressRing({
  completedCount,
  totalSteps,
  indeterminate = false,
}: {
  completedCount: number
  totalSteps: number
  indeterminate?: boolean
}) {
  const radius = 22
  const stroke = 3
  const center = 26
  const circumference = 2 * Math.PI * radius
  const pct = totalSteps > 0 ? completedCount / totalSteps : 0
  const offset = circumference * (1 - pct)
  // Arc indéterminé : 28% de la circonférence (rotation CSS s'occupe du mouvement)
  const indetDash = `${circumference * 0.28} ${circumference}`

  return (
    <div className={`learning-progress-ring-wrap${indeterminate ? ' learning-progress-ring-wrap-indet' : ''}`}>
      <svg width="52" height="52" viewBox="0 0 52 52" className={`learning-progress-ring${indeterminate ? ' learning-progress-ring-indet' : ''}`}>
        <circle cx={center} cy={center} r={radius} fill="none" stroke="rgba(13,148,136,.1)" strokeWidth={stroke} />
        {indeterminate ? (
          <circle
            cx={center} cy={center} r={radius} fill="none"
            stroke="url(#lp-ring-grad)" strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={indetDash}
            className="learning-progress-ring-fill-indet"
          />
        ) : (
          <circle
            cx={center} cy={center} r={radius} fill="none"
            stroke="url(#lp-ring-grad)" strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            className="learning-progress-ring-fill"
          />
        )}
        <defs>
          <linearGradient id="lp-ring-grad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#0d9488" />
            <stop offset="100%" stopColor="#2dd4bf" />
          </linearGradient>
        </defs>
      </svg>
      <span className="learning-progress-ring-pct">
        {indeterminate ? null : `${Math.round(pct * 100)}%`}
      </span>
    </div>
  )
}

function StepIcon({ status }: { status: AgentStepStatus }) {
  if (status === 'completed') {
    return (
      <div className="learning-step-icon learning-step-icon-completed">
        <CheckIcon size={16} />
      </div>
    )
  }
  if (status === 'failed') {
    return (
      <div className="learning-step-icon learning-step-icon-failed">
        <CloseIcon size={16} />
      </div>
    )
  }
  if (status === 'running') {
    return <div className="learning-step-icon learning-step-icon-running" />
  }
  return <div className="learning-step-icon learning-step-icon-pending" />
}

interface LearningProgressScreenProps {
  progress: LearningProgress
  onRetry?: () => void
  onSkipPartial?: () => void
  skipPartialLabel?: string
  onCancel?: () => void
  onReconnectEmail?: () => void
  title?: string
  subtitle?: string
  steps?: StepInfo[]
  isActive?: boolean
}

const OAUTH_PROBLEM_KEYS: OAuthProblemKey[] = [
  'missing_scopes',
  'callback_loop',
  'wrong_account',
  'popup_blocked',
]

function OAuthProblemGuide({
  error,
  provider,
  selectedProblem,
  onSelectProblem,
  onReconnectEmail,
  onRetry,
}: {
  error: string
  provider: 'gmail' | 'outlook' | 'unknown'
  selectedProblem: OAuthProblemKey
  onSelectProblem: (problem: OAuthProblemKey) => void
  onReconnectEmail?: () => void
  onRetry?: () => void
}) {
  const { t } = useTranslation('onboarding')
  const primaryAction = onReconnectEmail ?? onRetry
  const providerName = provider === 'outlook' ? 'Outlook' : 'Gmail'

  const optionLabels: Record<OAuthProblemKey, string> = {
    missing_scopes: t('oauth_problem_missing_scopes', 'J’ai refusé certaines autorisations'),
    callback_loop: t('oauth_problem_callback_loop', 'Je reviens toujours au login'),
    wrong_account: t('oauth_problem_wrong_account', 'J’ai choisi le mauvais compte Google'),
    popup_blocked: t('oauth_problem_popup_blocked', 'La fenêtre Google ne s’ouvre pas'),
  }

  const descriptions: Record<OAuthProblemKey, string> = {
    missing_scopes: t(
      'oauth_problem_missing_scopes_desc',
      {
        providerName,
        defaultValue: `${providerName} a accepté la connexion, mais toutes les autorisations nécessaires n’ont pas été accordées. Agentys ne peut donc pas synchroniser vos emails.`,
      },
    ),
    callback_loop: t(
      'oauth_problem_callback_loop_desc',
      'Le retour depuis Google n’a pas donné un résultat OAuth complet. Relancez la connexion dans le même onglet et attendez le retour automatique vers Agentys.',
    ),
    wrong_account: t(
      'oauth_problem_wrong_account_desc',
      'Déconnectez le mauvais compte Google ou choisissez “Utiliser un autre compte” pendant la connexion, puis sélectionnez l’adresse email attendue.',
    ),
    popup_blocked: t(
      'oauth_problem_popup_blocked_desc',
      'Le navigateur bloque probablement la fenêtre OAuth. Autorisez les pop-ups pour Agentys ou relancez la connexion en plein onglet.',
    ),
  }

  const steps: Record<OAuthProblemKey, string[]> = {
    missing_scopes: [
      t('oauth_problem_missing_scopes_step1', { providerName, defaultValue: `Cliquez sur “Reconnecter ${providerName}”.` }),
      t('oauth_problem_missing_scopes_step2', 'Sur Google, acceptez toutes les autorisations demandées.'),
      t('oauth_problem_missing_scopes_step3', 'Si Google ne redemande rien, retirez l’accès Agentys dans votre compte Google puis recommencez.'),
    ],
    callback_loop: [
      t('oauth_problem_callback_loop_step1', 'Cliquez sur “Relancer la connexion”.'),
      t('oauth_problem_callback_loop_step2', 'Gardez l’onglet Agentys ouvert jusqu’au retour automatique.'),
      t('oauth_problem_callback_loop_step3', 'Si le problème revient, essayez Safari/Chrome sans bloqueur de tracking pour cette connexion.'),
    ],
    wrong_account: [
      t('oauth_problem_wrong_account_step1', { providerName, defaultValue: `Cliquez sur “Reconnecter ${providerName}”.` }),
      t('oauth_problem_wrong_account_step2', 'Dans Google, utilisez “Changer de compte” ou “Utiliser un autre compte”.'),
      t('oauth_problem_wrong_account_step3', 'Sélectionnez l’adresse email que vous voulez utiliser dans Agentys.'),
    ],
    popup_blocked: [
      t('oauth_problem_popup_blocked_step1', 'Autorisez les pop-ups pour app.agentys.io dans votre navigateur.'),
      t('oauth_problem_popup_blocked_step2', 'Relancez la connexion depuis Agentys.'),
      t('oauth_problem_popup_blocked_step3', 'Sur iPhone, préférez le bouton de connexion en plein onglet si le navigateur le propose.'),
    ],
  }

  const ctaLabel = selectedProblem === 'callback_loop' || selectedProblem === 'popup_blocked'
    ? t('oauth_problem_cta_retry', 'Relancer la connexion')
    : t('oauth_problem_cta_reconnect', { providerName, defaultValue: `Reconnecter ${providerName}` })

  return (
    <div className="oauth-guidance" role="alert">
      <div className="oauth-guidance__badge">{t('oauth_problem_detected', 'Problème détecté automatiquement')}</div>
      <h4>{t('oauth_problem_title', 'Connexion Gmail à finaliser')}</h4>
      <p className="oauth-guidance__intro">
        {t(
          'oauth_problem_intro',
          'Choisissez ce qui ressemble le plus à votre situation. Agentys vous guide ensuite vers l’action adaptée.',
        )}
      </p>

      <div className="oauth-guidance__choices" role="radiogroup" aria-label={t('oauth_problem_select_label', 'Sélectionner le problème rencontré')}>
        {OAUTH_PROBLEM_KEYS.map(problem => (
          <button
            key={problem}
            type="button"
            role="radio"
            aria-checked={selectedProblem === problem}
            className={`oauth-guidance__choice${selectedProblem === problem ? ' oauth-guidance__choice--selected' : ''}`}
            onClick={() => onSelectProblem(problem)}
          >
            {optionLabels[problem]}
          </button>
        ))}
      </div>

      <div className="oauth-guidance__resolution">
        <p>{descriptions[selectedProblem]}</p>
        <ol>
          {steps[selectedProblem].map(step => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </div>

      <div className="oauth-guidance__actions">
        {primaryAction && (
          <button
            type="button"
            className="onboarding-btn onboarding-btn-primary"
            onClick={primaryAction}
          >
            {ctaLabel}
          </button>
        )}
        <a
          className="oauth-guidance__link"
          href="https://myaccount.google.com/permissions"
          target="_blank"
          rel="noreferrer"
        >
          {t('oauth_problem_google_permissions', 'Gérer l’accès Agentys dans Google')}
        </a>
      </div>

      <details className="oauth-guidance__details">
        <summary>{t('oauth_problem_technical_details', 'Détails techniques')}</summary>
        <code>{error}</code>
      </details>
    </div>
  )
}

export function LearningProgressScreen({
  progress,
  onRetry,
  onSkipPartial,
  skipPartialLabel,
  onCancel,
  onReconnectEmail,
  title,
  subtitle,
  steps,
  isActive,
}: LearningProgressScreenProps) {
  const { t } = useTranslation('onboarding')
  const oauthGuidance = detectOAuthErrorGuidance(progress.error)
  const [selectedOAuthProblem, setSelectedOAuthProblem] = useState<OAuthProblemKey>('missing_scopes')

  useEffect(() => {
    if (oauthGuidance) setSelectedOAuthProblem(oauthGuidance.defaultProblem)
  }, [oauthGuidance?.defaultProblem, progress.error])

  // Le pilier `knowledge` (Savoir) a été retiré de l'onboarding : il n'est
  // plus exposé en UI bien que KnowledgeAgent tourne toujours en backend pour
  // alimenter les contacts/règles/projets dérivés. Aligné avec la liste
  // `ONBOARDING_PILLARS` de Step3TrainAI (profil / style / autolabel).
  const defaultSteps: StepInfo[] = [
    { key: 'profile', title: t('progress_profile'), description: t('progress_profile_desc') },
    { key: 'style', title: t('progress_style'), description: t('progress_style_desc') },
    { key: 'label', title: t('progress_label'), description: t('progress_label_desc') },
  ]

  const resolvedSteps = steps ?? defaultSteps
  const active = isActive ?? progress.isActive
  const hasError = !!progress.error
  const completedCount = resolvedSteps.filter(s => progress.agentSteps[s.key] === 'completed').length
  const smoothProcessed = useSmoothCount(progress.emailsProcessed)

  return (
    <div className="learning-progress">
      <div className="learning-progress-header">
        {hasError ? (
          <div className="learning-progress-error-icon">
            <svg aria-hidden="true" width="48" height="48" viewBox="0 0 48 48" fill="none">
              <circle cx="24" cy="24" r="22" stroke="var(--error)" strokeWidth="3" fill="none"/>
              <path d="M24 14V28" stroke="var(--error)" strokeWidth="3" strokeLinecap="round"/>
              <circle cx="24" cy="34" r="2" fill="var(--error)"/>
            </svg>
          </div>
        ) : (
          <ProgressRing
            completedCount={completedCount}
            totalSteps={resolvedSteps.length}
            /* Indéterminé tant qu'aucune étape visible n'est complétée — la ring
               tourne en continu pendant toute la phase sync + agents qui tournent,
               puis bascule en déterminé dès la 1re completion (saut à 33% avec
               transition fluide). Évite les "0% figé" pendant 5-14s. */
            indeterminate={active && completedCount === 0}
          />
        )}
        {(title || title === undefined) && (
          <h3>{title ?? (hasError ? t('progress_error_title') : t('progress_title'))}</h3>
        )}
        {(subtitle || subtitle === undefined) && (
          <p className="learning-progress-phase">
            {subtitle ?? (hasError ? t('progress_error_desc') : t('progress_subtitle'))}
          </p>
        )}
      </div>

      {!hasError && (
        <div className="learning-progress-stats">
          <span className="learning-progress-stat">
            {/* Pendant la sync Gmail, `emailsTotal` vaut MIN_EMAILS_FOR_ANALYSIS
                (un seuil mini, pas un total à scanner), donc afficher X/Y produit
                des fractions absurdes type 80/15 quand le sync continue après
                le seuil. On bascule sur "X emails synchronisés..." sans fraction
                tant que l'indexation n'a pas posé un vrai total.
                Hidden on error: a "50/50 emails" counter next to a
                "no sent emails found" message reads as contradictory — the 50
                are received-only and don't satisfy the style training. */}
            {progress.currentPhaseKey === 'scan_phase_syncing'
              ? t('progress_emails_syncing', { count: smoothProcessed })
              : progress.emailsTotal > 0
                ? (smoothProcessed > 0
                    ? <><span className="learning-progress-count-live">{Math.min(smoothProcessed, progress.emailsTotal)}</span>{' / '}{progress.emailsTotal} emails</>
                    : <>{progress.emailsTotal} emails</>)
                : t('progress_loading')
            }
          </span>
        </div>
      )}

      <div className="learning-steps">
        {resolvedSteps.map((step) => {
          const status = progress.agentSteps[step.key]
          const pendingClass = active && status === 'pending' ? ' learning-step-active-pending' : ''
          return (
            <div key={step.key} className={`learning-step learning-step-${status}${pendingClass}`}>
              <StepIcon status={status} />
              <div className="learning-step-content">
                <span className="learning-step-title">{step.title}</span>
                <span className="learning-step-description">{step.description}</span>
              </div>
            </div>
          )
        })}
      </div>

      {hasError && (
        oauthGuidance && progress.error ? (
          <OAuthProblemGuide
            error={progress.error}
            provider={oauthGuidance.provider}
            selectedProblem={selectedOAuthProblem}
            onSelectProblem={setSelectedOAuthProblem}
            onReconnectEmail={onReconnectEmail}
            onRetry={onRetry}
          />
        ) : (
          <div className="learning-progress-error">
            {progress.error === 'reauth_required' ? (
              <span>
                {t(
                  'progress_reauth_required',
                  "Impossible de synchroniser votre boîte mail — votre connexion OAuth a expiré ou été révoquée. Reconnectez votre compte pour continuer."
                )}
              </span>
            ) : progress.error === 'billing_required' ? (
              <span>
                {t(
                  'progress_billing_required',
                  "L’onboarding IA est réservé aux abonnements actifs. Vous pouvez continuer en mode gratuit."
                )}
              </span>
            ) : (
              <span>{progress.error}</span>
            )}
          </div>
        )
      )}

      {hasError && (onRetry || onSkipPartial) && !oauthGuidance && (
        <div className="learning-retry-actions">
          {onRetry && (
            <button
              type="button"
              className="onboarding-btn onboarding-btn-primary"
              onClick={onRetry}
            >
              {t('progress_retry')}
            </button>
          )}
          {onSkipPartial && (
            <button
              type="button"
              className="onboarding-btn onboarding-btn-secondary"
              onClick={onSkipPartial}
            >
              {skipPartialLabel ?? t('progress_skip_partial')}
            </button>
          )}
        </div>
      )}

      {!hasError && onCancel && (
        <div className="learning-cancel-actions">
          <button
            type="button"
            className="learning-cancel-btn"
            onClick={onCancel}
          >
            {t('progress_cancel')}
          </button>
          <span className="learning-cancel-hint">
            {t('progress_cancel_hint')}
          </span>
        </div>
      )}
    </div>
  )
}
