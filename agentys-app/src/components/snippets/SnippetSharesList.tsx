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

import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import type { SnippetShareInfo } from '../../types/snippets'
import { fetchSnippetShares } from '../../api/snippets'
import { useOptimisticMutation } from '../../hooks/useOptimisticMutation'
import { CloseIcon } from '../icons/ActionIcons'
import './SnippetSharesList.css'

interface SnippetSharesListProps {
  isOpen: boolean
  onClose: () => void
  snippetId: string
  onRevoke: (email: string) => Promise<void>
}

export function SnippetSharesList({
  isOpen,
  onClose,
  snippetId,
  onRevoke,
}: SnippetSharesListProps) {
  const { t } = useTranslation('common')
  const [shares, setShares] = useState<SnippetShareInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [revoking, setRevoking] = useState<string | null>(null)
  const popoverRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!isOpen) return
    setLoading(true)
    fetchSnippetShares(snippetId)
      .then((res) => setShares(res.shares))
      .catch(console.warn)
      .finally(() => setLoading(false))
  }, [isOpen, snippetId])

  useEffect(() => {
    if (!isOpen) return
    const handleClickOutside = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isOpen, onClose])

  // Audit Cluster D (2026-05-17) Toast Site 7 / #330: previously
  // console.warn only. The revoke spinner cleared with no feedback so
  // the user thought it worked, then the share reappeared at next refresh.
  const runRevokeShare = useOptimisticMutation<void>({
    scope: 'snippet-shares-revoke',
    i18nKey: 'toasts.snippet_share_revoke_failed',
  })
  const handleRevoke = async (email: string) => {
    setRevoking(email)
    await runRevokeShare(async () => {
      await onRevoke(email)
      setShares((prev) => prev.filter((s) => s.email !== email))
    })
    setRevoking(null)
  }

  if (!isOpen) return null

  return (
    <div className="snippet-shares-list" ref={popoverRef}>
      <div className="snippet-shares-header">
        <span>{t('snippets_shared_with')}</span>
        <button className="snippet-shares-close" onClick={onClose}>
          <CloseIcon size={14} />
        </button>
      </div>

      {loading ? (
        <div className="snippet-shares-loading">
          <span className="snippet-shares-spinner" />
        </div>
      ) : shares.length === 0 ? (
        <div className="snippet-shares-empty">
          {t('snippets_no_shares')}
        </div>
      ) : (
        <div className="snippet-shares-items">
          {shares.map((share) => (
            <div key={share.share_id} className="snippet-share-item">
              <span className="snippet-share-email">{share.email}</span>
              <button
                className="snippet-share-revoke"
                onClick={() => handleRevoke(share.email)}
                disabled={revoking === share.email}
                title={t('revoke')}
                aria-label={t('revoke')}
              >
                {revoking === share.email ? '...' : <CloseIcon size={14} />}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
