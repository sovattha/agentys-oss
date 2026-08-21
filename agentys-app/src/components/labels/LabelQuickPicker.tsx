import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import type { EmailLabel } from '../../types/email'
import { DEFAULT_LABELS, isDefaultLabel, getLabelDisplayName } from '../../types/labels'

import { useAnimatedUnmount } from '../../hooks/useAnimatedUnmount'
import { CheckIcon, ChevronRightIcon } from '../icons/ActionIcons'
import './LabelQuickPicker.css'

/** Keys for reason suggestions per default label */
const REASON_SUGGESTION_KEYS: Record<string, string[]> = {
  Action: [
    'suggestion_always_tasks',
    'suggestion_invoice',
    'suggestion_awaiting_reply',
  ],
  FYI: [
    'suggestion_contact',
    'suggestion_fyi',
  ],
  Noise: [
    'suggestion_spam',
    'suggestion_notification',
    'suggestion_newsletter',
    'suggestion_unsubscribe',
  ],
}

interface LabelQuickPickerProps {
  position: { x: number; y: number }
  currentLabels: EmailLabel[]
  /** `reasonKey` is the i18n key of the chip clicked (e.g. 'suggestion_invoice');
   *  undefined when the user typed a free-text reason via "Autre…". The backend
   *  uses it to short-circuit the LLM with a deterministic rule mapping. */
  onSelectDefault: (label: { name: string; color: string }, reason: string, reasonKey?: string) => void
  onToggleCustom: (label: { name: string; color: string }, add: boolean) => void
  onClose: () => void
}

export function LabelQuickPicker({
  position,
  currentLabels,
  onSelectDefault,
  onToggleCustom: _onToggleCustom,
  onClose,
}: LabelQuickPickerProps) {
  const { t } = useTranslation('inbox')
  const ref = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [selectedLabel, setSelectedLabel] = useState<{ name: string; color: string } | null>(null)
  const [reason, setReason] = useState('')
  const [showCustom, setShowCustom] = useState(false)
  const [step, setStep] = useState<1 | 2>(1)
  const [adjustedPos, setAdjustedPos] = useState(position)
  const { isClosing, handleClose } = useAnimatedUnmount(true, onClose)

  // Find current default label
  const currentDefault = currentLabels.find((l) => isDefaultLabel(l.name))?.name || null

  // Keep the picker inside the viewport. Triggered initially and on step
  // change because step 2 can shrink/grow with the custom-reason textarea.
  useEffect(() => {
    if (!ref.current) return
    const rect = ref.current.getBoundingClientRect()
    const x = Math.min(position.x, window.innerWidth - rect.width - 8)
    const y = Math.min(position.y, window.innerHeight - rect.height - 8)
    setAdjustedPos({ x: Math.max(8, x), y: Math.max(8, y) })
  }, [position, step, showCustom])

  useEffect(() => {
    const handleMouseDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        handleClose()
      }
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (showCustom) {
          setShowCustom(false)
          setReason('')
        } else if (step === 2) {
          setStep(1)
          setSelectedLabel(null)
          setReason('')
          setShowCustom(false)
        } else {
          handleClose()
        }
      }
    }

    document.addEventListener('mousedown', handleMouseDown)
    document.addEventListener('keydown', handleKeyDown)

    return () => {
      document.removeEventListener('mousedown', handleMouseDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [handleClose, step, showCustom])

  // Auto-focus textarea when showing custom input
  useEffect(() => {
    if (showCustom && textareaRef.current) {
      requestAnimationFrame(() => textareaRef.current?.focus())
    }
  }, [showCustom])

  const handleDefaultClick = (label: { name: string; color: string }) => {
    // If already the current default, do nothing
    if (label.name === currentDefault) return
    setSelectedLabel(label)
    setStep(2)
    setShowCustom(false)
    setReason('')
  }

  const handleReasonClick = (r: string, key: string) => {
    if (selectedLabel) {
      onSelectDefault(selectedLabel, r, key)
    }
  }

  const handleConfirmCustom = () => {
    if (selectedLabel) {
      onSelectDefault(selectedLabel, reason.trim())
    }
  }

  const handleTextareaKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleConfirmCustom()
    }
  }


  const suggestionKeys = selectedLabel ? (REASON_SUGGESTION_KEYS[selectedLabel.name] ?? []) : []

  return createPortal(
    <div
      ref={ref}
      className={`lqp${isClosing ? ' lqp-closing' : ''}`}
      style={{
        position: 'fixed',
        left: adjustedPos.x,
        top: adjustedPos.y,
      }}
      role="menu"
      aria-label={t('label')}
      data-escape-owner=""
    >
      {/* Teal glow accent line */}
      <div className="lqp-glow-line" />

      {step === 1 ? (
        <div className="lqp-step lqp-step-labels" key="step1">
          {/* Section 1: Classification (default labels — radio style) */}
          <div className="lqp-header">
            <span className="lqp-header-title" role="heading" aria-level={3}>{t('label')}</span>
          </div>
          <div className="lqp-list">
            {DEFAULT_LABELS.map((label, i) => (
              <button
                key={label.name}
                className={`lqp-item ${label.name === currentDefault ? 'lqp-item--active' : ''}`}
                onClick={() => handleDefaultClick({ name: label.name, color: label.color })}
                role="menuitemradio"
                aria-checked={label.name === currentDefault}
                style={{ animationDelay: `${i * 30}ms` }}
              >
                <span className="lqp-dot-wrap">
                  <span
                    className="lqp-dot"
                    style={{ background: label.color }}
                  />
                </span>
                <span className="lqp-item-name">{getLabelDisplayName(label.name)}</span>
                {label.name === currentDefault ? (
                  <CheckIcon size={14} className="lqp-item-check" />
                ) : (
                  <ChevronRightIcon size={14} className="lqp-item-arrow" />
                )}
              </button>
            ))}
          </div>

        </div>
      ) : (
        <div className="lqp-step lqp-step-reason" key="step2">
          <div className="lqp-header">
            <span
              className="lqp-dot"
              style={{ background: selectedLabel?.color }}
            />
            <span className="lqp-header-title" role="heading" aria-level={3}>{selectedLabel ? getLabelDisplayName(selectedLabel.name) : ''}</span>
          </div>

          <div className="lqp-reason-body">
            <div className="lqp-reason-subtitle">{t('change_label')}</div>
            <div className="lqp-suggestions">
              {suggestionKeys.map((key, i) => (
                <button
                  key={key}
                  className="lqp-suggestion"
                  onClick={() => handleReasonClick(t(key), key)}
                  style={{ animationDelay: `${i * 40}ms` }}
                >
                  {t(key)}
                </button>
              ))}
              <button
                className={`lqp-suggestion lqp-suggestion--other ${showCustom ? 'lqp-suggestion--active' : ''}`}
                onClick={() => setShowCustom(!showCustom)}
                style={{ animationDelay: `${suggestionKeys.length * 40}ms` }}
              >
                {t('label_picker_other')}
              </button>
            </div>

            {showCustom && (
              <div className="lqp-custom-reason">
                <textarea
                  ref={textareaRef}
                  className="lqp-textarea"
                  placeholder={t('label_picker_other_placeholder')}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  onKeyDown={handleTextareaKeyDown}
                  rows={2}
                />
                <div className="lqp-actions">
                  <button
                    className="lqp-confirm"
                    onClick={handleConfirmCustom}
                    disabled={!reason.trim()}
                  >
                    {t('label_picker_confirm')}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>,
    document.body
  )
}
