import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchLabels, deleteLabel } from '../../api/labels'
import type { Label } from '../../types/labels'
import { LabelBadge } from './LabelBadge'
import { LabelEditor } from './LabelEditor'
import { GhostAddCard } from '../ui/GhostAddCard'
import { ChevronLeftIcon, CloseIcon, PlusIcon, TrashIcon } from '../icons/ActionIcons'
import { useSharedLabels } from '../../contexts/LabelsContext'
import './LabelLibrary.css'


interface LabelLibraryProps {
  isOpen: boolean
  onClose: () => void
  onBack?: () => void
  onOpenEmail?: (emailId: string) => void
}

export function LabelLibrary({ isOpen, onClose, onBack, onOpenEmail }: LabelLibraryProps) {
  const { t } = useTranslation('inbox')
  const { t: tc } = useTranslation('common')
  const { toggleFavorite: contextToggleFavorite } = useSharedLabels()
  const [labels, setLabels] = useState<Label[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editingLabel, setEditingLabel] = useState<Label | null>(null)
  const [isCreating, setIsCreating] = useState(false)
  const [deletingLabel] = useState<string | null>(null)
  const [pendingEmailOpen, setPendingEmailOpen] = useState<string | null>(null)

  const loadLabels = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await fetchLabels()
      setLabels(response.labels)
    } catch (err) {
      console.error('Failed to load labels:', err)
      setError(t('label_library_load_error'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (isOpen) {
      loadLabels()
    }
  }, [isOpen, loadLabels])

  // Fire pending email open after library closes
  useEffect(() => {
    if (!isOpen && pendingEmailOpen) {
      onOpenEmail?.(pendingEmailOpen)
      setPendingEmailOpen(null)
    }
  }, [isOpen, pendingEmailOpen, onOpenEmail])

  const handleToggleFavorite = useCallback(async (label: Label) => {
    // Update shared context (calls API + updates ribbon in EmailListHeader)
    await contextToggleFavorite(label.name)
    // Sync local state to reflect the change
    setLabels(prev =>
      prev.map(l => (l.name === label.name ? { ...l, is_favorite: !l.is_favorite } : l))
    )
  }, [contextToggleFavorite])

  const handleDelete = useCallback(async (name: string) => {
    const prev = labels
    setLabels(l => l.filter(x => x.name !== name))
    try {
      await deleteLabel(name)
    } catch (err) {
      console.error('Failed to delete label:', err)
      setLabels(prev)
    }
  }, [labels])

  const handleSaveLabel = useCallback(() => {
    setEditingLabel(null)
    setIsCreating(false)
    loadLabels()
  }, [loadLabels])

  // Escape key closes the library — skip when typing in fields so inner
  // popups (search input, label editor) handle Escape themselves first.
  useEffect(() => {
    if (!isOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      const tgt = e.target as HTMLElement | null
      if (tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA' || tgt.isContentEditable)) {
        return
      }
      onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [isOpen, onClose])

  if (!isOpen) return null

  // Show editor if editing or creating
  if (editingLabel || isCreating) {
    return (
      <LabelEditor
        label={editingLabel}
        isOpen={true}
        onClose={() => {
          setEditingLabel(null)
          setIsCreating(false)
        }}
        onSave={handleSaveLabel}
      />
    )
  }

  const defaultLabels = labels.filter(l => l.is_default)
  const customLabels = labels.filter(l => !l.is_default)

  return (
    <div className="label-library-overlay" onClick={onClose}>
      <div className="label-library-container" onClick={(e) => e.stopPropagation()}>
        <div className="label-library-header">
          <div className="label-library-header-left">
            {onBack && (
              <button className="label-library-back" onClick={onBack} aria-label={tc('back')} title={tc('back')}>
                <ChevronLeftIcon size={20} />
              </button>
            )}
            <h2>{t('label_library_title')}</h2>
          </div>
          <div className="label-library-header-actions">
            <button className="label-library-close" onClick={onClose}>
              <CloseIcon size={20} />
            </button>
          </div>
        </div>

        <div className="label-library-content">
          {loading ? (
            <div className="label-library-loading">{t('loading', { ns: 'common' })}</div>
          ) : error ? (
            <div className="label-library-error">
              <span>{error}</span>
              <button className="label-library-retry-btn" onClick={loadLabels}>
                {tc('retry')}
              </button>
            </div>
          ) : (
            <>
              {/* Default Labels Section — card boxes */}
              <section className="label-library-section">
                <h3>{t('label_library_action_title')}</h3>
                <p className="label-library-section-desc">
                  {t('label_library_action_desc')}
                </p>
                <div className="label-library-default-cards">
                  {defaultLabels.map(label => (
                    <div
                      key={label.name}
                      className="label-library-default-card"
                      onClick={() => setEditingLabel(label)}
                    >
                      <div className="label-library-default-card-header">
                        <LabelBadge name={label.name} color={label.color} size="medium" />
                        <button
                          className={`label-library-star ${label.is_favorite ? 'active' : ''}`}
                          onClick={(e) => { e.stopPropagation(); handleToggleFavorite(label); }}
                          title={label.is_favorite ? t('label_library_fav_remove') : t('label_library_fav_add')}
                        >
                          <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill={label.is_favorite ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2">
                            <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                          </svg>
                        </button>
                      </div>
                      <p className="label-library-default-card-desc">
                        {label.name === 'Action' ? t('label_library_default_action') :
                         label.name === 'FYI' ? t('label_library_default_fyi') :
                         label.name === 'Noise' ? t('label_library_default_noise') :
                         label.description || ''}
                      </p>
                    </div>
                  ))}
                </div>
              </section>

              {/* Custom Labels Section */}
              <section className="label-library-section">
                <h3>{t('label_library_custom_title')}</h3>
                <p className="label-library-section-desc">
                  {t('label_library_custom_desc')}
                </p>
                {customLabels.length === 0 ? (
                  <div className="label-library-empty">
                    <div className="label-library-empty-icon">
                      <svg aria-hidden="true" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/>
                        <circle cx="7" cy="7" r="1.5" fill="currentColor" stroke="none"/>
                      </svg>
                    </div>
                    <p>{t('label_library_empty_title')}</p>
                    <button
                      className="label-library-empty-cta"
                      onClick={() => setIsCreating(true)}
                    >
                      <PlusIcon size={14} />
                      {t('label_library_add')}
                    </button>
                  </div>
                ) : (
                  <div className="label-library-grid">
                    <GhostAddCard label={t('label_library_add')} onClick={() => setIsCreating(true)} />
                    {customLabels.map(label => (
                      <div
                        key={label.name}
                        className="label-library-item"
                        style={{ '--label-color': label.color } as React.CSSProperties}
                        onClick={() => setEditingLabel(label)}
                      >
                        <div className="label-library-item-header">
                          <div className="label-library-item-label-row">
                            <LabelBadge name={label.name} color={label.color} size="medium" />
                            {label.is_project && (
                              <svg className="label-library-project-icon" aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                              </svg>
                            )}
                          </div>
                          <button
                            className={`label-library-star ${label.is_favorite ? 'active' : ''}`}
                            onClick={(e) => { e.stopPropagation(); handleToggleFavorite(label); }}
                            title={label.is_favorite ? t('label_library_fav_remove') : t('label_library_fav_add')}
                          >
                            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill={label.is_favorite ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2">
                              <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                            </svg>
                          </button>
                        </div>
                        {label.description && <p className="label-library-item-desc">{label.description}</p>}
                        <div className="label-library-item-footer">
                          <div className="label-library-item-rules">
                            {label.rules.length > 0 && (
                              <span className="label-library-rule-count">
                                {t('label_library_rules', { count: label.rules.length })}
                              </span>
                            )}
                            {label.ai_prompt && (
                              <span className="label-library-ai-badge">IA</span>
                            )}
                          </div>
                          <button
                            className="label-library-btn-trash icon-btn--delete"
                            onClick={(e) => { e.stopPropagation(); handleDelete(label.name); }}
                            disabled={deletingLabel === label.name}
                            title={t('label_library_delete')}
                          >
                            <TrashIcon size={14} />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </section>

            </>
          )}
        </div>
      </div>
    </div>
  )
}
