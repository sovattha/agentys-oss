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

import { useEffect, useState, useRef, useCallback } from 'react'
import * as Sentry from '@sentry/react'
import { API_URL } from '../config'

/**
 * Y001 (Session Y, 2026-05-19): the backend can go briefly unreachable
 * (restart / deploy / crash) and return a burst of HTTP 502 across a mix of
 * endpoints while `/api/health` still answers 200 — so the existing
 * `backendStatus` health-poll stays green and the failures are silent (empty
 * calendar, stale labels, no toast).
 *
 * `api.ts` now dispatches two window events from its request layer:
 *   - `api:connection-lost`     when a request gives up on a gateway-class
 *                               failure (502/503/504, timeout, network error)
 *   - `api:connection-restored` when a request gets a real backend response
 *
 * This hook debounces those into a single `offline` flag so a one-off blip
 * (already absorbed by api.ts's one silent retry) never flashes the banner:
 * it shows only after 2+ failures, or after >3s of continuous failure.
 *
 * While `offline`, the hook ALSO probes `/api/ping` itself (backoff 2s → 30s,
 * ±20% jitter). Without this, the "reconnecting…" label was a lie: recovery
 * depended on some OTHER request happening to succeed, and on an idle screen
 * with no active polling the banner stayed up forever even after the backend
 * came back. On a successful probe the hook clears itself and dispatches
 * `api:connection-restored` so other listeners self-heal too.
 *
 * Audit connectivité 2026-06-13 :
 *   - `clientOffline` : navigator.onLine + événements online/offline. Quand
 *     c'est le poste de l'utilisateur qui n'a plus de réseau, le bandeau doit
 *     dire « Vous êtes hors ligne » plutôt que « Connexion perdue » (le
 *     backend n'y est pour rien).
 *   - Sentry : chaque épisode backend-down (bandeau réellement affiché, donc
 *     débouncé) émet UN `connection_lost` taggé avec la cause portée par
 *     l'event api.ts (gateway / timeout / network). Objectif : quantifier les
 *     épisodes et les corréler aux deploys Railway. Jamais d'event quand le
 *     client est lui-même offline — ce n'est pas un incident backend, et le
 *     SDK le mettrait en queue pour l'envoyer au retour du réseau.
 */
const SHOW_AFTER_MS = 3000
const FAILS_TO_SHOW = 2
const PROBE_BASE_DELAY_MS = 2000
const PROBE_MAX_DELAY_MS = 30000

function isNavigatorOffline(): boolean {
  return typeof navigator !== 'undefined' && navigator.onLine === false
}

export function useConnectionHealth(): {
  offline: boolean
  clientOffline: boolean
  clear: () => void
} {
  const [offline, setOffline] = useState(false)
  const [clientOffline, setClientOffline] = useState(isNavigatorOffline())
  const failCountRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastCauseRef = useRef<string>('unknown')
  const episodeReportedRef = useRef(false)

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  // One Sentry event per displayed episode — reset on restore/clear.
  // Review F05 (sémantique assumée) : le tag `cause` est la DERNIÈRE cause
  // reçue avant l'affichage du bandeau, pas la première — si un timeout puis
  // un 502 arrivent dans la fenêtre de grâce, l'épisode est taggé 'gateway'.
  // C'est voulu : la cause la plus récente décrit le mieux l'état du backend
  // au moment où l'épisode devient visible.
  const reportEpisode = useCallback(() => {
    if (episodeReportedRef.current) return
    episodeReportedRef.current = true
    if (isNavigatorOffline()) return
    Sentry.captureMessage('connection_lost', {
      level: 'warning',
      tags: { cause: lastCauseRef.current },
    })
  }, [])

  useEffect(() => {
    const isHidden = () => typeof document !== 'undefined' && document.hidden
    const onLost = (e: Event) => {
      const detail = (e as CustomEvent<{ cause?: string }>).detail
      lastCauseRef.current = detail?.cause || 'unknown'
      // Onglet en arrière-plan : un onglet occulté gèle ses fetches (qui expirent
      // sur AbortSignal) et throttle ses timers — les « échecs » qui en résultent
      // ne reflètent PAS une panne backend. On ne les compte pas et on ne flashe
      // pas « Connection lost » au retour de l'onglet (diagnostic stabilité
      // 2026-06-24) ; le flux normal de requêtes re-détecte une vraie panne au
      // premier plan. (On ne déclenche pas non plus de faux épisode Sentry.)
      if (isHidden()) return
      failCountRef.current += 1
      if (failCountRef.current >= FAILS_TO_SHOW) {
        clearTimer()
        setOffline(true)
        reportEpisode()
      } else if (!timerRef.current) {
        // First failure: arm a grace timer instead of flashing immediately.
        timerRef.current = setTimeout(() => {
          timerRef.current = null
          if (failCountRef.current > 0) {
            setOffline(true)
            reportEpisode()
          }
        }, SHOW_AFTER_MS)
      }
    }
    const onRestored = () => {
      failCountRef.current = 0
      episodeReportedRef.current = false
      clearTimer()
      setOffline(false)
    }
    // Au passage en arrière-plan : reset + masquer la bannière (donc stopper la
    // sonde de fond), pour ne pas afficher un état périmé au retour.
    const onVisibilityChange = () => {
      if (isHidden()) {
        failCountRef.current = 0
        episodeReportedRef.current = false
        clearTimer()
        setOffline(false)
      }
    }
    window.addEventListener('api:connection-lost', onLost)
    window.addEventListener('api:connection-restored', onRestored)
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      window.removeEventListener('api:connection-lost', onLost)
      window.removeEventListener('api:connection-restored', onRestored)
      document.removeEventListener('visibilitychange', onVisibilityChange)
      clearTimer()
    }
  }, [clearTimer, reportEpisode])

  // Client-side connectivity — the browser knows, no debounce needed.
  useEffect(() => {
    // Review F04: guard the online re-probe against unmount, so a stale
    // .then() can't broadcast api:connection-restored to other listeners
    // after this hook instance is gone.
    let disposed = false
    const onOffline = () => setClientOffline(true)
    const onOnline = () => {
      setClientOffline(false)
      // Network is back: re-probe immediately instead of waiting out the
      // backoff, so the banner doesn't linger up to 30s after wifi returns.
      if (typeof fetch !== 'undefined') {
        fetch(`${API_URL}/api/ping`, { signal: AbortSignal.timeout(3000) })
          .then((res) => {
            if (!disposed && res.ok) {
              window.dispatchEvent(new CustomEvent('api:connection-restored'))
            }
          })
          .catch(() => {})
      }
    }
    window.addEventListener('offline', onOffline)
    window.addEventListener('online', onOnline)
    return () => {
      disposed = true
      window.removeEventListener('offline', onOffline)
      window.removeEventListener('online', onOnline)
    }
  }, [])

  // Active reconnect probe — the thing that makes "reconnecting…" true.
  // Armed only while the banner is visible; success clears the banner and
  // broadcasts api:connection-restored.
  useEffect(() => {
    if (!offline) return
    if (typeof fetch === 'undefined') return
    let cancelled = false
    let probeTimer: ReturnType<typeof setTimeout> | null = null
    let attempt = 0

    const scheduleProbe = () => {
      const base = Math.min(PROBE_BASE_DELAY_MS * Math.pow(2, attempt), PROBE_MAX_DELAY_MS)
      const jitter = base * 0.2 * (Math.random() * 2 - 1)
      probeTimer = setTimeout(() => {
        // Ne pas sonder un onglet en arrière-plan (batterie/serveur) ; on
        // re-tente au retour au premier plan.
        if (typeof document !== 'undefined' && document.hidden) { scheduleProbe(); return }
        attempt += 1
        fetch(`${API_URL}/api/ping`, { signal: AbortSignal.timeout(3000) })
          .then((res) => {
            if (cancelled) return
            if (res.ok) {
              failCountRef.current = 0
              episodeReportedRef.current = false
              setOffline(false)
              window.dispatchEvent(new CustomEvent('api:connection-restored'))
            } else {
              scheduleProbe()
            }
          })
          .catch(() => { if (!cancelled) scheduleProbe() })
      }, Math.round(base + jitter))
    }

    scheduleProbe()
    return () => {
      cancelled = true
      if (probeTimer) clearTimeout(probeTimer)
    }
  }, [offline])

  // Optimistic hide when the user clicks Retry; the next failed request will
  // re-arm the banner if the backend is still down.
  const clear = useCallback(() => {
    failCountRef.current = 0
    episodeReportedRef.current = false
    clearTimer()
    setOffline(false)
  }, [clearTimer])

  return { offline, clientOffline, clear }
}

export default useConnectionHealth
