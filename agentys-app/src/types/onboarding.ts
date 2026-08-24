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

// Types for the onboarding flow (Issue #33)

export type OnboardingStep = 'welcome' | 'faq_source' | 'learning' | 'insights'

export interface OnboardingState {
  step: OnboardingStep
  isComplete: boolean
  isFirstLaunch: boolean
}

export interface PatternDetected {
  type: 'style' | 'topic' | 'contact' | 'signature' | 'greeting'
  label: string
  confidence: number
}

export type AgentStepStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface AgentSteps {
  profile: AgentStepStatus
  style: AgentStepStatus
  knowledge: AgentStepStatus
  label: AgentStepStatus
}

/** A single narrative finding from the onboarding pipeline.
 *  Emitted one-per-wow-moment as the agents complete — the DiscoveryFeed
 *  component picks them up and rolls them through as a live log. */
export interface Discovery {
  /** Visual treatment: starting (discreet arrow) / finding (checkmark,
   *  most common) / insight (spark, rare punchlines). */
  kind: 'starting' | 'finding' | 'insight'
  /** Which agent produced the finding. Used for debug + potential
   *  filtering; not displayed in the default UI. */
  agent: 'profile' | 'knowledge' | 'style' | 'label' | ''
  /** Stable i18n key — the feed re-translates on render so switching
   *  locale mid-scan updates already-displayed items. */
  messageKey: string
  /** Interpolation args for the i18n key (counts, names, etc). */
  messageParams: Record<string, unknown>
  /** Last-resort text if the i18n key is missing in the current locale. */
  fallbackMessage: string
  /** Backend emission time (ms since epoch). Used for ordering + unique
   *  React keys when two discoveries share the same messageKey. */
  timestampMs: number
  /** Client-side unique id for React key stability. */
  id: string
}

export interface LearningProgress {
  isActive: boolean
  emailsProcessed: number
  emailsTotal: number
  patterns: PatternDetected[]
  confidenceScore: number
  currentPhase: string
  /** Raw i18n key of the most recent backend-emitted phase, preserved so the
   *  narrator can re-translate on language switch (currentPhase captures the
   *  translation at event time and goes stale when locale changes). */
  currentPhaseKey?: string | null
  currentPhaseParams?: Record<string, unknown> | null
  agentSteps: AgentSteps
  error: string | null
  /** Dernier `step` reçu via WS (profile/style/knowledge/label). Sert à dériver la narration. */
  currentStep?: keyof AgentSteps | null
  /** Index du lot courant (1-based) pour l'entraînement approfondi. */
  batchCurrent?: number
  /** Nombre total de lots pour l'entraînement approfondi. */
  batchTotal?: number
  /** Découvertes live (émises par le backend dans `onboarding:progress_updated`). */
  newContacts?: number
  newRules?: number
  /** Rolling narrative feed. Latest discoveries last — newest item at
   *  the tail. Capped to the last N entries in the hook. */
  discoveries: Discovery[]
}

// --- Analysis results from backend ---

export interface ProfileSignature {
  name?: string
  title?: string | null
  department?: string | null
  company?: string | null
}

export interface ProfileTone {
  default_tone?: string
  /** "tu" | "vous" | "mixed" — null for English-only corpora. */
  addressing?: 'tu' | 'vous' | 'mixed' | null
  /** Singular representatives flattened by the backend from the plural maps
   *  (cf. OnboardingManager._flatten_profile_styles). Always populated when
   *  the plural maps are non-empty. */
  greeting_style?: string
  closing_style?: string
  /** Full plural maps keyed by `<formality>_<lang>` — kept for consumers
   *  that want to display every variant (settings screen). */
  greeting_styles?: Record<string, string>
  closing_styles?: Record<string, string>
  uses_emoji?: boolean
  average_response_length?: string
}

export interface UserProfile {
  user_email?: string
  user_name?: string
  /** Short form the user signs with (e.g. "Alex" vs "Alexandre Dupont"). */
  preferred_name?: string
  /** Free-form profession detected during onboarding, confirmed by the user. */
  profession?: string
  profession_confirmed?: boolean
  signature?: ProfileSignature
  tone?: ProfileTone
  languages?: string[]
}

export interface KnowledgeContact {
  email: string
  name: string
  company?: string | null
  title?: string | null
  preferred_language?: string
  preferred_tone?: string
  interaction_count?: number
  language_variant?: string | null
  /** Legacy — `type` (sociological classification) and `topics` (per-contact
   *  interaction themes) were removed from the KnowledgeAgent schema in
   *  favour of a leaner prompt. Kept optional so old memoire.md snapshots
   *  parsed by the frontend don't break if they still carry these keys. */
  type?: string
  topics?: string[]
}

export interface KnowledgeProject {
  name: string
  description?: string
  contacts?: string[]
  status?: string
  keywords?: string[]
}

export interface KnowledgeBase {
  contacts?: KnowledgeContact[]
  /**
   * Legacy: projects were auto-detected in older builds. Initial onboarding
   * no longer produces any — kept on the type for settings views that still
   * render persisted KBs from older users.
   */
  projects?: KnowledgeProject[]
  /**
   * Legacy: terminology was auto-extracted in older builds. Not produced
   * by the scanner anymore; kept for settings views reading older KBs.
   */
  terminology?: Record<string, string>
}

export interface ContactRule {
  contact_email: string
  tone: string
  language: string
  /** "tu" | "vous" — null for English contacts or unknown. */
  addressing?: 'tu' | 'vous' | null
  greeting: string
  closing: string
}

export interface GeneralRule {
  /** Single descriptive sentence — the StyleAgent prompt no longer asks
   *  the LLM to emit structured `name` / `trigger` / `action` because
   *  the backend collapsed them all to `description` before persistence.
   *  Optional `name` / `trigger` / `action` are kept so legacy KBs from
   *  before the simplification still deserialize without errors. */
  description: string
  name?: string
  trigger?: string
  action?: string
}

export interface RulesSet {
  contact_rules?: ContactRule[]
  general_rules?: GeneralRule[]
  forbidden_phrases?: string[]
}

export interface SuggestedLabel {
  name: string
  description: string
  color: string
  rules: string[]
  example_subjects: string[]
  email_count: number
  is_project?: boolean
}

export interface CategoryAnalysis {
  statistics: Record<string, number>
}

export interface LearningInsights {
  profile: UserProfile | null
  knowledge: KnowledgeBase | null
  rules: RulesSet | null
  categories: CategoryAnalysis | null
  emailsAnalysed: number
  ready: boolean
}

// --- Learning activity tracking (auto-refresh) ---

export interface LearningActivity {
  lastCorrectionAt: string | null
  eventsSinceRefresh: number
  threshold: number
  isRefreshing: boolean
  hasNewLearning: boolean
  lastRefreshAt: string | null
}
