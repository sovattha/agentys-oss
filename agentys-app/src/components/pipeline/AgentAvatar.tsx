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
