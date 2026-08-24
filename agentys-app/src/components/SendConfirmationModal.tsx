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

/* eslint-disable react-refresh/only-export-components */
import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { CloseIcon } from './icons/ActionIcons';
import './SendConfirmationModal.css';

const SEND_CONFIRMATION_SKIP_KEY = 'agentys_skip_send_confirmation';
const COUNTDOWN_SECONDS = 3;

interface SendConfirmationModalProps {
  isOpen: boolean;
  recipient: string;
  recipientName?: string;
  subject: string;
  onConfirm: () => void;
  onCancel: () => void;
  isLoading?: boolean;
}

export function SendConfirmationModal({
  isOpen,
  recipient,
  recipientName,
  subject,
  onConfirm,
  onCancel,
  isLoading = false,
}: SendConfirmationModalProps) {
  const { t } = useTranslation('compose');
  const [countdown, setCountdown] = useState(COUNTDOWN_SECONDS);
  const [skipNextTime, setSkipNextTime] = useState(false);
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const confirmButtonRef = useRef<HTMLButtonElement>(null);

  // Reset countdown and start timer when modal opens
  useEffect(() => {
    if (isOpen) {
      setCountdown(COUNTDOWN_SECONDS);
      setSkipNextTime(false);

      countdownRef.current = setInterval(() => {
        setCountdown((prev) => {
          if (prev <= 1) {
            if (countdownRef.current) {
              clearInterval(countdownRef.current);
            }
            return 0;
          }
          return prev - 1;
        });
      }, 1000);

      return () => {
        if (countdownRef.current) {
          clearInterval(countdownRef.current);
        }
      };
    }
  }, [isOpen]);

  // Save skip preference and confirm
  const handleConfirm = useCallback(() => {
    if (skipNextTime) {
      localStorage.setItem(SEND_CONFIRMATION_SKIP_KEY, 'true');
    }
    onConfirm();
  }, [skipNextTime, onConfirm]);

  // Focus confirm button when countdown finishes
  useEffect(() => {
    if (countdown === 0 && confirmButtonRef.current && !isLoading) {
      confirmButtonRef.current.focus();
    }
  }, [countdown, isLoading]);

  const isConfirmDisabled = countdown > 0 || isLoading;
  const displayName = recipientName || recipient;

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open && !isLoading) onCancel(); }}>
      <DialogContent className="send-confirmation-modal" showCloseButton={false} data-testid="send-confirmation-overlay">
        <div className="send-confirmation-modal-header">
          <DialogTitle>{t('send_confirmation_title')}</DialogTitle>
          <button
            className="send-confirmation-modal-close"
            onClick={onCancel}
            disabled={isLoading}
            aria-label={t('close')}
            data-testid="close-button"
          >
            <CloseIcon />
          </button>
        </div>

        <div className="send-confirmation-modal-body">
          <DialogDescription className="send-confirmation-description">
            {t('send_confirmation_description')}
          </DialogDescription>

          {/* Summary Section (AC1) */}
          <div className="send-summary" data-testid="send-summary">
            <div className="summary-row">
              <span className="summary-label">{t('recipient')}</span>
              <span className="summary-value" data-testid="summary-recipient">
                {displayName}
                {recipientName && <span className="summary-email"> &lt;{recipient}&gt;</span>}
              </span>
            </div>
            <div className="summary-row">
              <span className="summary-label">{t('email_subject')}</span>
              <span className="summary-value" data-testid="summary-subject">{subject}</span>
            </div>
          </div>

          {/* Countdown Progress (AC3) */}
          {countdown > 0 && (
            <div className="countdown-container" data-testid="countdown-container">
              <div className="countdown-progress">
                <div
                  className="countdown-bar"
                  style={{ width: `${((COUNTDOWN_SECONDS - countdown) / COUNTDOWN_SECONDS) * 100}%` }}
                />
              </div>
              <span className="countdown-text" data-testid="countdown-text">
                {t(countdown > 1 ? 'countdown_text_other' : 'countdown_text_one', { count: countdown })}
              </span>
            </div>
          )}

          {/* Skip checkbox (AC4) */}
          <label className="skip-checkbox-label" data-testid="skip-checkbox-label">
            <input
              type="checkbox"
              checked={skipNextTime}
              onChange={(e) => setSkipNextTime(e.target.checked)}
              disabled={isLoading}
              data-testid="skip-checkbox"
            />
            <span>{t('skip_confirmation')}</span>
          </label>
        </div>

        <div className="send-confirmation-modal-footer">
          {/* Confirm button (AC2, AC3) */}
          <button
            ref={confirmButtonRef}
            type="button"
            className="send-confirmation-confirm"
            onClick={handleConfirm}
            disabled={isConfirmDisabled}
            data-testid="confirm-button"
          >
            {isLoading ? (
              <>
                <span className="send-spinner" />
                {t('sending_in_progress')}
              </>
            ) : countdown > 0 ? (
              t('confirm_send_countdown', { count: countdown })
            ) : (
              t('confirm_send')
            )}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// Helper to check if confirmation should be skipped
export function shouldSkipSendConfirmation(): boolean {
  return localStorage.getItem(SEND_CONFIRMATION_SKIP_KEY) === 'true';
}

// Helper to reset skip preference (for settings)
export function resetSendConfirmationPreference(): void {
  localStorage.removeItem(SEND_CONFIRMATION_SKIP_KEY);
}
