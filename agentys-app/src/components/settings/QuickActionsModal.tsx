/**
 * QuickActionsModal — overlay around QuickStepsManager.
 *
 * We deliberately avoid Radix Dialog here: the editor embeds
 * ContactAutocomplete which renders its suggestion list via
 * ``createPortal(document.body)`` — Radix's pointer-down-outside detector
 * dismisses the modal before the suggestion's onMouseDown can register.
 * Same root cause for the QuickStepsPalette and the run-confirmation
 * dialog. A plain overlay portal avoids all three issues without giving
 * up dismiss-on-overlay-click + Escape.
 */
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'

import { QuickStepsManager } from './QuickStepsManager'
import { ChevronLeftIcon, CloseIcon } from '../icons/ActionIcons'
import './QuickActionsModal.css'

interface QuickActionsModalProps {
  isOpen: boolean
  onClose: () => void
}

export function QuickActionsModal({ isOpen, onClose }: QuickActionsModalProps) {
  const { t } = useTranslation('settings')
  const { t: tc } = useTranslation('common')

  // Editor state lifted from QuickStepsManager so the modal header can swap its
  // title and route the back arrow to "return to list" instead of closing.
  const [editorState, setEditorState] = useState<
    { title: string; onCancel: () => void } | null
  >(null)

  // Reset editor state when the modal closes so reopening starts fresh.
  useEffect(() => {
    if (!isOpen) setEditorState(null)
  }, [isOpen])

  const handleBack = editorState ? editorState.onCancel : onClose
  const headerTitle = editorState
    ? editorState.title
    : t('quicksteps_title', { defaultValue: 'Quick actions' })

  // Esc closes the modal — only while open so we don't fight other handlers.
  useEffect(() => {
    if (!isOpen) return
    const handler = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      // Don't fire when an overlapping floating UI is open (autocomplete
      // suggestions, palette, run-confirmation modal). Those own the Esc.
      const target = event.target as HTMLElement | null
      if (target?.closest('.suggestions-list, .qs-palette, .quicksteps-confirm')) {
        return
      }
      onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isOpen, onClose])

  // Lock body scroll while open so the underlying Settings doesn't
  // scroll-jack behind the overlay.
  useEffect(() => {
    if (!isOpen) return
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [isOpen])

  if (!isOpen) return null

  return createPortal(
    <div
      className="quick-actions-overlay"
      role="presentation"
      onClick={(event) => {
        // Close only when the click landed on the overlay itself, not on
        // any of the modal content / portaled children.
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        className="quick-actions-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="quick-actions-modal-title"
      >
        <div className="quick-actions-modal-header">
          <button
            type="button"
            className="quick-actions-modal-back"
            onClick={handleBack}
            aria-label={tc('back', { defaultValue: 'Retour' })}
          >
            <ChevronLeftIcon />
          </button>
          <h2 id="quick-actions-modal-title" className="quick-actions-modal-title">
            {headerTitle}
          </h2>
          <button
            type="button"
            className="quick-actions-modal-close"
            onClick={onClose}
            aria-label={tc('close', { defaultValue: 'Fermer' })}
          >
            <CloseIcon />
          </button>
        </div>

        <div className="quick-actions-modal-body">
          <QuickStepsManager onEditingChange={setEditorState} />
        </div>
      </div>
    </div>,
    document.body,
  )
}
