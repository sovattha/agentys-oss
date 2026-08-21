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
