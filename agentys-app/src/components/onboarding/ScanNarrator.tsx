import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import type { LearningProgress, AgentSteps } from '../../types/onboarding'
import './ScanNarrator.css'

interface ScanNarratorProps {
  progress: LearningProgress
  elapsedSeconds: number
  isActive: boolean
}

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return s > 0 ? `${m}m ${s}s` : `${m}m`
}

// Priorité: le step running "en tête" de la narration quand plusieurs tournent
// en parallèle (orchestrateur). `knowledge` retiré : l'agent tourne toujours
// en backend pour alimenter contacts/règles/projets, mais il n'est plus
// exposé comme pilier visible (aligné avec ONBOARDING_PILLARS de Step3TrainAI).
const STEP_PRIORITY: (keyof AgentSteps)[] = ['style', 'profile', 'label']

function derivePhaseKey(progress: LearningProgress, isActive: boolean): string {
  const { agentSteps, currentStep, emailsTotal } = progress

  if (!isActive) return 'scan_phase_idle'

  // 1) Le dernier step `running` signalé par le backend est prioritaire
  if (currentStep && agentSteps[currentStep] === 'running') {
    return `scan_phase_${currentStep}`
  }

  // 2) Sinon, premier step running dans l'ordre narratif
  const running = STEP_PRIORITY.find((k) => agentSteps[k] === 'running')
  if (running) return `scan_phase_${running}`

  // 3) Tous complétés mais encore actif → finalisation (merge KB, auto-label).
  //    On check UNIQUEMENT les 3 piliers visibles (`knowledge` caché mais
  //    pourrait failover en `partial` → ne doit pas bloquer la phrase de fin).
  const allCompleted = (['profile', 'style', 'label'] as const).every(
    (k) => agentSteps[k] === 'completed'
  )
  if (allCompleted) return 'scan_phase_finishing'

  // 4) Rien n'a encore bougé. Total connu = sync en cours côté backend
  //    (onboarding:waiting_for_sync incrémente emailsProcessed → emailsTotal
  //    pendant la synchro Gmail). Total inconnu = initialisation.
  if (emailsTotal > 0) return 'scan_phase_syncing'
  return 'scan_phase_initializing'
}

/**
 * Phrases génériques qu'on SAIT être des placeholders backend peu informatifs.
 * Quand `currentPhase` contient ça, on préfère le fallback i18n par step.
 */
const GENERIC_PHASE_MESSAGES = new Set([
  '',
  'Initialisation...',
  'Démarrage de l\'analyse...',
  'Analyse en cours...',
])

function isRichBackendPhase(currentPhase: string | undefined): boolean {
  if (!currentPhase) return false
  const trimmed = currentPhase.trim()
  if (GENERIC_PHASE_MESSAGES.has(trimmed)) return false
  // Un message backend "riche" a au moins ~12 caractères et n'est pas juste un step nu.
  return trimmed.length >= 12
}

export function ScanNarrator({ progress, elapsedSeconds, isActive }: ScanNarratorProps) {
  const { t } = useTranslation('onboarding')

  const phaseKey = useMemo(() => derivePhaseKey(progress, isActive), [progress, isActive])

  // Pendant les phases non-agent (initialisation, récupération sent cache, sync),
  // le step-based phaseKey reste générique. Si le backend émet un message riche
  // via `phase_key` (i18n stable) ou `phase` (legacy), on l'affiche à la place —
  // évite le "Initialisation de l'analyse..." figé pendant 60-90s alors que le
  // backend fait quelque chose de précis.
  //
  // Preference order when overriding the generic phase:
  //   1. backend `currentPhaseKey` re-translated on every render (survives
  //      language switch mid-flow)
  //   2. backend `currentPhase` (legacy string, already translated at event
  //      time — stale if user switched locale after emission)
  const shouldUseBackendPhrase = useMemo(() => {
    if (!isActive) return false
    const isGenericPhase = phaseKey === 'scan_phase_initializing' || phaseKey === 'scan_phase_idle'
    if (!isGenericPhase) return false
    if (progress.currentPhaseKey) return true
    return isRichBackendPhase(progress.currentPhase)
  }, [isActive, phaseKey, progress.currentPhase, progress.currentPhaseKey])

  const backendPhrase = useMemo(() => {
    if (!progress.currentPhaseKey) return progress.currentPhase
    const normalized = progress.currentPhaseKey.startsWith('onboarding.')
      ? progress.currentPhaseKey.slice('onboarding.'.length)
      : progress.currentPhaseKey
    const translated = t(normalized, progress.currentPhaseParams ?? {})
    if (translated && translated !== normalized) return translated
    return progress.currentPhase
  }, [progress.currentPhaseKey, progress.currentPhaseParams, progress.currentPhase, t])

  const displayedPhrase = shouldUseBackendPhrase ? backendPhrase : t(phaseKey)

  const batchLabel = useMemo(() => {
    const { batchCurrent = 0, batchTotal = 0 } = progress
    if (batchTotal <= 0 || batchCurrent <= 0) return null
    return t('scan_stats_batch', { current: batchCurrent, total: batchTotal })
  }, [progress, t])

  const confidenceLabel = useMemo(() => {
    const c = Math.round(progress.confidenceScore)
    if (c < 5) return null
    return t('scan_stats_confidence', { pct: c })
  }, [progress.confidenceScore, t])

  const contactsLabel = useMemo(() => {
    const n = progress.newContacts ?? 0
    if (n <= 0) return null
    return t('scan_stats_contacts', { count: n })
  }, [progress.newContacts, t])

  const rulesLabel = useMemo(() => {
    const n = progress.newRules ?? 0
    if (n <= 0) return null
    return t('scan_stats_rules', { count: n })
  }, [progress.newRules, t])

  const elapsedLabel = elapsedSeconds >= 5 ? formatElapsed(elapsedSeconds) : null

  const hasChip = batchLabel || confidenceLabel || contactsLabel || rulesLabel || elapsedLabel

  return (
    <div className="scan-narrator" role="status" aria-live="polite">
      <div className="scan-narrator-phase-wrap">
        <span className="scan-narrator-pulse" aria-hidden="true" />
        <p key={displayedPhrase} className="scan-narrator-phase">
          {displayedPhrase}
        </p>
      </div>

      {hasChip && (
        <div className="scan-narrator-chips">
          {batchLabel && <span className="scan-narrator-chip">{batchLabel}</span>}
          {contactsLabel && <span className="scan-narrator-chip scan-narrator-chip-discovery">{contactsLabel}</span>}
          {rulesLabel && <span className="scan-narrator-chip scan-narrator-chip-discovery">{rulesLabel}</span>}
          {confidenceLabel && <span className="scan-narrator-chip">{confidenceLabel}</span>}
          {elapsedLabel && (
            <span className="scan-narrator-chip scan-narrator-chip-elapsed">{elapsedLabel}</span>
          )}
        </div>
      )}
    </div>
  )
}
