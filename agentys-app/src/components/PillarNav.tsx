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
import type { Pillar } from '../types/training';
import './PillarNav.css';

interface PillarNavProps {
  activePillar: Pillar;
  onSelect: (p: Pillar) => void;
  /** Override hint text per pillar (uses default i18n keys when not provided) */
  hintOverrides?: Partial<Record<Pillar, string>>;
  /** Show a checkmark indicator on pillars that have detected data */
  detected?: Partial<Record<Pillar, boolean>>;
  /**
   * When true, pillars explicitly marked `detected[id] === false` render a
   * hollow "to configure" status dot (and sr-only label) instead of nothing.
   * Off by default so existing consumers (onboarding) stay unchanged.
   */
  markIncomplete?: boolean;
  /** Restrict visible pillars to this subset. Defaults to all 4. */
  visiblePillars?: Pillar[];
}

function IconProfil() {
  return (
    <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}

function IconStyle() {
  return (
    <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z" />
    </svg>
  );
}

function IconSavoir() {
  return (
    <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
      <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
    </svg>
  );
}

function IconAutolabel() {
  return (
    <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" />
      <line x1="7" y1="7" x2="7.01" y2="7" />
    </svg>
  );
}

const DetectedCheck = () => (
  <svg aria-hidden="true" width="12" height="12" viewBox="0 0 16 16" fill="none">
    <circle cx="8" cy="8" r="7" fill="currentColor" />
    <path d="M5 8l2 2 4-4" stroke="var(--surface-primary, #fff)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const TodoDot = () => (
  <svg aria-hidden="true" width="12" height="12" viewBox="0 0 16 16" fill="none">
    <circle cx="8" cy="8" r="6.25" stroke="currentColor" strokeWidth="1.5" strokeDasharray="2.6 2.4" />
  </svg>
);

const PILLAR_CONFIG: { id: Pillar; labelKey: string; hintKey: string; Icon: () => React.JSX.Element }[] = [
  { id: 'profil', labelKey: 'pillar_profil', hintKey: 'pillar_hint_profil', Icon: IconProfil },
  { id: 'style', labelKey: 'pillar_style', hintKey: 'pillar_hint_style', Icon: IconStyle },
  { id: 'savoir', labelKey: 'pillar_savoir', hintKey: 'pillar_hint_savoir', Icon: IconSavoir },
  { id: 'autolabel', labelKey: 'pillar_autolabel', hintKey: 'pillar_hint_autolabel', Icon: IconAutolabel },
];

export function PillarNav({ activePillar, onSelect, hintOverrides, detected, markIncomplete, visiblePillars }: PillarNavProps) {
  const { t } = useTranslation('agents');

  const visible = visiblePillars
    ? PILLAR_CONFIG.filter(p => visiblePillars.includes(p.id))
    : PILLAR_CONFIG;

  // Override la grille 4-col par défaut quand on a moins d'items
  const gridStyle = visible.length !== 4
    ? { gridTemplateColumns: `repeat(${visible.length}, 1fr)` }
    : undefined;

  return (
    <div className="pillar-nav" style={gridStyle}>
      {visible.map(({ id, labelKey, hintKey, Icon }) => {
        const hint = hintOverrides?.[id] || t(hintKey);
        const isDone = detected?.[id] === true;
        const isTodo = !!markIncomplete && detected?.[id] === false;
        const showStatus = isDone || isTodo;
        return (
          <button
            key={id}
            className={`pillar-nav-card${activePillar === id ? ' active' : ''}`}
            onClick={() => onSelect(id)}
            type="button"
          >
            <span className="pillar-nav-icon"><Icon /></span>
            {showStatus && (
              <span className={`pillar-nav-status ${isDone ? 'is-done' : 'is-todo'}`} aria-hidden="true">
                {isDone ? <DetectedCheck /> : <TodoDot />}
              </span>
            )}
            {showStatus && (
              <span className="pillar-nav-sr">
                {isDone ? t('pillar_status_configured') : t('pillar_status_todo')}
              </span>
            )}
            <span className="pillar-nav-label">{t(labelKey)}</span>
            <span className="pillar-nav-hint">{hint}</span>
          </button>
        );
      })}
    </div>
  );
}
