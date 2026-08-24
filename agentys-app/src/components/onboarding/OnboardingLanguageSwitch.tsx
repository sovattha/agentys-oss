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
import i18n from '../../i18n'

const LANGS = [
  { code: 'fr', abbr: 'FR' },
  { code: 'en', abbr: 'EN' },
]

export function OnboardingLanguageSwitch() {
  const { i18n: i18nInstance } = useTranslation()
  const current = (i18nInstance.language || 'fr').slice(0, 2)

  const handle = async (code: string) => {
    if (code === current) return
    localStorage.setItem('agentys_language', code)
    await i18n.changeLanguage(code)
  }

  return (
    <div className="po-lang-switch" role="group" aria-label="Language">
      {LANGS.map(l => (
        <button
          key={l.code}
          type="button"
          className={`po-lang-btn${current === l.code ? ' active' : ''}`}
          onClick={() => handle(l.code)}
          aria-pressed={current === l.code}
        >
          {l.abbr}
        </button>
      ))}
    </div>
  )
}
