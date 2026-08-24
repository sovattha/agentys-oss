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

import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchAccounts } from '../../api/accounts'
import { ContactAutocomplete } from './ContactAutocomplete'
import { Button } from '../ui/button'
import './ComposeEmailForm.css'

export interface ComposeEmailRequest {
  to: string
  subject: string
  instructions: string
  useHistory: boolean
}

interface ComposeEmailFormProps {
  onSubmit: (data: ComposeEmailRequest) => void
  onCancel: () => void
  isLoading: boolean
}

interface FormErrors {
  to?: string
  subject?: string
}

function validateEmail(email: string): boolean {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  return emailRegex.test(email)
}

export function ComposeEmailForm({ onSubmit, onCancel, isLoading }: ComposeEmailFormProps) {
  const { t } = useTranslation('compose')
  const { t: tCommon } = useTranslation('common')
  const [to, setTo] = useState('')
  const [subject, setSubject] = useState('')
  const [instructions, setInstructions] = useState('')
  const [useHistory, setUseHistory] = useState(true)
  const [errors, setErrors] = useState<FormErrors>({})
  const [currentAccountId, setCurrentAccountId] = useState<string | undefined>()

  useEffect(() => {
    fetchAccounts().then(({ accounts, current_account_id }) => {
      const current = current_account_id
        ? accounts.find(a => a.id === current_account_id)
        : accounts[0]
      if (current) setCurrentAccountId(current.id)
    }).catch(err => console.error('[ComposeEmailForm] fetch accounts failed:', err))
  }, [])

  const validate = (): boolean => {
    const newErrors: FormErrors = {}

    if (!to.trim()) {
      newErrors.to = t('email_required')
    } else if (!validateEmail(to.trim())) {
      newErrors.to = t('email_invalid')
    }

    if (!subject.trim()) {
      newErrors.subject = t('subject_required')
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()

    if (!validate()) {
      return
    }

    onSubmit({
      to: to.trim(),
      subject: subject.trim(),
      instructions: instructions.trim(),
      useHistory,
    })
  }

  return (
    <form className="compose-email-form" data-testid="compose-form" onSubmit={handleSubmit} noValidate>
      <div className="form-field">
        <label htmlFor="compose-to">{t('to_label')}</label>
        <ContactAutocomplete
          value={to}
          onChange={setTo}
          accountId={currentAccountId}
          placeholder="alex@agentys.app"
          disabled={isLoading}
          autoFocus
          aria-describedby={errors.to ? "compose-to-error" : undefined}
          aria-invalid={!!errors.to}
        />
        {errors.to && <span id="compose-to-error" className="field-error" data-testid="error-to" role="alert">{errors.to}</span>}
      </div>

      <div className="form-field">
        <label htmlFor="compose-subject">{t('subject_label_upper')}</label>
        <input
          id="compose-subject"
          data-testid="compose-subject"
          type="text"
          name="subject"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          placeholder={t('subject_placeholder_text')}
          disabled={isLoading}
          aria-describedby={errors.subject ? "compose-subject-error" : undefined}
          aria-invalid={!!errors.subject}
        />
        {errors.subject && <span id="compose-subject-error" className="field-error" data-testid="error-subject" role="alert">{errors.subject}</span>}
      </div>

      <div className="form-field">
        <label htmlFor="compose-instructions">{t('instructions_label')}</label>
        <textarea
          id="compose-instructions"
          data-testid="compose-instructions"
          name="instructions"
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          placeholder={t('ask_agentys')}
          rows={4}
          disabled={isLoading}
        />
      </div>

      <div className="form-field-checkbox">
        <input
          id="compose-use-history"
          data-testid="compose-use-history"
          type="checkbox"
          checked={useHistory}
          onChange={(e) => setUseHistory(e.target.checked)}
          disabled={isLoading}
        />
        <label htmlFor="compose-use-history">
          {t('use_history')}
        </label>
      </div>

      <div className="form-actions">
        <Button
          type="button"
          variant="outline"
          data-testid="compose-cancel"
          onClick={onCancel}
          disabled={isLoading}
        >
          {tCommon('cancel')}
        </Button>
        <Button
          type="submit"
          data-testid="compose-submit"
          disabled={isLoading}
        >
          {isLoading ? t('generating_draft') : t('generate_draft')}
        </Button>
      </div>
    </form>
  )
}
