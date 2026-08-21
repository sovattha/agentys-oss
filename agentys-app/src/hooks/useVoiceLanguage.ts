import { useState } from 'react'

/**
 * Whitelist of voice-input languages exposed in the picker. The full backend
 * accepts more (see `_VALID_LANG_CODES` in routes_misc.py) — we only surface
 * the most common ones to keep the menu compact.
 *
 * `auto` is a UI-only token meaning "let the backend STT auto-detect". The hook
 * returns it as-is in `languageParam` ; useWhisperRecording then treats 'auto'
 * (or '') as a signal to omit the lang param on the wire so the backend uses
 * detect_language=true.
 */
export const SUPPORTED_VOICE_LANGUAGES = [
  { code: 'auto', label: 'Auto', flag: '🌐' },
  { code: 'fr', label: 'Français', flag: '🇫🇷' },
  { code: 'en', label: 'English', flag: '🇬🇧' },
  { code: 'es', label: 'Español', flag: '🇪🇸' },
  { code: 'it', label: 'Italiano', flag: '🇮🇹' },
  { code: 'pt', label: 'Português', flag: '🇵🇹' },
] as const

export type VoiceLanguageCode = typeof SUPPORTED_VOICE_LANGUAGES[number]['code']

/**
 * Voice-input language preference for the dictation pipeline.
 *
 * Priority chain (highest → lowest) :
 *   1. **userOverride** — set by `setLanguage()` when the user clicks the picker.
 *      Lives only for this modal session (in-memory). Closing the modal resets
 *      it so the next compose starts fresh.
 *   2. **defaultLanguage** — the recipient's preferred language (Settings →
 *      Training per-contact data), passed by the caller. Lets dictation START
 *      in the language the user most likely speaks to this contact (a French
 *      contact → mic en FR). `null`/omitted → no recipient hint.
 *   3. `'auto'` — the STT provider detects the spoken language.
 *
 * (2026-06-11 → 2026-06-23) Le hint destinataire avait été SUPPRIMÉ après un
 * incident prod : profil contact « En » + dictée française de 23 s → Deepgram
 * épinglé language=en → transcript vide, dictée perdue. Il est RÉTABLI ici à la
 * demande utilisateur (« le contact est en français, le micro devrait déjà être
 * en fr »). Le risque d'origine est RÉDUIT, PAS totalement supprimé :
 * useWhisperRecording rejoue automatiquement en auto-détection quand une langue
 * épinglée renvoie un transcript VIDE alors que de la parole a été détectée — le
 * symptôme DOMINANT de l'incident. RÉSIDU NON couvert : un pin erroné peut aussi
 * produire un transcript NON-vide mais MAL transcrit (Deepgram mâche le FR en EN
 * approximatif, cf. useWhisperRecording ~l.353) ; ce cas n'est pas rattrapé
 * automatiquement. Le badge (VoiceLanguageBadge) affiche la langue épinglée pour
 * que l'utilisateur la repère et la corrige ; un choix explicite du picker gagne.
 */
export function useVoiceLanguage(defaultLanguage?: VoiceLanguageCode | null) {
  const [userOverride, setUserOverride] = useState<VoiceLanguageCode | null>(null)

  const language: VoiceLanguageCode = userOverride ?? defaultLanguage ?? 'auto'

  const setLanguage = (code: VoiceLanguageCode) => {
    setUserOverride(code)
  }

  return {
    language,
    /**
     * Pass directly to useWhisperRecording's `language` option.
     * 'auto' is a sentinel : useWhisperRecording maps it to "no lang on the wire".
     */
    languageParam: language,
    setLanguage,
    supportedLanguages: SUPPORTED_VOICE_LANGUAGES,
  }
}
