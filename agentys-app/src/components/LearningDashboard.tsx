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

import { useState, useMemo, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { formatShortDateFromDate } from '../utils/dateFormat'
import { useLearningDashboard } from '../hooks/useLearningDashboard'
import type { LearningRule, ContactInsight } from '../hooks/useLearningDashboard'
import { ChevronLeftIcon, ChevronDownIcon, CloseIcon, TrashIcon } from './icons/ActionIcons'
import { getInitials as getAvatarInitials } from './Avatar'
import './LearningDashboard.css'

interface LearningDashboardProps {
  onClose: () => void
  onBack?: () => void
}

// ── Category config ──────────────────────────────────────────────────

const RULE_CAT_KEYS: Record<string, string> = {
  greeting: 'rule_cat_greeting',
  closing: 'rule_cat_closing',
  tone: 'rule_cat_tone',
  length: 'rule_cat_length',
  content: 'rule_cat_content',
  formule: 'rule_cat_formule',
  format: 'rule_cat_format',
  vocabulary: 'rule_cat_vocabulary',
  vocabulaire: 'rule_cat_vocabulary',
  structure: 'rule_cat_structure',
}

// ── Helpers ──────────────────────────────────────────────────────────

function formatTime(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)} min`
  const h = Math.floor(minutes / 60)
  const m = Math.round(minutes % 60)
  return m > 0 ? `${h}h ${m}min` : `${h}h`
}

// Initiales : déléguées au canon Avatar.getInitials (règle unique « toujours
// 2 lettres », 2026-06-09) — la signature locale email-only est conservée.
function getInitials(email: string): string {
  return getAvatarInitials(null, email)
}

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr)
    if (Number.isNaN(d.getTime())) return dateStr
    // Active UI language + ordinal house style: "May 27th" (EN) / "27 mai" (FR).
    return formatShortDateFromDate(d, i18n.language)
  } catch {
    return dateStr
  }
}

// ── Component ────────────────────────────────────────────────────────

export function LearningDashboard({ onClose, onBack }: LearningDashboardProps) {
  const { t } = useTranslation('agents')
  const { t: tCommon } = useTranslation('common')
  const data = useLearningDashboard()
  const {
    hero, trend, tiers, rules, editPatterns, contacts, comparisons,
    isLoading, period, setPeriod, toggleRule, deleteRule,
  } = data

  const [openCategories, setOpenCategories] = useState<Set<string>>(new Set(['tone', 'greeting']))

  // Group rules by category
  const rulesByCategory = useMemo(() => {
    const grouped: Record<string, LearningRule[]> = {}
    for (const rule of rules) {
      const cat = rule.category || 'content'
      if (!grouped[cat]) grouped[cat] = []
      grouped[cat].push(rule)
    }
    return grouped
  }, [rules])

  // Edit patterns — find max for highlight
  const patternEntries = useMemo(() => {
    const entries = [
      { key: 'greeting', labelKey: 'rule_cat_greeting', count: editPatterns.greeting },
      { key: 'tone', labelKey: 'rule_cat_tone', count: editPatterns.tone },
      { key: 'content', labelKey: 'rule_cat_content', count: editPatterns.content },
      { key: 'length', labelKey: 'rule_cat_length', count: editPatterns.length },
      { key: 'formule', labelKey: 'rule_cat_formule', count: editPatterns.formule || 0 },
      { key: 'closing', labelKey: 'rule_cat_closing', count: editPatterns.closing },
    ]
    const maxCount = Math.max(...entries.map(e => e.count), 1)
    return entries.map(e => ({
      ...e,
      isMax: e.count === maxCount && maxCount > 0,
      intensity: e.count / maxCount > 0.6 ? 'intensity-high' : e.count / maxCount > 0.25 ? 'intensity-mid' : 'intensity-low',
      flex: Math.max(0.5, e.count / maxCount * 4),
    }))
  }, [editPatterns])

  const toggleCategory = useCallback((cat: string) => {
    setOpenCategories(prev => {
      const next = new Set(prev)
      if (next.has(cat)) next.delete(cat)
      else next.add(cat)
      return next
    })
  }, [])

  // Ring circumference: r=30 → C = 2*PI*30 = 188.5
  const ringCirc = 188.5
  const ringOffset = ringCirc - (ringCirc * hero.acceptanceRate / 100)

  const maxTier = Math.max(tiers.simple, tiers.standard, tiers.complex, 1)

  if (isLoading) {
    return (
      <div className="learning-dashboard">
        <div className="ld-loading">{t('loading_dashboard')}</div>
      </div>
    )
  }

  return (
    <div className="learning-dashboard">
      <div className="ld-top-bar">
        {onBack && (
          <button className="ld-back-btn" onClick={onBack} aria-label={tCommon('back')} title={tCommon('back')}>
            <ChevronLeftIcon size={20} />
          </button>
        )}
        <button className="ld-close-btn" onClick={onClose} title={tCommon('close')} aria-label={tCommon('close')}>
          <CloseIcon />
        </button>
      </div>

      {/* Header */}
      <div className="ld-header">
        <h1>{t('learning_dashboard_title')}</h1>
        <p>{t('learning_dashboard_subtitle')}</p>
      </div>

      {/* ═══ 1. HERO STATS ═══ */}
      <div className="ld-hero-grid">
        <div className="ld-hero-tile">
          <div className="ld-hero-ring">
            <svg aria-hidden="true" viewBox="0 0 72 72">
              <circle className="ring-track" cx="36" cy="36" r="30" />
              <circle className="ring-fill" cx="36" cy="36" r="30"
                style={{ strokeDashoffset: ringOffset }} />
            </svg>
            <span className="ring-label">{Math.round(hero.acceptanceRate)}%</span>
          </div>
          <div className="ld-hero-text">
            <h3>{tCommon('learning_rate')}</h3>
            <div className="ld-hero-value">{Math.round(hero.acceptanceRate)}%</div>
          </div>
        </div>

        <div className="ld-hero-tile">
          <div className="ld-hero-icon">
            <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M22 2L11 13" /><path d="M22 2L15 22L11 13L2 9L22 2Z" /></svg>
          </div>
          <div className="ld-hero-text">
            <h3>{tCommon('drafts_sent')}</h3>
            <div className="ld-hero-value">{hero.totalSent}</div>
            <div className="ld-hero-detail">{hero.sentThisWeek} {tCommon('this_week')}</div>
          </div>
        </div>

        <div className="ld-hero-tile">
          <div className="ld-hero-icon">
            <svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>
          </div>
          <div className="ld-hero-text">
            <h3>{tCommon('time_saved')}</h3>
            <div className="ld-hero-value">{formatTime(hero.timeSavedMin)}</div>
            <div className="ld-hero-detail">{tCommon('this_week')}</div>
          </div>
        </div>

        <div className="ld-hero-tile">
          <div className="ld-hero-icon">
            <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 20h9" /><path d="M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z" /></svg>
          </div>
          <div className="ld-hero-text">
            <h3>{t('active_rules')}</h3>
            <div className="ld-hero-value">{hero.activeRules}</div>
            <div className="ld-hero-detail">{t('avg_confidence', { value: hero.avgConfidence.toFixed(2) })}</div>
          </div>
        </div>
      </div>

      {/* ═══ 2. QUALITY TREND ═══ */}
      <div className="ld-section">
        <div className="ld-section-header">
          <div className="ld-section-title">
            <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M18 20V10" /><path d="M12 20V4" /><path d="M6 20v-6" /></svg>
            {t('quality_trend')}
          </div>
          <div className="ld-period-selector">
            {[7, 14, 30].map(d => (
              <button key={d} className={`ld-period-btn${period === d ? ' active' : ''}`}
                onClick={() => setPeriod(d)}>{d}j</button>
            ))}
          </div>
        </div>

        {trend.length > 0 ? (
          <>
            <div className="ld-trend-chart">
              {trend.map((day, i) => {
                const level = day.rate >= 80 ? 'high' : day.rate >= 60 ? 'mid' : 'low'
                return (
                  <div key={i} className="ld-trend-bar-group">
                    <div className={`ld-trend-bar ${level}`}
                      style={{ height: `${Math.max(3, day.rate)}%` }}
                      title={`${day.rate}% — ${day.total} envoi(s)`} />
                    <span className="ld-trend-date">{formatDate(day.date)}</span>
                  </div>
                )
              })}
            </div>

            <div className="ld-tier-breakdown">
              {(['simple', 'standard', 'complex'] as const).map(tier => (
                <div key={tier}>
                  <div className="ld-tier-label">
                    {tier.charAt(0).toUpperCase() + tier.slice(1)}
                    <span className="ld-tier-count">{tiers[tier]}</span>
                  </div>
                  <div className="ld-tier-bar-track">
                    <div className="ld-tier-bar-fill"
                      style={{ width: `${(tiers[tier] / maxTier) * 100}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </>
        ) : (
          <div className="ld-empty">{t('no_data_period')}</div>
        )}
      </div>

      {/* ═══ 3. RULES MANAGER ═══ */}
      <div className="ld-section">
        <div className="ld-section-header">
          <div className="ld-section-title">
            <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /></svg>
            {t('rules_manager')}
          </div>
          <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--text-muted)' }}>
            {t('rules_active_total', { active: hero.activeRules, total: rules.length })}
          </span>
        </div>

        {Object.entries(rulesByCategory).length > 0 ? (
          Object.entries(rulesByCategory).map(([cat, catRules]) => (
            <div key={cat} className={`ld-rules-category${openCategories.has(cat) ? ' open' : ''}`}>
              <button className="ld-rules-cat-header" onClick={() => toggleCategory(cat)}>
                <span className="ld-rules-cat-name">{RULE_CAT_KEYS[cat] ? t(RULE_CAT_KEYS[cat]) : cat}</span>
                <span className="ld-rules-cat-badge">{catRules.length}</span>
                <ChevronDownIcon className="ld-rules-cat-chevron" />
              </button>
              <div className="ld-rules-list">
                {catRules.map(rule => (
                  <div key={rule.id} className="ld-rule-row">
                    <label className="ld-rule-toggle" onClick={e => e.stopPropagation()}>
                      <input type="checkbox" checked={rule.active}
                        onChange={() => toggleRule(rule.id, !rule.active)} />
                      <span className="slider" />
                    </label>
                    <span className={`ld-rule-scope ${rule.scope || 'global'}`}>
                      {(rule.scope || 'global') === 'global' ? t('rule_scope_global') : t('rule_scope_contact')}
                    </span>
                    <span className="ld-rule-text" title={rule.rule_text}>{rule.rule_text}</span>
                    <div className="ld-rule-confidence">
                      <div className="ld-confidence-track">
                        <div className="ld-confidence-fill" style={{ width: `${(rule.confidence || 0) * 100}%` }} />
                      </div>
                      <span className="ld-confidence-val">{(rule.confidence || 0).toFixed(2)}</span>
                    </div>
                    <div className="ld-rule-actions">
                      <button className="ld-rule-action-btn icon-btn--delete" title={tCommon('delete')} aria-label={tCommon('delete')}
                        onClick={e => { e.stopPropagation(); deleteRule(rule.id) }}>
                        <TrashIcon size={14} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))
        ) : (
          <div className="ld-empty">{t('no_rules_learned')}</div>
        )}
      </div>

      {/* ═══ 4. EDIT PATTERNS ═══ */}
      {patternEntries.some(e => e.count > 0) && (
        <div className="ld-section">
          <div className="ld-section-header">
            <div className="ld-section-title">
              <svg aria-hidden="true" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" ry="2" /><rect x="7" y="7" width="3" height="9" /><rect x="14" y="7" width="3" height="5" /></svg>
              {t('edit_zones')}
            </div>
          </div>
          <div className="ld-heatmap">
            {patternEntries.map(e => (
              <div key={e.key}
                className={`ld-heatmap-block ${e.intensity}${e.isMax ? ' highlight' : ''}`}
                style={{ flex: e.flex }}>
                <span className="ld-heatmap-label">{t(e.labelKey)}</span>
                <span className="ld-heatmap-count">{t('editions_count', { count: e.count })}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ═══ 5. CONTACT INSIGHTS ═══ */}
      {contacts.length > 0 && (
        <div className="ld-section">
          <div className="ld-section-header">
            <div className="ld-section-title">
              <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M23 21v-2a4 4 0 00-3-3.87" /><path d="M16 3.13a4 4 0 010 7.75" /></svg>
              {t('contact_insights')}
            </div>
          </div>
          <table className="ld-contacts-table">
            <thead>
              <tr>
                <th>{t('contact_header')}</th>
                <th>{t('sends_header')}</th>
                <th>{t('avg_length_header')}</th>
                <th>{t('edit_ratio_header')}</th>
                <th>{t('cc_header')}</th>
              </tr>
            </thead>
            <tbody>
              {contacts.map((c: ContactInsight) => {
                const fillColor = c.avg_edit_ratio < 0.15
                  ? 'var(--success)'
                  : c.avg_edit_ratio < 0.3 ? 'var(--warning)' : 'var(--error)'
                return (
                  <tr key={c.contact}>
                    <td>
                      <div className="ld-contact-cell">
                        <div className="ld-contact-avatar">{getInitials(c.contact)}</div>
                        <span className="ld-contact-email">{c.contact}</span>
                      </div>
                    </td>
                    <td>{c.total_sends}</td>
                    <td>{c.avg_length != null ? t('words_unit', { count: c.avg_length }) : '—'}</td>
                    <td>
                      <div className="ld-edit-ratio-bar">
                        <div className="ld-edit-ratio-track">
                          <div className="ld-edit-ratio-fill"
                            style={{ width: `${c.avg_edit_ratio * 100}%`, background: fillColor }} />
                        </div>
                        <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                          {(c.avg_edit_ratio * 100).toFixed(0)}%
                        </span>
                      </div>
                    </td>
                    <td>
                      <div className="ld-cc-tags">
                        {c.cc_patterns.length > 0
                          ? c.cc_patterns.map(cc => <span key={cc} className="ld-cc-tag">{cc}</span>)
                          : <span style={{ color: 'var(--text-placeholder)' }}>—</span>
                        }
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ═══ 6. BEFORE/AFTER ═══ */}
      {comparisons.length > 0 && (
        <div className="ld-section">
          <div className="ld-section-header">
            <div className="ld-section-title">
              <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M16 3h5v5" /><path d="M8 3H3v5" /><path d="M12 22V8" /><path d="M21 3l-9 9" /><path d="M3 3l9 9" /></svg>
              {t('before_after')}
            </div>
          </div>
          {comparisons.map((comp, i) => (
            <div key={i} className="ld-comparison-pair">
              <div className="ld-comparison-card before">
                <span className="ld-comparison-badge">{t('v1_draft')}</span>
                {comp.timestamp && <div className="ld-comparison-date">{formatDate(comp.timestamp)}</div>}
                <div className="ld-comparison-text">
                  {(comp.original || '').substring(0, 200)}
                  {(comp.original || '').length > 200 ? '...' : ''}
                </div>
              </div>
              <div className="ld-comparison-card after">
                <span className="ld-comparison-badge">{t('sent_label')}</span>
                {comp.timestamp && <div className="ld-comparison-date">{formatDate(comp.timestamp)}</div>}
                <div className="ld-comparison-text">
                  {(comp.sent || '').substring(0, 200)}
                  {(comp.sent || '').length > 200 ? '...' : ''}
                </div>
              </div>
            </div>
          ))}
          <div className="ld-comparison-summary">
            {t('avg_improvement', { rate: Math.round(hero.acceptanceRate) })}
          </div>
        </div>
      )}

    </div>
  )
}
