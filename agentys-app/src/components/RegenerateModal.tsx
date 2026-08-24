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

import { useState, useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { CloseIcon } from './icons/ActionIcons';
import './RegenerateModal.css';

interface RegenerateModalProps {
  isOpen: boolean;
  onClose: () => void;
  onRegenerate: (instructions: string) => Promise<void>;
  previousInstructions?: string;
  isLoading?: boolean;
}

export function RegenerateModal({
  isOpen,
  onClose,
  onRegenerate,
  previousInstructions = '',
  isLoading = false,
}: RegenerateModalProps) {
  const { t } = useTranslation('drafts');
  const [instructions, setInstructions] = useState(previousInstructions);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Pre-fill with previous instructions when modal opens
  useEffect(() => {
    if (isOpen) {
      setInstructions(previousInstructions);
      // Focus textarea when modal opens
      setTimeout(() => {
        textareaRef.current?.focus();
      }, 100);
    }
  }, [isOpen, previousInstructions]);

  const handleSubmit = useCallback(async () => {
    if (!instructions.trim() || isLoading) return;
    await onRegenerate(instructions.trim());
  }, [instructions, isLoading, onRegenerate]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Ctrl/Cmd + Enter to submit
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && !isLoading) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open && !isLoading) onClose(); }}>
      <DialogContent className="regenerate-modal" showCloseButton={false}>
        <div className="regenerate-modal-header">
          <DialogTitle>{t('regenerate_modal_title')}</DialogTitle>
          <button
            className="regenerate-modal-close"
            onClick={onClose}
            disabled={isLoading}
            aria-label={t('cancel')}
          >
            <CloseIcon />
          </button>
        </div>

        <div className="regenerate-modal-body">
          <DialogDescription className="regenerate-modal-description">
            {t('regenerate_modal_description')}
          </DialogDescription>

          <label htmlFor="regenerate-instructions" className="regenerate-modal-label">
            {t('regenerate_modal_label')}
          </label>
          <textarea
            id="regenerate-instructions"
            ref={textareaRef}
            className="regenerate-modal-textarea"
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t('regenerate_modal_label')}
            disabled={isLoading}
            rows={4}
            maxLength={2000}
            data-testid="regenerate-instructions-input"
          />
          <div className="regenerate-modal-char-count">
            {t('regenerate_char_count', { count: instructions.length })}
          </div>

          {/* Quick suggestions */}
          <div className="regenerate-modal-suggestions">
            <span className="suggestions-label">{t('regenerate_suggestions_label')}</span>
            <button
              type="button"
              className="suggestion-chip"
              onClick={() => setInstructions(t('regenerate_more_formal'))}
              disabled={isLoading}
            >
              {t('regenerate_more_formal_chip')}
            </button>
            <button
              type="button"
              className="suggestion-chip"
              onClick={() => setInstructions(t('refine_shorten'))}
              disabled={isLoading}
            >
              {t('regenerate_shorter_chip')}
            </button>
            <button
              type="button"
              className="suggestion-chip"
              onClick={() => setInstructions(t('refine_friendlier'))}
              disabled={isLoading}
            >
              {t('regenerate_friendlier_chip')}
            </button>
            <button
              type="button"
              className="suggestion-chip"
              onClick={() => setInstructions(t('refine_more_detail'))}
              disabled={isLoading}
            >
              {t('regenerate_more_detail_chip')}
            </button>
          </div>
        </div>

        <div className="regenerate-modal-footer">
          <button
            type="button"
            className="regenerate-modal-submit"
            onClick={handleSubmit}
            disabled={isLoading || !instructions.trim()}
            data-testid="regenerate-submit-button"
          >
            {isLoading ? (
              <>
                <span className="regenerate-spinner" />
                {t('regenerating')}
              </>
            ) : (
              t('regenerate')
            )}
          </button>
        </div>

        <div className="regenerate-modal-hint">
          {t('regenerate_hint')}
        </div>
      </DialogContent>
    </Dialog>
  );
}
