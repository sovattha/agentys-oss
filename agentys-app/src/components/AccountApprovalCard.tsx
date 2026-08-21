import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { apiClient } from '../services/api'
import type { PendingDraft } from '../services/api'
import './AccountApprovalCard.css'

type AccountInfo = NonNullable<PendingDraft['account_info']>

interface AccountApprovalCardProps {
  draftId: string
  accountInfo: AccountInfo
  onConfirmed: (updated: AccountInfo, newDraftBody?: string) => void
  onRejected: (updated: AccountInfo) => void
}

const ACTION_ICONS: Record<string, React.JSX.Element> = {
  password_reset: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  ),
  email_change: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
      <polyline points="22,6 12,13 2,6" />
    </svg>
  ),
}

export function AccountApprovalCard({ draftId, accountInfo, onConfirmed, onRejected }: AccountApprovalCardProps) {
  const { t } = useTranslation('common')
  const [state, setState] = useState<'idle' | 'rejecting' | 'loading'>('idle')
  const [rejectReason, setRejectReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [localInfo, setLocalInfo] = useState<AccountInfo>(accountInfo)
  const [revealedPassword, setRevealedPassword] = useState<string | null>(null)

  const isLoading = state === 'loading'
  const actionLabel = localInfo.action === 'password_reset'
    ? t('account_password_reset')
    : t('account_email_change')

  async function handleConfirm() {
    setState('loading')
    setError(null)
    try {
      const resp = await apiClient.confirmAccountAction(draftId)
      const updated: AccountInfo = { ...localInfo, status: 'executed' }
      setLocalInfo(updated)
      if (resp.new_password) {
        setRevealedPassword(resp.new_password)
      }
      onConfirmed(updated, resp.new_body)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t('error')
      setError(msg)
      setState('idle')
    }
  }

  async function handleReject() {
    setState('loading')
    setError(null)
    try {
      await apiClient.rejectAccountAction(draftId, rejectReason)
      const updated: AccountInfo = { ...localInfo, status: 'rejected' }
      setLocalInfo(updated)
      onRejected(updated)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t('error')
      setError(msg)
    } finally {
      setState('idle')
    }
  }

  return (
    <div className="account-card" role="region" aria-label={t('account_action_detected')}>
      <div className="account-card-header">
        {ACTION_ICONS[localInfo.action] || ACTION_ICONS.password_reset}
        <span>{t('account_action_detected')}</span>
      </div>

      <div className="account-card-body">
        <div className="account-card-row">
          <span className="account-label">{t('account_action_type')}</span>
          <span className="account-value account-action">{actionLabel}</span>
        </div>
        <div className="account-card-row">
          <span className="account-label">{t('account_requester')}</span>
          <span className="account-value">{localInfo.requester_email}</span>
        </div>
        {localInfo.wp_username && (
          <div className="account-card-row">
            <span className="account-label">{t('account_wp_user')}</span>
            <code className="account-value account-mono">{localInfo.wp_username}</code>
          </div>
        )}
        {localInfo.wp_user_id && (
          <div className="account-card-row">
            <span className="account-label">ID</span>
            <code className="account-value account-mono">#{localInfo.wp_user_id}</code>
          </div>
        )}
        {localInfo.action === 'email_change' && localInfo.new_email && (
          <div className="account-card-row">
            <span className="account-label">{t('account_new_email')}</span>
            <span className="account-value account-highlight">{localInfo.wp_user_email} → {localInfo.new_email}</span>
          </div>
        )}
        <div className="account-card-row">
          <span className="account-label">{t('account_status')}</span>
          <span className={`account-badge account-badge--${localInfo.status}`}>
            {t(`account_status_${localInfo.status}`)}
          </span>
        </div>

        {(localInfo.status === 'not_found' ||
          localInfo.status === 'executed' ||
          (localInfo.status === 'pending' && !localInfo.wp_user_id)) && (
          <p className="account-warn-reason">{localInfo.reason}</p>
        )}

        {revealedPassword && (
          <div className="account-password-reveal">
            <span className="account-label">{t('account_new_password')}</span>
            <code className="account-value account-mono account-password">{revealedPassword}</code>
          </div>
        )}

        {error && <p className="account-error">{error}</p>}
      </div>

      {localInfo.status === 'pending' && (
        <div className="account-card-actions">
          {state === 'rejecting' ? (
            <div className="account-reject-form">
              <textarea
                className="account-reject-textarea"
                placeholder={t('account_reject_reason_placeholder')}
                value={rejectReason}
                onChange={e => setRejectReason(e.target.value)}
                rows={2}
                autoFocus
              />
              <div className="account-reject-buttons">
                <button className="account-btn account-btn--reject" onClick={handleReject} disabled={isLoading}>
                  {t('account_confirm_reject')}
                </button>
                <button className="account-btn account-btn--cancel" onClick={() => setState('idle')} disabled={isLoading}>
                  {t('cancel')}
                </button>
              </div>
            </div>
          ) : (
            <>
              <button
                className="account-btn account-btn--confirm"
                onClick={handleConfirm}
                disabled={isLoading}
                title={actionLabel}
              >
                {isLoading
                  ? <><span className="account-spinner" />{t('account_processing')}</>
                  : t('account_confirm_btn')
                }
              </button>
              <button
                className="account-btn account-btn--reject"
                onClick={() => setState('rejecting')}
                disabled={isLoading}
              >
                {t('account_reject_btn')}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}
