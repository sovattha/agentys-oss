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

import { useState, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { ContactAutocomplete } from '../compose/ContactAutocomplete'
import { CloseIcon, CheckIcon } from '../icons/ActionIcons'
import './ShareSnippetDialog.css'

interface ShareSnippetDialogProps {
  isOpen: boolean
  onClose: () => void
  snippetName: string
  onShare: (email: string) => Promise<void>
}

export function ShareSnippetDialog({
  isOpen,
  onClose,
  snippetName,
  onShare,
}: ShareSnippetDialogProps) {
  const { t } = useTranslation('settings')
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (isOpen) {
      setEmail('')
      setError(null)
      setSuccess(false)
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 100)
    }
  }, [isOpen])

  const handleSubmit = async () => {
    const trimmed = email.trim().toLowerCase()
    if (!trimmed || !trimmed.includes('@')) {
      setError('Veuillez saisir un email valide')
      return
    }

    setLoading(true)
    setError(null)

    try {
      await onShare(trimmed)
      setSuccess(true)
      setTimeout(() => onClose(), 1500)
    } catch (err: unknown) {
      setError((err as Error).message || 'Erreur lors du partage')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="share-dialog" showCloseButton={false} aria-describedby={undefined}>
        <div className="share-dialog-header">
          <DialogTitle asChild><h3>{t('share_snippet_title')}</h3></DialogTitle>
          <button className="share-dialog-close" onClick={onClose}>
            <CloseIcon />
          </button>
        </div>

        <p className="share-dialog-snippet-name">{snippetName}</p>

        {success ? (
          <div className="share-dialog-success">
            <CheckIcon size={20} />
            {t('share_snippet_success')}
          </div>
        ) : (
          <>
            <div className="share-dialog-field">
              <label htmlFor="share-email">{t('share_snippet_email_label')}</label>
              {/*
                ContactAutocomplete in single-mode (multi=false) so the user
                picks ONE coworker to share to. ``includeAllContacts`` so
                inbound senders (not just sent-to recipients) show up — a
                shared snippet often goes to someone you've corresponded
                with, in either direction. ``includeSelf=false`` because
                sharing a snippet to yourself is meaningless.
              */}
              <ContactAutocomplete
                value={email}
                onChange={(v) => {
                  setEmail(v)
                  setError(null)
                }}
                inputRef={inputRef}
                placeholder={t('share_snippet_placeholder')}
                disabled={loading}
                multi={false}
                includeAllContacts={true}
                includeSelf={false}
                onContactSelect={({ email: picked }) => {
                  setEmail(picked)
                  setError(null)
                }}
                autoFocus
              />
            </div>

            {error && (
              <div className="share-dialog-error" role="alert">
                {error}
              </div>
            )}

            <div className="share-dialog-actions">
              <button
                className="share-dialog-submit"
                onClick={handleSubmit}
                disabled={loading || !email.trim()}
              >
                {loading ? t('share_snippet_sharing') : t('share_snippet_share')}
              </button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
