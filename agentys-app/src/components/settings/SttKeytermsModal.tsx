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

import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { SttKeytermsManager } from './SttKeytermsManager'
import { ChevronLeftIcon, CloseIcon } from '../icons/ActionIcons'
import './SttKeytermsModal.css'

interface SttKeytermsModalProps {
  isOpen: boolean
  onClose: () => void
}

export function SttKeytermsModal({ isOpen, onClose }: SttKeytermsModalProps) {
  const { t } = useTranslation('settings')

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent
        className="stt-keyterms-modal"
        showCloseButton={false}
        aria-describedby={undefined}
      >
        <div className="stt-keyterms-modal-header">
          <button
            type="button"
            className="stt-keyterms-modal-back"
            onClick={onClose}
            aria-label={t('common:back')}
          >
            <ChevronLeftIcon />
          </button>
          <DialogTitle className="stt-keyterms-modal-title">
            {t('stt_keyterms_modal_title')}
          </DialogTitle>
          <button
            type="button"
            className="stt-keyterms-modal-close"
            onClick={onClose}
            aria-label={t('common:close')}
          >
            <CloseIcon />
          </button>
        </div>

        <div className="stt-keyterms-modal-body">
          <SttKeytermsManager />
        </div>
      </DialogContent>
    </Dialog>
  )
}
