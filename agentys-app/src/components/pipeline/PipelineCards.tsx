/* eslint-disable react-refresh/only-export-components */
import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { getAgentPersona } from '../../config/agentPersonas';
import { AgentAvatar } from './AgentAvatar';
import { ChevronDownIcon } from '../icons/ActionIcons';
import './PipelineCards.css';

// ── Stage definitions ────────────────────────────────────────────────────────

export const PIPELINE_STAGES = [
  { key: 'classification', labelKey: 'pipeline_stage_classification', shortLabelKey: 'pipeline_stage_classification_short' },
  { key: 'redaction', labelKey: 'pipeline_stage_drafting', shortLabelKey: 'pipeline_stage_drafting_short' },
  { key: 'optimisation', labelKey: 'pipeline_stage_critique', shortLabelKey: 'pipeline_stage_critique_short' },
  { key: 'finalisation', labelKey: 'pipeline_stage_finishing', shortLabelKey: 'pipeline_stage_finishing_short' },
] as const;

export type StageKey = typeof PIPELINE_STAGES[number]['key'];
export type StageStatus = 'pending' | 'active' | 'complete';

// ── getStageStatus ───────────────────────────────────────────────────────────

export function getStageStatus(
  stageKey: StageKey,
  activeStageName: string | null,
  isComplete: boolean,
): StageStatus {
  if (isComplete) return 'complete';
  if (!activeStageName) return stageKey === 'classification' ? 'active' : 'pending';

  const stageOrder = PIPELINE_STAGES.map(s => s.key);
  const activeIdx = stageOrder.indexOf(activeStageName as StageKey);
  const currentIdx = stageOrder.indexOf(stageKey);

  if (activeIdx < 0) return 'pending';
  if (currentIdx < activeIdx) return 'complete';
  if (currentIdx === activeIdx) return 'active';
  return 'pending';
}

// ── StageIcon (4 SVG icons) ──────────────────────────────────────────────────

export function StageIcon({ stageKey, size = 16 }: { stageKey: StageKey; size?: number }) {
  const props = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };

  switch (stageKey) {
    case 'classification':
      return (
        <svg aria-hidden="true" {...props}>
          <circle cx="11" cy="11" r="8" />
          <path d="M21 21l-4.35-4.35" />
        </svg>
      );
    case 'redaction':
      return (
        <svg aria-hidden="true" {...props}>
          <path d="M12 19l7-7 3 3-7 7-3-3z" />
          <path d="M18 13l-1.5-7.5L2 2l3.5 14.5L13 18l5-5z" />
          <path d="M2 2l7.586 7.586" />
          <circle cx="11" cy="11" r="2" />
        </svg>
      );
    case 'optimisation':
      return (
        <svg aria-hidden="true" {...props}>
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        </svg>
      );
    case 'finalisation':
      return (
        <svg aria-hidden="true" {...props}>
          <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
        </svg>
      );
  }
}

// ── StageFlow (horizontal progress during generation) ────────────────────────

export function StageFlow({ activeStageName, isComplete }: { activeStageName: string | null; isComplete: boolean }) {
  const { t: tCommon } = useTranslation('common');
  return (
    <div className="pipe-stage-flow" role="progressbar" aria-label={tCommon('ai_agents_title')}>
      {PIPELINE_STAGES.map((stage, i) => {
        const status = getStageStatus(stage.key, activeStageName, isComplete);
        return (
          <React.Fragment key={stage.key}>
            {i > 0 && (
              <div className={`pipe-stage-connector pipe-stage-connector--${status === 'pending' ? 'pending' : 'active'}`} />
            )}
            <div className={`pipe-stage-card pipe-stage-card--${status}`}>
              <div className="pipe-stage-icon-frame">
                <StageIcon stageKey={stage.key} size={14} />
                {status === 'complete' && (
                  <span className="pipe-stage-check-overlay">
                    <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#22c55e" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M20 6L9 17l-5-5" />
                    </svg>
                  </span>
                )}
              </div>
              <span className="pipe-stage-label">{tCommon(stage.shortLabelKey)}</span>
            </div>
          </React.Fragment>
        );
      })}
    </div>
  );
}

// ── Badge types for PipelineCard ─────────────────────────────────────────────

type BadgeVariant = 'approved' | 'rejected' | 'corrected' | 'clean';

interface PipelineCardProps {
  stageKey: StageKey;
  title: string;
  badge?: { label: string; variant: BadgeVariant };
  children: React.ReactNode;
  defaultOpen?: boolean;
  index?: number;
  agentId?: string;
}

// ── PipelineCard (accordion) ─────────────────────────────────────────────────

export function PipelineCard({ stageKey, title, badge, children, defaultOpen = false, index = 0, agentId }: PipelineCardProps) {
  const [open, setOpen] = useState(defaultOpen);
  const persona = agentId ? getAgentPersona(agentId) : null;

  return (
    <div className="pipe-card" style={{ animationDelay: `${index * 0.06}s` }}>
      <button
        type="button"
        className={`pipe-card-header${open ? ' pipe-card-header--open' : ''}`}
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        {persona ? (
          <AgentAvatar persona={persona} size={22} />
        ) : (
          <div className="pipe-card-icon-frame">
            <StageIcon stageKey={stageKey} size={14} />
          </div>
        )}
        <span className="pipe-card-title">{title}</span>
        {persona && <span className="pipe-card-agent-name">{persona.name}</span>}
        {badge && (
          <span className={`pipe-card-badge pipe-card-badge--${badge.variant}`}>
            {badge.label}
          </span>
        )}
        <span className={`pipe-card-chevron${open ? ' pipe-card-chevron--open' : ''}`}>
          <ChevronDownIcon size={12} />
        </span>
      </button>
      {open && (
        <div className="pipe-card-content">
          {children}
        </div>
      )}
    </div>
  );
}

// ── PipelineConnector (vertical line between accordion cards) ────────────────

export function PipelineConnector() {
  return <div className="pipe-connector" />;
}
