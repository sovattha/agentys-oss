import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { API_URL } from '../config';
import { getAuthHeaders } from '../services/authToken';
import './TrainingCommon.css';

/**
 * Issue #187 — Style observé depuis l'outbox.
 *
 * Affiche les métriques statistiques de style inférées par StyleInferenceService
 * (backend) à partir des emails envoyés. Remplace les sliders explicites de
 * Formalité et Niveau d'émotion qui produisaient une prose caricaturale.
 *
 * Lecture seule. Bouton "Re-analyser mon style" déclenche POST /api/style/reanalyze.
 */

interface StyleMetrics {
  avg_sentence_length: number;
  sentence_length_variance: number;
  vocabulary_density: number;
  formality_score: number;
  emoji_rate: number;
  exclamation_rate: number;
  bullet_usage_rate: number;
  avg_paragraph_count: number;
}

interface ReanalyzeResponse {
  status: string;
  account_id: number;
  email_count: number;
  metrics: StyleMetrics;
  examples_count: number;
}

interface StyleObservedFromOutboxProps {
  accountId: number | null;
}

const formatPercent = (value: number): string => `${Math.round(value * 100)}%`;
const formatRatio = (value: number): string => value.toFixed(2);

function describeFormality(score: number, t: (k: string) => string): string {
  if (score >= 0.75) return t('style_observed_formal');
  if (score <= 0.3) return t('style_observed_casual');
  return t('style_observed_mixed');
}

export function StyleObservedFromOutbox({ accountId }: StyleObservedFromOutboxProps) {
  const { t } = useTranslation('agents');
  const [metrics, setMetrics] = useState<StyleMetrics | null>(null);
  const [emailCount, setEmailCount] = useState(0);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadProfile = useCallback(async () => {
    if (!accountId) return;
    try {
      const response = await fetch(
        `${API_URL}/api/writing-style/profile?account_id=${accountId}`,
        { headers: getAuthHeaders() },
      );
      if (!response.ok) return;
      const json = await response.json();
      if (json?.profile) {
        setMetrics({
          avg_sentence_length: json.profile.avg_sentence_length ?? 0,
          sentence_length_variance: json.profile.sentence_length_variance ?? 0,
          vocabulary_density: json.profile.vocabulary_density ?? 0,
          formality_score: json.profile.formality_score ?? 0.5,
          emoji_rate: json.profile.emoji_frequency ?? 0,
          exclamation_rate: json.profile.exclamation_rate ?? 0,
          bullet_usage_rate: json.profile.bullet_list_ratio ?? 0,
          avg_paragraph_count: json.profile.avg_paragraph_count ?? 0,
        });
        setEmailCount(json.profile.email_count ?? 0);
      }
    } catch {
      /* silent — bouton "Re-analyser" reste disponible */
    }
  }, [accountId]);

  useEffect(() => {
    loadProfile();
  }, [loadProfile]);

  const handleReanalyze = useCallback(async () => {
    if (!accountId) return;
    setIsAnalyzing(true);
    setError(null);
    try {
      const response = await fetch(`${API_URL}/api/style/reanalyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ account_id: accountId }),
      });
      const json = (await response.json().catch(() => null)) as ReanalyzeResponse | { error?: string } | null;
      if (!response.ok) {
        const message = (json as { error?: string })?.error ?? t('style_observed_error_generic');
        setError(message);
        return;
      }
      if (json && 'metrics' in json) {
        setMetrics(json.metrics);
        setEmailCount(json.email_count);
      }
    } catch {
      setError(t('style_observed_error_network'));
    } finally {
      setIsAnalyzing(false);
    }
  }, [accountId, t]);

  if (!accountId) {
    return null;
  }

  return (
    <div className="style-observed" aria-labelledby="style-observed-title">
      <div className="pillar-section-header">
        <span id="style-observed-title" className="pillar-section-title">
          {t('style_observed_title')}
        </span>
        <span className="pillar-section-subtitle">{t('style_observed_subtitle')}</span>
      </div>

      {metrics ? (
        <dl className="style-observed-metrics">
          <div className="style-observed-metric">
            <dt>{t('style_observed_formality')}</dt>
            <dd>
              <strong>{formatPercent(metrics.formality_score)}</strong>
              <span className="style-observed-hint">{describeFormality(metrics.formality_score, t)}</span>
            </dd>
          </div>
          <div className="style-observed-metric">
            <dt>{t('style_observed_sentence_length')}</dt>
            <dd>
              <strong>{metrics.avg_sentence_length.toFixed(0)} {t('style_observed_words')}</strong>
              <span className="style-observed-hint">
                ±{metrics.sentence_length_variance.toFixed(1)}
              </span>
            </dd>
          </div>
          <div className="style-observed-metric">
            <dt>{t('style_observed_vocabulary')}</dt>
            <dd>
              <strong>{formatRatio(metrics.vocabulary_density)}</strong>
            </dd>
          </div>
          <div className="style-observed-metric">
            <dt>{t('style_observed_emojis')}</dt>
            <dd>
              <strong>{formatRatio(metrics.emoji_rate)}</strong>
              <span className="style-observed-hint">{t('style_observed_per_email')}</span>
            </dd>
          </div>
        </dl>
      ) : (
        <p className="style-observed-empty">{t('style_observed_no_data')}</p>
      )}

      <div className="style-observed-footer">
        <span className="pillar-field-hint">
          {emailCount > 0
            ? t('style_observed_email_count', { count: emailCount })
            : t('style_observed_no_analysis')}
        </span>
        <button
          type="button"
          className="style-observed-reanalyze"
          onClick={handleReanalyze}
          disabled={isAnalyzing}
          aria-busy={isAnalyzing}
        >
          {isAnalyzing ? t('style_observed_analyzing') : t('style_observed_reanalyze')}
        </button>
      </div>

      {error && (
        <div className="style-observed-error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
