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

import { useState, useRef, useCallback, useId, type ReactNode } from 'react'
import { useTooltipSettings } from '../hooks/useTooltipSettings.js'
import './Tooltip.css'

export type TooltipPosition = 'top' | 'bottom' | 'left' | 'right'

interface TooltipProps {
  /** Tooltip text content */
  content: string
  /** Keyboard shortcut to display (e.g., "Cmd+N") */
  shortcut?: string
  /** Position relative to the target element */
  position?: TooltipPosition
  /** Delay before showing tooltip in ms (default: 500ms per AC3) */
  delay?: number
  /** Disable this specific tooltip */
  disabled?: boolean
  /** Target element(s) to attach tooltip to */
  children: ReactNode
}

/**
 * Accessible tooltip component with keyboard shortcut support.
 *
 * @example
 * <Tooltip content="Synchroniser les emails" shortcut="Cmd+Shift+S">
 *   <button onClick={handleSync}>
 *     <SyncIcon />
 *   </button>
 * </Tooltip>
 */
export function Tooltip({
  content,
  shortcut,
  children,
  position = 'top',
  delay = 500,
  disabled = false,
}: TooltipProps) {
  const [isVisible, setIsVisible] = useState(false)
  const showTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const hideTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const tooltipId = useId()
  const { tooltipsEnabled } = useTooltipSettings()

  const isEffectivelyDisabled = disabled || !tooltipsEnabled

  const clearTimeouts = useCallback(() => {
    if (showTimeoutRef.current) {
      clearTimeout(showTimeoutRef.current)
      showTimeoutRef.current = null
    }
    if (hideTimeoutRef.current) {
      clearTimeout(hideTimeoutRef.current)
      hideTimeoutRef.current = null
    }
  }, [])

  const show = useCallback(() => {
    if (isEffectivelyDisabled) return
    clearTimeouts()
    showTimeoutRef.current = setTimeout(() => {
      setIsVisible(true)
    }, delay)
  }, [isEffectivelyDisabled, delay, clearTimeouts])

  const hide = useCallback(() => {
    clearTimeouts()
    hideTimeoutRef.current = setTimeout(() => {
      setIsVisible(false)
    }, 100)
  }, [clearTimeouts])

  return (
    <div
      className="tooltip-wrapper"
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      aria-describedby={isVisible ? tooltipId : undefined}
    >
      {children}
      {isVisible && (
        <div
          id={tooltipId}
          role="tooltip"
          className={`tooltip tooltip-${position}`}
        >
          <span className="tooltip-content">{content}</span>
          {shortcut && (
            <kbd className="tooltip-shortcut">{shortcut}</kbd>
          )}
        </div>
      )}
    </div>
  )
}
