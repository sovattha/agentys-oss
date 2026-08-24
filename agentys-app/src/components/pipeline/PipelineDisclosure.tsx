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

import { useTranslation } from 'react-i18next'
import { LabelBadge } from '../labels/LabelBadge'
import type { MemoryTrace } from '../../types/training'
import { MemoryTracePanel } from './MemoryTracePanel'
import { PipelineCard, PipelineConnector } from './PipelineCards'
import { PipelineSummary } from './PipelineSummary'
import { CheckIcon } from '../icons/ActionIcons'
import type { PipelineInfo } from './pipelineInfo'

interface PipelineDisclosureProps {
  pipelineInfo: PipelineInfo
  draftId: string
}

/**
 * Accordion disclosure panel rendering the full AI pipeline: classification,
 * drafter V1, critic verdict, post-processing, plus memory trace and summary.
 *
 * Extracted from ReplyComposer so future surfaces (NewMessageModal once
 * issue #235 delivers pipeline data from compose_email) can mount the same
 * disclosure without copying ~100 lines of JSX.
 */
export function PipelineDisclosure({ pipelineInfo, draftId }: PipelineDisclosureProps) {
  const { t } = useTranslation('compose')

  // BUG-G003 fix: normalize routing_tier — strip any "TIER_" prefix, lowercase,
  // and map special values onto the three known display tiers.
  const rawTier = (pipelineInfo.routing_tier || 'standard').toLowerCase().replace(/^tier_/, '')
  const tier = ['simple', 'standard', 'complex'].includes(rawTier)
    ? rawTier
    : rawTier === 'skip'
      ? 'simple'
      : 'complex'

  const critiqueRejected = (pipelineInfo.critique || '').toLowerCase().includes('rejet')

  return (
    <div className="rc-pipeline">
      <div className="rc-pipeline-cards">
        {/* Step 1: Classification */}
        <PipelineCard
          stageKey="classification"
          title={t('pipeline_classification')}
          index={0}
          defaultOpen
          agentId="classifier"
        >
          <div className="rc-tl-meta">
            <LabelBadge
              name={pipelineInfo.classification || 'Unlabeled'}
              color={pipelineInfo.classification_color || '#9ca3af'}
              size="small"
            />
            <span className={`rc-tl-tier tier-${tier}`}>
              {tier === 'simple'
                ? t('tier_simple')
                : tier === 'standard'
                  ? t('tier_standard')
                  : t('tier_complex')}
            </span>
          </div>
          {pipelineInfo.classification_reason && (
            <p className="pipe-classification-reason">{pipelineInfo.classification_reason}</p>
          )}
        </PipelineCard>

        {/* Step 2: Drafter Agent */}
        {pipelineInfo.draft_v1 && (
          <>
            <PipelineConnector />
            <PipelineCard
              stageKey="redaction"
              title={t('pipeline_drafting')}
              index={1}
              agentId="drafter"
            >
              <pre>{pipelineInfo.draft_v1}</pre>
            </PipelineCard>
          </>
        )}

        {/* Step 3: Critic Agent */}
        {pipelineInfo.critique && (
          <>
            <PipelineConnector />
            <PipelineCard
              stageKey="optimisation"
              title={t('pipeline_critique')}
              badge={{
                label: critiqueRejected ? t('badge_rejected') : t('badge_approved'),
                variant: critiqueRejected ? 'rejected' : 'approved',
              }}
              index={2}
              agentId="critic"
            >
              <pre>{pipelineInfo.critique}</pre>
            </PipelineCard>
          </>
        )}

        {/* Step 4: Post-LLM Pipeline */}
        <PipelineConnector />
        <PipelineCard
          stageKey="finalisation"
          title={t('pipeline_post_processing')}
          badge={{
            label: pipelineInfo.revision_failed
              ? t('badge_revision_failed')
              : pipelineInfo.was_corrected
                ? t(
                    (pipelineInfo.corrections_count || 1) > 1
                      ? 'pipeline_corrections_other'
                      : 'pipeline_corrections_one',
                    { count: pipelineInfo.corrections_count || 1 },
                  )
                : t('badge_clean'),
            variant: pipelineInfo.revision_failed
              ? 'rejected'
              : pipelineInfo.was_corrected
                ? 'corrected'
                : 'clean',
          }}
          index={3}
          agentId="postprocessor"
        >
          {pipelineInfo.revision_failed ? (
            <span className="pipe-card-revision-failed">
              <svg
                aria-hidden="true"
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <circle cx="12" cy="12" r="10" />
                <line x1="15" y1="9" x2="9" y2="15" />
                <line x1="9" y1="9" x2="15" y2="15" />
              </svg>
              {t('pipeline_revision_failed')}
            </span>
          ) : pipelineInfo.correction_details && pipelineInfo.correction_details.length > 0 ? (
            <ul className="pipe-correction-list">
              {pipelineInfo.correction_details.map((c, i) => (
                <li key={i} className="pipe-correction-item">
                  <CheckIcon size={10} />
                  {t(`correction_${c}`, c)}
                </li>
              ))}
            </ul>
          ) : pipelineInfo.was_corrected ? (
            <span className="pipe-card-corrections">
              <CheckIcon size={12} />
              {t(
                (pipelineInfo.corrections_count || 1) > 1
                  ? 'pipeline_corrections_other'
                  : 'pipeline_corrections_one',
                { count: pipelineInfo.corrections_count || 1 },
              )}
            </span>
          ) : (
            <span className="pipe-card-no-corrections">{t('pipeline_no_corrections')}</span>
          )}
        </PipelineCard>
      </div>
      <MemoryTracePanel trace={pipelineInfo.memory_trace as MemoryTrace | null | undefined} />
      <PipelineSummary draftId={draftId} />
    </div>
  )
}
