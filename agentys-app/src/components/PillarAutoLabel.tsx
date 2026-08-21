import { useTranslation } from 'react-i18next';
import { getLabelDisplayName } from '../types/labels';
import { useLabels } from '../hooks/useLabels';
import type { AutoLabelLabelStat } from '../types/training';
import './TrainingCommon.css';
import './PillarAutoLabel.css';

interface AutoLabelRule {
  id: string;
  rule_text: string;
  category: string;
  // 0..1, or null when the rule hasn't matched any email yet (no data → no %).
  confidence: number | null;
  active: boolean;
  created_at?: string;
  total_matches?: number;
  total_corrections?: number;
}

interface AutoLabelCategory {
  id: string;
  name: string;
  description: string;
  count: number;
  accuracy?: number;
  total_matches?: number;
  total_corrections?: number;
  by_label?: AutoLabelLabelStat[];
  items: AutoLabelRule[];
}

interface PillarAutoLabelProps {
  category: AutoLabelCategory | null;
}

/**
 * Read-only display of auto-label rules detected during onboarding.
 * These are system rules (Noise/FYI/Action) — not user-editable.
 */
export function PillarAutoLabel({ category }: PillarAutoLabelProps) {
  const { t } = useTranslation('agents');
  const { getLabelByName } = useLabels();

  const items = category?.items ?? [];
  const accuracy = category?.accuracy;
  // Per-label email volume across all folders. Every label is shown — even
  // low-volume ones — and the bar is its share of the total labelled mail.
  const byLabel = category?.by_label ?? [];
  const totalLabeled = byLabel.reduce((sum, s) => sum + s.email_count, 0);

  return (
    <div className="pillar-autolabel">
      <div className="pillar-section-header">
        <span className="pillar-section-title">{t('autolabel_section_title')}</span>
      </div>

      {items.length === 0 && byLabel.length === 0 ? (
        <div className="pillar-empty-state">
          <div className="pillar-empty-icon">
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M11.5 2.5l6 6-7.5 7.5-6-6V4a1.5 1.5 0 011.5-1.5h4.5z" />
              <circle cx="7.5" cy="7.5" r="1" fill="currentColor" stroke="none" />
            </svg>
          </div>
          <span className="pillar-empty-title">{t('autolabel_empty')}</span>
          <span className="pillar-empty-hint">{t('autolabel_empty_hint')}</span>
        </div>
      ) : (
        <>
          {byLabel.length > 0 && (
            <div className="autolabel-breakdown">
              {byLabel.map(stat => (
                <div key={stat.label} className="autolabel-label-stat">
                  <span
                    className="autolabel-label-stat-name"
                    style={{ '--label-color': getLabelByName(stat.label)?.color || '#6b7280' } as React.CSSProperties}
                  >
                    {getLabelDisplayName(stat.label)}
                  </span>
                  <div className="autolabel-label-stat-bar">
                    <div
                      className="autolabel-label-stat-fill"
                      style={{ width: totalLabeled > 0 ? `${(stat.email_count / totalLabeled) * 100}%` : '0%' }}
                    />
                  </div>
                  <span className="autolabel-label-stat-count">
                    {totalLabeled > 0 && (
                      <span className="autolabel-label-stat-pct">
                        {t('autolabel_label_share', { value: Math.round((stat.email_count / totalLabeled) * 100) })}
                      </span>
                    )}
                    {t('autolabel_label_count', { count: stat.email_count })}
                  </span>
                </div>
              ))}
            </div>
          )}

          {accuracy != null && (
            <div className="autolabel-accuracy">
              <span className="autolabel-accuracy-label">
                {t('autolabel_accuracy', { value: Math.round(accuracy) })}
              </span>
              <div className="autolabel-accuracy-bar">
                <div
                  className="autolabel-accuracy-fill"
                  style={{ width: `${Math.min(Math.round(accuracy), 100)}%` }}
                />
              </div>
            </div>
          )}

          {items.length > 0 && (
            <div className="autolabel-rule-list">
              {items.map(rule => (
                <div key={rule.id} className="autolabel-rule-item">
                  <span className="autolabel-rule-text">{rule.rule_text}</span>
                  {rule.confidence != null && (
                    <span
                      className="autolabel-rule-precision"
                      title={t('autolabel_rule_precision_title', { count: rule.total_matches ?? 0 })}
                    >
                      {t('autolabel_rule_precision', { value: Math.round(rule.confidence * 100) })}
                    </span>
                  )}
                  <span
                    className="autolabel-label-badge"
                    style={{ '--label-color': getLabelByName(rule.category)?.color || '#6b7280' } as React.CSSProperties}
                  >
                    {getLabelDisplayName(rule.category)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
