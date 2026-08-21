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
