import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useLearningProgress } from '../../../hooks/useLearningProgress'
import { API_URL } from '../../../config'
import { getAuthHeaders, handleAuthResponse } from '../../../services/authToken'
import { fetchAccounts } from '../../../api/accounts'
import { LearningProgressScreen } from '../LearningProgressScreen'
import { ScanNarrator } from '../ScanNarrator'
import { DiscoveryFeed } from '../DiscoveryFeed'
import { PillarNav } from '../../PillarNav'
import { PillarProfilReadOnly } from '../../PillarProfilReadOnly'
import { PillarStyleReadOnly } from '../../PillarStyleReadOnly'
import { PillarAutoLabelReadOnly } from '../../PillarAutoLabelReadOnly'
import '../LearningInsights.css'
import type { TrainingData } from '../useOnboardingWizard'
import type { Pillar } from '../../../types/training'
import type { ContactRule, KnowledgeContact } from '../../../types/onboarding'

// Stall timeout: if no step transitions after this many seconds, show an error.
// Covers the worst-case path: 5 min waiting for the initial inbox sync +
// ~1 min for the analysis itself.
// Overridable via window.__TEST_STALL_TIMEOUT for E2E tests.
const STALL_TIMEOUT_SECONDS: number = (() => {
  if (typeof window !== 'undefined') {
    const override = (window as unknown as { __TEST_STALL_TIMEOUT?: number }).__TEST_STALL_TIMEOUT
    if (typeof override === 'number') return override
  }
  return 360
})()

/**
 * Écran d'attente quand Step 3 est atteint sans accountId (race OAuth, reset
 * partiel, token expiré, ou compte non reconnu côté backend).
 *
 * Parcours :
 * 1. Affiche immédiatement un bouton "Connecter ma messagerie" qui renvoie
 *    l'utilisateur à Step 1 pour refaire le flux OAuth — Step 1 est hors
 *    STEP_ORDER donc sans cette porte l'utilisateur tournait en boucle
 *    Step 3 ↔ Step 0 sans jamais atteindre la connexion.
 * 2. Après 15s sans resolution d'accountId, bascule automatiquement sur
 *    Step 1 — couvre le cas où le polling /api/init ne remonte jamais
 *    d'account (compte purgé, user_id mismatch, OAuth partiel).
 */
function WaitingForAccountBlock({ onGoToConnect }: { onGoToConnect: () => void }) {
  const { t } = useTranslation('onboarding')
  useEffect(() => {
    const tid = setTimeout(onGoToConnect, 15_000)
    return () => clearTimeout(tid)
  }, [onGoToConnect])
  return (
    <div style={{ textAlign: 'center', padding: '32px 0', color: 'var(--text-tertiary)', fontSize: 14, display: 'flex', flexDirection: 'column', gap: 16, alignItems: 'center' }}>
      <div>{t('step3_waiting_account')}</div>
      <button
        type="button"
        className="po-btn-primary"
        onClick={onGoToConnect}
        aria-label={t('step3_retry_connect_aria', 'Connecter ma messagerie')}
      >
        {t('step3_retry_connect', 'Connecter ma messagerie')}
      </button>
    </div>
  )
}

const InfoIcon = () => (
  <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <line x1="12" y1="16" x2="12" y2="12" />
    <line x1="12" y1="8" x2="12.01" y2="8" />
  </svg>
)

interface Step3Props {
  accountId: number
  accountEmail: string
  onNext: () => void
  onBack: () => void
  onTrainingDone: (data: TrainingData) => void
  /** Route the user back to Step 1 (Connect) when accountId never arrives. */
  onGoToConnect: () => void
  /** Leave the AI onboarding and continue using the free product surface. */
  onContinueFree?: () => void
  /** True when PremiumOnboarding already called startLearning during Step 0 */
  learningAlreadyStarted?: boolean
}

export function Step3TrainAI({ accountId, accountEmail, onNext, onBack: _onBack, onTrainingDone, onGoToConnect, onContinueFree, learningAlreadyStarted }: Step3Props) {
  const { t } = useTranslation('onboarding')

  const { progress, insights, isStalled, startLearning, fetchInsights, startStatusPolling } = useLearningProgress()
  const [started, setStarted] = useState(false)
  const startedRef = useRef(false)
  const [done, setDone] = useState(false)
  // User profile photo for the celebration hero. Fetched once on mount so by
  // the time `done` flips true the URL is already in state. We never use a
  // Gravatar fallback here — if `avatar_url` is missing we keep the brand
  // logo, which is a more honest neutral than a guessed Gravatar.
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null)
  const [avatarFailed, setAvatarFailed] = useState(false)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [stalledError, setStalledError] = useState<string | null>(null)
  const [_showSkip, setShowSkip] = useState(false)
  const [activePillar, setActivePillar] = useState<Pillar>('profil')
  const elapsedTimer = useRef<ReturnType<typeof setInterval>>(undefined)
  const stallTimer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const hasProgressRef = useRef(false)

  // Resolve the user's avatar_url once. The component receives accountId as
  // an int DB id but Account.id is the multi-account hash, so we filter
  // fetchAccounts() by email instead. Fire once on mount — the celebration
  // hero only renders ~30s+ later when `done` flips true, plenty of time.
  useEffect(() => {
    if (!accountEmail) return
    let cancelled = false
    fetchAccounts()
      .then(({ accounts }) => {
        if (cancelled) return
        const match = accounts.find(a => a.email.toLowerCase() === accountEmail.toLowerCase())
        if (match?.avatar_url) setAvatarUrl(match.avatar_url)
      })
      .catch(() => {
        // Non-fatal: hero falls back to logo. No retry — the user already
        // has an account-less escape hatch via the Settings avatar uploader.
      })
    return () => { cancelled = true }
  }, [accountEmail])

  // Auto-start learning + HTTP polling fallback
  useEffect(() => {
    if (startedRef.current || accountId <= 0) return
    startedRef.current = true
    setStarted(true)
    let stopPolling: (() => void) | null = null
    let cancelled = false

    void (async () => {
      if (!learningAlreadyStarted) {
        // Normal path: learning hasn't started yet — initiate it now
        // Séquencement : on attend la confirmation 200 du POST /start avant de
        // lancer le polling GET /status → évite les 404 "No onboarding found"
        // pendant le round-trip initial.
        const result = await startLearning(accountId, accountEmail)
        if (cancelled) return
        if (!result.ok) return  // l'erreur est déjà dans progress.error
      }
      // Eager path: learning was already started from Step 0 — jump straight to
      // HTTP polling to catch up on current status (WS events may have been missed).
      if (!cancelled) {
        stopPolling = startStatusPolling(accountId, () => {
          // Server confirmed alive via HTTP — cancel stall timer immediately
          hasProgressRef.current = true
          setStalledError(null)
          if (stallTimer.current) clearTimeout(stallTimer.current)
        })
      }
    })()
    return () => {
      cancelled = true
      // Reset ref so that React 18 Strict Mode's second mount (dev-only) can restart
      startedRef.current = false
      if (stopPolling) stopPolling()
    }

  }, [accountId])

  // Elapsed timer + stall detection while active
  useEffect(() => {
    if (progress.isActive && !done) {
      setElapsedSeconds(0)
      setShowSkip(false)
      elapsedTimer.current = setInterval(() => {
        setElapsedSeconds(s => s + 1)
      }, 1000)
      const skipTimer = setTimeout(() => setShowSkip(true), 15_000)
      stallTimer.current = setTimeout(() => {
        if (!hasProgressRef.current) {
          setStalledError(t('step3_stall_error'))
        }
      }, STALL_TIMEOUT_SECONDS * 1000)
      return () => {
        clearInterval(elapsedTimer.current!)
        clearTimeout(stallTimer.current!)
        clearTimeout(skipTimer)
      }
    }
    return () => {
      if (elapsedTimer.current) clearInterval(elapsedTimer.current)
      if (stallTimer.current) clearTimeout(stallTimer.current)
    }
  }, [progress.isActive, done, t])

  // Track step progress to cancel stall detection.
  // On n'efface PAS l'erreur de stall si elle est déjà affichée : une fois
  // `step3_stall_error` visible, l'utilisateur a déjà vu le message et peut
  // cliquer Retry — faire disparaître l'erreur parce qu'un WS event arrive
  // tardivement créerait un UI clignotant (stall ↔ en cours) et masquerait
  // l'état "instable" du serveur.
  useEffect(() => {
    const steps = progress.agentSteps
    const anyProgress = Object.values(steps).some(s => s === 'running' || s === 'completed')
    if (anyProgress) {
      hasProgressRef.current = true
      if (stallTimer.current) clearTimeout(stallTimer.current)
    }
  }, [progress.agentSteps])

  // Si reauth_required arrive, on neutralise le stall timer — le message
  // d'erreur dédié (dans LearningProgressScreen) est plus utile qu'un
  // double-affichage "analyse stuck" générique.
  useEffect(() => {
    if (progress.error === 'reauth_required' && stallTimer.current) {
      clearTimeout(stallTimer.current)
      stallTimer.current = undefined
    }
  }, [progress.error])

  // Si le backend émet learning_completed tardivement APRES que le stall
  // ait déjà fire, on résout la contradiction : l'analyse a réellement
  // abouti, on efface l'erreur de stall et on laisse le reveal screen
  // s'afficher. Sans ça, user voit "error" alors que tous les steps sont
  // completed côté state.
  useEffect(() => {
    const steps = progress.agentSteps
    const allStepsDone =
      steps.profile === 'completed' &&
      steps.style === 'completed' &&
      steps.label === 'completed'
    if (allStepsDone && stalledError) {
      setStalledError(null)
    }
  }, [progress.agentSteps, stalledError])

  // Detect completion — on ne check QUE les 3 piliers visibles (profile/style/label).
  // `knowledge` tourne en backend mais n'est plus exposé dans l'UI ; exiger sa
  // completion ici bloquait l'onboarding en cas de partial failure de KnowledgeAgent.
  useEffect(() => {
    const steps = progress.agentSteps
    const allDone = steps.profile === 'completed'
      && steps.style === 'completed' && steps.label === 'completed'
    if (allDone && !done && started) {
      setDone(true)
      fetchInsights(accountId)
      if (elapsedTimer.current) clearInterval(elapsedTimer.current)
    }
  }, [progress.agentSteps, done, started, fetchInsights, accountId])

  // Once insights are ready, compute summary
  useEffect(() => {
    if (done && insights.ready) {
      const tone = insights.profile?.tone?.default_tone || 'professionnel'
      onTrainingDone({
        emailsAnalysed: progress.emailsProcessed || insights.emailsAnalysed || 0,
        tone,
        contactsCount: 0,
      })
    }
  }, [done, insights, progress.emailsProcessed, onTrainingDone])

  // Bypass d'urgence pour les comptes vides (0 emails reçus/envoyés ou < seuil
  // d'analyse). Quand le pipeline retourne status="partial", l'utilisateur n'a
  // aucune action correctrice possible — "Recommencer" boucle indéfiniment.
  // Ce handler force la sortie du Step 3 avec un profil minimal : l'utilisateur
  // pourra relancer l'entraînement plus tard depuis Réglages quand sa boîte
  // contiendra plus de signaux.
  const handleSkipPartial = useCallback(() => {
    onTrainingDone({
      emailsAnalysed: progress.emailsProcessed || 0,
      tone: insights.profile?.tone?.default_tone || 'professionnel',
      contactsCount: 0,
    })
    setDone(true)
    onNext()
  }, [onTrainingDone, onNext, progress.emailsProcessed, insights.profile])

  const handleRetry = useCallback(() => {
    setStarted(false)
    setDone(false)
    setStalledError(null)
    setElapsedSeconds(0)
    setShowSkip(false)
    hasProgressRef.current = false
    startedRef.current = false
    void (async () => {
      // Cancel any zombie row first. Without this, the backend's "already
      // active" guard makes /start a no-op (it returns the existing
      // waiting_for_sync row) and the worker thread is never re-spawned —
      // exactly the symptom that prompted this retry button. Best-effort:
      // a 404/500 here just means there was nothing to cancel, which is
      // fine — we proceed with /start unconditionally.
      try {
        await handleAuthResponse(await fetch(`${API_URL}/api/onboarding/cancel`, {
          method: 'POST',
          headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
          body: JSON.stringify({ account_id: String(accountId), user_email: accountEmail }),
        }))
      } catch {
        // Network or auth error — fall through and let /start surface a
        // user-visible error if it also fails.
      }
      if (startedRef.current) return
      startedRef.current = true
      setStarted(true)
      await startLearning(accountId, accountEmail)
      startStatusPolling(accountId, () => {
        hasProgressRef.current = true
        setStalledError(null)
        if (stallTimer.current) clearTimeout(stallTimer.current)
      })
    })()
  }, [accountId, accountEmail, startLearning, startStatusPolling])

  // ─── Derived data for done screen ───
  const revealData = useMemo(() => {
    if (!done) return null
    const emailsCount = progress.emailsProcessed || insights.emailsAnalysed || 0
    const languages: string[] = insights.profile?.languages || []

    const contacts: KnowledgeContact[] = insights.knowledge?.contacts || []

    const contactRules: ContactRule[] = insights.rules?.contact_rules || []

    const labelStats: Record<string, number> = insights.categories?.statistics || {}

    return { emailsCount, languages, contacts, contactRules, labelStats }
  }, [done, progress.emailsProcessed, insights])

  // ─── CountUp hook ───
  const [countUpValue, setCountUpValue] = useState(0)
  useEffect(() => {
    if (!done || !revealData) return
    const target = revealData.emailsCount
    if (target <= 0) { setCountUpValue(0); return }
    const duration = 1200
    const startTime = performance.now()
    let raf: number
    const tick = (now: number) => {
      const t = Math.min((now - startTime) / duration, 1)
      const eased = 1 - Math.pow(1 - t, 3)
      setCountUpValue(Math.round(eased * target))
      if (t < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [done, revealData])

  // ─── Pillar data availability ───
  // Savoir est intentionnellement absent de l'onboarding : il se configure
  // dans les Settings (TrainingPage → PillarSavoir) où l'utilisateur peut
  // ajouter sa FAQ si désiré. Les données contacts/projets/terminologie
  // continuent d'être scannées et restent visibles dans Settings.
  const pillarAvailable = useMemo<Partial<Record<Pillar, boolean>>>(() => {
    if (!revealData) return { profil: false, style: false, autolabel: false }
    return {
      profil: !!insights.profile,
      style: !!insights.profile?.tone,
      autolabel: true, // always available — 3 default labels are always active
    }
  }, [revealData, insights.profile])

  // ─── Onboarding-specific hints for PillarNav ───
  const pillarHints = useMemo<Partial<Record<Pillar, string>>>(() => ({
    profil: t('step3_pillar_hint_profil'),
    style: t('step3_pillar_hint_style'),
    autolabel: t('step3_pillar_hint_autolabel'),
  }), [t])

  // Piliers visibles pendant l'onboarding (Savoir retiré — voir commentaire ci-dessus)
  const ONBOARDING_PILLARS: Pillar[] = ['profil', 'style', 'autolabel']

  // Always land on Profil when the reveal screen opens.

  // ─── Done state ───
  if (done && revealData) {
    const { contacts, contactRules, languages } = revealData
    const INVALID_NAMES = new Set(['none', 'null', 'n/a', 'na', 'undefined', 'unknown', 'inconnu', 'inconnue', 'user', ''])
    const rawProfile = insights.profile
    const rawUserName = rawProfile?.user_name?.trim() ?? ''
    const safeUserName = INVALID_NAMES.has(rawUserName.toLowerCase()) ? '' : rawUserName
    const profile = rawProfile ? { ...rawProfile, user_name: safeUserName } : rawProfile
    const firstName = safeUserName.split(' ')[0] || undefined
    return (
      <div className="s3-reveal-root">
        {/* Hero */}
        <div className="s3-hero s3-reveal s3-delay-0">
          {avatarUrl && !avatarFailed ? (
            <div className="s3-hero-logo s3-hero-avatar">
              <img
                src={avatarUrl}
                alt={firstName ? `${firstName}'s profile` : accountEmail}
                onError={() => setAvatarFailed(true)}
              />
            </div>
          ) : (
            <div className="s3-hero-logo" aria-hidden="true">
              <svg width={80} height={80} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M16 2.5L1.5 29.5h29z" stroke="#2dd4bf" strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round" fill="none"/>
                <path d="M16 12L8.5 25h15L16 12z" fill="#0d9488"/>
                <path d="M16 16.5L11.5 23.5h9L16 16.5z" fill="var(--surface-base, #faf9f7)" opacity="0.92"/>
              </svg>
            </div>
          )}
          <h3 className="po-celebration-title">
            {firstName ? `${firstName}, ${t('step3_ready_title')}` : t('step3_ready_title_generic')}
          </h3>
          <p className="s3-hero-count">
            <span className="s3-count-number">{countUpValue}</span> {t('step3_emails_analysed')}
          </p>
        </div>

        {/* Pillar navigation tabs */}
        <div className="s3-reveal s3-delay-1">
          <PillarNav
            activePillar={activePillar}
            onSelect={setActivePillar}
            hintOverrides={pillarHints}
            detected={pillarAvailable}
            visiblePillars={ONBOARDING_PILLARS}
          />
        </div>

        {/* Active pillar content (one at a time) */}
        <div className="s3-pillar-content" key={activePillar}>
          {activePillar === 'profil' && (
            profile
              ? <PillarProfilReadOnly profile={profile} languages={languages} />
              : <p className="s3-empty-pillar">{t('step3_no_data')}</p>
          )}
          {activePillar === 'style' && (
            profile?.tone
              ? <PillarStyleReadOnly
                  tone={profile.tone}
                  contactRules={contactRules}
                  contacts={contacts}
                />
              : <p className="s3-empty-pillar">{t('step3_no_data')}</p>
          )}
          {activePillar === 'autolabel' && (
            <PillarAutoLabelReadOnly statistics={revealData.labelStats} />
          )}
        </div>

        {/* Settings reference note */}
        <div className="s3-settings-note s3-reveal s3-delay-3">
          <InfoIcon />
          <p>{t('step3_settings_note')}</p>
        </div>

        {/* CTA sticky */}
        <div className="s3-sticky-cta">
          <button className="po-btn-primary" onClick={onNext}>
            <span>{t('step1_continue')}</span>
            <svg className="w0-btn-arrow" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
          </button>
        </div>
      </div>
    )
  }

  // ─── accountId missing ───
  // Protection contre un Step 3 atteint sans accountId (race OAuth / reset
  // partiel / compte non reconnu). WaitingForAccountBlock propose tout de
  // suite un bouton "Connecter ma messagerie" qui renvoie vers Step 1 et
  // bascule automatiquement après 15s si le polling /api/init ne remonte
  // toujours rien — évite la boucle Step 3 ↔ Step 0 de l'ancien retry.
  if (!started && accountId <= 0) {
    return <WaitingForAccountBlock onGoToConnect={onGoToConnect} />
  }

  // ─── Training in progress ───
  const progressWithStall = stalledError
    ? { ...progress, isActive: false, error: stalledError }
    : progress
  const billingRequired = progressWithStall.error === 'billing_required'

  return (
    <>
      <h2 className="po-section-title">{t('step3_title')}</h2>
      <p className="po-section-subtitle">
        {t('step3_subtitle')}
      </p>
      <div className="s3-privacy-note" role="note">
        <InfoIcon />
        <span>{t('step3_privacy_note', 'Content is processed from your provider during analysis. Agentys Cloud does not store email bodies or attachments; only the necessary profiles, rules and states are retained.')}</span>
      </div>

      <LearningProgressScreen
        progress={progressWithStall}
        onRetry={billingRequired ? undefined : handleRetry}
        onSkipPartial={
          billingRequired
            ? onContinueFree
            : progressWithStall.error && progressWithStall.error !== 'reauth_required'
              ? handleSkipPartial
              : undefined
        }
        skipPartialLabel={
          billingRequired
            ? t('progress_continue_free', 'Continuer en mode gratuit')
            : undefined
        }
        title=""
        subtitle=""
        isActive={progress.isActive && !stalledError}
      />

      {/* Soft stall banner: shows after ~2 min with no observable progress
          while the run is still flagged active. The hard ``stalledError``
          path above triggers later (6 min) and replaces the spinner with a
          terminal error screen — this banner is its early, dismissable
          counterpart. Auto-disappears the moment progress resumes (the
          isStalled flag in the hook is reset on any progress update). */}
      {progress.isActive && isStalled && !stalledError && (
        <div
          role="status"
          style={{
            margin: '12px 0',
            padding: '12px 16px',
            borderRadius: 8,
            background: 'var(--surface-2, rgba(255, 200, 0, 0.08))',
            border: '1px solid var(--border-warning, rgba(255, 200, 0, 0.4))',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 12,
            flexWrap: 'wrap',
          }}
        >
          <span style={{ fontSize: 14, color: 'var(--text-secondary)' }}>
            {t('step3_stalled_banner', "L'analyse semble bloquée. Vous pouvez la relancer.")}
          </span>
          <button
            className="po-btn-secondary"
            onClick={handleRetry}
            style={{ whiteSpace: 'nowrap' }}
          >
            {t('step3_stalled_retry', 'Réessayer')}
          </button>
        </div>
      )}

      {progress.isActive && !stalledError && (
        <>
          <ScanNarrator
            progress={progress}
            elapsedSeconds={elapsedSeconds}
            isActive={progress.isActive}
          />
          {/* Rolling narrative feed — surfaces real findings from each
              agent's output so the user feels the AI actually learning
              them (not just a spinner). Hidden when empty so there's no
              blank reservation until the first discovery lands. */}
          <DiscoveryFeed discoveries={progress.discoveries} />
        </>
      )}

    </>
  )
}
