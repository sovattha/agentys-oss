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

import { useTranslation } from 'react-i18next';
import './AIProgressBar.css';

export type AIStage = 'idle' | 'analyse' | 'redaction' | 'critique' | 'done';

interface AIProgressBarProps {
  stage: AIStage;
  visible: boolean;
}

const STAGES: { key: AIStage; labelKey: string; color: string }[] = [
  { key: 'analyse', labelKey: 'stage_analysis', color: '#3b82f6' },
  { key: 'redaction', labelKey: 'stage_drafting', color: '#8b5cf6' },
  { key: 'critique', labelKey: 'stage_critique', color: '#22c55e' },
];

export function AIProgressBar({ stage, visible }: AIProgressBarProps) {
  const { t } = useTranslation('common');
  if (!visible || stage === 'idle') return null;

  const activeIndex = STAGES.findIndex(s => s.key === stage);

  return (
    <div className="ai-progress-bar" title={stage === 'done' ? t('done') : t('stage_in_progress', { stage: STAGES[activeIndex] ? t(STAGES[activeIndex].labelKey) : '' })}>
      {STAGES.map((s, i) => {
        const isDone = stage === 'done' || i < activeIndex;
        const isActive = i === activeIndex && stage !== 'done';
        return (
          <div
            key={s.key}
            className={`ai-progress-segment ${isDone ? 'done' : ''} ${isActive ? 'active' : ''}`}
            style={{ '--segment-color': s.color } as React.CSSProperties}
          >
            {isActive && <div className="ai-progress-pulse" />}
          </div>
        );
      })}
    </div>
  );
}
