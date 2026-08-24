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

import { useState, useCallback, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { SupportChat } from './SupportChat'
import { SupportForm } from './SupportForm'
import { SupportHelpSection } from './SupportHelpSection'
import { ChevronLeftIcon, CloseIcon, CheckIcon, SendIcon } from '../icons/ActionIcons'
import './SupportPanel.css'

export type PanelView =
  | { screen: 'chat' }
  | { screen: 'form'; intent: 'support' | 'feedback' | 'bug' | 'feature' }
  | { screen: 'help' }
  | { screen: 'help-article'; articleId: string }
  | { screen: 'sending' }
  | { screen: 'success'; ticketRef: string }
  | { screen: 'error'; message: string }

interface SupportPanelProps {
  isOpen: boolean
  onClose: () => void
  accountEmail: string
}

export function SupportPanel({ isOpen, onClose, accountEmail }: SupportPanelProps) {
  const { t } = useTranslation('support')
  const [view, setView] = useState<PanelView>({ screen: 'chat' })
  const [isClosing, setIsClosing] = useState(false)

  const handleClose = useCallback(() => {
    setIsClosing(true)
    setTimeout(() => {
      onClose()
      setIsClosing(false)
      setView({ screen: 'chat' })
    }, 150)
  }, [onClose])

  const handleBack = useCallback(() => {
    switch (view.screen) {
      case 'form':
      case 'help':
      case 'success':
      case 'error':
        setView({ screen: 'chat' })
        break
      case 'help-article':
        setView({ screen: 'help' })
        break
      default:
        handleClose()
    }
  }, [view, handleClose])

  // Escape key handling
  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        if (view.screen === 'chat') {
          handleClose()
        } else {
          handleBack()
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown, true)
    return () => window.removeEventListener('keydown', handleKeyDown, true)
  }, [isOpen, view, handleClose, handleBack])

  if (!isOpen && !isClosing) return null

  // Resolve title + subtitle
  const SCREEN_TITLE_KEYS: Record<string, string> = {
    chat: 'screen_chat_title',
    help: 'screen_help_title',
    'help-article': 'screen_article_title',
    sending: 'screen_sending_title',
    success: 'screen_success_title',
    error: 'screen_error_title',
  }

  let title: string
  let subtitle: string | undefined
  if (view.screen === 'form' && 'intent' in view) {
    const intentKey = view.intent as string
    title = t(`form_${intentKey}_title`)
    subtitle = t(`form_${intentKey}_subtitle`)
  } else {
    title = t(SCREEN_TITLE_KEYS[view.screen] ?? 'screen_chat_title')
    subtitle = view.screen === 'chat' ? t('screen_chat_subtitle') : undefined
  }

  const showBack = view.screen !== 'chat' && view.screen !== 'sending'

  return (
    <div className={`sp-overlay${isClosing ? ' sp-closing' : ''}`} role="dialog" aria-label="Support Agentys">
      {/* Accent gradient bar */}
      <div className="sp-accent-bar" />

      {/* Header */}
      <div className="sp-header">
        {showBack && (
          <button className="sp-header-back" onClick={handleBack} aria-label={t('back')}>
            <ChevronLeftIcon size={20} />
          </button>
        )}
        <div className="sp-header-center">
          <div className="sp-header-title">{title}</div>
          {subtitle && (
            <div className="sp-header-subtitle">
              {view.screen === 'chat' && <span className="sp-status-dot" />}
              {subtitle}
            </div>
          )}
        </div>
        <button className="sp-header-close" onClick={handleClose} aria-label={t('close')}>
          <CloseIcon />
        </button>
      </div>

      {/* Body */}
      <div className={`sp-body${view.screen === 'chat' ? ' sp-body-chat' : ''}`}>
        {view.screen === 'chat' && (
          <SupportChat onNavigate={setView} onClose={handleClose} accountEmail={accountEmail} />
        )}

        {view.screen === 'form' && 'intent' in view && (
          <SupportForm
            intent={view.intent}
            accountEmail={accountEmail}
            formId="sp-contact-form"
            onSending={() => setView({ screen: 'sending' })}
            onSuccess={(ticketRef) => setView({ screen: 'success', ticketRef })}
            onError={(message) => setView({ screen: 'error', message })}
          />
        )}

        {view.screen === 'help' && (
          <SupportHelpSection
            onNavigateToArticle={(articleId) => setView({ screen: 'help-article', articleId })}
          />
        )}

        {view.screen === 'help-article' && 'articleId' in view && (
          <SupportHelpSection
            articleId={view.articleId}
            onNavigateToArticle={(articleId) => setView({ screen: 'help-article', articleId })}
          />
        )}

        {view.screen === 'sending' && (
          <div className="sp-sending">
            <div className="sp-spinner" />
            <span className="sp-sending-text">{t('sending_text')}</span>
          </div>
        )}

        {view.screen === 'success' && 'ticketRef' in view && (
          <div className="sp-success">
            <div className="sp-success-check">
              <CheckIcon size={26} />
            </div>
            <span className="sp-success-title">{t('message_sent')}</span>
            {view.ticketRef && <span className="sp-success-ref">{view.ticketRef}</span>}
            <span className="sp-success-msg">{t('success_ref_hint')}</span>
            <button className="sp-success-btn" onClick={handleClose}>{t('close')}</button>
          </div>
        )}

        {view.screen === 'error' && 'message' in view && (
          <div className="sp-error">
            <div className="sp-error-icon">
              <CloseIcon size={24} />
            </div>
            <span className="sp-error-title">{t('error_title')}</span>
            <span className="sp-error-msg">{view.message}</span>
            <button className="sp-error-btn" onClick={handleBack}>{t('retry')}</button>
          </div>
        )}
      </div>

      {/* Footer with submit button — outside scroll area to avoid border-radius clipping */}
      {view.screen === 'form' && (
        <div className="sp-footer">
          <button type="submit" form="sp-contact-form" className="sp-submit">
            <SendIcon size={15} />
            {t('send')}
          </button>
        </div>
      )}
    </div>
  )
}
