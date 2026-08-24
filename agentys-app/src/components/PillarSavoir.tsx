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

import { useState, useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import type { SavoirEntry, KnowledgeCategory } from '../types/training';
import { FaqSourceStep, type FaqSourceMode } from './onboarding/FaqSourceStep';
import { GhostAddRow } from './ui/GhostAddRow';
import { CloseIcon, ChevronLeftIcon } from './icons/ActionIcons';
import './TrainingCommon.css';
import './PillarSavoir.css';

interface LearnedSavoirItem {
  id: string;
  rule_text: string;
  category: string;
  created_at?: string;
}

interface FaqImportEntry {
  question: string;
  answer: string;
  source?: string;
}

interface PillarSavoirProps {
  savoir: SavoirEntry[];
  learnedSavoirs: LearnedSavoirItem[];
  onAddSavoir: (category?: KnowledgeCategory) => void;
  onUpdateSavoir: (id: string, field: 'question' | 'answer' | 'context', value: string) => void;
  onUpdateSavoirCategory: (id: string, category: string) => void;
  onRemoveSavoir: (id: string) => void;
  onDeleteLearnedSavoir: (id: string) => void;
  onImportFaq?: (entries: FaqImportEntry[]) => void;
}


/** Static badge — no dropdown, just a colored label */
function StaticCategoryBadge({ label, color }: { label: string; color: string }) {
  return (
    <span
      className="savoir-static-badge"
      style={{
        background: `${color}18`,
        color,
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0 }} />
      {label}
    </span>
  );
}

export function PillarSavoir({
  savoir,
  learnedSavoirs,
  onAddSavoir,
  onUpdateSavoir,
  onUpdateSavoirCategory,
  onRemoveSavoir,
  onDeleteLearnedSavoir,
  onImportFaq,
}: PillarSavoirProps) {
  const { t } = useTranslation('agents');
  const [showImport, setShowImport] = useState(false);
  const [faqMode, setFaqMode] = useState<FaqSourceMode>('choose');
  const faqBackRef = useRef<(() => void) | null>(null);

  const faqEntries = savoir.filter(s => s.category === 'FAQ');
  const learnedFaq = learnedSavoirs.filter(s => s.category === 'FAQ');

  void onUpdateSavoirCategory;

  const handleImportConfirm = useCallback((entries: FaqImportEntry[]) => {
    if (onImportFaq) {
      onImportFaq(entries);
    }
    setShowImport(false);
  }, [onImportFaq]);

  useEffect(() => {
    if (!showImport) setFaqMode('choose');
  }, [showImport]);

  // Close modal on Escape key
  useEffect(() => {
    if (!showImport) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowImport(false);
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [showImport]);

  return (
    <div className="pillar-savoir">
      <div className="pillar-section-header">
        <span className="pillar-section-title">{t('savoir_section_faq')}</span>
        <button
          type="button"
          className="pillar-import-btn"
          onClick={() => setShowImport(true)}
          title={t('savoir_import_faq')}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          {t('savoir_import_faq')}
        </button>
      </div>

      <GhostAddRow label={t('savoir_new_faq')} onClick={() => onAddSavoir('FAQ')} />

      {faqEntries.length === 0 ? (
        <p className="pillar-savoir-empty">{t('savoir_empty_faq')}</p>
      ) : (
        <div className="savoir-list">
          {faqEntries.map(entry => (
            <div key={entry.id} className="savoir-card">
              <div className="savoir-card-header">
                <StaticCategoryBadge label="FAQ" color="#10b981" />
                <input
                  className="savoir-question"
                  value={entry.question}
                  onChange={e => onUpdateSavoir(entry.id, 'question', e.target.value)}
                  placeholder={t('savoir_placeholder_question')}
                />
                <button
                  type="button"
                  className="pillar-delete-btn"
                  onClick={() => onRemoveSavoir(entry.id)}
                >
                  <CloseIcon size={14} />
                </button>
              </div>
              <textarea
                className="savoir-answer"
                value={entry.answer}
                onChange={e => onUpdateSavoir(entry.id, 'answer', e.target.value)}
                placeholder={t('savoir_placeholder_answer')}
                rows={2}
              />
              <input
                className="savoir-context"
                value={entry.context || ''}
                onChange={e => onUpdateSavoir(entry.id, 'context', e.target.value)}
              />
            </div>
          ))}
        </div>
      )}

      {learnedFaq.length > 0 && (
        <div className="savoir-list">
          {learnedFaq.map(item => (
            <div key={item.id} className="savoir-learned-item">
              <span className="savoir-learned-badge">{t('savoir_badge_learned')}</span>
              <span className="savoir-learned-text">{item.rule_text}</span>
              <button type="button" className="pillar-delete-btn"
                onClick={() => onDeleteLearnedSavoir(item.id)}><CloseIcon size={14} /></button>
            </div>
          ))}
        </div>
      )}

      {/* ── FAQ Import Modal Popup ── */}
      {showImport && (
        <div className="faq-modal-backdrop" onClick={() => setShowImport(false)}>
          <div
            className="faq-modal-container"
            onClick={e => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label={t('savoir_import_faq')}
            data-escape-owner=""
          >
            <div className="faq-modal-header">
              <div className="faq-modal-header-left">
                {faqMode !== 'choose' && (
                  <button
                    type="button"
                    className="faq-modal-back"
                    onClick={() => faqBackRef.current?.()}
                    aria-label="Back"
                  >
                    <ChevronLeftIcon />
                  </button>
                )}
                <h3 className="faq-modal-title">{t('savoir_import_faq')}</h3>
              </div>
              <button
                type="button"
                className="faq-modal-close"
                onClick={() => setShowImport(false)}
                aria-label="Close"
              >
                <CloseIcon />
              </button>
            </div>
            <div className="faq-modal-body">
              <FaqSourceStep
                compact
                onConfirm={handleImportConfirm}
                onSkip={() => setShowImport(false)}
                onModeChange={setFaqMode}
                backHandlerRef={faqBackRef}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
