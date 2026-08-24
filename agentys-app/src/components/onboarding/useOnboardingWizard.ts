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

import { useReducer, useCallback, useEffect } from 'react'
import {
  ONBOARDING_COMPLETE_KEY,
  ONBOARDING_KB_COMPLETE_KEY,
} from '../../lib/storageKeys'

/* ─── Types ─── */
export type OnboardingStep = 0 | 1 | 2 | 3 | 4 | 5 | 'final'

export interface InboxScanData {
  unread_count: number
  newsletter_count: number
  older_than_30_days: number
  total_count: number
  newsletters_older_7_days: number
  read_older_30_days: number
  notification_unread_count: number
}

export interface CleanupData {
  total_handled: number
  estimated_time_saved_minutes: number
}

export interface TrainingData {
  emailsAnalysed: number
  tone: string
  contactsCount: number
}

export interface LabelData {
  autoLabelEnabled: boolean
  labelCounts: Record<string, number>
}

export interface OnboardingState {
  step: OnboardingStep
  direction: 'forward' | 'backward'
  /* per-step data */
  connected: boolean
  llmConfigured: boolean
  scanData: InboxScanData | null
  cleanupData: CleanupData | null
  trainingData: TrainingData | null
  labelData: LabelData | null
  /* timing */
  startedAt: string | null
  completedAt: string | null
}

const STORAGE_KEY = 'agentys_premium_onboarding'

const DEFAULT_STATE: OnboardingState = {
  step: 0,
  direction: 'forward',
  connected: false,
  llmConfigured: false,
  scanData: null,
  cleanupData: null,
  trainingData: null,
  labelData: null,
  startedAt: null,
  completedAt: null,
}

/* ─── Actions ─── */
type Action =
  | { type: 'NEXT_STEP' }
  | { type: 'PREV_STEP' }
  | { type: 'GO_TO_STEP'; step: OnboardingStep }
  | { type: 'SET_CONNECTED' }
  | { type: 'SET_LLM_CONFIGURED' }
  | { type: 'SET_SCAN_DATA'; data: InboxScanData }
  | { type: 'SET_CLEANUP_DATA'; data: CleanupData }
  | { type: 'SET_TRAINING_DATA'; data: TrainingData }
  | { type: 'SET_LABEL_DATA'; data: LabelData }
  | { type: 'COMPLETE' }
  | { type: 'RESET' }

const STEP_ORDER: OnboardingStep[] = [0, 3, 4, 'final']

function nextStep(current: OnboardingStep): OnboardingStep {
  // Step 1 (Connect) est hors STEP_ORDER — c'est le chemin de récupération
  // vers lequel Step 3 renvoie quand l'accountId n'arrive pas. Sans ce cas
  // spécial, STEP_ORDER.indexOf(1) = -1 ferait retomber l'utilisateur sur
  // Step 0 après une connexion réussie, et il faudrait attendre que
  // PremiumOnboarding détecte alreadyConnected pour rebondir — flicker.
  if (current === 1) return 3
  const idx = STEP_ORDER.indexOf(current)
  return idx < STEP_ORDER.length - 1 ? STEP_ORDER[idx + 1] : current
}

function prevStep(current: OnboardingStep): OnboardingStep {
  const idx = STEP_ORDER.indexOf(current)
  return idx > 0 ? STEP_ORDER[idx - 1] : current
}

function reducer(state: OnboardingState, action: Action): OnboardingState {
  switch (action.type) {
    case 'NEXT_STEP':
      return { ...state, step: nextStep(state.step), direction: 'forward' }
    case 'PREV_STEP':
      return { ...state, step: prevStep(state.step), direction: 'backward' }
    case 'GO_TO_STEP':
      return {
        ...state,
        step: action.step,
        direction: STEP_ORDER.indexOf(action.step) > STEP_ORDER.indexOf(state.step)
          ? 'forward' : 'backward',
      }
    case 'SET_CONNECTED':
      return { ...state, connected: true }
    case 'SET_LLM_CONFIGURED':
      return { ...state, llmConfigured: true }
    case 'SET_SCAN_DATA':
      return { ...state, scanData: action.data }
    case 'SET_CLEANUP_DATA':
      return { ...state, cleanupData: action.data }
    case 'SET_TRAINING_DATA':
      return { ...state, trainingData: action.data }
    case 'SET_LABEL_DATA':
      return { ...state, labelData: action.data }
    case 'COMPLETE':
      return { ...state, completedAt: new Date().toISOString() }
    case 'RESET':
      return { ...DEFAULT_STATE, startedAt: new Date().toISOString() }
    default:
      return state
  }
}

/* ─── Persistence helpers ─── */
function loadState(): OnboardingState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as OnboardingState
      // Step 5 used to be the automatic follow-ups onboarding page. It was
      // removed from the flow; users resuming there should finish cleanly.
      if (parsed.step === 5) return { ...parsed, step: 'final' }
      // Validate step is in the valid range
      if (parsed.step === 1 || STEP_ORDER.includes(parsed.step)) return parsed
    }
  } catch { /* noop */ }
  return { ...DEFAULT_STATE, startedAt: new Date().toISOString() }
}

function persistState(state: OnboardingState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch { /* quota exceeded — ignore */ }
}

/* ─── Hook ─── */
export function useOnboardingWizard() {
  const [state, dispatch] = useReducer(reducer, undefined, loadState)

  // Persist on every state change
  useEffect(() => {
    persistState(state)
  }, [state])

  const next = useCallback(() => dispatch({ type: 'NEXT_STEP' }), [])
  const prev = useCallback(() => dispatch({ type: 'PREV_STEP' }), [])
  const goTo = useCallback((step: OnboardingStep) => dispatch({ type: 'GO_TO_STEP', step }), [])

  const setConnected = useCallback(() => dispatch({ type: 'SET_CONNECTED' }), [])
  const setLlmConfigured = useCallback(() => dispatch({ type: 'SET_LLM_CONFIGURED' }), [])
  const setScanData = useCallback((data: InboxScanData) => dispatch({ type: 'SET_SCAN_DATA', data }), [])
  const setCleanupData = useCallback((data: CleanupData) => dispatch({ type: 'SET_CLEANUP_DATA', data }), [])
  const setTrainingData = useCallback((data: TrainingData) => dispatch({ type: 'SET_TRAINING_DATA', data }), [])
  const setLabelData = useCallback((data: LabelData) => dispatch({ type: 'SET_LABEL_DATA', data }), [])

  const complete = useCallback(() => {
    dispatch({ type: 'COMPLETE' })
    localStorage.setItem(ONBOARDING_COMPLETE_KEY, 'true')
    localStorage.setItem(ONBOARDING_KB_COMPLETE_KEY, 'true')
  }, [])

  const reset = useCallback(() => dispatch({ type: 'RESET' }), [])

  const stepIndex = STEP_ORDER.indexOf(state.step)
  const totalSteps = STEP_ORDER.length - 1 // exclude 'final' from count
  const progress = state.step === 'final' ? 1 : stepIndex / totalSteps

  return {
    state,
    step: state.step,
    direction: state.direction,
    progress,
    stepIndex,
    totalSteps,
    /* actions */
    next,
    prev,
    goTo,
    setConnected,
    setLlmConfigured,
    setScanData,
    setCleanupData,
    setTrainingData,
    setLabelData,
    complete,
    reset,
  }
}

export type OnboardingWizard = ReturnType<typeof useOnboardingWizard>
