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

import { useTranslation } from 'react-i18next'
import i18n from '../i18n'
import { apiClient } from '../services/api'

const LANGUAGES = [
  { code: 'fr', abbr: 'FR', label: 'Français' },
  { code: 'en', abbr: 'EN', label: 'English' },
]

interface LanguageSelectorProps {
  onChangeLanguage?: (lang: string) => void
}

export function LanguageSelector({ onChangeLanguage }: LanguageSelectorProps) {
  const { t } = useTranslation('settings')
  const currentLang = i18n.language?.slice(0, 2) || 'fr'

  const handleChange = async (code: string) => {
    localStorage.setItem('agentys_language', code)
    onChangeLanguage?.(code)
    await i18n.changeLanguage(code)
    // Persist language preference to backend (fire-and-forget)
    apiClient.request('/user/preferences', {
      method: 'PATCH',
      body: JSON.stringify({ preferred_language: code }),
    }).catch(() => { /* fire-and-forget */ })
  }

  return (
    <div className="settings-language-selector">
      <span className="settings-label">{t('language')}</span>
      <div className="language-options">
        {LANGUAGES.map(lang => (
          <button
            key={lang.code}
            type="button"
            className={`language-option-btn${currentLang === lang.code ? ' active' : ''}`}
            onClick={() => handleChange(lang.code)}
            aria-pressed={currentLang === lang.code}
          >
            <span className="language-abbr">{lang.abbr}</span>
            <span className="language-label">{lang.label}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
