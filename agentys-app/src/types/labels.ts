/**
 * Types for the Smart Labeling System
 */
import i18n from '../i18n'

export interface Label {
  name: string
  color: string
  description: string
  is_default: boolean
  is_favorite: boolean
  is_project?: boolean
  project_name?: string
  project_number?: string
  project_abbreviation?: string
  subject_prefix?: string
  created_at: string
  rules: string[]
  ai_prompt?: string
}

export interface LabelingRule {
  rule_id: string
  label_name: string
  condition_type: 'sender' | 'subject' | 'body' | 'cc' | 'recipient'
  condition_value: string
  priority: number
  confidence: number
  learned_from?: string
  created_at: string
  last_used_at?: string
  use_count: number
  is_active: boolean
  total_matches: number
  corrections: number
  disabled_reason?: string | null
}

export interface LabelAssignment {
  email_id: string
  labels: string[]
  confidences: Record<string, number>
  reasons: Record<string, string>
  is_cc: boolean
  assigned_at: string
  assigned_by: 'ai' | 'user'
}

export interface LabelsResponse {
  labels: Label[]
  count: number
}

export interface RulesResponse {
  rules: LabelingRule[]
  count: number
}

export interface CreateLabelPayload {
  name: string
  color?: string
  description?: string
  is_favorite?: boolean
  is_project?: boolean
  project_name?: string | null
  project_number?: string | null
  project_abbreviation?: string | null
  subject_prefix?: string | null
  ai_prompt?: string
}

export interface UpdateLabelPayload {
  color?: string
  description?: string
  is_favorite?: boolean
  is_project?: boolean
  project_name?: string | null
  project_number?: string | null
  project_abbreviation?: string | null
  subject_prefix?: string | null
  ai_prompt?: string
}

export interface CreateRulePayload {
  label_name: string
  condition_type: 'sender' | 'subject' | 'body' | 'cc' | 'recipient'
  condition_value: string
  priority?: number
  confidence?: number
}

/** Set of default (exclusive) label names — exactly 1 per email */
export const DEFAULT_LABEL_NAMES = new Set(['Action', 'FYI', 'Noise'])

/** Display names for default labels, per language */
const LABEL_DISPLAY_NAMES_BY_LANG: Record<string, Record<string, string>> = {
  fr: { FYI: 'Info', Noise: 'Bruit' },
  en: { FYI: 'Info', Noise: 'Noise' },
  de: { FYI: 'Info', Noise: 'Werbung' },
  es: { FYI: 'Info', Noise: 'Ruido' },
}

/** Get the display name for a label, respecting the current UI language */
export function getLabelDisplayName(name: string): string {
  const lang = (localStorage.getItem('agentys_language') ?? i18n.language ?? 'fr').slice(0, 2)
  const map = LABEL_DISPLAY_NAMES_BY_LANG[lang] ?? LABEL_DISPLAY_NAMES_BY_LANG.fr
  return map[name] ?? name
}

/** Check if a label name is a default (classification) label */
export function isDefaultLabel(name: string): boolean {
  return DEFAULT_LABEL_NAMES.has(name)
}

// Pre-built label definitions (synced with backend)
export const DEFAULT_LABELS: Omit<Label, 'created_at' | 'rules'>[] = [
  {
    name: 'Action',
    color: '#dc2626', // Red
    description: 'Emails nécessitant une action de votre part',
    is_default: true,
    is_favorite: true,
  },
  {
    name: 'FYI',
    color: '#3b82f6', // Blue
    description: 'Emails pour information uniquement (CC, newsletters informatives)',
    is_default: true,
    is_favorite: true,
  },
  {
    name: 'Noise',
    color: '#6b7280', // Grey
    description: 'Promotions, newsletters, automated junk',
    is_default: true,
    is_favorite: false, // Not a favorite by default
  },
]

// Label colors palette for custom labels
export const LABEL_COLORS = [
  '#dc2626', // Red
  '#ea580c', // Orange
  '#eab308', // Yellow
  '#22c55e', // Green
  '#0d9488', // Teal
  '#3b82f6', // Blue
  '#8b5cf6', // Purple
  '#ec4899', // Pink
  '#6b7280', // Grey
  '#1f2937', // Dark
]
