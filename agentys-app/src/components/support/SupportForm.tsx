import { useState, useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { apiClient } from '../../services/api'
import { CloseIcon } from '../icons/ActionIcons'

type Intent = 'support' | 'feedback' | 'bug' | 'feature'

interface SupportFormProps {
  intent: Intent
  accountEmail: string
  onSending: () => void
  onSuccess: (ticketRef: string) => void
  onError: (message: string) => void
  /** Render the submit button outside the scroll area via form= attribute */
  formId?: string
}

function generateTicketRef(): string {
  const num = Math.floor(10000 + Math.random() * 90000)
  return `AG-${num}`
}

function StarIcon({ filled }: { filled: boolean }) {
  return (
    <svg aria-hidden="true" width="24" height="24" viewBox="0 0 24 24" fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
    </svg>
  )
}

export function SupportForm({ intent, accountEmail, onSending, onSuccess, onError, formId = 'sp-form' }: SupportFormProps) {
  const { t } = useTranslation('support')
  const SUPPORT_CATEGORIES = [
    t('form_category_connection'),
    t('cat_ai_drafts'),
    t('form_category_billing'),
    t('form_category_other'),
  ]
  const [category, setCategory] = useState(() => t('form_category_connection'))
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [steps, setSteps] = useState('')
  const [rating, setRating] = useState(0)
  const [hoverRating, setHoverRating] = useState(0)
  const [images, setImages] = useState<{ file: File; preview: string }[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleAddImages = (files: FileList | File[] | null) => {
    if (!files) return
    const newImages = Array.from(files)
      .filter(f => f.type.startsWith('image/') && f.size <= 10 * 1024 * 1024)
      .slice(0, 3 - images.length)
      .map(file => ({ file, preview: URL.createObjectURL(file) }))
    setImages(prev => [...prev, ...newImages].slice(0, 3))
  }

  const handleRemoveImage = (index: number) => {
    setImages(prev => {
      URL.revokeObjectURL(prev[index].preview)
      return prev.filter((_, i) => i !== index)
    })
  }

  useEffect(() => {
    const handlePaste = (e: ClipboardEvent) => {
      const items = e.clipboardData?.items
      if (!items) return
      const imageFiles: File[] = []
      for (const item of Array.from(items)) {
        if (item.type.startsWith('image/')) {
          const file = item.getAsFile()
          if (file) imageFiles.push(file)
        }
      }
      if (imageFiles.length > 0) {
        e.preventDefault()
        handleAddImages(imageFiles)
      }
    }
    document.addEventListener('paste', handlePaste)
    return () => document.removeEventListener('paste', handlePaste)

  }, [images.length])

  const fileToBase64 = (file: File): Promise<string> =>
    new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve((reader.result as string).split(',')[1])
      reader.onerror = reject
      reader.readAsDataURL(file)
    })

  const canSubmit = (() => {
    switch (intent) {
      case 'support': return description.trim().length > 0
      case 'feedback': return rating > 0 && description.trim().length > 0
      case 'bug': return title.trim().length > 0 && description.trim().length > 0
      case 'feature': return title.trim().length > 0 && description.trim().length > 0
    }
  })()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return

    const ticketRef = intent === 'bug' || intent === 'feature' ? '' : generateTicketRef()
    const now = new Date().toLocaleString('fr-FR', { dateStyle: 'long', timeStyle: 'short' })

    let subject: string
    let body: string

    switch (intent) {
      case 'support':
        subject = `[Support] ${category} - ${ticketRef}`
        body = [
          `Type: Support client`,
          `Catégorie: ${category}`,
          `Référence: ${ticketRef}`,
          '',
          description,
          '',
          '---',
          `Compte: ${accountEmail}`,
          `Date: ${now}`,
        ].join('\n')
        break

      case 'feedback':
        subject = `[Commentaire] Note ${rating}/5 - ${ticketRef}`
        body = [
          `Type: Commentaire`,
          `Note: ${'★'.repeat(rating)}${'☆'.repeat(5 - rating)} (${rating}/5)`,
          `Référence: ${ticketRef}`,
          '',
          description,
          '',
          '---',
          `Compte: ${accountEmail}`,
          `Date: ${now}`,
        ].join('\n')
        break

      case 'bug':
        subject = `[Bug] ${title}`
        body = [
          `Type: Rapport de bug`,
          `Titre: ${title}`,
          '',
          'Description:',
          description,
          '',
          ...(steps.trim() ? ['Étapes pour reproduire:', steps, ''] : []),
          '---',
          `Compte: ${accountEmail}`,
          `Date: ${now}`,
        ].join('\n')
        break

      case 'feature':
        subject = `[Idée amélioration] ${title}`
        body = [
          `Type: Idée d'amélioration`,
          `Titre: ${title}`,
          '',
          description,
          '',
          '---',
          `Compte: ${accountEmail}`,
          `Date: ${now}`,
        ].join('\n')
        break
    }

    onSending()

    try {
      const attachments = await Promise.all(
        images.map(async (img) => ({
          filename: img.file.name,
          data: await fileToBase64(img.file),
          content_type: img.file.type,
        }))
      )
      await apiClient.sendNewEmail('support@agentys.io', subject, body, undefined, undefined, attachments.length > 0 ? attachments : undefined)
      onSuccess(ticketRef)
    } catch (err) {
      onError(err instanceof Error ? err.message : t('send_failed'))
    }
  }

  return (
    <form className="sp-form" id={formId} onSubmit={handleSubmit}>
      {/* Support: category select */}
      {intent === 'support' && (
        <div className="sp-field">
          <label className="sp-label">{t('form_category_label')}</label>
          <select className="sp-select" value={category} onChange={(e) => setCategory(e.target.value)}>
            {SUPPORT_CATEGORIES.map((cat) => (
              <option key={cat} value={cat}>{cat}</option>
            ))}
          </select>
        </div>
      )}

      {/* Feedback: star rating */}
      {intent === 'feedback' && (
        <div className="sp-field">
          <label className="sp-label">{t('form_rating_label')}</label>
          <div className="sp-stars">
            {[1, 2, 3, 4, 5].map((n) => (
              <button
                key={n}
                type="button"
                className={`sp-star ${n <= (hoverRating || rating) ? 'sp-star-active' : ''}`}
                onClick={() => setRating(n)}
                onMouseEnter={() => setHoverRating(n)}
                onMouseLeave={() => setHoverRating(0)}
                aria-label={n === 1 ? t('form_star_aria', { n }) : t('form_stars_aria', { n })}
              >
                <StarIcon filled={n <= (hoverRating || rating)} />
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Bug/Feature: title input */}
      {(intent === 'bug' || intent === 'feature') && (
        <div className="sp-field">
          <label className="sp-label">{t('form_title_label')}</label>
          <input
            className="sp-input"
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={intent === 'bug' ? t('form_bug_title_placeholder') : t('form_feature_title_placeholder')}
            autoFocus
          />
        </div>
      )}

      {/* Description (all intents) */}
      <div className="sp-field">
        <label className="sp-label">
          {intent === 'feedback' ? t('form_comments_label') : t('form_description_label')}
        </label>
        <textarea
          className="sp-textarea"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={
            intent === 'support' ? t('form_support_detail_placeholder') :
            intent === 'feedback' ? t('form_feedback_placeholder') :
            intent === 'bug' ? t('form_bug_what_placeholder') :
            t('idea_placeholder')
          }
          rows={4}
          autoFocus={intent === 'support' || intent === 'feedback'}
        />
      </div>

      {/* Bug: repro steps */}
      {intent === 'bug' && (
        <div className="sp-field">
          <label className="sp-label">{t('form_steps_label')}</label>
          <textarea
            className="sp-textarea"
            value={steps}
            onChange={(e) => setSteps(e.target.value)}
            placeholder={t('form_steps_placeholder')}
            rows={3}
          />
        </div>
      )}

      {/* Image attachments */}
      <div className="sp-field">
        <label className="sp-label">{t('form_screenshots_label')}</label>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          multiple
          onChange={(e) => { handleAddImages(e.target.files); e.target.value = '' }}
          style={{ display: 'none' }}
        />
        {images.length > 0 && (
          <div className="sp-image-grid">
            {images.map((img, i) => (
              <div key={i} className="sp-image-thumb">
                <img src={img.preview} alt={`Capture ${i + 1}`} />
                <button type="button" className="sp-image-remove" onClick={() => handleRemoveImage(i)} aria-label={t('form_aria_remove_image')}>
                  <CloseIcon size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
        {images.length < 3 && (
          <button type="button" className="sp-add-image-btn" onClick={() => fileInputRef.current?.click()}>
            <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
              <circle cx="8.5" cy="8.5" r="1.5" />
              <polyline points="21 15 16 10 5 21" />
            </svg>
            <span>{t('form_add_image')}</span>
          </button>
        )}
      </div>

    </form>
  )
}
