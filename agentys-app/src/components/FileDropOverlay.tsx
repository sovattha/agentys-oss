import { useTranslation } from 'react-i18next'
import './FileDropOverlay.css'

interface FileDropOverlayProps {
  visible: boolean
}

export function FileDropOverlay({ visible }: FileDropOverlayProps) {
  const { t } = useTranslation('compose')
  if (!visible) return null
  return (
    <div className="file-drop-overlay" aria-hidden="true">
      <div className="file-drop-card">
        <div className="file-drop-icon-wrap">
          <span className="file-drop-icon-halo" />
          <svg
            className="file-drop-paperclip"
            width="40"
            height="40"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
          </svg>
        </div>
        <div className="file-drop-title">{t('drop_title', 'Lâchez pour joindre')}</div>
        <div className="file-drop-hint">
          {t('drop_hint', 'Fichiers et dossiers acceptés — 25 Mo max')}
        </div>
      </div>
    </div>
  )
}
