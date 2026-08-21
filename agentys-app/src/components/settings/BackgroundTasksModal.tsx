import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { BulkActionsPanel } from './BulkActionsPanel'
import { ChevronLeftIcon, CloseIcon } from '../icons/ActionIcons'
import './BackgroundTasksModal.css'

interface BackgroundTasksModalProps {
  isOpen: boolean
  onClose: () => void
}

export function BackgroundTasksModal({ isOpen, onClose }: BackgroundTasksModalProps) {
  const { t } = useTranslation('settings')

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent
        className="bg-tasks-modal"
        showCloseButton={false}
        aria-describedby={undefined}
      >
        <div className="bg-tasks-modal-header">
          <button
            type="button"
            className="bg-tasks-modal-back"
            onClick={onClose}
            aria-label={t('common:back')}
          >
            <ChevronLeftIcon />
          </button>
          <DialogTitle className="bg-tasks-modal-title">
            {t('bulk_actions_title')}
          </DialogTitle>
          <button
            type="button"
            className="bg-tasks-modal-close"
            onClick={onClose}
            aria-label={t('common:close')}
          >
            <CloseIcon />
          </button>
        </div>

        <div className="bg-tasks-modal-body">
          <BulkActionsPanel />
        </div>
      </DialogContent>
    </Dialog>
  )
}
