import { useState, useEffect, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { apiClient } from '../services/api'
import { CloseIcon } from './icons/ActionIcons'
import './KnowledgeSuggestionToast.css'

export interface KnowledgeSuggestion {
  question: string
  answer: string
  context: string
}

interface KnowledgeSuggestionToastProps {
  suggestion: KnowledgeSuggestion
  onDismiss: () => void
}

export function KnowledgeSuggestionToast({ suggestion, onDismiss }: KnowledgeSuggestionToastProps) {
  const { t } = useTranslation()
  const [state, setState] = useState<'idle' | 'saving' | 'saved'>('idle')
  const [isExiting, setIsExiting] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const dismiss = useCallback(() => {
    setIsExiting(true)
    setTimeout(onDismiss, 300)
  }, [onDismiss])

  // Auto-dismiss after 15s if no action
  useEffect(() => {
    timerRef.current = setTimeout(dismiss, 15000)
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [dismiss])

  const handleAdd = async () => {
    if (timerRef.current) clearTimeout(timerRef.current)
    setState('saving')
    try {
      await apiClient.addKnowledgeFact(suggestion.question, suggestion.answer)
      setState('saved')
      setTimeout(dismiss, 1500)
    } catch {
      // On error, just dismiss
      dismiss()
    }
  }

  const handleIgnore = () => {
    if (timerRef.current) clearTimeout(timerRef.current)
    dismiss()
  }

  return (
    <div className={`knowledge-toast${isExiting ? ' knowledge-toast--exit' : ''}`}>
      <div className="knowledge-toast__header">
        <span className="knowledge-toast__icon" aria-hidden="true">&#128214;</span>
        <span className="knowledge-toast__title">
          {state === 'saved' ? `${t('saved')} \u2713` : t('knowledge_toast_title')}
        </span>
        <button
          className="knowledge-toast__close"
          onClick={handleIgnore}
          aria-label={t('close')}
          type="button"
        >
          <CloseIcon />
        </button>
      </div>

      <div className="knowledge-toast__fact">
        <span className="knowledge-toast__answer">{suggestion.answer}</span>
        {suggestion.context && (
          <span className="knowledge-toast__context">{suggestion.context}</span>
        )}
      </div>

      {state === 'idle' && (
        <div className="knowledge-toast__actions">
          <button
            className="knowledge-toast__btn knowledge-toast__btn--secondary"
            onClick={handleIgnore}
            type="button"
          >
            {t('ignore')}
          </button>
          <button
            className="knowledge-toast__btn knowledge-toast__btn--primary"
            onClick={handleAdd}
            type="button"
          >
            {t('knowledge_toast_add')}
          </button>
        </div>
      )}

      {state === 'saving' && (
        <div className="knowledge-toast__actions">
          <span className="knowledge-toast__saving">{t('saving')}</span>
        </div>
      )}
    </div>
  )
}
