import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import './MicPermissionDialog.css'

interface MicPermissionDialogProps {
  open: boolean
  onConfirm: () => void
  onCancel: () => void
}

const MicIcon = () => (
  <svg
    aria-hidden="true"
    className="mpd-mic-icon"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" />
    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
    <line x1="12" y1="19" x2="12" y2="22" />
    <line x1="8" y1="22" x2="16" y2="22" />
  </svg>
)

export function MicPermissionDialog({ open, onConfirm, onCancel }: MicPermissionDialogProps) {
  const { t } = useTranslation('compose')
  const primaryBtnRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const id = requestAnimationFrame(() => primaryBtnRef.current?.focus())
    return () => cancelAnimationFrame(id)
  }, [open])

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => { if (!nextOpen) onCancel() }}>
      <DialogContent
        className="mpd-card"
        showCloseButton={true}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            onConfirm()
          }
        }}
      >
        <div className="mpd-icon-area">
          <div className="mpd-icon-ring">
            <MicIcon />
          </div>
        </div>

        <div className="mpd-content">
          <DialogTitle className="mpd-title">{t('mic_permission_title')}</DialogTitle>
          <DialogDescription className="mpd-description">
            {t('mic_permission_desc')}
          </DialogDescription>
        </div>

        <div className="mpd-actions">
          <Button ref={primaryBtnRef} onClick={onConfirm}>
            {t('mic_permission_continue')}
          </Button>
          <Button variant="outline" onClick={onCancel}>
            {t('mic_permission_cancel')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
