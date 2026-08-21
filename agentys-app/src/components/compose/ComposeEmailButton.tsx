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
