import { useEffect, useState } from 'react'

import { API_URL } from '../config'
import { getAuthHeaders } from '../services/authToken'

/**
 * Mémoire process-wide pour éviter de re-fetcher la langue d'un même contact à
 * chaque montage de composant ou keystroke dans le champ destinataire. Pas de
 * TTL : la langue d'un contact change rarement, et un hard-reload de l'app
 * suffit à invalider. `null` = fetched et confirmé inconnu (sert à distinguer
 * "jamais fetched" de "fetched et pas de profil").
 */
const CACHE = new Map<string, string | null>()
const PENDING = new Map<string, Promise<string | null>>()

// F-04 (audit 2026-04-30): Gmail/IMAP commonly return display-name format
// like "Alex Smith <alex@example.com>". Lowercasing+trimming alone leaves
// the wrapper intact, so the cache key + the backend lookup both miss the
// canonical "alex@example.com" entry. Extract the bracketed address when
// present, otherwise treat the input as a bare address.
function _normalize(email: string | null | undefined): string | null {
  if (!email) return null
  const trimmed = email.trim()
  if (!trimmed) return null
  const bracketed = /<([^>]+)>/.exec(trimmed)
  const candidate = bracketed ? bracketed[1] : trimmed
  const lower = candidate.trim().toLowerCase()
  return lower.includes('@') ? lower : null
}

async function _fetchContactLanguage(email: string): Promise<string | null> {
  const cached = CACHE.get(email)
  if (cached !== undefined) return cached

  const inflight = PENDING.get(email)
  if (inflight) return inflight

  const promise = (async () => {
    try {
      const url = `${API_URL}/api/contact-language?email=${encodeURIComponent(email)}`
      const res = await fetch(url, { headers: getAuthHeaders() })
      if (!res.ok) return null
      const data = await res.json()
      const lang = typeof data?.language === 'string' && data.language.length === 2
        ? data.language
        : null
      CACHE.set(email, lang)
      return lang
    } catch {
      return null
    } finally {
      PENDING.delete(email)
    }
  })()

  PENDING.set(email, promise)
  return promise
}

/**
 * Renvoie un code langue ISO 639-1 (`fr`, `en`, ...) pour passer en `lang` à
 * `/api/transcribe`. Chaîne de fallback :
 *   1. ContactStyleProfile.langue / langue_variante du destinataire
 *   2. (si `composeFallback=true`) navigator.language
 *   3. ''  (auto-detect Whisper)
 *
 * `composeFallback` doit être true côté NewMessageModal (pas d'historique
 * d'email reçu pour deviner) et false côté Reply/PendingDraft (où on a déjà
 * `email.body` qui peut servir de signal supplémentaire — non implémenté ici
 * pour rester minimal).
 *
 * Ne fetch jamais quand `email` est null/empty/invalid. Debounce naturel :
 * le hook ne refetch que quand `email` change, et le cache global évite les
 * doublons entre composants.
 */
export function useContactLanguage(
  email: string | null | undefined,
  options: { composeFallback?: boolean } = {},
): string {
  const { composeFallback = false } = options
  const [language, setLanguage] = useState<string>('')

  useEffect(() => {
    const normalized = _normalize(email)
    if (!normalized) {
      // Pas de contact identifié : fallback compose ou auto-detect.
      if (composeFallback) {
        const navLang = (typeof navigator !== 'undefined' ? navigator.language : '')
          .split('-')[0]
          ?.toLowerCase()
        const SUPPORTED = ['fr', 'en', 'es', 'de', 'it', 'pt', 'ja', 'zh', 'ar']
        setLanguage(navLang && SUPPORTED.includes(navLang) ? navLang : '')
      } else {
        setLanguage('')
      }
      return
    }

    // Fast path : cache hit.
    const cached = CACHE.get(normalized)
    if (cached !== undefined) {
      if (cached) {
        setLanguage(cached)
        return
      }
      // Profil connu mais pas de langue → fallback identique au cas "pas de contact"
      if (composeFallback) {
        const navLang = (typeof navigator !== 'undefined' ? navigator.language : '')
          .split('-')[0]
          ?.toLowerCase()
        const SUPPORTED = ['fr', 'en', 'es', 'de', 'it', 'pt', 'ja', 'zh', 'ar']
        setLanguage(navLang && SUPPORTED.includes(navLang) ? navLang : '')
      } else {
        setLanguage('')
      }
      return
    }

    // Slow path : fetch puis update si toujours montés sur le même email.
    let cancelled = false
    _fetchContactLanguage(normalized).then(lang => {
      if (cancelled) return
      if (lang) {
        setLanguage(lang)
      } else if (composeFallback) {
        const navLang = (typeof navigator !== 'undefined' ? navigator.language : '')
          .split('-')[0]
          ?.toLowerCase()
        const SUPPORTED = ['fr', 'en', 'es', 'de', 'it', 'pt', 'ja', 'zh', 'ar']
        setLanguage(navLang && SUPPORTED.includes(navLang) ? navLang : '')
      } else {
        setLanguage('')
      }
    })
    return () => { cancelled = true }
  }, [email, composeFallback])

  return language
}
