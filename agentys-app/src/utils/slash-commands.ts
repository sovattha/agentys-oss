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

/**
 * Slash Commands — single shared source of truth
 *
 * Used by: PendingDraftDetail, ReplyComposer, NewMessageModal
 */

export interface SlashCommand {
  command: string
  /** Fallback display label — used when `labelKey` is absent or unresolved. */
  label: string
  /** i18n key (compose namespace) resolved at render time via `t(labelKey, label)`.
   *  Module-level tables must not bake translations at import time (language
   *  switches at runtime) — same pattern as QUICK_STEP_TEMPLATE_VARIABLES. */
  labelKey?: string
  /** LLM prompt payload — intentionally NOT localized. */
  instruction: string
  /** Group displayed in the menu */
  group?: string
  /** If true: embed the existing body as notes in the instruction (/expand mode) */
  expand?: boolean
  /** Highlighted as the primary chip (green/teal pill in AICommandMenu) */
  featured?: boolean
}

// ── Contextual detection (without LLM) ────────────────────────────────────────

const BINARY_PATTERNS = [
  // Tutoiement — présent, conditionnel, futur
  /peux-tu|veux-tu|viendrais-tu|serais-tu|pourrais-tu|pourras-tu|acceptes?-tu|accepterais-tu|es-tu disponible/i,
  // Vouvoiement
  /pouvez-vous|voulez-vous|viendriez-vous|seriez-vous|pourriez-vous|pourrez-vous|êtes-vous disponible|accepteriez-vous/i,
  // Formes neutres
  /est-ce (que|possible)|serait-il possible|auriez-vous le temps|avez-vous le temps/i,
  // Invitation directe
  /je (vous |t[''])invite|on se voit|on s['']appelle|on se retrouve|tu es (dispo|disponible)|vous êtes (dispo|disponible)/i,
]

const EXCLUSION_PATTERNS = /combien|quand|pourquoi|comment|\bquel(le)?s?\b|où\b/i

/** Extracts the last 3 non-empty sentences from a text */
function lastSentences(text: string, n = 3): string {
  return text
    .replace(/<[^>]*>/g, ' ')
    .split(/[.!?]+/)
    .map(s => s.trim())
    .filter(Boolean)
    .slice(-n)
    .join('. ')
}

/**
 * Returns true when the email body looks like a binary (yes/no) question.
 * Used by PendingDraftDetail to skip pre-generated draft body for these cases.
 */
export function isBinaryQuestion(emailBody: string): boolean {
  if (!emailBody || emailBody.length > 2000) return false

  const tail = lastSentences(emailBody, 3)

  // Exclude open-ended questions (who/what/how/how many…)
  if (EXCLUSION_PATTERNS.test(tail)) return false

  return BINARY_PATTERNS.some(p => p.test(tail))
}

const IDEES_INSTRUCTION = 'Transform these notes into an email. Adapt the tone to the content: formal if the notes are professional, casual if they are informal. Address by first name if available. No "Subject:" line. Never refuse — always produce an email, even from very short or casual notes.'

// ── Single shared command list ─────────────────────────────────────────────

export const SLASH_COMMANDS: SlashCommand[] = [
  { command: '/expand', label: 'Draft from notes', labelKey: 'cmd_expand', instruction: IDEES_INSTRUCTION, group: 'Expand', expand: true, featured: true },
]

// ── Compose-only presets (NewMessageModal AI popup) ─────────────────────────
// Kept separate from SLASH_COMMANDS to avoid polluting Reply / PendingDraft
// contexts where these instructions don't make sense.
export const COMPOSE_PRESETS: SlashCommand[] = [
  {
    command: '/meeting',
    label: 'Demander une réunion',
    labelKey: 'cmd_meeting',
    instruction: 'Write a polite, concise email asking the recipient for a meeting. Propose 2-3 options (e.g. early next week) and state the purpose in one short sentence. Match the tone of the conversation language.',
    group: 'Presets',
  },
  {
    command: '/thanks',
    label: 'Remercier',
    labelKey: 'cmd_thanks',
    instruction: 'Write a short, warm thank-you email. One paragraph, sincere, no over-the-top language. Match the tone of the conversation language.',
    group: 'Presets',
  },
  {
    command: '/decline',
    label: 'Décliner poliment',
    labelKey: 'cmd_decline',
    instruction: 'Write a polite, firm email declining the request. Brief reason, no apologies-cascade, leave the door open for the future. Match the tone of the conversation language.',
    group: 'Presets',
  },
  {
    command: '/followup',
    label: 'Relancer',
    labelKey: 'cmd_followup',
    instruction: 'Write a short, friendly follow-up email asking for an update on the prior thread. Reference the original ask in one line, no guilt-tripping. Match the tone of the conversation language.',
    group: 'Presets',
  },
]
