import { useState, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { CloseIcon } from '../icons/ActionIcons'
import './SaveSearchModal.css'

interface SaveSearchModalProps {
  query: string
  onSave: (name: string, query: string) => void
  onClose: () => void
}

export function SaveSearchModal({ query, onSave, onClose }: SaveSearchModalProps) {
  const { t } = useTranslation('search')
  const [name, setName] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    requestAnimationFrame(() => inputRef.current?.focus())
  }, [])

  const handleSave = () => {
    const trimmed = name.trim()
    if (!trimmed) return
    onSave(trimmed, query)
    onClose()
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleSave()
    }
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="save-search-modal" showCloseButton={false} aria-describedby={undefined}>
        <div className="save-search-header">
          <DialogTitle asChild><h3 className="save-search-title">{t('save_search_title')}</h3></DialogTitle>
          <button className="save-search-close" onClick={onClose} type="button" aria-label={t('common:close')}>
            <CloseIcon />
          </button>
        </div>
        <div className="save-search-preview">
          <span className="save-search-preview-label">{t('save_search_query_label')}</span>
          <span className="save-search-preview-query">{query}</span>
        </div>
        <input
          ref={inputRef}
          type="text"
          className="save-search-input"
          placeholder={t('save_search_name_placeholder')}
          value={name}
          onChange={e => setName(e.target.value)}
          onKeyDown={handleKeyDown}
          maxLength={60}
        />
        <div className="save-search-actions">
          <Button
            type="button"
            onClick={handleSave}
            disabled={!name.trim()}
          >
            {t('save_search_btn')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
