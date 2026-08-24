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
import './TrainingCommon.css';
import './PillarAutoLabel.css';
import './onboarding/LearningInsights.css';

interface PillarAutoLabelReadOnlyProps {
  statistics?: Record<string, number>;
}

const DEFAULT_LABELS: { key: string; nameKey: string; descKey: string; color: string; icon: string }[] = [
  { key: 'action', nameKey: 'step3_autolabel_action', descKey: 'step3_autolabel_action_desc', color: '#ef4444', icon: '!' },
  { key: 'fyi', nameKey: 'step3_autolabel_fyi', descKey: 'step3_autolabel_fyi_desc', color: '#3b82f6', icon: 'i' },
  { key: 'noise', nameKey: 'step3_autolabel_noise', descKey: 'step3_autolabel_noise_desc', color: '#94a3b8', icon: '~' },
];

/**
 * Auto-label pillar for onboarding.
 * Shows the 3 default labels (Action, Info, Noise) with distribution stats.
 * Custom labels are created manually by the user in Step4SmartOrg / settings.
 */
export function PillarAutoLabelReadOnly({ statistics }: PillarAutoLabelReadOnlyProps) {
  const { t } = useTranslation('onboarding');

  const stats = statistics || {};
  const total = Object.values(stats).reduce((sum, v) => sum + v, 0) || 100;

  return (
    <div className="pillar-autolabel">
      <div className="pillar-section-header">
        <span className="pillar-section-title">{t('step3_autolabel_intro')}</span>
      </div>

      <div className="s3-autolabel-defaults">
        {DEFAULT_LABELS.map(({ key, nameKey, descKey, color, icon }) => {
          const pct = total > 0 ? Math.round(((stats[key] || 0) / total) * 100) : 0;
          return (
            <div key={key} className="s3-autolabel-card">
              <div className="s3-autolabel-card-header">
                <span className="s3-autolabel-dot" style={{ background: color }}>{icon}</span>
                <div className="s3-autolabel-card-text">
                  <span className="s3-autolabel-name">{t(nameKey)}</span>
                  <span className="s3-autolabel-desc">{t(descKey)}</span>
                </div>
                {pct > 0 && <span className="s3-autolabel-pct">{pct}%</span>}
              </div>
              {pct > 0 && (
                <div className="s3-autolabel-bar">
                  <div className="s3-autolabel-bar-fill" style={{ width: `${pct}%`, background: color }} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
