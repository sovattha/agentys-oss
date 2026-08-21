import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { apiClient } from '../../services/api'
import { EditIcon } from '../icons/ActionIcons'
import './SurgicalEditBar.css'

export interface SurgicalEditBarProps {
  /** True quand la bar est visible. Permet l'animation enter/exit gérée
   *  côté parent par mount/unmount conditionnel. */
  isOpen: boolean
  body: string
  to?: string
  /** Voice — props passées par le useWhisperRecording du parent (instance
   *  unique partagée avec le toolbar). isRecording reflète l'état réel,
   *  onMicToggle = handleMicClick (start si idle, stop si recording).
   *  Le transcript final atterrit ici via setInstruction côté parent
   *  (qui regarde un flag isSurgicalEditOpenRef). */
  isRecording: boolean
  isTranscribing: boolean
  onMicToggle: () => void
  dictationEnabled?: boolean
  /** Texte courant + setter — lifté côté parent pour qu'il puisse y router
   *  les transcripts vocaux quand la bar est ouverte. */
  instruction: string
  setInstruction: (s: string) => void
  /** Appelé après un submit réussi. fastPath=true si find-replace JS pur
   *  (zéro LLM, instantané), false si appel /api/refine-text. */
  onSubmit: (modifiedBody: string, fastPath: boolean) => void
  onClose: () => void
}

/* ─── Fast-path : find-replace côté client ─────────────────────────────── */

function parseReplaceInstruction(s: string): { old: string; new: string } | null {
  const t = s.trim()
  // remplace/change/mets/substitue X par/en/avec Y
  const m1 = t.match(/^(?:remplace[rz]?|chang[er]z?|mets|mettre|substitu[er]z?)\s+(.+?)\s+(?:par|en|avec)\s+(.+?)\s*\.?$/i)
  if (m1?.[1] && m1?.[2]) {
    return { old: stripQuotes(m1[1]), new: stripQuotes(m1[2]) }
  }
  // mets Y à la place de X (ordre inversé)
  const m2 = t.match(/^(?:mets|mettre|place[rz]?)\s+(.+?)\s+(?:à\s+la\s+place\s+de|au\s+lieu\s+de)\s+(.+?)\s*\.?$/i)
  if (m2?.[1] && m2?.[2]) {
    return { old: stripQuotes(m2[2]), new: stripQuotes(m2[1]) }
  }
  return null
}

function stripQuotes(s: string): string {
  return s.replace(/^["«''`]|["»''`]$/g, '').trim()
}

function tryClientFastReplace(body: string, instruction: string): string | null {
  const parsed = parseReplaceInstruction(instruction)
  if (!parsed) return null
  const { old: oldStr, new: newStr } = parsed
  if (!oldStr || !newStr || oldStr === newStr) return null
  const plain = body.replace(/<[^>]*>/g, '')
  const occurrences = plain.split(oldStr).length - 1
  if (occurrences !== 1) return null
  return body.replace(oldStr, newStr)
}

/* ─── Component ────────────────────────────────────────────────────────── */

export function SurgicalEditBar({
  isOpen,
  body,
  to,
  isRecording,
  isTranscribing,
  onMicToggle,
  dictationEnabled = true,
  instruction,
  setInstruction,
  onSubmit,
  onClose,
}: SurgicalEditBarProps) {
  const { t } = useTranslation('compose')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const barRef = useRef<HTMLDivElement>(null)
  const spaceTriggeredRecordRef = useRef(false)

  // Click-outside : ferme la bar si l'utilisateur clique en dehors d'elle.
  // Équivalent UX au bouton X (qu'on a retiré pour minimalisme) et à Esc.
  // Skip pendant un recording (user est en train de dicter, ne pas
  // interrompre) et pendant un loading (LLM en cours, attendre la réponse).
  useEffect(() => {
    if (!isOpen) return
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as Node
      if (barRef.current?.contains(target)) return  // click dans la bar → ignorer
      if (isRecording || isTranscribing || loading) return  // pas pendant une action
      onClose()
    }
    // Léger délai pour éviter la fermeture immédiate due à l'event qui a
    // ouvert la bar (click sur "Modifier" dans la popup, par ex.)
    const id = setTimeout(() => {
      document.addEventListener('mousedown', handleClickOutside)
    }, 50)
    return () => {
      clearTimeout(id)
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [isOpen, isRecording, isTranscribing, loading, onClose])

  // Focus input à l'ouverture, reset state à la fermeture
  useEffect(() => {
    if (isOpen) {
      setError(null)
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 30)
    }
  }, [isOpen])

  // Reset error quand l'utilisateur tape (UX : error stale)
  useEffect(() => {
    if (error && instruction) setError(null)
  }, [instruction, error])

  const submit = async () => {
    const trimmed = instruction.trim()
    if (!trimmed || loading) return
    setError(null)

    // 1. Fast-path : find-replace JS pur si l'instruction match un pattern clair
    const fast = tryClientFastReplace(body, trimmed)
    if (fast !== null) {
      onSubmit(fast, true)
      return
    }

    // 2. LLM avec mode surgical
    setLoading(true)
    try {
      const res = await apiClient.refineText(
        body,
        trimmed,
        undefined,
        to?.trim() || undefined,
        { surgical: true },
      )
      if (!res.success || !res.refined_text?.trim()) {
        setError('Aucune modification appliquée. Essayez plus précis.')
        return
      }
      const refined = res.refined_text.trim()
      if (refined === body.trim()) {
        setError("L'IA n'a rien trouvé à changer. Précisez la modification.")
        return
      }
      onSubmit(refined, false)
    } catch (e) {
      // Backend renvoie 422 avec un message clair quand il détecte une
      // sur-édition (placeholder leak, nom propre disparu) — on l'affiche
      // verbatim, sans préfixer "Erreur" parce que c'est déjà actionnable.
      const msg = (e as Error)?.message || 'erreur inconnue'
      // ApiError throws with status — si c'est un 422 (validation), pas
      // besoin du préfixe. Sinon préfixer "Erreur" pour distinguer du
      // soft-fail "rien trouvé à changer".
      const isValidationError = /templater|supprimé|chirurgicale/i.test(msg)
      setError(isValidationError ? msg : `Erreur : ${msg}`)
    } finally {
      setLoading(false)
    }
  }

  /* Spacebar PTT — Hold Space (input vide) → start record. Release → stop.
     Le transcript revient via le useWhisperRecording du parent qui appelle
     setInstruction quand isSurgicalEditOpenRef.current === true.
     Quand l'input contient déjà du texte, Space tape un espace normal. */
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
      return
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      if (isRecording) onMicToggle()
      onClose()
      return
    }
    // PTT — uniquement si input vide ET pas déjà en train d'enregistrer
    if (e.key === ' ' && !instruction && !isRecording && !isTranscribing && !loading && dictationEnabled) {
      e.preventDefault()
      if (!spaceTriggeredRecordRef.current) {
        spaceTriggeredRecordRef.current = true
        onMicToggle()
      }
    }
  }

  const handleKeyUp = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === ' ' && spaceTriggeredRecordRef.current) {
      e.preventDefault()
      spaceTriggeredRecordRef.current = false
      if (isRecording) onMicToggle()
    }
  }

  if (!isOpen) return null

  const canSubmit = instruction.trim().length > 0 && !loading && !isRecording && !isTranscribing

  return (
    <div
      ref={barRef}
      className={`surgical-bar${isRecording ? ' surgical-bar--recording' : ''}${loading ? ' surgical-bar--loading' : ''}`}
      role="region"
      aria-label={t('surgical_edit_aria')}
      data-testid="surgical-edit-bar"
    >
      {/* Accent bar à gauche (teal) */}
      <div className="surgical-bar__accent" aria-hidden="true" />

      {/* Icône crayon */}
      <div className="surgical-bar__icon" aria-hidden="true">
        <EditIcon size={14} />
      </div>

      {/* Input principal — l'unique ligne. Le placeholder change selon le
          state (recording/transcribing/idle/error). Si une erreur fire,
          on l'affiche en tooltip flottant au-dessus de la bar (cf. plus bas)
          plutôt que d'ajouter une ligne sous la bar. */}
      <input
        ref={inputRef}
        type="text"
        className={`surgical-bar__input${error ? ' surgical-bar__input--error' : ''}`}
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
        onKeyDown={handleKeyDown}
        onKeyUp={handleKeyUp}
        placeholder={
          error
            ? error
            : isRecording
              ? t('surgical_listening')
              : isTranscribing
                ? t('transcribing')
                : t('surgical_placeholder')
        }
        autoComplete="off"
        spellCheck={false}
        disabled={loading || isTranscribing}
        data-testid="surgical-edit-input"
        aria-invalid={!!error}
      />


      {/* Submit */}
      <button
        type="button"
        className="surgical-bar__submit"
        onClick={submit}
        disabled={!canSubmit}
        aria-label={t('surgical_apply_aria')}
        data-testid="surgical-edit-submit"
        title={t('surgical_apply_title')}
      >
        {loading ? (
          <span className="surgical-bar__submit-spinner" aria-hidden="true" />
        ) : (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <line x1="12" y1="19" x2="12" y2="5"/>
            <polyline points="5 12 12 5 19 12"/>
          </svg>
        )}
      </button>

      {/* Bouton X retiré — la bar se ferme via :
            • Esc (input focused → handleKeyDown)
            • Click n'importe où en dehors de la bar (cf. useEffect ci-dessus)
            • Submit réussi (parent setSurgicalEditOpen(false)) */}
    </div>
  )
}
