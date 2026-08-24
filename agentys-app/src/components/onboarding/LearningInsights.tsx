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

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { LearningInsights as LearningInsightsType } from '../../types/onboarding'
import './LearningInsights.css'

interface LearningInsightsProps {
  insights: LearningInsightsType
  onComplete: () => void
  onConfirmProfession: (profession: string) => Promise<void>
}

export function LearningInsights({ insights, onComplete, onConfirmProfession }: LearningInsightsProps) {
  const { t } = useTranslation('onboarding')
  const { profile, knowledge, rules } = insights
  const [professionValue, setProfessionValue] = useState(profile?.profession ?? '')
  const [professionError, setProfessionError] = useState<string | null>(null)
  const [isSavingProfession, setIsSavingProfession] = useState(false)
  const trimmedProfession = professionValue.trim()

  useEffect(() => {
    setProfessionValue(profile?.profession ?? '')
    setProfessionError(null)
  }, [profile?.profession])

  const toneLabel = (tone: string) => t(`tone_${tone.replace('-', '_')}`, tone)
  const addressingLabel = (addressing: string) => t(`addressing_${addressing}`, addressing)
  // Note: `contact.type` (sociological classification) was removed from the
  // KnowledgeAgent schema — it cost LLM tokens but wasn't consumed by the
  // drafter pipeline. contactLabel helper kept as no-op fallback for any
  // legacy memoire.md content a user might still have on disk.

  // OB-R7 (audit 2026-04-25 onboarding-residual): detect a fully empty
  // insights payload — every section blank means the agents all returned
  // empty defaults (now flagged `_partial` upstream by C-3) and rendering
  // empty cards underneath "Vos découvertes" misleads the user into
  // thinking onboarding succeeded. Surface a banner with a retry hint
  // instead of a green checkmark over nothing.
  const hasProfileData = !!profile && (
    !!profile.user_name || !!profile.preferred_name ||
    !!profile.profession ||
    !!profile.signature?.title || !!profile.signature?.company || !!profile.signature?.department ||
    !!profile.tone?.default_tone || !!profile.tone?.greeting_style || !!profile.tone?.closing_style ||
    (Array.isArray(profile.languages) && profile.languages.length > 0)
  )
  const hasKnowledgeData = !!knowledge?.contacts && knowledge.contacts.length > 0
  const hasRulesData = !!rules?.contact_rules && rules.contact_rules.length > 0
  const isEmpty = !hasProfileData && !hasKnowledgeData && !hasRulesData
  const isProfessionMissing = trimmedProfession.length === 0

  const handleFinish = async () => {
    if (isProfessionMissing) {
      setProfessionError(t('insights_profession_required', 'Confirmez votre métier pour continuer.'))
      return
    }

    setIsSavingProfession(true)
    setProfessionError(null)
    try {
      await onConfirmProfession(trimmedProfession)
      onComplete()
    } catch {
      setProfessionError(t('insights_profession_save_error', 'Impossible de sauvegarder votre métier. Réessayez.'))
    } finally {
      setIsSavingProfession(false)
    }
  }

  return (
    <div className="learning-insights">
      <div className="learning-insights-header">
        <h3>{t('insights_title')}</h3>
        <p className="learning-insights-subtitle">
          {t('insights_subtitle', { count: insights.emailsAnalysed })}
        </p>
      </div>

      {isEmpty && (
        <div
          className="learning-insights-section learning-insights-empty"
          role="alert"
          style={{
            background: 'rgba(245, 158, 11, 0.08)',
            border: '1px solid rgba(245, 158, 11, 0.4)',
            borderRadius: 12,
            padding: 16,
            marginBottom: 16,
          }}
        >
          <h4 style={{ marginTop: 0 }}>
            {t('insights_empty_title', 'Analyse incomplète')}
          </h4>
          <p style={{ margin: 0 }}>
            {t(
              'insights_empty_desc',
              'Nous n\'avons pas pu extraire assez de données de votre boîte. Relancez l\'entraînement depuis les Réglages quand vous aurez plus d\'emails envoyés.',
            )}
          </p>
        </div>
      )}

      {/* === PROFIL === */}
      {profile && (
        <div className="learning-insights-section">
          <h4>{t('insights_profile')}</h4>
          <div className="learning-insights-profile-grid">
            {profile.user_name && (
              <div className="learning-insights-field">
                <span className="learning-insights-field-label">{t('insights_field_name')}</span>
                <span className="learning-insights-field-value">{profile.user_name}</span>
              </div>
            )}
            {profile.preferred_name && profile.preferred_name !== profile.user_name && (
              <div className="learning-insights-field">
                <span className="learning-insights-field-label">{t('insights_field_preferred_name')}</span>
                <span className="learning-insights-field-value">{profile.preferred_name}</span>
              </div>
            )}
            <div className="learning-insights-field learning-insights-field-full">
              <label className="learning-insights-field-label" htmlFor="learning-insights-profession">
                {t('insights_field_profession', 'Métier détecté')}
              </label>
              <input
                id="learning-insights-profession"
                className="learning-insights-input"
                type="text"
                value={professionValue}
                maxLength={120}
                placeholder={t('insights_profession_placeholder', 'Ex. courtier immobilier, avocate, fondateur SaaS')}
                aria-invalid={!!professionError}
                onChange={event => {
                  setProfessionValue(event.target.value)
                  if (professionError) setProfessionError(null)
                }}
              />
              {professionError && (
                <span className="learning-insights-error" role="alert">{professionError}</span>
              )}
            </div>
            {profile.signature?.title && (
              <div className="learning-insights-field">
                <span className="learning-insights-field-label">{t('insights_field_title')}</span>
                <span className="learning-insights-field-value">{profile.signature.title}</span>
              </div>
            )}
            {profile.signature?.company && (
              <div className="learning-insights-field">
                <span className="learning-insights-field-label">{t('insights_field_company')}</span>
                <span className="learning-insights-field-value">{profile.signature.company}</span>
              </div>
            )}
            {profile.signature?.department && (
              <div className="learning-insights-field">
                <span className="learning-insights-field-label">{t('insights_field_department')}</span>
                <span className="learning-insights-field-value">{profile.signature.department}</span>
              </div>
            )}
            {profile.languages && profile.languages.length > 0 && (
              <div className="learning-insights-field">
                <span className="learning-insights-field-label">{t('insights_field_languages')}</span>
                <span className="learning-insights-field-value">
                  {profile.languages.map(l => l.toUpperCase()).join(', ')}
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* === TON & STYLE === */}
      {profile?.tone && (
        <div className="learning-insights-section">
          <h4>{t('insights_style')}</h4>
          <div className="learning-insights-profile-grid">
            {profile.tone.default_tone && (
              <div className="learning-insights-field">
                <span className="learning-insights-field-label">{t('insights_field_tone')}</span>
                <span className="learning-insights-field-value">
                  {toneLabel(profile.tone.default_tone)}
                </span>
              </div>
            )}
            {profile.tone.addressing && (
              <div className="learning-insights-field">
                <span className="learning-insights-field-label">{t('insights_field_addressing')}</span>
                <span className="learning-insights-field-value">
                  {addressingLabel(profile.tone.addressing)}
                </span>
              </div>
            )}
            {profile.tone.greeting_style && (
              <div className="learning-insights-field">
                <span className="learning-insights-field-label">{t('insights_field_greeting')}</span>
                <span className="learning-insights-field-value">{profile.tone.greeting_style}</span>
              </div>
            )}
            {profile.tone.closing_style && (
              <div className="learning-insights-field">
                <span className="learning-insights-field-label">{t('insights_field_closing')}</span>
                <span className="learning-insights-field-value">{profile.tone.closing_style}</span>
              </div>
            )}
            {profile.tone.average_response_length && (
              <div className="learning-insights-field">
                <span className="learning-insights-field-label">{t('insights_field_reply_length')}</span>
                <span className="learning-insights-field-value">{profile.tone.average_response_length}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* === CONTACTS === */}
      {knowledge?.contacts && knowledge.contacts.length > 0 && (
        <div className="learning-insights-section">
          <h4>{t('insights_contacts', { count: knowledge.contacts.length })}</h4>
          <div className="learning-insights-contacts">
            {knowledge.contacts.slice(0, 10).map((contact, i) => (
              <div key={i} className="learning-insights-contact">
                <span className="learning-insights-contact-name">{contact.name}</span>
                {contact.company && (
                  <span className="learning-insights-contact-company">{contact.company}</span>
                )}
              </div>
            ))}
            {knowledge.contacts.length > 10 && (
              <p className="learning-insights-more">
                {t('insights_more_contacts', { count: knowledge.contacts.length - 10 })}
              </p>
            )}
          </div>
        </div>
      )}

      {/* === RÈGLES DE COMMUNICATION === */}
      {rules?.contact_rules && rules.contact_rules.length > 0 && (
        <div className="learning-insights-section">
          <h4>{t('insights_contact_rules', { count: rules.contact_rules.length })}</h4>
          <div className="learning-insights-rules">
            {rules.contact_rules.slice(0, 6).map((rule, i) => (
              <div key={i} className="learning-insights-rule">
                <span className="learning-insights-rule-email">{rule.contact_email}</span>
                <span className="learning-insights-rule-detail">
                  {toneLabel(rule.tone)}
                  {rule.addressing ? ` · ${addressingLabel(rule.addressing)}` : ''}
                  {' · '}{rule.language.toUpperCase()} · « {rule.greeting} ... {rule.closing} »
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="learning-insights-footer">
        <button
          type="button"
          className="learning-insights-btn"
          onClick={handleFinish}
          disabled={isProfessionMissing || isSavingProfession}
        >
          {isSavingProfession ? t('insights_start_saving', 'Sauvegarde...') : t('insights_start')}
        </button>
      </div>
    </div>
  )
}
