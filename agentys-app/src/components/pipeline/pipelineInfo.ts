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
 * PipelineInfo — post-generation metadata consumed by RecapBanner and
 * PipelineDisclosure. Built from the backend /pending-drafts payload plus
 * the WebSocket-derived critique snapshot (score/motive).
 *
 * Only the reply pipeline (Drafter → Critic) populates this today. The
 * compose flow goes through a simpler single-LLM path and therefore does
 * not produce a PipelineInfo — see GitHub issue #235.
 */
export interface PipelineInfo {
  classification?: string
  classification_color?: string
  classification_reason?: string
  routing_tier?: string
  draft_v1?: string
  critique?: string
  was_corrected?: boolean
  corrections_count?: number
  correction_details?: string[]
  revision_failed?: boolean
  memory_trace?: Record<string, unknown> | null
  /** Final critique score (0-100). Populated from WS critique_complete payload. */
  critique_score?: number
  /** Score of the V1 critique before revision, when applicable. */
  initial_critique_score?: number
  /** Derived motive keyword used by the RecapBanner narrative ("direct", "long"…). */
  critique_motive?: string
  /** True when the Critic produced a V2 via revision. */
  revised?: boolean
}

export const CLASSIFICATION_COLORS: Record<string, string> = {
  action: '#dc2626',
  fyi: '#3b82f6',
  noise: '#6b7280',
  unlabeled: '#9ca3af',
  urgent: '#dc2626',
  important: '#dc2626',
  normal: '#3b82f6',
  newsletter: '#6b7280',
  promo: '#6b7280',
  cc_only: '#9ca3af',
  spam: '#6b7280',
}

interface FullDraftForPipeline {
  classification?: string
  classification_reason?: string
  routing_tier?: string
  draft_v1?: string
  draft_body?: string
  critique?: string
  memory_trace?: Record<string, unknown> | null
  correction_details?: string[]
}

interface LiveCritiqueSnapshot {
  score?: number
  initialScore?: number
  motive?: string
}

/** Build PipelineInfo from a pending-draft API response plus optional WS critique snapshot. */
export function buildPipelineInfo(
  fullDraft: FullDraftForPipeline,
  liveCritique?: LiveCritiqueSnapshot | null,
): PipelineInfo {
  const classRaw = fullDraft.classification || 'Unlabeled'
  const classKey = classRaw.toLowerCase()
  const classColor = CLASSIFICATION_COLORS[classKey] || '#9ca3af'
  const classDisplay = classRaw.charAt(0).toUpperCase() + classRaw.slice(1).toLowerCase()
  const wasCorrected = !!(
    fullDraft.draft_v1 && fullDraft.draft_body && fullDraft.draft_v1 !== fullDraft.draft_body
  )
  const corrCount = wasCorrected
    ? Math.max(1, Math.round(Math.abs(fullDraft.draft_v1!.length - fullDraft.draft_body!.length) / 20))
    : 0
  const critiqueText = fullDraft.critique || ''
  const critiqueRejected = critiqueText.toLowerCase().includes('rejet')
  const revisionFailed = critiqueRejected && !wasCorrected

  return {
    classification: classDisplay,
    classification_color: classColor,
    classification_reason: fullDraft.classification_reason || '',
    routing_tier: fullDraft.routing_tier,
    draft_v1: fullDraft.draft_v1,
    critique: fullDraft.critique,
    was_corrected: wasCorrected,
    corrections_count: fullDraft.correction_details?.length || corrCount,
    correction_details: fullDraft.correction_details,
    revision_failed: revisionFailed,
    memory_trace: (fullDraft.memory_trace as Record<string, unknown> | null) ?? null,
    critique_score: liveCritique?.score,
    initial_critique_score: liveCritique?.initialScore,
    critique_motive: liveCritique?.motive,
    revised: wasCorrected,
  }
}
