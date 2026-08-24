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
/**
 * Toast Component
 *
 * Story 7-7: Plain Language Error Messages
 * - AC2: Each error proposes a concrete action
 * - AC6: Direct action buttons when possible
 *
 * Enhanced toast notifications with action buttons and click-to-expand for error details.
 */

import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { type HumanError, type ErrorActionType } from '../services/errorMessages'
import { CloseIcon } from './icons/ActionIcons'
import './Toast.css'

export type ToastType = 'success' | 'error' | 'info' | 'warning'

export interface ToastAction {
  label: string
  onClick: () => void
}

export interface ToastData {
  id: string
  message: string
  type: ToastType
  action?: ToastAction
  /** Full error details for click-to-expand */
  errorDetails?: HumanError
  /** Duration in ms (0 = no auto-dismiss) */
  duration?: number
  /** Optional secondary line shown below `message` (smaller, dimmer).
   *  Used for quick-action toasts to carry the rule name / "why this fired"
   *  without bloating the primary message. */
  detail?: string
}

interface ToastProps {
  toast: ToastData
  onDismiss: (id: string) => void
  onShowDetails?: (error: HumanError) => void
  defaultDuration?: number
}

interface ToastContainerProps {
  toasts: ToastData[]
  onDismiss: (id: string) => void
  onShowDetails?: (error: HumanError) => void
}

// Duration by type (errors stay longer)
const DEFAULT_DURATIONS: Record<ToastType, number> = {
  success: 3000,
  info: 4000,
  warning: 5000,
  error: 6000,
}

export function Toast({
  toast,
  onDismiss,
  onShowDetails,
  defaultDuration,
}: ToastProps) {
  const { t } = useTranslation('common')
  const [isExiting, setIsExiting] = useState(false)

  const duration =
    toast.duration ?? defaultDuration ?? DEFAULT_DURATIONS[toast.type] ?? 5000

  const handleDismiss = useCallback(() => {
    setIsExiting(true)
    setTimeout(() => {
      onDismiss(toast.id)
    }, 200) // Animation duration
  }, [onDismiss, toast.id])

  const handleClick = useCallback(() => {
    if (toast.errorDetails && onShowDetails) {
      onShowDetails(toast.errorDetails)
      handleDismiss()
    }
  }, [toast.errorDetails, onShowDetails, handleDismiss])

  const handleActionClick = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation()
      if (toast.action) {
        toast.action.onClick()
        handleDismiss()
      }
    },
    [toast.action, handleDismiss]
  )

  useEffect(() => {
    if (duration > 0) {
      const timer = setTimeout(() => {
        handleDismiss()
      }, duration)

      return () => clearTimeout(timer)
    }
  }, [duration, handleDismiss])

  const getIcon = () => {
    switch (toast.type) {
      case 'success':
        return '✓'
      case 'error':
        return '✕'
      case 'warning':
        return '⚠'
      case 'info':
        return 'ℹ'
      default:
        return ''
    }
  }

  const isClickable = toast.errorDetails && onShowDetails

  return (
    <div
      className={`toast toast-${toast.type} ${isExiting ? 'toast-exit' : ''} ${isClickable ? 'toast-clickable' : ''}`}
      role="alert"
      aria-live={toast.type === 'error' ? 'assertive' : 'polite'}
      onClick={isClickable ? handleClick : undefined}
    >
      <span className="toast-icon" aria-hidden="true">
        {getIcon()}
      </span>
      <div className="toast-text">
        <span className="toast-message" title={toast.message}>{toast.message}</span>
        {toast.detail && (
          <span className="toast-detail" title={toast.detail}>{toast.detail}</span>
        )}
      </div>

      {toast.action && duration > 0 && (
        <svg
          className="toast-progress"
          viewBox="0 0 20 20"
          aria-hidden="true"
          style={{ animationDuration: `${duration}ms` } as React.CSSProperties}
        >
          <circle cx="10" cy="10" r="8" className="toast-progress-bg" />
          <circle
            cx="10"
            cy="10"
            r="8"
            className="toast-progress-ring"
            style={{ animationDuration: `${duration}ms` } as React.CSSProperties}
          />
        </svg>
      )}

      {toast.action && (
        <button
          className="toast-action"
          onClick={handleActionClick}
          type="button"
        >
          {toast.action.label}
        </button>
      )}

      {isClickable && (
        <span className="toast-expand-hint" aria-hidden="true">
          {t('toast_click_details')}
        </span>
      )}

      <button
        className="toast-dismiss"
        onClick={(e) => {
          e.stopPropagation()
          handleDismiss()
        }}
        aria-label={t('close')}
        type="button"
      >
        <CloseIcon size={14} />
      </button>
    </div>
  )
}

export function ToastContainer({
  toasts,
  onDismiss,
  onShowDetails,
}: ToastContainerProps) {
  const { t } = useTranslation('common')
  if (toasts.length === 0) return null

  return (
    <div className="toast-container" aria-label={t('notifications_label')} aria-live="polite" role="log">
      {toasts.map((toast) => (
        <Toast
          key={toast.id}
          toast={toast}
          onDismiss={onDismiss}
          onShowDetails={onShowDetails}
        />
      ))}
    </div>
  )
}

// Custom hook for managing toasts with error support
export interface UseToastOptions {
  maxToasts?: number
  onShowErrorDetails?: (error: HumanError) => void
}

export function useToast(options: UseToastOptions = {}) {
  const { maxToasts = 5, onShowErrorDetails } = options
  const [toasts, setToasts] = useState<ToastData[]>([])

  const addToast = useCallback(
    (
      message: string,
      type: ToastType = 'info',
      toastOptions?: {
        action?: ToastAction
        errorDetails?: HumanError
        duration?: number
        detail?: string
      }
    ) => {
      const id = `toast-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`

      setToasts((prev) => {
        const newToasts = [...prev, { id, message, type, ...toastOptions }]
        // Keep only the most recent toasts
        if (newToasts.length > maxToasts) {
          return newToasts.slice(-maxToasts)
        }
        return newToasts
      })

      return id
    },
    [maxToasts]
  )

  const addErrorToast = useCallback(
    (
      error: HumanError,
      options?: {
        onAction?: (actionType: ErrorActionType) => void
      }
    ) => {
      const action =
        error.action && options?.onAction
          ? {
              label: error.action.label,
              onClick: () => options.onAction!(error.action!.type),
            }
          : undefined

      return addToast(error.title, 'error', {
        action,
        errorDetails: error,
        duration: DEFAULT_DURATIONS.error,
      })
    },
    [addToast]
  )

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const clearAllToasts = useCallback(() => {
    setToasts([])
  }, [])

  const handleShowDetails = useCallback(
    (error: HumanError) => {
      onShowErrorDetails?.(error)
    },
    [onShowErrorDetails]
  )

  return {
    toasts,
    addToast,
    addErrorToast,
    dismissToast,
    clearAllToasts,
    handleShowDetails,
  }
}
