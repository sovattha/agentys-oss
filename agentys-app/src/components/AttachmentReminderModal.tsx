import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { PlusIcon } from './icons/ActionIcons'
import './AttachmentReminderModal.css'

interface AttachmentReminderModalProps {
  /** The detected keyword label (e.g. "pièce jointe", "ci-joint") */
  keyword: string
  /** The raw matched text from the body */
  matchedText: string
  /** Called when user chooses to attach a file */
  onAttach: () => void
  /** Called when user chooses to send without attachment */
  onSendAnyway: () => void
  /** Called to dismiss (Escape) — same as onSendAnyway or custom */
  onClose: () => void
}

/** Paperclip SVG icon — crisp stroke design matching Agentys outlined icons */
const PaperclipIcon = () => (
  <svg aria-hidden="true"
    className="arm-paperclip"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
  </svg>
)

export function AttachmentReminderModal({
  matchedText,
  onAttach,
  onSendAnyway,
  onClose,
}: AttachmentReminderModalProps) {
  const { t } = useTranslation('compose')
  const primaryBtnRef = useRef<HTMLButtonElement>(null)

  // Auto-focus primary button for accessibility
  useEffect(() => {
    requestAnimationFrame(() => primaryBtnRef.current?.focus())
  }, [])

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent
        className="arm-card"
        showCloseButton={true}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            onAttach()
          }
        }}
      >
        {/* Animated icon */}
        <div className="arm-icon-area">
          <div className="arm-icon-ring">
            <PaperclipIcon />
          </div>
        </div>

        {/* Content */}
        <div className="arm-content">
          <DialogTitle className="arm-title">{t('forgotten_attachment_title')}</DialogTitle>
          <DialogDescription className="arm-description">
            {t('forgotten_attachment_desc')}
          </DialogDescription>

          {/* Detected keyword chip */}
          <div className="arm-keyword">
            <span className="arm-keyword-quote">&laquo;&thinsp;{matchedText}&thinsp;&raquo;</span>
          </div>
        </div>

        {/* Actions */}
        <div className="arm-actions">
          <Button
            ref={primaryBtnRef}
            onClick={onAttach}
          >
            <PlusIcon size={16} />
            {t('add_attachment')}
          </Button>
          <Button
            variant="outline"
            onClick={onSendAnyway}
          >
            {t('send_without_attachment')}
          </Button>
        </div>

      </DialogContent>
    </Dialog>
  )
}
