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

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import "./MyStyle.css";
import { BeforeAfterComparison } from "./BeforeAfterComparison";
import { API_URL } from "../config";
import { getAuthHeaders } from "../services/authToken";
import { formatCompactDate } from '../utils/dateFormat';
import { CloseIcon } from "./icons/ActionIcons";

interface MyStyleProps {
  onClose: () => void;
}

interface LearningStats {
  total_feedback: number;
  positive_feedback: number;
  negative_feedback: number;
  patterns_count: number;
  last_learning_date: string | null;
  validation_rate: number;
}

interface Pattern {
  id: string;
  pattern_type: string;
  description: string;
  confidence: number;
  examples: string[];
  created_at: string;
}

interface PatternsResponse {
  count: number;
  patterns: Pattern[];
}

function formatPatternType(type: string, formality: string, t: (key: string) => string): string {
  if (type === 'formality') return formality;
  const labels: Record<string, string> = {
    signature: 'Signature',
    greeting: t('mystyle_greeting'),
    tone: t('mystyle_tone'),
    closing: t('mystyle_closing'),
  };
  return labels[type] || type;
}

function formatDate(dateString: string): string {
  return formatCompactDate(new Date(dateString));
}

function calculateMaturityScore(stats: LearningStats): number {
  const feedbackScore = Math.min(stats.total_feedback / 100, 1) * 40;
  const patternsScore = Math.min(stats.patterns_count / 10, 1) * 30;
  const validationScore = (stats.validation_rate / 100) * 30;
  return Math.round(feedbackScore + patternsScore + validationScore);
}

export function MyStyle({ onClose }: MyStyleProps) {
  const { t } = useTranslation('common');
  const { t: tSettings } = useTranslation('settings');
  const { t: tErrors } = useTranslation('errors');
  const [stats, setStats] = useState<LearningStats | null>(null);
  const [patterns, setPatterns] = useState<Pattern[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // F09 (MEDIUM): AbortController so a rapid open/close of the modal
    // doesn't fire setState on an unmounted component (React warning) and
    // doesn't pin two requests in the network panel for nothing.
    const controller = new AbortController();
    let cancelled = false;

    async function fetchData() {
      try {
        const [statsRes, patternsRes] = await Promise.all([
          fetch(`${API_URL}/api/learning/stats`, {
            headers: { ...getAuthHeaders() },
            signal: controller.signal,
          }),
          fetch(`${API_URL}/api/learning/patterns`, {
            headers: { ...getAuthHeaders() },
            signal: controller.signal,
          }),
        ]);

        if (!statsRes.ok || !patternsRes.ok) {
          throw new Error(tErrors('data_load_error'));
        }

        const statsData: LearningStats = await statsRes.json();
        const patternsData: PatternsResponse = await patternsRes.json();

        if (cancelled) return;
        setStats(statsData);
        setPatterns(patternsData.patterns);
      } catch (err) {
        // Aborted fetch is a normal teardown path — don't surface as error.
        if (cancelled || (err instanceof Error && err.name === 'AbortError')) return;
        setError(err instanceof Error ? err.message : t('unknown_error'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchData();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, []);

  const maturityScore = stats ? calculateMaturityScore(stats) : 0;

  return (
    <div className="my-style">
      <div className="my-style-header">
        <h2>{t('mystyle_title')}</h2>
        <button
          className="my-style-close"
          onClick={onClose}
          aria-label={t('close')}
        >
          <CloseIcon />
        </button>
      </div>

      <div className="my-style-content">
        {loading && (
          <div className="my-style-loading">
            <p>{t('loading')}</p>
          </div>
        )}

        {error && (
          <div className="my-style-error">
            <p>{t('mystyle_error', { message: error })}</p>
          </div>
        )}

        {!loading && !error && stats && (
          <>
            <section className="my-style-section">
              <h3>{t('mystyle_ai_maturity')}</h3>
              <div className="my-style-maturity">
                <div
                  className="my-style-maturity-bar"
                  role="progressbar"
                  aria-valuenow={maturityScore}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <div
                    className="my-style-maturity-fill"
                    style={{ width: `${maturityScore}%` }}
                  />
                </div>
                <span className="my-style-maturity-label">{maturityScore}%</span>
              </div>
            </section>

            <section className="my-style-section">
              <h3>{t('mystyle_statistics')}</h3>
              <div className="my-style-stats">
                <div className="my-style-stat">
                  <span className="my-style-stat-value">{stats.total_feedback}</span>
                  <span className="my-style-stat-label">{t('mystyle_feedbacks')}</span>
                </div>
                <div className="my-style-stat">
                  <span className="my-style-stat-value">{Math.round(stats.validation_rate)}%</span>
                  <span className="my-style-stat-label">{t('mystyle_validation_v1')}</span>
                </div>
                <div className="my-style-stat">
                  <span className="my-style-stat-value">{stats.patterns_count}</span>
                  <span className="my-style-stat-label">{t('mystyle_detected')}</span>
                </div>
              </div>
            </section>

            <section className="my-style-section">
              <h3>{t('mystyle_learned_patterns')}</h3>
              {patterns.length === 0 ? (
                <p className="my-style-empty">{t('mystyle_no_patterns')}</p>
              ) : (
                <div className="my-style-patterns">
                  {patterns.map((pattern) => (
                    <div key={pattern.id} className="my-style-pattern">
                      <div className="my-style-pattern-header">
                        <span className="my-style-pattern-type">
                          {formatPatternType(pattern.pattern_type, tSettings('formality'), t)}
                        </span>
                        <span className="my-style-pattern-confidence">
                          {Math.round(pattern.confidence * 100)}%
                        </span>
                      </div>
                      <p className="my-style-pattern-description">
                        {pattern.description}
                      </p>
                      {pattern.examples.length > 0 && (
                        <div className="my-style-pattern-examples">
                          {pattern.examples.map((example, idx) => (
                            <span key={idx} className="my-style-pattern-example">
                              "{example}"
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="my-style-section">
              <h3>Timeline</h3>
              <div className="my-style-timeline">
                {stats.last_learning_date ? (
                  <p>
                    {t('mystyle_last_learning', { date: formatDate(stats.last_learning_date) })}
                  </p>
                ) : (
                  <p>{t('mystyle_no_learning')}</p>
                )}
              </div>
            </section>

            <section className="my-style-section">
              <BeforeAfterComparison />
            </section>
          </>
        )}
      </div>
    </div>
  );
}
