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
