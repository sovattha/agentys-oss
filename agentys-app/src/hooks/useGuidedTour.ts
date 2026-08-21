import { useState, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'

const TOUR_KEY = 'agentys_tour_completed'
const TIPS_KEY = 'agentys_tips_disabled'

export interface TourStep {
  target: string       // CSS selector or data-testid
  title: string
  description: string
  position: 'right' | 'bottom' | 'top'
}

interface TourStepDef {
  target: string
  titleKey: string
  descKey: string
  position: 'right' | 'bottom' | 'top'
}

const TOUR_STEP_DEFS: TourStepDef[] = [
  {
    target: '[data-testid="sidebar"]',
    titleKey: 'onboarding:tour_sidebar_title',
    descKey: 'onboarding:tour_sidebar_desc',
    position: 'right',
  },
  {
    target: '[data-testid="nav-drafts"]',
    titleKey: 'onboarding:tour_drafts_title',
    descKey: 'onboarding:tour_drafts_desc',
    position: 'right',
  },
  {
    target: '.shortcuts-ribbon',
    titleKey: 'onboarding:tour_shortcuts_title',
    descKey: 'onboarding:tour_shortcuts_desc',
    position: 'bottom',
  },
  {
    target: '[data-testid="nav-deep-work"]',
    titleKey: 'onboarding:tour_focus_title',
    descKey: 'onboarding:tour_focus_desc',
    position: 'right',
  },
]

export interface GuidedTourState {
  isActive: boolean
  currentStep: number
  totalSteps: number
  step: TourStep | null
  next: () => void
  skip: () => void
  start: () => void
  isCompleted: boolean
  tipsDisabled: boolean
  setTipsDisabled: (disabled: boolean) => void
}

export function useGuidedTour(): GuidedTourState {
  const { t } = useTranslation('onboarding')
  const [isCompleted, setIsCompleted] = useState(() =>
    localStorage.getItem(TOUR_KEY) === 'true'
  )
  const [isActive, setIsActive] = useState(false)
  const [currentStep, setCurrentStep] = useState(0)
  const [tipsDisabled, setTipsDisabledState] = useState(() =>
    localStorage.getItem(TIPS_KEY) === 'true'
  )

  const tourSteps: TourStep[] = useMemo(() =>
    TOUR_STEP_DEFS.map(def => ({
      target: def.target,
      title: t(def.titleKey),
      description: t(def.descKey),
      position: def.position,
    })),
    [t]
  )

  const start = useCallback(() => {
    setIsActive(true)
    setCurrentStep(0)
  }, [])

  const complete = useCallback(() => {
    setIsActive(false)
    setIsCompleted(true)
    localStorage.setItem(TOUR_KEY, 'true')
  }, [])

  const next = useCallback(() => {
    if (currentStep >= tourSteps.length - 1) {
      complete()
    } else {
      setCurrentStep(prev => prev + 1)
    }
  }, [currentStep, complete, tourSteps.length])

  const skip = useCallback(() => {
    complete()
  }, [complete])

  const setTipsDisabled = useCallback((disabled: boolean) => {
    setTipsDisabledState(disabled)
    localStorage.setItem(TIPS_KEY, disabled ? 'true' : 'false')
  }, [])

  return {
    isActive,
    currentStep,
    totalSteps: tourSteps.length,
    step: isActive ? tourSteps[currentStep] || null : null,
    next,
    skip,
    start,
    isCompleted,
    tipsDisabled,
    setTipsDisabled,
  }
}
