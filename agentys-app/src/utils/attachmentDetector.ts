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
 * Forgotten Attachment Detector
 *
 * Pure regex detection — no LLM needed.
 * Scans user-authored text (excluding quoted replies) for mentions of
 * attachments in French and English. Returns the matched keyword for
 * display in the reminder modal.
 */

// ── Patterns ────────────────────────────────────────────────────────────────
// Each entry: [regex, human-readable label shown in the modal]
const ATTACHMENT_PATTERNS: Array<[RegExp, string]> = [
  // ── French explicit ──
  [/\bpi[èe]ce[s]?\s*jointe[s]?\b/i, 'pièce jointe'],
  [/\bp\.?\s*j\.?\b/i, 'P.J.'],
  [/\bci[\s-]?joint[es]?\b/i, 'ci-joint'],
  [/\ben\s+annexe\b/i, 'en annexe'],
  [/\bvous\s+trouverez\s+(ci[\s-]?joint|joint|en\s+annexe)/i, 'vous trouverez joint'],
  [/\bje\s+(vous\s+)?(joins|envoie|transmets|fais\s+suivre)\s+(le|la|les|un|une|mon|mes|ce|cette)\s+(fichier|document|rapport|contrat|facture|devis|photo|image|pr[ée]sentation|plan|dossier|tableur|feuille|pdf)/i, 'fichier joint'],
  [/\b(voici|voir)\s+(le|la|les|mon|mes|notre|nos|ce|cette)\s+(fichier|document|rapport|contrat|facture|devis|photo|image|pr[ée]sentation|plan|dossier|tableur|feuille|pdf)/i, 'document joint'],
  [/\b(le|la)\s+(fichier|document|rapport)\s+(joint|attach[ée]|ci[\s-]?joint)/i, 'document joint'],
  [/\ben\s+pi[èe]ce\b/i, 'en pièce'],

  // ── English explicit ──
  [/\battach(ed|ment|ments|ing)\b/i, 'attachment'],
  [/\b(find|see|per)\s+attach/i, 'see attached'],
  [/\benclosed\s+(please\s+find|herewith|is|are)\b/i, 'enclosed'],
  [/\bi('m|\s+am)\s+attach/i, 'attaching'],
]

// ── Quoted-text stripper ────────────────────────────────────────────────────
// Removes lines that are part of quoted replies so we only scan user text.
// Covers: > prefix, "On ... wrote:", "Le ... a écrit :", "-----" separators
function stripQuotedText(text: string): string {
  const lines = text.split('\n')
  const result: string[] = []

  for (const line of lines) {
    // Stop at quoted-reply markers
    if (/^>/.test(line)) continue
    if (/^On .+ wrote:$/i.test(line.trim())) break
    if (/^Le .+ a [ée]crit\s*:$/i.test(line.trim())) break
    if (/^-{3,}/.test(line.trim())) break
    if (/^_{3,}/.test(line.trim())) break
    result.push(line)
  }

  return result.join('\n')
}

// ── Public API ──────────────────────────────────────────────────────────────

export interface AttachmentDetectionResult {
  /** Whether an attachment mention was detected */
  detected: boolean
  /** The human-readable keyword that was matched (for display) */
  keyword: string
  /** The raw matched text from the body */
  matchedText: string
}

/**
 * Scan email body for forgotten-attachment keywords.
 *
 * @param body      The email body text (plain text or stripped HTML)
 * @param hasAttachments  Whether the email already has attachments
 * @returns Detection result with matched keyword, or `{ detected: false }` if clean.
 */
export function detectForgottenAttachment(
  body: string,
  hasAttachments: boolean,
): AttachmentDetectionResult {
  // If attachments are already present, no reminder needed
  if (hasAttachments) {
    return { detected: false, keyword: '', matchedText: '' }
  }

  const cleanBody = stripQuotedText(body)

  for (const [pattern, label] of ATTACHMENT_PATTERNS) {
    const match = cleanBody.match(pattern)
    if (match) {
      return {
        detected: true,
        keyword: label,
        matchedText: match[0],
      }
    }
  }

  return { detected: false, keyword: '', matchedText: '' }
}
