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
import './AIProcessButton.css'

interface AIProcessButtonProps {
  active: boolean
  onClick: () => void
  disabled?: boolean
}

export function AIProcessButton({ active, onClick, disabled }: AIProcessButtonProps) {
  const { t } = useTranslation('compose')
  const label = t('ai_process')
  return (
    <button
      type="button"
      className={`rc-ai-toggle${active ? ' rc-ai-toggle--active' : ''}`}
      title={label}
      aria-label={label}
      aria-pressed={active}
      onClick={onClick}
      disabled={disabled}
      data-testid="ai-process-button"
    >
      AI
    </button>
  )
}
