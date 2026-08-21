import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { API_URL } from '../../config';
import { getAuthHeaders } from '../../services/authToken';
import './PipelineSummary.css';

interface PipelineSummaryProps {
  draftId: string;
  cachedSummary?: string | null;
}

export function PipelineSummary({ draftId, cachedSummary }: PipelineSummaryProps) {
  const { t } = useTranslation('compose');
  const [summary, setSummary] = useState<string>(cachedSummary || '');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleExplain = async () => {
    if (summary || !draftId) return;
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_URL}/api/pending-drafts/${draftId}/explain`, {
        method: 'POST',
        headers: { ...getAuthHeaders() },
      });
      const data = await res.json();
      if (data.success && data.summary) {
        setSummary(data.summary);
      } else {
        setError(data.error || t('explain_error'));
      }
    } catch {
      setError(t('explain_error'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="pipeline-summary">
      {!summary && !loading && (
        <button type="button" className="pipeline-summary-btn" onClick={handleExplain}>
          <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          {t('explain_button', 'Comprendre ce brouillon')}
        </button>
      )}
      {loading && (
        <div className="pipeline-summary-loading">
          <span className="pipeline-summary-spinner" />
          {t('explain_loading', 'Analyse en cours...')}
        </div>
      )}
      {error && <p className="pipeline-summary-error">{error}</p>}
      {summary && (
        <div className="pipeline-summary-text">
          <h4 className="pipeline-summary-title">
            <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
            {t('explain_title', 'Résumé du processus')}
          </h4>
          <p>{summary}</p>
        </div>
      )}
    </div>
  );
}
