import { useCallback, useEffect, useState } from 'react'
import {
  ONBOARDING_KB_COMPLETE_KEY as KB_COMPLETE_KEY,
  FORCE_ONBOARDING_KEY,
} from '../lib/storageKeys'

export type V2Phase = 'idle' | 'welcome' | 'labelTip' | 'shortcutBar' | 'compose'

const V2_COMPLETE_KEY = 'agentys_onboarding_v2_complete'

export interface UseOnboardingV2 {
  phase: V2Phase
  isActive: boolean
  start: () => void
  next: () => void
  skip: () => void
  complete: () => void
}

function isOAuthCallback(): boolean {
  try {
    const params = new URLSearchParams(window.location.search)
    return params.has('code') || params.has('state') || window.location.pathname.includes('/oauth')
  } catch {
    return false
  }
}

export function useOnboardingV2(): UseOnboardingV2 {
  const [phase, setPhase] = useState<V2Phase>('idle')

  // Auto-start after Part I completes, unless blocked by a concurrent flow
  useEffect(() => {
    const kbDone = localStorage.getItem(KB_COMPLETE_KEY) === 'true'
    const v2Done = localStorage.getItem(V2_COMPLETE_KEY) === 'true'
    const forceOnboarding = localStorage.getItem(FORCE_ONBOARDING_KEY) === 'true'
    const oauthInFlight = isOAuthCallback()
    if (kbDone && !v2Done && !forceOnboarding && !oauthInFlight) {
      const t = setTimeout(() => setPhase('welcome'), 700)
      return () => clearTimeout(t)
    }
  }, [])

  // External events — replay from Settings, refine success from composer
  useEffect(() => {
    const onReplay = () => {
      localStorage.removeItem(V2_COMPLETE_KEY)
      setPhase('welcome')
    }
    const onRefineSuccess = () => {
      // Ctrl+G succeeded — the product speaks for itself, auto-dismiss the tour.
      setPhase((p) => {
        if (p === 'compose') {
          localStorage.setItem(V2_COMPLETE_KEY, 'true')
          return 'idle'
        }
        return p
      })
    }
    window.addEventListener('onboarding-v2:replay', onReplay)
    window.addEventListener('onboarding-v2:refine-success', onRefineSuccess)
    return () => {
      window.removeEventListener('onboarding-v2:replay', onReplay)
      window.removeEventListener('onboarding-v2:refine-success', onRefineSuccess)
    }
  }, [])

  // Body data-attribute for CSS targeting
  useEffect(() => {
    if (phase === 'idle') {
      delete document.body.dataset.onboardingV2
    } else {
      document.body.dataset.onboardingV2 = phase
    }
    return () => {
      delete document.body.dataset.onboardingV2
    }
  }, [phase])

  const start = useCallback(() => setPhase('welcome'), [])

  const next = useCallback(() => {
    setPhase((p) => {
      switch (p) {
        case 'welcome':
          return 'labelTip'
        case 'labelTip':
          return 'shortcutBar'
        case 'shortcutBar':
          return 'compose'
        default:
          return p
      }
    })
  }, [])

  const complete = useCallback(() => {
    localStorage.setItem(V2_COMPLETE_KEY, 'true')
    setPhase('idle')
  }, [])

  const skip = useCallback(() => {
    localStorage.setItem(V2_COMPLETE_KEY, 'true')
    setPhase('idle')
  }, [])

  // Escape = skip, but only when no modal is expected to own Escape.
  // During `compose` the NewMessageModal owns Escape (close composer),
  // so we deliberately don't intercept — modal close naturally ends the tour.
  useEffect(() => {
    if (phase === 'idle' || phase === 'compose') return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') skip()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [phase, skip])

  return { phase, isActive: phase !== 'idle', start, next, skip, complete }
}
