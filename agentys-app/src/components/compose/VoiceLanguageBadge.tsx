import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { SUPPORTED_VOICE_LANGUAGES, type VoiceLanguageCode } from '../../hooks/useVoiceLanguage'
import { CheckIcon } from '../icons/ActionIcons'
import './VoiceLanguageBadge.css'

interface VoiceLanguageBadgeProps {
  language: VoiceLanguageCode
  onChange: (code: VoiceLanguageCode) => void
  /** Hide when recording or transcribing — language is locked once dictation starts. */
  disabled?: boolean
}

export function VoiceLanguageBadge({ language, onChange, disabled }: VoiceLanguageBadgeProps) {
  const { t } = useTranslation('compose')
  const [open, setOpen] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const current = SUPPORTED_VOICE_LANGUAGES.find(l => l.code === language) ?? SUPPORTED_VOICE_LANGUAGES[0]

  useEffect(() => {
    if (!open) return
    const handleClickOutside = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleEsc, true)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEsc, true)
    }
  }, [open])

  return (
    <div ref={wrapperRef} className="voice-lang-badge-wrapper">
      <button
        type="button"
        className="voice-lang-badge"
        onClick={() => setOpen(o => !o)}
        disabled={disabled}
        title={t('voice_lang_title', { lang: current.label, defaultValue: 'Dictation language: {{lang}}' })}
        aria-label={t('voice_lang_aria', { lang: current.label, defaultValue: 'Current dictation language: {{lang}}. Click to change.' })}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="voice-lang-code">{current.code === 'auto' ? 'Auto' : current.code.charAt(0).toUpperCase() + current.code.slice(1)}</span>
      </button>
      {open && (
        <ul className="voice-lang-menu" role="listbox" aria-label={t('voice_lang_choose', 'Choose dictation language')}>
          {SUPPORTED_VOICE_LANGUAGES.map(lang => (
            <li
              key={lang.code}
              role="option"
              aria-selected={lang.code === language}
              className={`voice-lang-item${lang.code === language ? ' is-active' : ''}`}
              onClick={() => {
                onChange(lang.code)
                setOpen(false)
              }}
            >
              <span className="voice-lang-flag">{lang.flag}</span>
              <span className="voice-lang-label">{lang.label}</span>
              {lang.code === language && <span className="voice-lang-check" aria-hidden="true"><CheckIcon size={14} /></span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
