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
import type { AgentPersona } from '../../config/agentPersonas';
import './AgentAvatar.css';

interface AgentAvatarProps {
  persona: AgentPersona;
  size?: number;
}

/**
 * Styled avatar circle with initials and agent-specific color.
 * No stock photos — uses initials with a colored background.
 */
export function AgentAvatar({ persona, size = 28 }: AgentAvatarProps) {
  const { t } = useTranslation('agents');
  const role = persona.roleKey ? t(persona.roleKey, persona.role) : persona.role;
  return (
    <div
      className="agent-avatar"
      style={{
        '--avatar-color': persona.color,
        '--avatar-size': `${size}px`,
      } as React.CSSProperties}
      title={`${persona.name} — ${role}`}
      aria-label={`${persona.name}, ${role}`}
    >
      <span className="agent-avatar-initials">{persona.initials}</span>
    </div>
  );
}
