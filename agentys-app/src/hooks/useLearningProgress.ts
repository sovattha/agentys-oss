import { useState, useEffect, useCallback, useRef } from 'react'
import i18n from '../i18n'
import { getWebSocketClient, type WebSocketEvent } from '../services/websocket'
import { getAuthHeaders, handleAuthResponse } from '../services/authToken'
import type { LearningProgress, LearningInsights, LearningActivity, AgentSteps, AgentStepStatus, Discovery } from '../types/onboarding'

// Newest discoveries kept in state. Older ones are discarded — the
// DiscoveryFeed only renders the last few anyway, and keeping arbitrary
// history would bloat the progress state between re-renders.
const DISCOVERY_CAP = 30
import { API_URL } from '../config'

function translateOnboardingKey(
  key: string | undefined,
  params: Record<string, unknown> | undefined,
  fallback: string | undefined,
): string {
  if (key && typeof key === 'string') {
    const normalized = key.startsWith('onboarding.')
      ? key.slice('onboarding.'.length)
      : key
    const translated = i18n.t(normalized, {
      ns: 'onboarding',
      ...(params ?? {}),
    } as Record<string, unknown>)
    if (translated && translated !== normalized) return translated
  }
  return fallback ?? ''
}

// Translate a backend-emitted phase string. Prefers phase_key (stable i18n key)
// when present so the UI reflects the user's chosen language; falls back to
// the legacy phase string for backward compatibility.
// Resolves against the `onboarding` namespace explicitly because defaultNS is
// `common`, which doesn't contain scan_phase_* entries. Accepts both bare keys
// (`scan_phase_X`) and legacy `onboarding.scan_phase_X` form.
function translatePhase(
  key: string | undefined,
  params: Record<string, unknown> | undefined,
  fallback: string | undefined,
): string {
  return translateOnboardingKey(key, params, fallback)
}

const INITIAL_STEPS: AgentSteps = {
  profile: 'pending',
  style: 'pending',
  knowledge: 'pending',
  label: 'pending',
}

const INITIAL_PROGRESS: LearningProgress = {
  isActive: false,
  emailsProcessed: 0,
  emailsTotal: 0,
  patterns: [],
  confidenceScore: 0,
  currentPhase: '',
  currentPhaseKey: null,
  currentPhaseParams: null,
  agentSteps: { ...INITIAL_STEPS },
  error: null,
  currentStep: null,
  batchCurrent: 0,
  batchTotal: 0,
  newContacts: 0,
  newRules: 0,
  discoveries: [],
}

const INITIAL_INSIGHTS: LearningInsights = {
  profile: null,
  knowledge: null,
  rules: null,
  categories: null,
  emailsAnalysed: 0,
  ready: false,
}

const INITIAL_ACTIVITY: LearningActivity = {
  lastCorrectionAt: null,
  eventsSinceRefresh: 0,
  threshold: 10,
  isRefreshing: false,
  hasNewLearning: false,
  lastRefreshAt: null,
}

export function useLearningProgress() {
  const [progress, setProgress] = useState<LearningProgress>(INITIAL_PROGRESS)
  const [insights, setInsights] = useState<LearningInsights>(INITIAL_INSIGHTS)
  const [learningActivity, setLearningActivity] = useState<LearningActivity>(INITIAL_ACTIVITY)
  // OB-R6 (audit 2026-04-25 onboarding-residual): timestamp of the
  // most recent WebSocket update that touched per-agent state. The
  // 4 s HTTP polling uses this to back off from agentSteps writes when
  // a fresher WS event has just arrived — the existing `anyStepActive`
  // guard at the polling site already handles the common case but a
  // window between WS push and React state flush could let the polling
  // overwrite an in-flight `running → completed` transition. The ref is
  // only ever updated, never read by render, so it doesn't trigger
  // re-renders.
  const lastWsAgentTouchAt = useRef<number>(0)

  // Stall detection : Date.now() at which the onboarding last made
  // observable progress (emails count went up, agent step transitioned).
  // Reset on every fresh start. Read by a 1s ticker that flips the
  // ``isStalled`` flag when no progress has been seen for STALE_THRESHOLD_MS
  // while the run is still flagged active. Powers the "Réessayer" button
  // in OnboardingContainer — backend watchdog will eventually flip the row
  // server-side too. Keep this above normal single-agent LLM latency: the
  // first-run pipeline can legitimately spend 60-90s inside one agent while
  // still making progress server-side.
  const STALE_THRESHOLD_MS = 120_000
  const lastProgressAt = useRef<number>(Date.now())
  const [isStalled, setIsStalled] = useState<boolean>(false)

  // Bump the progress timestamp whenever a meaningful field moves. The
  // dependency array intentionally references object-typed fields by
  // reference: every setProgress already produces a new object, so this
  // resets the stall timer on every real update. Marking inactive resets
  // the stall flag so a new run starts clean.
  useEffect(() => {
    if (progress.isActive) {
      lastProgressAt.current = Date.now()
      setIsStalled(false)
    } else {
      setIsStalled(false)
    }
  }, [progress.isActive, progress.emailsProcessed, progress.emailsTotal, progress.agentSteps])

  // Stall ticker: while the run is active, watch the elapsed time since
  // the last bump. Flip ``isStalled`` once the user has been waiting on a
  // motionless UI for STALE_THRESHOLD_MS. Stops as soon as the run leaves
  // the active state — error/completed/cancelled all clear it.
  useEffect(() => {
    if (!progress.isActive) {
      setIsStalled(false)
      return
    }
    const tick = setInterval(() => {
      if (Date.now() - lastProgressAt.current > STALE_THRESHOLD_MS) {
        setIsStalled(true)
      }
    }, 2000)
    return () => clearInterval(tick)
  }, [progress.isActive])

  const fetchInsights = useCallback(async (accountId: number) => {
    try {
      const response = handleAuthResponse(await fetch(`${API_URL}/api/onboarding/insights?account_id=${accountId}`, {
        headers: { ...getAuthHeaders() },
      }))
      if (response.ok) {
        const data = await response.json()
        setInsights({
          profile: data.profile || null,
          knowledge: data.knowledge || null,
          rules: data.rules || null,
          categories: data.categories || null,
          emailsAnalysed: data.emails_analysed || 0,
          ready: true,
        })
      }
    } catch {
      // Insights will be retried
    }
  }, [])

  // Fetch initial learning status from backend
  const fetchLearningStatus = useCallback(async () => {
    try {
      const response = handleAuthResponse(await fetch(`${API_URL}/api/onboarding/learning-status`, {
        headers: { ...getAuthHeaders() },
      }))
      if (response.ok) {
        const data = await response.json()
        setLearningActivity(prev => ({
          ...prev,
          eventsSinceRefresh: data.event_counter ?? prev.eventsSinceRefresh,
          threshold: data.threshold ?? prev.threshold,
          lastRefreshAt: data.last_refresh_at ?? prev.lastRefreshAt,
        }))
      }
    } catch {
      // Will be retried on next mount
    }
  }, [])

  useEffect(() => {
    fetchLearningStatus()
  }, [fetchLearningStatus])

  // Subscribe to onboarding + learning WebSocket events from /daemon namespace
  useEffect(() => {
    const ws = getWebSocketClient()

    const unsubscribe = ws.subscribe((event: WebSocketEvent) => {
      const eventType = event.type as string

      if (eventType === 'onboarding:learning_started') {
        const data = event.data as Record<string, unknown>
        setProgress({
          isActive: true,
          emailsProcessed: 0,
          emailsTotal: (data.total_emails as number) || 0,
          patterns: [],
          confidenceScore: 0,
          currentPhase: 'Analyse en cours...',
          agentSteps: { ...INITIAL_STEPS },
          error: null,
          // Reset the discovery feed on a fresh start — a previous failed
          // attempt shouldn't leak its findings into the new run.
          discoveries: [],
        })
      } else if (eventType === 'onboarding:waiting_for_sync') {
        // Backend is waiting for the initial email sync to finish before
        // running the analysis. Reuse emailsTotal/emailsProcessed to surface
        // the sync progress in the existing progress bar UI.
        const data = event.data as Record<string, unknown>
        const current = (data.current as number) ?? 0
        const target = (data.target as number) ?? 15
        setProgress(prev => ({
          ...prev,
          isActive: true,
          emailsProcessed: current,
          emailsTotal: target,
          // Phase i18n key explicite : sans ça, ScanNarrator voit un
          // emailsTotal>0 sans phase clé et retombe sur le currentPhase
          // générique "Initialisation..." hérité de startLearning.
          currentPhaseKey: 'scan_phase_syncing',
          currentPhaseParams: null,
          // Keep agent steps as 'pending' while we wait — analysis hasn't started yet
          agentSteps: { ...INITIAL_STEPS },
          error: null,
        }))
      } else if (eventType === 'onboarding:progress_updated') {
        const data = event.data as Record<string, unknown>
        const step = data.step as string | undefined
        const stepStatus = data.step_status as string | undefined
        // OB-R6: stamp the WS-touch timestamp BEFORE the setProgress call
        // so the polling's stale-protection check (below) sees it on its
        // next iteration regardless of React's state-flush ordering.
        if (step && step !== 'all' && step !== 'error') {
          lastWsAgentTouchAt.current = Date.now()
        }
        setProgress(prev => {
          const newSteps = { ...prev.agentSteps }
          if (step && step !== 'all' && step !== 'error' && step in newSteps) {
            newSteps[step as keyof AgentSteps] = (stepStatus as AgentStepStatus) || 'running'
          }
          // Capture le step actif pour alimenter la narration : on le garde si
          // stepStatus === 'running', sinon on retombe sur la valeur précédente
          // (évite de perdre le contexte narratif entre deux events).
          const isRunning = stepStatus === 'running' || !stepStatus
          const nextStep = (step && isRunning && step in newSteps)
            ? (step as keyof AgentSteps)
            : prev.currentStep ?? null
          // Compteurs de découvertes — pris du backend quand disponibles,
          // sinon on garde la valeur max connue (les events antérieurs ont pu
          // pousser un compte plus élevé qu'un event ultérieur qui n'envoie pas
          // le champ).
          const nextContacts = (data.new_contacts as number) ?? prev.newContacts ?? 0
          const nextRules = (data.new_rules as number) ?? prev.newRules ?? 0
          const phaseKey = (data.phase_key as string | undefined) ?? undefined
          const phaseParams = (data.phase_params as Record<string, unknown> | undefined) ?? undefined
          const translatedPhase = translatePhase(
            phaseKey,
            phaseParams,
            data.phase as string | undefined,
          )
          return {
            ...prev,
            isActive: true,
            emailsProcessed: (data.emails_processed as number) ?? prev.emailsProcessed,
            emailsTotal: (data.total as number) ?? prev.emailsTotal,
            confidenceScore: (data.confidence as number) ?? prev.confidenceScore,
            currentPhase: translatedPhase || prev.currentPhase,
            currentPhaseKey: phaseKey ?? prev.currentPhaseKey ?? null,
            currentPhaseParams: phaseParams ?? prev.currentPhaseParams ?? null,
            agentSteps: newSteps,
            currentStep: nextStep,
            batchCurrent: (data.batch_current as number) ?? prev.batchCurrent,
            batchTotal: (data.batch_total as number) ?? prev.batchTotal,
            newContacts: Math.max(nextContacts, prev.newContacts ?? 0),
            newRules: Math.max(nextRules, prev.newRules ?? 0),
          }
        })
      } else if (eventType === 'onboarding:discovery') {
        // Narrative findings from the agent pipeline — one event per
        // wow moment (signature found, top contact identified, etc).
        // Stored in a capped rolling buffer that the DiscoveryFeed
        // component animates in/out.
        const data = event.data as Record<string, unknown>
        const messageKey = String(data.message_key ?? '')
        if (!messageKey) return
        const kindRaw = String(data.kind ?? 'finding')
        const kind: Discovery['kind'] =
          kindRaw === 'starting' || kindRaw === 'insight' ? kindRaw : 'finding'
        const agentRaw = String(data.agent ?? '')
        const agent: Discovery['agent'] =
          agentRaw === 'profile' || agentRaw === 'knowledge' ||
          agentRaw === 'style' || agentRaw === 'label'
            ? agentRaw
            : ''
        const timestampMs = Number(data.timestamp_ms ?? Date.now())
        const discovery: Discovery = {
          kind,
          agent,
          messageKey,
          messageParams: (data.message_params as Record<string, unknown>) || {},
          fallbackMessage: String(data.fallback_message ?? ''),
          timestampMs,
          id: `${messageKey}-${timestampMs}`,
        }
        setProgress(prev => {
          const next = [...prev.discoveries, discovery]
          // Drop the oldest if we exceed the cap (cheap circular buffer).
          const overflow = next.length - DISCOVERY_CAP
          return {
            ...prev,
            discoveries: overflow > 0 ? next.slice(overflow) : next,
          }
        })
      } else if (eventType === 'onboarding:learning_completed') {
        // OB-R6: completion event also touches agentSteps.
        lastWsAgentTouchAt.current = Date.now()
        const data = event.data as Record<string, unknown>
        const status = data.status as string
        const failed = status === 'failed'
        const partial = status === 'partial'
        setProgress(prev => {
          const newSteps = { ...prev.agentSteps }
          if (failed) {
            // Total failure: mark all non-completed steps as failed
            for (const key of Object.keys(newSteps) as (keyof AgentSteps)[]) {
              if (newSteps[key] !== 'completed') {
                newSteps[key] = 'failed'
              }
            }
          } else if (partial) {
            // Partial: mark still-running steps as failed, keep completed ones
            for (const key of Object.keys(newSteps) as (keyof AgentSteps)[]) {
              if (newSteps[key] === 'running' || newSteps[key] === 'pending') {
                newSteps[key] = 'failed'
              }
            }
          }
          const errorKey = (data.error_key as string | undefined) ?? undefined
          const errorParams = (data.error_params as Record<string, unknown> | undefined) ?? undefined
          const fallbackError = (data.error as string) || 'Erreur inconnue'
          const translatedError = translateOnboardingKey(errorKey, errorParams, fallbackError)
          return {
            ...prev,
            isActive: false,
            confidenceScore: failed ? prev.confidenceScore : (partial ? prev.confidenceScore : 100),
            emailsProcessed: (data.emails_analysed as number) ?? prev.emailsProcessed,
            currentPhase: failed ? i18n.t('common:analysis_failed') : (partial ? i18n.t('common:analysis_partial') : i18n.t('common:analysis_complete')),
            agentSteps: newSteps,
            error: (failed || partial) ? translatedError : null,
          }
        })
      } else if (eventType === 'onboarding:insights_generated') {
        // Insights summary from WebSocket — full data fetched via API
      } else if (eventType === 'learning:correction_recorded') {
        const data = event.data as Record<string, unknown>
        setLearningActivity(prev => ({
          ...prev,
          lastCorrectionAt: new Date().toISOString(),
          eventsSinceRefresh: prev.eventsSinceRefresh + 1,
          hasNewLearning: (data.had_correction as boolean) || prev.hasNewLearning,
        }))
      } else if (eventType === 'learning:label_corrected') {
        setLearningActivity(prev => ({
          ...prev,
          lastCorrectionAt: new Date().toISOString(),
          eventsSinceRefresh: prev.eventsSinceRefresh + 1,
          hasNewLearning: true,
        }))
      } else if (eventType === 'learning:analysis_completed') {
        setLearningActivity(prev => ({
          ...prev,
          hasNewLearning: true,
        }))
      } else if (eventType === 'learning:refresh_completed') {
        const data = event.data as Record<string, unknown>
        setLearningActivity(prev => ({
          ...prev,
          isRefreshing: false,
          eventsSinceRefresh: 0,
          hasNewLearning: true,
          lastRefreshAt: new Date().toISOString(),
        }))
        // Auto-refresh insights après un KB refresh
        const accountId = data.account_id as number
        if (accountId) {
          fetchInsights(accountId)
        }
      }
    })

    return unsubscribe
  }, [fetchInsights])

  const waitForSyncReady = useCallback(async (
    onPhaseUpdate: (phase: string) => void,
    timeoutMs = 30_000,
    pollIntervalMs = 3_000,
    accountId?: number,
  ): Promise<{ needsReauth: boolean }> => {
    // Ne bloque QUE si un sync est activement en cours. Sur un compte fresh
    // qui n'a jamais synchronisé, last_sync_at est null — attendre `hasSynced`
    // boucle tout le timeout. Le backend gère déjà le cas "pas assez d'emails"
    // via _wait_for_sync_then_run (5 min de patience côté serveur).
    // Tous les chemins de sortie (503, 4xx, network error, pas de sync actif)
    // déclenchent un return immédiat — pas de polling aveugle.
    const deadline = Date.now() + timeoutMs
    while (Date.now() < deadline) {
      try {
        const res = await fetch(`${API_URL}/api/sync/status`, {
          headers: { ...getAuthHeaders() },
        })
        if (!res.ok) {
          // Sync service pas initialisé (503) ou compte non autorisé (401/403) :
          // inutile d'attendre, le backend lancera malgré tout l'analyse.
          return { needsReauth: false }
        }
        const data = await res.json()
        const status = data?.status
        // Circuit breaker : si le backend signale que le compte est en auth
        // backoff (OAuth révoqué), inutile d'attendre — on remonte l'info au
        // caller pour qu'il affiche "Reconnectez votre compte" au lieu d'un
        // spinner "Loading..." infini (5+ min).
        const reauthIds: number[] = Array.isArray(status?.reauth_required_account_ids)
          ? status.reauth_required_account_ids
          : []
        if (accountId && reauthIds.includes(accountId)) {
          return { needsReauth: true }
        }
        const isSyncing = status?.is_syncing === true
        if (!isSyncing) return { needsReauth: false }
        onPhaseUpdate('Synchronisation Gmail en cours...')
      } catch {
        // Sync service injoignable → on passe immédiatement à l'onboarding
        return { needsReauth: false }
      }
      await new Promise(resolve => setTimeout(resolve, pollIntervalMs))
    }
    return { needsReauth: false }
  }, [])

  const startLearning = useCallback(async (
    accountId: number,
    userEmail: string,
    faqEntries?: Array<{ question: string; answer: string }>,
  ): Promise<{ ok: boolean; status?: string; error?: string }> => {
    // Visual feedback immédiat : le premier step tourne dès l'init pour
    // éviter l'impression de freeze pendant l'attente de sync + POST /start.
    setProgress({
      ...INITIAL_PROGRESS,
      isActive: true,
      currentPhase: 'Initialisation...',
      agentSteps: { ...INITIAL_STEPS, profile: 'running' },
    })
    setInsights(INITIAL_INSIGHTS)

    const syncResult = await waitForSyncReady(() => {}, 30_000, 3_000, accountId)
    if (syncResult.needsReauth) {
      const errorMsg = 'reauth_required'
      setProgress(prev => ({
        ...prev,
        isActive: false,
        agentSteps: { ...INITIAL_STEPS },
        error: errorMsg,
      }))
      return { ok: false, error: errorMsg }
    }

    setProgress(prev => ({ ...prev, currentPhase: 'Démarrage de l\'analyse...' }))

    try {
      const response = handleAuthResponse(await fetch(`${API_URL}/api/onboarding/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({
          account_id: accountId,
          user_email: userEmail,
          max_emails: 250,
          ...(faqEntries && faqEntries.length > 0 ? { faq_entries: faqEntries } : {}),
        }),
      }))
      if (!response.ok) {
        const err = await response.json().catch(() => ({ error: 'Erreur inconnue' }))
        const errorMsg = err.error_code === 'BILLING_REQUIRED'
          ? 'billing_required'
          : err.error || i18n.t('common:analysis_start_error')
        setProgress(prev => ({
          ...prev,
          isActive: false,
          agentSteps: { ...INITIAL_STEPS },
          error: errorMsg,
        }))
        return { ok: false, error: errorMsg }
      }
      const data = await response.json().catch(() => ({}))
      const status = (data?.status as string) || 'started'
      // Backend confirme que la row DB existe et le thread est spawné.
      // Phase plus lisible pour l'utilisateur.
      setProgress(prev => ({
        ...prev,
        currentPhase: 'Analyse en cours...',
      }))
      return { ok: true, status }
    } catch {
      const errorMsg = 'Impossible de contacter le serveur'
      setProgress(prev => ({
        ...prev,
        isActive: false,
        agentSteps: { ...INITIAL_STEPS },
        error: errorMsg,
      }))
      return { ok: false, error: errorMsg }
    }
  }, [waitForSyncReady])

  const clearNewLearning = useCallback(() => {
    setLearningActivity(prev => ({ ...prev, hasNewLearning: false }))
  }, [])

  // isActive ref for polling — avoids stale closure issues
  const isActiveRef = useRef(false)
  useEffect(() => {
    isActiveRef.current = progress.isActive
  }, [progress.isActive])

  const startStatusPolling = useCallback((accountId: number, onServerAlive?: () => void) => {
    // Eager-start UX gap: when Step3TrainAI mounts with
    // `learningAlreadyStarted=true`, it skips its own startLearning() and
    // calls startStatusPolling() directly. The inner useLearningProgress
    // instance is separate from the outer one (PremiumOnboarding) that
    // actually fired startLearning, so its progress state is INITIAL_PROGRESS
    // (isActive=false, all steps pending) until the FIRST poll response
    // lands ~1-3 s later. The user sees "0% Loading…" with three empty
    // circles during that window. Flip isActive=true and put the visible
    // pillars in `running` immediately so the UI reflects "we're working"
    // from frame 0; the first poll response will refine the actual state.
    setProgress(prev => {
      // Only override when state is still pristine — never clobber a
      // poll/WS update that already arrived (would briefly visualise a
      // step regression from completed → running).
      const allPending = (Object.values(prev.agentSteps) as AgentStepStatus[])
        .every(s => s === 'pending')
      if (!allPending) return prev
      return {
        ...prev,
        isActive: true,
        agentSteps: {
          profile: 'running',
          style: 'running',
          knowledge: 'running',
          label: 'running',
        },
      }
    })

    let stopped = false
    // `unmounted` est distinct de `stopped` : le polling peut s'arrêter
    // (status=completed → stopped=true) SANS que le composant soit démonté.
    // La cascade de reveal doit continuer à fire après l'arrêt du polling.
    // Seul un vrai unmount doit annuler les setProgress en cours.
    let unmounted = false
    let serverAliveNotified = false
    // IDs des setTimeouts de cascade "analyse terminée trop vite" — doivent
    // être clearés si l'utilisateur navigue avant la fin de la cascade (1.4s).
    // Sans ça, setProgress() est appelé sur un composant démonté → warning React.
    const cascadeTimeouts: ReturnType<typeof setTimeout>[] = []
    // Garde-fous pour stopper un polling orphelin (compte supprimé par l'UI
    // de reset, onglet laissé ouvert après reset, etc.). Sans ça, le
    // setInterval hammer le backend pour toujours — cause observée :
    // logs backend remplis de /api/onboarding/status?account_id=X → 404
    // à chaque 4s après un reset, jusqu'à fermeture manuelle de l'onglet.
    let consecutiveAccountNotFound = 0  // 404
    let consecutiveNotStarted = 0        // 200 { status: 'not_started' }
    // 5xx burst handling: skip polling slots while the backend is
    // restarting/crashing. A naïve `if (!response.ok) return` keeps the
    // 4 s setInterval firing into a dead backend, which paints a wall of
    // ~12 red 500 entries in devtools per restart window (~45 s observed)
    // and uselessly contests the Vite proxy. We instead track consecutive
    // 5xx and skip the next N intervals, doubling up to a 30 s cap.
    let consecutive5xx = 0
    let skipUntilTick = 0
    let pollTickCounter = 0
    const MAX_ACCOUNT_NOT_FOUND = 8       // ~32s avant arrêt → compte vraiment disparu
    // OB-C-5 (audit 2026-04-25 onboarding-flawless) : raised from 3 → 8.
    // The backend POST /start can take >1 s to commit the row on a slow
    // SQLite (Railway cold start, big migration), and the polling used
    // to give up after ~12 s of 404 — leaving a frozen spinner on every
    // slow-start onboarding. 8 retries × 4 s ≈ 32 s of patience covers
    // the worst observed cold-start without hammering forever.
    const MAX_NOT_STARTED = 30            // ~2min avant arrêt → onboarding jamais démarré
    // Initial delay court (1s) : le /start a déjà confirmé que la row existe,
    // donc inutile d'attendre 5s avant le premier poll — on évite les 404.
    const initialDelay = setTimeout(() => {
      if (stopped) return
      const intervalId = setInterval(async () => {
        if (stopped) {
          clearInterval(intervalId)
          return
        }
        // Backend restart back-off: skip this tick while we're still
        // inside the cooldown window from a previous 5xx burst. Avoids
        // hammering a backend that's mid-restart.
        pollTickCounter += 1
        if (pollTickCounter < skipUntilTick) return
        try {
          const response = handleAuthResponse(await fetch(`${API_URL}/api/onboarding/status?account_id=${accountId}`, {
            headers: { ...getAuthHeaders() },
          }))
          // JWT expired/missing → App.tsx will logout (via auth:unauthorized).
          // Stop polling so we don't hammer the backend during the redirect.
          if (response.status === 401) {
            stopped = true
            clearInterval(intervalId)
            return
          }
          // 404 : compte introuvable (typiquement après un reset). On tolère
          // quelques retries (race condition au démarrage), puis on arrête.
          if (response.status === 404) {
            consecutiveAccountNotFound += 1
            if (consecutiveAccountNotFound >= MAX_ACCOUNT_NOT_FOUND) {
              stopped = true
              clearInterval(intervalId)
            }
            return
          }
          consecutiveAccountNotFound = 0
          // 5xx (typically Vite proxy reporting a backend that's down or
          // restarting): exponential skip. After each 5xx we wait 2,4,8...
          // ticks (= 8s, 16s, 32s) before retrying, capped at ~30s. The
          // first 200 reception resets the counter to 0.
          if (response.status >= 500) {
            consecutive5xx += 1
            const skipTicks = Math.min(2 ** consecutive5xx, 8)  // cap at 8 ticks ≈ 32s
            skipUntilTick = pollTickCounter + skipTicks
            return
          }
          consecutive5xx = 0
          if (!response.ok) return
          // Any valid 200 response proves the server is running — cancel stall timer once
          if (!serverAliveNotified) {
            serverAliveNotified = true
            onServerAlive?.()
          }
          const data = await response.json()
          const status = data.status as string
          // 200 { status: 'not_started' } : le compte existe mais aucune
          // session d'onboarding n'a été démarrée. Normal quelques secondes
          // (le client a pu arriver avant que POST /start soit persisté),
          // mais si ça dure trop, c'est un flow cassé → arrêt.
          if (status === 'not_started') {
            consecutiveNotStarted += 1
            if (consecutiveNotStarted >= MAX_NOT_STARTED) {
              stopped = true
              clearInterval(intervalId)
            }
            return
          }
          consecutiveNotStarted = 0
          if (status === 'completed') {
            stopped = true
            clearInterval(intervalId)
            // Si aucun step n'a été vu progresser (analyse trop rapide ou WS
            // absent), animer les 4 steps en cascade pour donner une sensation
            // de progression honnête au lieu d'un saut direct en vert.
            setProgress(prev => {
              const alreadyDone = Object.values(prev.agentSteps).every(s => s === 'completed')
              if (alreadyDone) return prev
              const anyCompleted = Object.values(prev.agentSteps).some(s => s === 'completed')
              const emailsAnalysed = (data.emails_analysed as number) || prev.emailsTotal
              if (!anyCompleted) {
                // Cascade sur les 3 piliers visibles uniquement — `knowledge`
                // est hors-UI mais son state backend est déjà à jour via WS events.
                // IDs capturés dans cascadeTimeouts pour pouvoir clear sur unmount.
                const cascadeSteps: (keyof AgentSteps)[] = ['profile', 'style', 'label']
                cascadeSteps.forEach((key, idx) => {
                  const id = setTimeout(() => {
                    if (unmounted) return
                    const isLast = idx === cascadeSteps.length - 1
                    setProgress(curr => ({
                      ...curr,
                      agentSteps: { ...curr.agentSteps, [key]: 'completed' },
                      emailsProcessed: emailsAnalysed,
                      emailsTotal: emailsAnalysed,
                      currentPhase: isLast ? i18n.t('common:analysis_complete') : curr.currentPhase,
                      isActive: !isLast,
                      // OB-R2 (audit 2026-04-25 onboarding-residual): bump
                      // the score to 100 on the final cascade tick so the
                      // OnboardingContainer auto-transition effect (which
                      // gates on `confidenceScore >= 100 && !isActive`)
                      // fires even when the WebSocket `learning_completed`
                      // event was lost (network drop at the wrong moment).
                      // Without this the user stayed on "Analyse terminée"
                      // indefinitely while the backend pipeline had
                      // already produced insights.
                      confidenceScore: isLast ? 100 : curr.confidenceScore,
                    }))
                  }, (idx + 1) * 350)
                  cascadeTimeouts.push(id)
                })
                return {
                  ...prev,
                  agentSteps: {
                    profile: 'running',
                    style: 'running',
                    knowledge: prev.agentSteps.knowledge,
                    label: 'running',
                  },
                  emailsTotal: emailsAnalysed,
                  emailsProcessed: emailsAnalysed,
                }
              }
              return {
                ...prev,
                isActive: false,
                emailsTotal: emailsAnalysed,
                emailsProcessed: emailsAnalysed,
                currentPhase: i18n.t('common:analysis_complete'),
                agentSteps: {
                  profile: 'completed',
                  style: 'completed',
                  knowledge: 'completed',
                  label: 'completed',
                },
                // OB-R2: same fallback as the cascade path — drive
                // confidenceScore to 100 so the consumer effect picks up
                // completion even when the WS event was missed.
                confidenceScore: 100,
                error: null,
              }
            })
          } else if (status === 'partial') {
            // OB-R2: also handle the partial completion path. Pre-fix
            // the polling had no branch for status="partial" and the
            // user could be stuck on "in progress" forever when the
            // pipeline finished partial without a WS push.
            stopped = true
            clearInterval(intervalId)
            setProgress(prev => ({
              ...prev,
              isActive: false,
              confidenceScore: 100,
              emailsTotal: (data.emails_analysed as number) || prev.emailsTotal,
              emailsProcessed: (data.emails_analysed as number) || prev.emailsProcessed,
              error: (data.error_message as string) || i18n.t('common:analysis_partial'),
            }))
          } else if (status === 'failed') {
            stopped = true
            clearInterval(intervalId)
            setProgress(prev => ({
              ...prev,
              isActive: false,
              error: (data.error_message as string) || i18n.t('common:analysis_failed'),
            }))
          } else if (status === 'waiting_for_sync') {
            // Sync still in progress. Le WS event `onboarding:waiting_for_sync`
            // ne fire QU'à chaque changement de count — un reload de page le
            // rate et laisse l'UI figée sur "Initializing analysis...".
            // On alimente donc emailsProcessed/Total + currentPhaseKey depuis
            // le polling HTTP pour que ScanNarrator bascule sur
            // "Syncing your inbox..." même sans WS event reçu.
            const currentCount = (data.current_email_count as number | undefined) ?? 0
            const minRequired = (data.min_emails_required as number | undefined) ?? 15
            setProgress(prev => ({
              ...prev,
              isActive: true,
              emailsProcessed: currentCount,
              emailsTotal: Math.max(minRequired, prev.emailsTotal),
              currentPhaseKey: 'scan_phase_syncing',
              currentPhaseParams: null,
              error: null,
            }))
          } else if (status === 'running') {
            const emailsAnalysed = data.emails_analysed as number
            // WS prioritaire : si des steps ont déjà progressé via WebSocket,
            // on n'écrase jamais leur statut — on se contente de mettre à jour
            // le total d'emails. Sinon, on marque les 4 steps en running en
            // parallèle (l'orchestrateur les lance simultanément).
            //
            // OB-R6: belt-and-braces — also skip agentSteps writes when a
            // WS event touched the state in the last 6 s, even if the
            // current `prev` snapshot doesn't yet reflect it (rare React
            // batching edge case where setProgress scheduled by WS hasn't
            // flushed when polling runs).
            const wsRecentlyTouched = (Date.now() - lastWsAgentTouchAt.current) < 6_000
            setProgress(prev => {
              const anyStepActive = Object.values(prev.agentSteps).some(
                s => s === 'running' || s === 'completed'
              )
              const nextEmailsTotal =
                emailsAnalysed > 0 && emailsAnalysed > prev.emailsTotal
                  ? emailsAnalysed
                  : prev.emailsTotal
              if (anyStepActive || wsRecentlyTouched) {
                // Ne pas toucher agentSteps : le WS est la source de vérité.
                return {
                  ...prev,
                  isActive: true,
                  emailsTotal: nextEmailsTotal,
                }
              }
              return {
                ...prev,
                isActive: true,
                agentSteps: {
                  profile: 'running' as AgentStepStatus,
                  style: 'running' as AgentStepStatus,
                  knowledge: 'running' as AgentStepStatus,
                  label: 'running' as AgentStepStatus,
                },
                emailsTotal: nextEmailsTotal,
              }
            })
          }
          // status === 'pending': no-op, still waiting
        } catch {
          // Network error — polling will retry next interval
        }
      }, 4000)

      return () => {
        stopped = true
        unmounted = true
        clearInterval(intervalId)
        cascadeTimeouts.forEach(clearTimeout)
      }
    }, 1000)

    return () => {
      stopped = true
      unmounted = true
      clearTimeout(initialDelay)
      cascadeTimeouts.forEach(clearTimeout)
    }
  }, [])

  return { progress, insights, learningActivity, isStalled, startLearning, fetchInsights, clearNewLearning, fetchLearningStatus, startStatusPolling }
}
