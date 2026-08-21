import { useEffect, useState, useCallback } from 'react'
import { API_URL } from '../config'
import { getAuthHeaders } from '../services/authToken'
import type { VoiceLanguageCode } from './useVoiceLanguage'

const SUPPORTED_BASE: ReadonlySet<string> = new Set([
  'fr', 'en', 'es', 'it', 'pt',
])

// Free-form `langue` field uses French/English label words instead of ISO codes.
// We map the most common spellings (ContactStyleProfile lets the user type freely
// in the Settings → Training UI). Unknown labels return null → no recipient hint.
const LANGUE_TO_CODE: Record<string, VoiceLanguageCode> = {
  fr: 'fr', francais: 'fr', 'français': 'fr', french: 'fr',
  en: 'en', anglais: 'en', english: 'en',
  es: 'es', espagnol: 'es', spanish: 'es',
  it: 'it', italien: 'it', italian: 'it',
  pt: 'pt', portugais: 'pt', portuguese: 'pt',
}

interface ContactProfile {
  email?: string
  langue?: string | null
  langue_variante?: string | null
}

function profileToCode(p: ContactProfile): VoiceLanguageCode | null {
  // langue_variante is more specific (e.g. 'fr-CA') ; we strip the region
  // since the picker + backend operate on ISO 639-1 base codes only.
  if (p.langue_variante) {
    const base = p.langue_variante.split('-')[0]?.toLowerCase()
    if (base && SUPPORTED_BASE.has(base)) return base as VoiceLanguageCode
  }
  if (p.langue) {
    const norm = p.langue.toLowerCase().trim()
    return LANGUE_TO_CODE[norm] ?? null
  }
  return null
}

/**
 * Fetches the per-contact `WritingStyleProfile.contact_profiles` list once and
 * exposes lookup helpers. Used by compose surfaces to default the dictation
 * language to the recipient's preferred language (Settings → Training data).
 *
 * Silent failure : if the fetch errors, lookups return null and callers fall
 * through to whatever default chain they have. We don't surface a toast.
 */
export function useContactLanguages() {
  const [byEmail, setByEmail] = useState<Map<string, VoiceLanguageCode>>(new Map())

  useEffect(() => {
    let cancelled = false
    fetch(`${API_URL}/api/writing-style/contacts`, { headers: { ...getAuthHeaders() } })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then((data: { contacts?: ContactProfile[] }) => {
        if (cancelled) return
        const map = new Map<string, VoiceLanguageCode>()
        for (const c of data.contacts ?? []) {
          if (!c.email) continue
          const code = profileToCode(c)
          if (code) map.set(c.email.toLowerCase(), code)
        }
        setByEmail(map)
      })
      .catch(() => { /* silent : fall through to no recipient hint */ })
    return () => { cancelled = true }
  }, [])

  const lookup = useCallback((email?: string | null): VoiceLanguageCode | null => {
    if (!email) return null
    return byEmail.get(email.toLowerCase()) ?? null
  }, [byEmail])

  /**
   * Aggregate over multiple recipient emails.
   * Returns a code only if ALL known recipients share the same language ;
   * any disagreement returns null so the caller falls back to auto-detect.
   */
  const aggregate = useCallback((emails: ReadonlyArray<string | null | undefined>): VoiceLanguageCode | null => {
    const codes: VoiceLanguageCode[] = []
    for (const e of emails) {
      const c = lookup(e)
      if (c) codes.push(c)
    }
    if (codes.length === 0) return null
    const first = codes[0]
    return codes.every(c => c === first) ? first : null
  }, [lookup])

  return { lookup, aggregate, byEmail }
}

const EMAIL_REGEX = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g

/**
 * Extract bare email addresses from a free-form recipients string.
 * Handles "Name <email>", comma/semicolon separators, and stripped whitespace.
 */
export function extractEmails(...inputs: Array<string | null | undefined>): string[] {
  const all = inputs.filter(Boolean).join(' ')
  if (!all) return []
  const matches = all.match(EMAIL_REGEX) ?? []
  return matches.map(e => e.toLowerCase())
}
