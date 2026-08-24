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

import { useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { SchedulePicker } from './SchedulePicker'
import { SendIcon, ChevronDownIcon } from '../icons/ActionIcons'

interface Props {
  onSend: () => void
  onSchedule: (sendAtUtc: Date) => void
  disabled?: boolean
  loading?: boolean
  /** Texte du bouton principal — par defaut "Envoyer" */
  label?: string
  /** testid du bouton principal pour les tests E2E */
  sendTestId?: string
  /** classname additionnel sur la pill */
  pillClassName?: string
}

export function SendButtonSplit({
  onSend,
  onSchedule,
  disabled,
  loading,
  label,
  sendTestId,
  pillClassName,
}: Props) {
  const { t } = useTranslation('inbox')
  const [pickerPos, setPickerPos] = useState<{ x: number; y: number; buttonTop: number } | null>(null)
  const chevronRef = useRef<HTMLButtonElement | null>(null)

  const handleChevronClick = () => {
    const rect = chevronRef.current?.getBoundingClientRect()
    if (!rect) return
    const x = Math.max(8, Math.min(rect.left, window.innerWidth - 328))
    setPickerPos({ x, y: rect.bottom, buttonTop: rect.top })
  }

  const handleSelect = (dateLocal: Date) => {
    setPickerPos(null)
    onSchedule(dateLocal)
  }

  const sendLabel = label ?? t('send', 'Envoyer')

  return (
    <>
      <span className={`send-pill-split ${pillClassName || ''}`} aria-disabled={disabled}>
        <button
          type="button"
          className="send-pill send-pill-split__main"
          onClick={onSend}
          disabled={disabled || loading}
          data-testid={sendTestId}
        >
          {loading ? (
            <span className="refine-spinner" />
          ) : (
            <SendIcon size={14} />
          )}
          <span>{sendLabel}</span>
        </button>
        <button
          ref={chevronRef}
          type="button"
          className="send-pill-split__chevron"
          onClick={handleChevronClick}
          disabled={disabled || loading}
          aria-label={t('schedule_send_aria', 'Programmer un envoi')}
          title={t('schedule_send_aria', 'Programmer un envoi')}
          data-testid="send-split-chevron"
        >
          <ChevronDownIcon size={12} />
        </button>
      </span>
      {pickerPos && createPortal(
        <SchedulePicker
          position={pickerPos}
          onSelect={handleSelect}
          onClose={() => setPickerPos(null)}
        />,
        document.body
      )}
    </>
  )
}
