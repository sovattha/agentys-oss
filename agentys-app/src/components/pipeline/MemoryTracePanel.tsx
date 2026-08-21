import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import type { MemoryTrace } from '../../types/training';
import './MemoryTracePanel.css';

interface MemoryTracePanelProps {
  trace: MemoryTrace | null | undefined;
}

const PROFIL_LABEL_KEYS: Record<string, string> = {
  nom_complet: 'memory_trace_field_name',
  name: 'memory_trace_field_name',
  nom: 'memory_trace_field_name',
  entreprise: 'memory_trace_field_company',
  company: 'memory_trace_field_company',
  poste: 'memory_trace_field_job_title',
  job_title: 'memory_trace_field_job_title',
  role: 'memory_trace_field_role',
  email: 'memory_trace_field_email',
  secteur: 'memory_trace_field_sector',
  sector: 'memory_trace_field_sector',
  langue: 'memory_trace_field_language',
  language: 'memory_trace_field_language',
};

const STYLE_LABEL_KEYS: Record<string, string> = {
  formality_level: 'memory_trace_field_formality',
  preferred_greetings: 'memory_trace_field_greetings',
  preferred_closings: 'memory_trace_field_closings',
};

function labelFromKey(key: string, map: Record<string, string>, t: TFunction): string {
  const tk = map[key];
  if (tk) return t(tk);
  // Fallback: turn snake_case into Title Case so raw keys never leak to the UI
  return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function isValidValue(v: unknown): boolean {
  if (v === null || v === undefined) return false;
  if (typeof v === 'string' && (!v || v.toLowerCase() === 'none')) return false;
  if (Array.isArray(v) && v.length === 0) return false;
  return true;
}

export function MemoryTracePanel({ trace }: MemoryTracePanelProps) {
  const { t } = useTranslation('compose');

  if (!trace) return null;

  const profilEntries = trace.profil
    ? Object.entries(trace.profil).filter(([, v]) => isValidValue(v))
    : [];
  const styleEntries = trace.style_default
    ? Object.entries(trace.style_default).filter(([, v]) => isValidValue(v))
    : [];
  const hasContact = trace.style_contact && Object.keys(trace.style_contact).length > 0;
  const hasSavoir = trace.savoir && trace.savoir.length > 0;
  const hasRules = trace.rules && trace.rules.length > 0;

  if (!profilEntries.length && !styleEntries.length && !hasSavoir && !hasRules) return null;

  return (
    <details className="memory-trace-panel" open>
      <summary className="memory-trace-summary">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <circle cx="8" cy="8" r="6" />
          <path d="M8 5v3l2 1.5" />
        </svg>
        {t('memory_trace_title', 'Mémoire utilisée')}
      </summary>

      <div className="memory-trace-sections">
        {profilEntries.length > 0 && (
          <div className="memory-trace-section">
            <h4 className="memory-trace-section-title">{t('memory_trace_profil', 'Profil')}</h4>
            <div className="memory-trace-fields">
              {profilEntries.map(([key, value]) => (
                <div key={key} className="memory-trace-field">
                  <span className="memory-trace-field-label">{labelFromKey(key, PROFIL_LABEL_KEYS, t)}</span>
                  <span className="memory-trace-field-value">{String(value)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {(styleEntries.length > 0 || hasContact) && (
          <div className="memory-trace-section">
            <h4 className="memory-trace-section-title">{t('memory_trace_style', 'Style')}</h4>
            {styleEntries.length > 0 && (
              <div className="memory-trace-fields">
                {styleEntries.map(([key, value]) => (
                  <div key={key} className="memory-trace-field">
                    <span className="memory-trace-field-label">{labelFromKey(key, STYLE_LABEL_KEYS, t)}</span>
                    <span className="memory-trace-field-value">
                      {Array.isArray(value) ? value.join(', ') : String(value)}
                    </span>
                  </div>
                ))}
              </div>
            )}
            {hasContact && (
              <div className="memory-trace-contact-badge">
                {t('memory_trace_contact_matched', 'Style adapté pour')} : {(trace.style_contact?.email as string) || '?'}
              </div>
            )}
          </div>
        )}

        {hasSavoir && (
          <div className="memory-trace-section">
            <h4 className="memory-trace-section-title">
              {t('memory_trace_savoir', 'Savoir consulté')}
              <span className="memory-trace-count">{trace.savoir.length}</span>
            </h4>
            <div className="memory-trace-chips">
              {trace.savoir.map((s, i) => (
                <span key={s.id || i} className="memory-trace-chip">
                  <span className="memory-trace-tag">{s.category}</span>
                  {s.question}
                </span>
              ))}
            </div>
          </div>
        )}

        {hasRules && (
          <div className="memory-trace-section">
            <h4 className="memory-trace-section-title">
              {t('memory_trace_rules', 'Règles apprises')}
              <span className="memory-trace-count">{trace.rules.length}</span>
            </h4>
            <ul className="memory-trace-list">
              {trace.rules.map((r, i) => (
                <li key={r.id || i} className="memory-trace-item">
                  <span>{r.rule_text}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </details>
  );
}
