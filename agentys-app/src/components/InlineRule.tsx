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

import { extractContactFromRuleText } from '../utils/ruleText';

interface InlineRuleProps {
  rule: { id: string; rule_text: string; confidence: number; active: boolean };
  onToggle: (id: string, active: boolean) => void;
  onDelete: (id: string) => void;
}

export function InlineRule({ rule, onToggle, onDelete }: InlineRuleProps) {
  // Strip the trailing "pour/for <email>" — the parent card already carries
  // the contact identity, so the suffix is pure repetition here.
  const { stripped: displayText } = extractContactFromRuleText(rule.rule_text);
  return (
    <div className="style-rule-item style-rule-item--inline">
      <button
        type="button"
        className={`pillar-toggle${rule.active ? ' active' : ''}`}
        onClick={() => onToggle(rule.id, rule.active)}
        aria-label={rule.active ? 'Disable' : 'Enable'}
      />
      <span className="style-rule-text">{displayText}</span>
      <div className="pillar-confidence-bar">
        <div
          className="pillar-confidence-fill"
          style={{ width: `${Math.round(rule.confidence * 100)}%` }}
        />
      </div>
      <button
        type="button"
        className="pillar-delete-btn"
        onClick={() => onDelete(rule.id)}
      >
        &#10005;
      </button>
    </div>
  );
}
