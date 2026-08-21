/**
 * useContactAvatar — fetches a contact's profile photo from
 * `/api/contacts/avatar?email=...` and exposes a blob URL the consumer
 * can drop into an <img src>.
 *
 * Why a fetch + blob URL instead of plain `<img src=...>`?
 * The endpoint is JWT-protected; HTML <img> can't carry an Authorization
 * header, and we don't want to leak the JWT into a query string. Fetching
 * with `getAuthHeaders()` keeps the same auth pipeline as every other
 * authenticated call.
 *
 * The module-level cache deduplicates requests across instances — when
 * the inbox renders 50 thread items with the same sender, only one
 * network call fires.
 */

import { useEffect, useRef, useState } from 'react'
import { API_URL } from '../config'
import { getAuthHeaders, getJwtEmail } from '../services/authToken'

type CacheEntry =
  | { state: 'pending'; promise: Promise<string | null> }
  | { state: 'resolved'; url: string | null }

const _cache = new Map<string, CacheEntry>()

function cacheKey(email: string): string {
  return email.trim().toLowerCase()
}

/**
 * Audit 2026-05-18: the `/api/contacts/avatar` endpoint queries the
 * provider's contacts directory, which never contains the user's own
 * address — every redraw produced a 404 in the console for messages
 * "from me". Short-circuit when the email matches the logged-in user
 * and resolve to null so the consumer renders the initial-letter
 * fallback (or, in the AccountManager, the account.avatar_url which
 * comes from a separate endpoint and is already loaded).
 */
function isOwnEmail(email: string): boolean {
  const jwt = (getJwtEmail() || '').trim().toLowerCase()
  if (!jwt) return false
  return cacheKey(email) === jwt
}

async function fetchAvatarUrl(email: string): Promise<string | null> {
  if (isOwnEmail(email)) return null
  const res = await fetch(
    `${API_URL}/api/contacts/avatar?email=${encodeURIComponent(email)}`,
    { headers: { ...getAuthHeaders() } },
  )
  if (!res.ok) return null
  const blob = await res.blob()
  if (!blob.size || !blob.type.startsWith('image/')) return null
  return URL.createObjectURL(blob)
}

function getOrFetch(email: string): Promise<string | null> {
  const key = cacheKey(email)
  const existing = _cache.get(key)
  if (existing) {
    if (existing.state === 'resolved') return Promise.resolve(existing.url)
    return existing.promise
  }
  const promise = fetchAvatarUrl(email)
    .then((url) => {
      _cache.set(key, { state: 'resolved', url })
      return url
    })
    .catch(() => {
      _cache.set(key, { state: 'resolved', url: null })
      return null
    })
  _cache.set(key, { state: 'pending', promise })
  return promise
}

export function useContactAvatar(email: string | null | undefined): string | null {
  const [url, setUrl] = useState<string | null>(() => {
    if (!email) return null
    const entry = _cache.get(cacheKey(email))
    return entry && entry.state === 'resolved' ? entry.url : null
  })
  // Track the email this effect was kicked off for so a fast-changing prop
  // doesn't race-condition the setState (older fetch resolving after newer).
  const liveEmailRef = useRef<string | null>(null)

  useEffect(() => {
    if (!email) {
      liveEmailRef.current = null
      setUrl(null)
      return
    }
    liveEmailRef.current = email
    const entry = _cache.get(cacheKey(email))
    if (entry && entry.state === 'resolved') {
      setUrl(entry.url)
      return
    }
    let cancelled = false
    getOrFetch(email).then((resolved) => {
      if (cancelled) return
      if (liveEmailRef.current !== email) return
      setUrl(resolved)
    })
    return () => {
      cancelled = true
    }
  }, [email])

  return url
}

/** Test/utility hook to wipe the cache (e.g. on logout). */
export function clearContactAvatarCache(): void {
  for (const entry of _cache.values()) {
    if (entry.state === 'resolved' && entry.url) {
      try {
        URL.revokeObjectURL(entry.url)
      } catch {
        /* nothing else to do */
      }
    }
  }
  _cache.clear()
}
