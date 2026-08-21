import { useState, useEffect, useCallback } from 'react'
import type { OnboardingStep, OnboardingState } from '../types/onboarding'
import {
  ONBOARDING_COMPLETE_KEY,
  ONBOARDING_KB_COMPLETE_KEY,
} from '../lib/storageKeys'

function _readBool(key: string): boolean {
  try {
    return localStorage.getItem(key) === 'true'
  } catch {
    // localStorage can be unavailable (private mode, blocked storage).
    return false
  }
}

export function useOnboardingState(): OnboardingState & {
  setStep: (step: OnboardingStep) => void
  completeOnboarding: () => void
  resetOnboarding: () => void
} {
  // Lazy initial reads so we don't crash when localStorage is blocked.
  const [kbComplete, setKbComplete] = useState<boolean>(() => _readBool(ONBOARDING_KB_COMPLETE_KEY))
  const [wizardComplete, setWizardComplete] = useState<boolean>(() => _readBool(ONBOARDING_COMPLETE_KEY))

  const [step, setStep] = useState<OnboardingStep>('welcome')

  // OB-R1 (audit 2026-04-25 onboarding-residual): sync state across
  // tabs. When tab 1 calls completeOnboarding() the browser fires a
  // `storage` event in every OTHER tab — without this listener tab 2
  // stayed on the welcome screen claiming "onboard me" while the KB
  // was already complete in tab 1, leading to a confusing re-click that
  // hit the backend dedupe (cf. C-4 already-running response). The
  // localStorage write itself is the source of truth; this hook just
  // re-reads when it changes elsewhere.
  useEffect(() => {
    const handler = (e: StorageEvent) => {
      // `storage` events from same-origin tabs only — no security risk.
      if (e.key === ONBOARDING_KB_COMPLETE_KEY) {
        setKbComplete(e.newValue === 'true')
      } else if (e.key === ONBOARDING_COMPLETE_KEY) {
        setWizardComplete(e.newValue === 'true')
      } else if (e.key === null) {
        // localStorage.clear() — full reset across tabs.
        setKbComplete(_readBool(ONBOARDING_KB_COMPLETE_KEY))
        setWizardComplete(_readBool(ONBOARDING_COMPLETE_KEY))
      }
    }
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [])

  const completeOnboarding = useCallback(() => {
    try {
      localStorage.setItem(ONBOARDING_KB_COMPLETE_KEY, 'true')
    } catch {
      // private mode / quota — non-fatal, the user just won't see
      // cross-tab sync this session.
    }
    setKbComplete(true)
  }, [])

  const resetOnboarding = useCallback(() => {
    try {
      localStorage.removeItem(ONBOARDING_KB_COMPLETE_KEY)
    } catch {
      // non-fatal — see above.
    }
    setKbComplete(false)
    setStep('welcome')
  }, [])

  return {
    step,
    isComplete: kbComplete,
    isFirstLaunch: wizardComplete && !kbComplete,
    setStep,
    completeOnboarding,
    resetOnboarding,
  }
}
