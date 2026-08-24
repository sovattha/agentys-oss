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
import "./BeforeAfterComparison.css";
import { API_URL } from "../config";
import { getAuthHeaders } from "../services/authToken";

interface BeforeState {
  date: string;
  response: string;
  score: number;
  issues: string[];
}

interface AfterState {
  date: string;
  response: string;
  score: number;
  improvements: string[];
}

interface Comparison {
  id: string;
  email_subject: string;
  before: BeforeState;
  after: AfterState;
}

interface ImprovementSummary {
  average_score_before: number;
  average_score_after: number;
  improvement_percentage: number;
  top_improvements: string[];
}

interface ComparisonData {
  comparisons: Comparison[];
  improvement_summary: ImprovementSummary | null;
}

export function BeforeAfterComparison() {
  const { t } = useTranslation('agents');
  const { t: tCommon } = useTranslation('common');
  const [data, setData] = useState<ComparisonData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentIndex, setCurrentIndex] = useState(0);

  useEffect(() => {
    async function fetchData() {
      try {
        const response = await fetch(`${API_URL}/api/learning/comparisons`, { headers: { ...getAuthHeaders() } });
        if (!response.ok) {
          throw new Error(tCommon('error'));
        }
        const result: ComparisonData = await response.json();
        setData(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : tCommon('unknown_error'));
      } finally {
        setLoading(false);
      }
    }

    fetchData();
  }, []);

  function handlePrevious() {
    if (data && currentIndex > 0) {
      setCurrentIndex(currentIndex - 1);
    }
  }

  function handleNext() {
    if (data && currentIndex < data.comparisons.length - 1) {
      setCurrentIndex(currentIndex + 1);
    }
  }

  if (loading) {
    return (
      <div className="before-after">
        <h3>{t('ba_title')}</h3>
        <div className="before-after-loading">
          <p>{t('ba_loading')}</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="before-after">
        <h3>{t('ba_title')}</h3>
        <div className="before-after-error">
          <p>{t('ba_error', { error })}</p>
        </div>
      </div>
    );
  }

  if (!data || data.comparisons.length === 0) {
    return (
      <div className="before-after">
        <h3>{t('ba_title')}</h3>
        <p className="before-after-empty">
          {t('ba_empty')}
        </p>
      </div>
    );
  }

  const comparison = data.comparisons[currentIndex];
  const summary = data.improvement_summary;

  return (
    <div className="before-after">
      <h3>{t('ba_title')}</h3>

      {summary && (
        <div className="before-after-summary">
          <div className="before-after-summary-score">
            <span className="before-after-score-before">{summary.average_score_before}</span>
            <span className="before-after-arrow" data-testid="improvement-arrow">→</span>
            <span className="before-after-score-after">{summary.average_score_after}</span>
          </div>
          <div className="before-after-improvement">
            <span className="before-after-improvement-value">+{summary.improvement_percentage}%</span>
            <span className="before-after-improvement-label">{t('ba_improvement')}</span>
          </div>
        </div>
      )}

      <div className="before-after-navigation">
        <button
          className="before-after-nav-button"
          onClick={handlePrevious}
          disabled={currentIndex === 0}
          aria-label={tCommon('previous')}
        >
          ←
        </button>
        <span className="before-after-counter">
          {currentIndex + 1} / {data.comparisons.length}
        </span>
        <button
          className="before-after-nav-button"
          onClick={handleNext}
          disabled={currentIndex === data.comparisons.length - 1}
          aria-label={tCommon('next')}
        >
          →
        </button>
      </div>

      <div className="before-after-subject">
        <strong>{t('ba_email_label')}</strong> {comparison.email_subject}
      </div>

      <div className="before-after-comparison">
        <div className="before-after-panel before-panel">
          <div className="before-after-panel-header">
            <span className="before-after-panel-title">{t('ba_before')}</span>
            <span className="before-after-panel-score">{comparison.before.score}/5</span>
          </div>
          <div className="before-after-panel-content">
            <p className="before-after-text">{comparison.before.response}</p>
          </div>
          <div className="before-after-panel-issues">
            <strong>{t('ba_issues')}</strong>
            <ul>
              {comparison.before.issues.map((issue, idx) => (
                <li key={idx}>{issue}</li>
              ))}
            </ul>
          </div>
        </div>

        <div className="before-after-arrow-container">
          <span className="before-after-big-arrow">→</span>
        </div>

        <div className="before-after-panel after-panel">
          <div className="before-after-panel-header">
            <span className="before-after-panel-title">{t('ba_after')}</span>
            <span className="before-after-panel-score">{comparison.after.score}/5</span>
          </div>
          <div className="before-after-panel-content">
            <p className="before-after-text">{comparison.after.response}</p>
          </div>
          <div className="before-after-panel-improvements">
            <strong>{t('ba_improvements')}</strong>
            <ul>
              {comparison.after.improvements.map((improvement, idx) => (
                <li key={idx}>{improvement}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
