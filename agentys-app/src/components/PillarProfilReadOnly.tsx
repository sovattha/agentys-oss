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
import type { UserProfile } from '../types/onboarding';
import './TrainingCommon.css';
import './PillarProfil.css';
import './onboarding/LearningInsights.css';

interface PillarProfilReadOnlyProps {
  profile: UserProfile;
  languages: string[];
}

/**
 * Read-only version of PillarProfil, mirroring the Settings identity layout.
 * Shows: full name, company/position side-by-side, languages as tags.
 */
export function PillarProfilReadOnly({ profile, languages }: PillarProfilReadOnlyProps) {
  const { t } = useTranslation('onboarding');

  return (
    <div className="pillar-profil">
      <div className="pillar-section-header">
        <span className="pillar-section-title">{t('step3_section_identity')}</span>
      </div>

      <div className="pillar-profil-form">
        {/* Nom complet */}
        {profile.user_name && (
          <div className="pillar-field">
            <label className="pillar-field-label">{t('step3_field_name')}</label>
            <div className="pillar-field-readonly">{profile.user_name}</div>
          </div>
        )}

        {/* Prénom usuel (only shown when different from the legal full name) */}
        {profile.preferred_name && profile.preferred_name !== profile.user_name && (
          <div className="pillar-field">
            <label className="pillar-field-label">{t('step3_field_preferred_name')}</label>
            <div className="pillar-field-readonly">{profile.preferred_name}</div>
          </div>
        )}

        {/* Entreprise + Poste côte-à-côte */}
        {(profile.signature?.company || profile.signature?.title) && (
          <div className="pillar-field-row">
            {profile.signature?.company && (
              <div className="pillar-field">
                <label className="pillar-field-label">{t('step3_field_company')}</label>
                <div className="pillar-field-readonly">{profile.signature.company}</div>
              </div>
            )}
            {profile.signature?.title && (
              <div className="pillar-field">
                <label className="pillar-field-label">{t('step3_field_position')}</label>
                <div className="pillar-field-readonly">{profile.signature.title}</div>
              </div>
            )}
          </div>
        )}

        {/* Langues en tags */}
        {languages.length > 0 && (
          <div className="pillar-field">
            <label className="pillar-field-label">{t('step3_field_languages')}</label>
            <div className="learning-insights-tags" style={{ marginTop: 4 }}>
              {languages.map((l, i) => (
                <span key={i} className="learning-insights-tag">{l.toUpperCase()}</span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
