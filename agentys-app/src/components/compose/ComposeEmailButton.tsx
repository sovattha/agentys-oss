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
import { Tooltip } from '../Tooltip'
import { formatShortcutForDisplay } from '../../types/shortcuts'
import { EditIcon } from '../icons/ActionIcons'
import './ComposeEmailButton.css'

interface ComposeEmailButtonProps {
  onClick: () => void
  disabled?: boolean
}

export function ComposeEmailButton({ onClick, disabled = false }: ComposeEmailButtonProps) {
  const { t } = useTranslation('compose')
  return (
    <Tooltip content={t('new_message')} shortcut={formatShortcutForDisplay('CmdOrCtrl+N')} position="bottom">
      <button
        className="compose-email-button"
        onClick={onClick}
        disabled={disabled}
        type="button"
        aria-label={t('compose_new_message')}
      >
        <EditIcon className="compose-email-icon" size={24} />
        <span className="compose-email-text">{t('new_message')}</span>
      </button>
    </Tooltip>
  )
}
