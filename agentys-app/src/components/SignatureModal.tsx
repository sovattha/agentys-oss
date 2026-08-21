import { useState, useEffect, useCallback, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import DOMPurify from 'dompurify'
import {
  fetchAccounts, syncSignature, uploadSignatureImage,
  listSignatures, createSignature, updateSignatureEntry, deleteSignatureEntry, setDefaultSignature,
  type SignatureEntry,
} from '../api/accounts'
import { setAccountSignatureCache } from '../hooks/useAccountSignature'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { ChevronLeftIcon, CheckIcon, CloseIcon, EditIcon, PlusIcon, TrashIcon } from './icons/ActionIcons'
import './SignatureModal.css'

interface SignatureModalProps {
  isOpen: boolean
  onClose: () => void
}

function plainTextToHtml(text: string): string {
  return text.split('\n').map(l => `<div>${l || '<br>'}</div>`).join('')
}

/** innerText avec repli textContent — jsdom (vitest) n'implémente pas innerText. */
function editorText(el: HTMLElement | null): string {
  return el ? (el.innerText ?? el.textContent ?? '') : ''
}

export function SignatureModal({ isOpen, onClose }: SignatureModalProps) {
  const { t } = useTranslation('settings')
  const { t: tCommon } = useTranslation('common')
  const [signature, setSignature] = useState('')
  const [accountId, setAccountId] = useState<string | null>(null)
  const [accountEmail, setAccountEmail] = useState<string>('')
  const [provider, setProvider] = useState<string>('gmail')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  // Bibliothèque multi-signatures : vue liste (défaut) ↔ vue éditeur.
  // La signature ACTIVE du compte reste accounts.signature/_html — le backend
  // la synchronise depuis l'entrée par défaut (set-default / save du défaut).
  const [view, setView] = useState<'list' | 'editor'>('list')
  const [entries, setEntries] = useState<SignatureEntry[]>([])
  // null = création depuis la ligne fantôme ; sinon édition de l'entrée
  const [editingEntry, setEditingEntry] = useState<SignatureEntry | null>(null)
  const [nameDraft, setNameDraft] = useState('')

  // Rich editor refs
  const editorRef = useRef<HTMLDivElement>(null)
  const editorHtmlRef = useRef<string>('')
  const savedRangeRef = useRef<Range | null>(null)

  // Image resize state
  const [selectedImg, setSelectedImg] = useState<HTMLImageElement | null>(null)
  const [imgBarPos, setImgBarPos] = useState<{top: number; left: number} | null>(null)

  // Popover state — only one open at a time
  type PopoverKey = 'color' | 'size' | 'templates' | null
  const [openPopover, setOpenPopover] = useState<PopoverKey>(null)
  const toolbarRef = useRef<HTMLDivElement>(null)

  const MAX_SIGNATURE_LENGTH = 2000

  useEffect(() => {
    if (!isOpen) return

    const loadLibrary = async () => {
      try {
        setLoading(true)
        setView('list')
        setEditingEntry(null)
        // Fermeture via Escape/overlay (Radix onOpenChange) ne passe pas par
        // handleCancel — purger les banners de la session précédente ici.
        setError(null)
        setSuccessMessage(null)
        const { accounts, current_account_id } = await fetchAccounts()

        const currentAccount = current_account_id
          ? accounts.find(a => a.id === current_account_id)
          : accounts[0]

        if (currentAccount) {
          setAccountId(currentAccount.id)
          setAccountEmail(currentAccount.email || '')
          setProvider(currentAccount.provider || 'gmail')
          // Le backend seede automatiquement la signature legacy en « Signature 1 »
          const { signatures } = await listSignatures(currentAccount.id)
          setEntries(signatures)
        }
      } catch (err) {
        console.error('Failed to load signature library:', err)
        setError(t('signature_load_error'))
      } finally {
        setLoading(false)
      }
    }

    loadLibrary()
  }, [isOpen])

  // Initialise le contenu de l'éditeur à l'entrée en vue éditeur
  useEffect(() => {
    if (view !== 'editor' || !editorRef.current) return
    const html = editingEntry
      ? (editingEntry.html || plainTextToHtml(editingEntry.text || ''))
      : ''
    editorRef.current.innerHTML = html
    editorHtmlRef.current = html
    setSignature(editorText(editorRef.current))
  }, [view, editingEntry])

  /** Recharge la bibliothèque et resynchronise le cache composer sur le défaut. */
  const refreshLibrary = useCallback(async (accId: string) => {
    const { signatures } = await listSignatures(accId)
    setEntries(signatures)
    const def = signatures.find(s => s.is_default)
    // accountEmail : notifie aussi le cache scopé (footer ReplyComposer)
    setAccountSignatureCache(def?.html || null, def?.text || null, accountEmail)
  }, [accountEmail])

  const openEditor = useCallback((entry: SignatureEntry | null) => {
    setEditingEntry(entry)
    setNameDraft(entry?.name ?? '')
    setError(null)
    setSuccessMessage(null)
    setView('editor')
  }, [])

  const backToList = useCallback(() => {
    setView('list')
    setEditingEntry(null)
    setError(null)
    setSuccessMessage(null)
  }, [])

  const execFormat = useCallback((cmd: string, value?: string) => {
    if (!editorRef.current) return
    // Restore saved selection before executing command
    const sel = window.getSelection()
    if (savedRangeRef.current && sel) {
      sel.removeAllRanges()
      sel.addRange(savedRangeRef.current)
    }
    editorRef.current.focus()
    document.execCommand(cmd, false, value)
    editorHtmlRef.current = editorRef.current.innerHTML
    savedRangeRef.current = null
  }, [])

  const handleFormatBold = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    execFormat('bold')
  }, [execFormat])

  const handleFormatItalic = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    execFormat('italic')
  }, [execFormat])

  const handleFormatUnderline = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    execFormat('underline')
  }, [execFormat])

  const handleSetColor = useCallback((color: string) => {
    if (!editorRef.current) return
    const sel = window.getSelection()
    if (savedRangeRef.current && sel) {
      sel.removeAllRanges()
      sel.addRange(savedRangeRef.current)
    }
    editorRef.current.focus()
    try { document.execCommand('styleWithCSS', false, 'true') } catch { /* noop */ }
    document.execCommand('foreColor', false, color === 'inherit' ? '' : color)
    if (color === 'inherit') document.execCommand('removeFormat')
    editorHtmlRef.current = editorRef.current.innerHTML
    savedRangeRef.current = null
    setOpenPopover(null)
  }, [])

  const handleSetFontSize = useCallback((size: string) => {
    if (!editorRef.current) return
    const sel = window.getSelection()
    if (savedRangeRef.current && sel) {
      sel.removeAllRanges()
      sel.addRange(savedRangeRef.current)
    }
    editorRef.current.focus()
    try { document.execCommand('styleWithCSS', false, 'true') } catch { /* noop */ }
    document.execCommand('fontSize', false, size)
    editorHtmlRef.current = editorRef.current.innerHTML
    savedRangeRef.current = null
    setOpenPopover(null)
  }, [])

  const handleAlign = useCallback((dir: 'Left' | 'Center' | 'Right') => {
    execFormat(`justify${dir}`)
    setOpenPopover(null)
  }, [execFormat])

  const resizeAndUploadImage = useCallback(async (file: File): Promise<string> => {
    if (!accountId) throw new Error('Account not loaded')
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = (ev) => {
        const img = new Image()
        img.onload = async () => {
          const canvas = document.createElement('canvas')
          const MAX = 500
          const ratio = Math.min(MAX / img.width, MAX / img.height, 1)
          canvas.width = Math.round(img.width * ratio)
          canvas.height = Math.round(img.height * ratio)
          canvas.getContext('2d')!.drawImage(img, 0, 0, canvas.width, canvas.height)
          try {
            const blob = await new Promise<Blob>((res, rej) =>
              canvas.toBlob(b => b ? res(b) : rej(new Error('toBlob failed')), 'image/jpeg', 0.8)
            )
            const uploadFile = new File([blob], 'logo.jpg', { type: 'image/jpeg' })
            const url = await uploadSignatureImage(accountId, uploadFile)
            resolve(url)
          } catch {
            resolve(canvas.toDataURL('image/jpeg', 0.8))
          }
        }
        img.onerror = () => reject(new Error('Image load failed'))
        img.src = ev.target!.result as string
      }
      reader.onerror = () => reject(new Error('FileReader failed'))
      reader.readAsDataURL(file)
    })
  }, [accountId])

  // Inline SVG placeholder for the logo template — renders as a dashed "LOGO" box
  const LOGO_PLACEHOLDER_SRC = `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"><rect width="62" height="62" x="1" y="1" fill="#f3f4f6" stroke="#d1d5db" stroke-width="2" stroke-dasharray="4 3" rx="6"/><text x="50%" y="50%" text-anchor="middle" dy=".35em" font-size="10" fill="#9ca3af" font-family="system-ui, sans-serif">LOGO</text></svg>`)}`

  const insertTemplate = useCallback((templateId: string) => {
    if (!editorRef.current) return
    const templates: Record<string, string> = {
      minimal: `<div><strong>Your Name</strong></div><div style="color:#6b7280">Title · Company</div><div><a href="mailto:you@example.com">you@example.com</a></div>`,
      logo: `<table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse"><tr><td style="padding-right:12px;vertical-align:top"><img src="${LOGO_PLACEHOLDER_SRC}" alt="Logo" style="width:64px;height:64px;object-fit:contain;border-radius:6px" data-logo-placeholder="true"></td><td style="vertical-align:top"><div><strong>Your Name</strong></div><div style="color:#6b7280">Title · Company</div><div style="margin-top:4px"><a href="mailto:you@example.com">you@example.com</a></div><div><a href="https://example.com">example.com</a></div></td></tr></table>`,
      twoColumn: `<table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse"><tr><td style="padding:0 16px 0 0;border-right:1px solid #e5e7eb;vertical-align:top"><div><strong>Your Name</strong></div><div style="color:#6b7280">Title</div><div style="color:#6b7280">Company</div></td><td style="padding:0 0 0 16px;vertical-align:top"><div><a href="mailto:you@example.com">you@example.com</a></div><div><a href="tel:+1234567890">+1 234 567 890</a></div><div><a href="https://example.com">example.com</a></div></td></tr></table>`,
    }
    const html = templates[templateId]
    if (!html) return
    editorRef.current.innerHTML = html
    editorHtmlRef.current = html
    setSignature(editorText(editorRef.current))
    setOpenPopover(null)

    // Auto-open file picker for the logo template so the user can upload their image immediately
    if (templateId === 'logo' && accountId) {
      const input = document.createElement('input')
      input.type = 'file'
      input.accept = 'image/*'
      input.onchange = async () => {
        const file = input.files?.[0]
        if (!file || !editorRef.current) return
        const placeholder = editorRef.current.querySelector('img[data-logo-placeholder="true"]') as HTMLImageElement | null
        if (!placeholder) return
        try {
          setError(null)
          const url = await resizeAndUploadImage(file)
          placeholder.src = url
          placeholder.removeAttribute('data-logo-placeholder')
          editorHtmlRef.current = editorRef.current.innerHTML
        } catch (err) {
          // F-03 (audit 2026-06-11) : échec avalé en console — l'utilisateur
          // re-cliquait en boucle sans aucun signal. Surface via le banner error.
          console.error('Logo upload failed:', err)
          setError(tCommon('toasts.upload_failed'))
        }
      }
      input.click()
    }
  }, [accountId, resizeAndUploadImage, LOGO_PLACEHOLDER_SRC, tCommon])

  // Click-outside → close open popover
  useEffect(() => {
    if (!openPopover) return
    const onDocClick = (e: MouseEvent) => {
      if (toolbarRef.current && !toolbarRef.current.contains(e.target as Node)) {
        setOpenPopover(null)
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [openPopover])

  // Escape → close only the open toolbar popover (size/color/templates).
  // The host is a Radix Dialog whose DismissableLayer closes the WHOLE modal on
  // Escape (capture phase). The popovers have no Escape handler of their own, so
  // without this the keystroke would discard unsaved signature edits. We
  // intercept in the capture phase and stopImmediatePropagation so Radix never
  // sees it while a popover is open. (escapeOwner's data-attr can't help here:
  // Radix's own listener doesn't consult it.)
  useEffect(() => {
    if (!openPopover) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopImmediatePropagation()
        setOpenPopover(null)
      }
    }
    document.addEventListener('keydown', onKey, true)
    return () => document.removeEventListener('keydown', onKey, true)
  }, [openPopover])

  const handleEditorInput = useCallback(() => {
    if (!editorRef.current) return
    editorHtmlRef.current = editorRef.current.innerHTML
    const text = editorText(editorRef.current)
    if (text.length <= MAX_SIGNATURE_LENGTH) {
      setSignature(text)
      setError(null)
    }
  }, [])

  const insertImage = useCallback((src: string) => {
    if (!editorRef.current) return

    editorRef.current.focus()

    const img = document.createElement('img')
    img.src = src
    img.style.cssText = 'max-width:200px;display:block;margin:4px 0'
    img.alt = 'signature image'

    const sel = window.getSelection()
    let range: Range

    if (savedRangeRef.current) {
      range = savedRangeRef.current
    } else if (sel && sel.rangeCount > 0) {
      range = sel.getRangeAt(0)
    } else {
      range = document.createRange()
      range.selectNodeContents(editorRef.current)
      range.collapse(false)
    }

    try {
      range.deleteContents()
      range.insertNode(img)
    } catch {
      // Fallback: range may be detached, append to end of editor
      editorRef.current.appendChild(img)
    }

    // Ensure image is actually in the editor (verify insertion succeeded)
    if (!editorRef.current.contains(img)) {
      editorRef.current.appendChild(img)
    }

    // Place cursor after the image
    const newRange = document.createRange()
    newRange.setStartAfter(img)
    newRange.collapse(true)
    if (sel) { sel.removeAllRanges(); sel.addRange(newRange) }

    editorHtmlRef.current = editorRef.current.innerHTML

    savedRangeRef.current = null
  }, [])

  const handlePasteImage = useCallback((file: File) => {
    if (!accountId) return
    const reader = new FileReader()
    reader.onload = (e) => {
      const img = new Image()
      img.onload = async () => {
        const canvas = document.createElement('canvas')
        const MAX = 200
        const ratio = Math.min(MAX / img.width, MAX / img.height, 1)
        canvas.width = Math.round(img.width * ratio)
        canvas.height = Math.round(img.height * ratio)
        canvas.getContext('2d')!.drawImage(img, 0, 0, canvas.width, canvas.height)
        try {
          const blob = await new Promise<Blob>((resolve, reject) =>
            canvas.toBlob(b => b ? resolve(b) : reject(new Error('toBlob failed')), 'image/jpeg', 0.65)
          )
          const uploadFile = new File([blob], 'pasted-image.jpg', { type: 'image/jpeg' })
          const url = await uploadSignatureImage(accountId, uploadFile)
          insertImage(url)
        } catch {
          // Fallback to base64 if upload fails
          insertImage(canvas.toDataURL('image/jpeg', 0.65))
        }
      }
      img.src = e.target!.result as string
    }
    reader.readAsDataURL(file)
  }, [accountId, insertImage])

  const setSelectedImgWidth = useCallback((w: number) => {
    if (!selectedImg || !editorRef.current) return
    const clamped = Math.max(16, Math.min(2000, Math.round(w)))
    selectedImg.style.width = `${clamped}px`
    selectedImg.style.height = 'auto'
    selectedImg.style.maxWidth = 'none'
    editorHtmlRef.current = editorRef.current.innerHTML
    setImgBarPos(pos => pos ? { ...pos } : null)
  }, [selectedImg])

  const resizeSelectedImg = useCallback((delta: number) => {
    if (!selectedImg) return
    const current = selectedImg.offsetWidth || parseInt(selectedImg.style.width) || 200
    setSelectedImgWidth(current + delta)
  }, [selectedImg, setSelectedImgWidth])

  const replaceSelectedImg = useCallback(() => {
    if (!selectedImg || !accountId) return
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = 'image/*'
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      try {
        setError(null)
        const url = await resizeAndUploadImage(file)
        selectedImg.src = url
        selectedImg.removeAttribute('data-logo-placeholder')
        editorHtmlRef.current = editorRef.current?.innerHTML || ''
      } catch (err) {
        // F-03 (audit 2026-06-11) : feedback utilisateur sur échec d'upload.
        console.error('Image replace failed:', err)
        setError(tCommon('toasts.upload_failed'))
      }
    }
    input.click()
  }, [selectedImg, accountId, resizeAndUploadImage, tCommon])

  const handleSave = useCallback(async () => {
    if (!accountId) return
    const html = editorRef.current?.innerHTML || editorHtmlRef.current || ''
    const text = editorText(editorRef.current) || signature
    // Validation locale : un 400 backend ("html is required") afficherait un
    // message brut non localisé — on bloque avant l'appel avec la clé i18n.
    if (!text.trim() && !html.replace(/<br\s*\/?>|<\/?div>/gi, '').trim()) {
      setError(t('signature_content_required'))
      return
    }
    try {
      setSaving(true)
      setError(null)
      const name = nameDraft.trim() || `Signature ${entries.length + 1}`
      if (editingEntry) {
        await updateSignatureEntry(accountId, editingEntry.id, { name, html, text })
      } else {
        await createSignature(accountId, { name, html, text })
      }
      // Le backend a propagé vers le compte si l'entrée est/devient le défaut ;
      // refreshLibrary réaligne la liste ET le cache composer dessus.
      await refreshLibrary(accountId)
      backToList()
    } catch (err) {
      console.error('Failed to save signature:', err)
      setError(err instanceof Error ? err.message : t('signature_save_error'))
    } finally {
      setSaving(false)
    }
  }, [accountId, signature, nameDraft, entries.length, editingEntry, refreshLibrary, backToList, t])

  const handleSetDefault = useCallback(async (entry: SignatureEntry) => {
    if (!accountId || entry.is_default) return
    try {
      setError(null)
      await setDefaultSignature(accountId, entry.id)
      setEntries(prev => prev.map(s => ({ ...s, is_default: s.id === entry.id })))
      setAccountSignatureCache(entry.html || null, entry.text || null, accountEmail)
    } catch (err) {
      console.error('Failed to set default signature:', err)
      setError(err instanceof Error ? err.message : t('signature_save_error'))
    }
  }, [accountId, accountEmail])

  const handleDelete = useCallback(async (entry: SignatureEntry) => {
    if (!accountId) return
    try {
      setError(null)
      await deleteSignatureEntry(accountId, entry.id)
      // Suppression du défaut → le backend promeut le suivant (ou vide le
      // compte si c'était la dernière) ; on recharge pour refléter son choix.
      await refreshLibrary(accountId)
    } catch (err) {
      console.error('Failed to delete signature:', err)
      setError(err instanceof Error ? err.message : t('signature_save_error'))
    }
  }, [accountId, refreshLibrary])

  const handleCancel = useCallback(() => {
    setError(null)
    setSuccessMessage(null)
    onClose()
  }, [onClose])

  const handleSyncFromProvider = useCallback(async () => {
    if (!accountId) return
    try {
      setSyncing(true)
      setError(null)
      setSuccessMessage(null)
      // dry_run : récupère la signature provider SANS la persister — un
      // import suivi d'Annuler ne doit pas changer la signature des envois.
      const result = await syncSignature(accountId, true)
      if (result.success && result.signature) {
        setSignature(result.signature)
        // L'import remplit l'ÉDITEUR uniquement — l'utilisateur choisit ensuite
        // de sauvegarder (création/màj d'une entrée de la bibliothèque).
        if (editorRef.current) {
          const newContent = result.signature_html || plainTextToHtml(result.signature)
          editorRef.current.innerHTML = newContent
          editorHtmlRef.current = newContent
        }
        setSuccessMessage(t('signature_import_success'))
      } else if (result.success && !result.signature) {
        setError(t('signature_no_signature'))
      } else {
        setError(result.error || t('signature_import_error'))
      }
    } catch (err) {
      console.error('Failed to sync signature:', err)
      setError(err instanceof Error ? err.message : t('signature_import_error'))
    } finally {
      setSyncing(false)
    }
  }, [accountId])

  const MICROSOFT_DOMAINS = ['hotmail.com', 'hotmail.fr', 'outlook.com', 'outlook.fr', 'live.com', 'live.fr', 'msn.com']
  const isOutlookAccount = provider === 'outlook' ||
    (provider === 'imap_smtp' && MICROSOFT_DOMAINS.includes(accountEmail.split('@')[1]?.toLowerCase() ?? ''))

  const syncButtonLabel = syncing
    ? t('signature_importing')
    : isOutlookAccount
      ? t('signature_import_outlook')
      : t('signature_import_gmail')

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="sig-modal" showCloseButton={false} aria-describedby={undefined}>

        {/* ── Header ── */}
        <div className="sig-header">
          <div className="sig-header-title">
            <button
              className="sig-back"
              onClick={view === 'editor' ? backToList : onClose}
              aria-label={t('common:back', 'Back')}
              title={t('common:back', 'Back')}
            >
              <ChevronLeftIcon size={20} />
            </button>
            <DialogTitle>
              {view === 'editor'
                ? (editingEntry?.name || t('signature_add'))
                : t('account_signature')}
            </DialogTitle>
          </div>
          <button className="sig-close" onClick={handleCancel} aria-label={t('signature_close')}>
            <CloseIcon />
          </button>
        </div>

        {/* ── Body ── */}
        <div className="sig-body">
          <p className="sig-description">
            {view === 'editor' ? t('signature_description') : t('signature_library_description')}
          </p>

          {loading ? (
            <div className="sig-loading">
              <span className="sig-loading-dot" /><span className="sig-loading-dot" /><span className="sig-loading-dot" />
            </div>
          ) : view === 'list' ? (
            <div className="sig-list" data-testid="sig-list" role="list">
              {/* Défaut toujours en premier ; la sélection « signature par
                  défaut » est un radio group (sémantique de choix unique),
                  pas un bouton d'action — supprime le bouton bordé qui
                  cassait l'alignement entre cartes. */}
              {[...entries]
                .sort((a, b) => Number(b.is_default) - Number(a.is_default))
                .map(entry => (
                <div
                  key={entry.id}
                  className="sig-list-item"
                  data-testid="sig-list-item"
                  role="listitem"
                  tabIndex={0}
                  onClick={() => openEditor(entry)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      openEditor(entry)
                    }
                  }}
                >
                  <span className="sig-radio-wrap" onClick={e => e.stopPropagation()}>
                    <input
                      type="radio"
                      className="sig-default-radio"
                      name="sig-default-choice"
                      data-testid="sig-set-default"
                      checked={entry.is_default}
                      onChange={() => handleSetDefault(entry)}
                      title={t('signature_set_default')}
                      aria-label={`${t('signature_set_default')} — ${entry.name}`}
                    />
                  </span>
                  <div className="sig-list-item-main">
                    <div className="sig-list-item-head">
                      <span className="sig-list-item-name">{entry.name}</span>
                      {entry.is_default && (
                        <span className="sig-default-badge" data-testid="sig-default-badge">
                          {t('signature_default_badge')}
                        </span>
                      )}
                    </div>
                    <div
                      className="sig-preview"
                      aria-hidden="true"
                      dangerouslySetInnerHTML={{
                        __html: DOMPurify.sanitize(entry.html || plainTextToHtml(entry.text || ''), { USE_PROFILES: { html: true } }),
                      }}
                    />
                  </div>
                  <div className="sig-list-item-actions" onClick={e => e.stopPropagation()}>
                    <button
                      type="button"
                      className="sig-edit-btn"
                      data-testid="sig-edit"
                      onClick={() => openEditor(entry)}
                      title={tCommon('edit')}
                      aria-label={tCommon('edit')}
                    >
                      <EditIcon size={14} />
                    </button>
                    <button
                      type="button"
                      className="sig-delete-btn"
                      data-testid="sig-delete"
                      onClick={() => handleDelete(entry)}
                      title={tCommon('delete')}
                      aria-label={tCommon('delete')}
                    >
                      <TrashIcon size={14} />
                    </button>
                  </div>
                </div>
              ))}
              {/* Affordance de création DANS la collection (ghost row) */}
              <button
                type="button"
                className="sig-add-row"
                data-testid="sig-add-row"
                onClick={() => openEditor(null)}
              >
                <PlusIcon size={14} />
                <span>{t('signature_add')}</span>
              </button>
            </div>
          ) : (
            <>
              {/* Nom de la signature */}
              <input
                className="sig-name-input"
                data-testid="sig-name-input"
                type="text"
                value={nameDraft}
                onChange={e => setNameDraft(e.target.value)}
                placeholder={t('signature_name_placeholder')}
                maxLength={100}
                disabled={saving || syncing}
                aria-label={t('signature_name_placeholder')}
              />
              {/* Éditeur riche */}
              <div className="sig-section">
                <div className="sig-editor-wrap">
                  {/* Formatting toolbar */}
                  <div className="sig-format-toolbar" ref={toolbarRef} onMouseDown={e => e.preventDefault()}>
                    <button
                      type="button"
                      className="sig-format-btn"
                      onMouseDown={handleFormatBold}
                      title={t('signature_bold_title')}
                      aria-label={t('signature_bold')}
                    >
                      <b>B</b>
                    </button>
                    <button
                      type="button"
                      className="sig-format-btn"
                      onMouseDown={handleFormatItalic}
                      title={t('signature_italic_title')}
                      aria-label={t('signature_italic')}
                    >
                      <i style={{ fontStyle: 'italic', fontWeight: 400 }}>I</i>
                    </button>
                    <button
                      type="button"
                      className="sig-format-btn"
                      onMouseDown={handleFormatUnderline}
                      title={t('signature_underline_title')}
                      aria-label={t('signature_underline')}
                    >
                      <span style={{ textDecoration: 'underline' }}>U</span>
                    </button>
                    <div className="sig-format-sep" aria-hidden="true" />

                    {/* Font size */}
                    <button
                      type="button"
                      className="sig-format-btn sig-format-btn-dropdown"
                      onClick={() => setOpenPopover(p => p === 'size' ? null : 'size')}
                      title={t('signature_size_title')}
                      aria-label={t('signature_size')}
                      aria-expanded={openPopover === 'size'}
                    >
                      <span style={{ fontWeight: 600 }}>A</span>
                      <svg className="sig-caret" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <polyline points="6 9 12 15 18 9"/>
                      </svg>
                    </button>

                    {/* Text color */}
                    <button
                      type="button"
                      className="sig-format-btn sig-format-btn-dropdown"
                      onClick={() => setOpenPopover(p => p === 'color' ? null : 'color')}
                      title={t('signature_color_title')}
                      aria-label={t('signature_color')}
                      aria-expanded={openPopover === 'color'}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <path d="M4 20h16"/>
                        <path d="m6 16 6-12 6 12"/>
                        <path d="M8 12h8"/>
                      </svg>
                      <svg className="sig-caret" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <polyline points="6 9 12 15 18 9"/>
                      </svg>
                    </button>
                    <div className="sig-format-sep" aria-hidden="true" />

                    {/* Alignment */}
                    <button
                      type="button"
                      className="sig-format-btn"
                      onMouseDown={e => { e.preventDefault(); handleAlign('Left') }}
                      title={t('signature_align_left_title')}
                      aria-label={t('signature_align_left')}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="15" y2="12"/><line x1="3" y1="18" x2="18" y2="18"/>
                      </svg>
                    </button>
                    <button
                      type="button"
                      className="sig-format-btn"
                      onMouseDown={e => { e.preventDefault(); handleAlign('Center') }}
                      title={t('signature_align_center_title')}
                      aria-label={t('signature_align_center')}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <line x1="3" y1="6" x2="21" y2="6"/><line x1="6" y1="12" x2="18" y2="12"/><line x1="5" y1="18" x2="19" y2="18"/>
                      </svg>
                    </button>
                    <button
                      type="button"
                      className="sig-format-btn"
                      onMouseDown={e => { e.preventDefault(); handleAlign('Right') }}
                      title={t('signature_align_right_title')}
                      aria-label={t('signature_align_right')}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <line x1="3" y1="6" x2="21" y2="6"/><line x1="9" y1="12" x2="21" y2="12"/><line x1="6" y1="18" x2="21" y2="18"/>
                      </svg>
                    </button>
                    <div className="sig-format-sep" aria-hidden="true" />

                    {/* Templates */}
                    <button
                      type="button"
                      className="sig-format-btn sig-format-btn-dropdown"
                      onClick={() => setOpenPopover(p => p === 'templates' ? null : 'templates')}
                      title={t('signature_templates_title')}
                      aria-label={t('signature_templates')}
                      aria-expanded={openPopover === 'templates'}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <rect x="3" y="3" width="7" height="7" rx="1"/>
                        <rect x="14" y="3" width="7" height="7" rx="1"/>
                        <rect x="3" y="14" width="7" height="7" rx="1"/>
                        <rect x="14" y="14" width="7" height="7" rx="1"/>
                      </svg>
                      <svg className="sig-caret" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <polyline points="6 9 12 15 18 9"/>
                      </svg>
                    </button>

                    {/* Popovers */}
                    {openPopover === 'size' && (
                      <div className="sig-popover" style={{ left: 10 }} role="menu">
                        <div className="sig-popover-title">{t('signature_size')}</div>
                        <div className="sig-size-list">
                          <button type="button" className="sig-size-item" onMouseDown={e => { e.preventDefault(); handleSetFontSize('2') }}>
                            <span className="sig-size-icon-s">Aa</span>
                            <span>{t('signature_size_small')}</span>
                            <span className="sig-size-item-preview">12</span>
                          </button>
                          <button type="button" className="sig-size-item" onMouseDown={e => { e.preventDefault(); handleSetFontSize('3') }}>
                            <span className="sig-size-icon-m">Aa</span>
                            <span>{t('signature_size_normal')}</span>
                            <span className="sig-size-item-preview">14</span>
                          </button>
                          <button type="button" className="sig-size-item" onMouseDown={e => { e.preventDefault(); handleSetFontSize('5') }}>
                            <span className="sig-size-icon-l">Aa</span>
                            <span>{t('signature_size_large')}</span>
                            <span className="sig-size-item-preview">18</span>
                          </button>
                        </div>
                      </div>
                    )}

                    {openPopover === 'color' && (
                      <div className="sig-popover" style={{ left: 42 }} role="menu">
                        <div className="sig-popover-title">{t('signature_color')}</div>
                        <div className="sig-color-grid">
                          <button type="button" className="sig-color-swatch sig-color-default" title={t('signature_color_default')} onMouseDown={e => { e.preventDefault(); handleSetColor('inherit') }} />
                          {['#000000','#6b7280','#0d9488','#2563eb','#9333ea','#dc2626','#ea580c','#ca8a04','#16a34a'].map(c => (
                            <button key={c} type="button" className="sig-color-swatch" style={{ background: c }} onMouseDown={e => { e.preventDefault(); handleSetColor(c) }} />
                          ))}
                        </div>
                      </div>
                    )}

                    {openPopover === 'templates' && (
                      <div className="sig-popover" style={{ right: 10, minWidth: 240 }} role="menu">
                        <div className="sig-popover-title">{t('signature_templates')}</div>
                        <div className="sig-template-list">
                          <button type="button" className="sig-template-item" onMouseDown={e => { e.preventDefault(); insertTemplate('minimal') }}>
                            <div>
                              <div>{t('signature_tpl_minimal')}</div>
                              <span className="sig-template-item-desc">{t('signature_tpl_minimal_desc')}</span>
                            </div>
                          </button>
                          <button type="button" className="sig-template-item" onMouseDown={e => { e.preventDefault(); insertTemplate('logo') }}>
                            <div>
                              <div>{t('signature_tpl_logo')}</div>
                              <span className="sig-template-item-desc">{t('signature_tpl_logo_desc')}</span>
                            </div>
                          </button>
                          <button type="button" className="sig-template-item" onMouseDown={e => { e.preventDefault(); insertTemplate('twoColumn') }}>
                            <div>
                              <div>{t('signature_tpl_two_column')}</div>
                              <span className="sig-template-item-desc">{t('signature_tpl_two_column_desc')}</span>
                            </div>
                          </button>
                        </div>
                      </div>
                    )}

                  </div>

                  {/* Contenteditable editor */}
                  <div
                    ref={editorRef}
                    className="sig-editor"
                    contentEditable={!saving && !syncing}
                    onInput={handleEditorInput}
                    onPaste={(e) => {
                      const file = Array.from(e.clipboardData.files).find(f => f.type.startsWith('image/'))
                      if (file) {
                        e.preventDefault()
                        handlePasteImage(file)
                      }
                    }}
                    onClick={(e) => {
                      const target = e.target as HTMLElement
                      if (target.tagName === 'IMG') {
                        const img = target as HTMLImageElement
                        // Logo placeholder → open file picker to replace
                        if (img.getAttribute('data-logo-placeholder') === 'true' && accountId) {
                          const input = document.createElement('input')
                          input.type = 'file'
                          input.accept = 'image/*'
                          input.onchange = async () => {
                            const file = input.files?.[0]
                            if (!file) return
                            try {
                              setError(null)
                              const url = await resizeAndUploadImage(file)
                              img.src = url
                              img.removeAttribute('data-logo-placeholder')
                              editorHtmlRef.current = editorRef.current?.innerHTML || ''
                            } catch (err) {
                              // F-03 (audit 2026-06-11) : feedback utilisateur sur échec d'upload.
                              console.error('Logo upload failed:', err)
                              setError(tCommon('toasts.upload_failed'))
                            }
                          }
                          input.click()
                          return
                        }
                        const rect = img.getBoundingClientRect()
                        setSelectedImg(img)
                        // Clamp the bar so it stays within the editor width — prevents the × button from being clipped
                        const BAR_WIDTH = 230
                        const editorRect = editorRef.current?.getBoundingClientRect()
                        const maxLeft = editorRect ? editorRect.right - BAR_WIDTH - 4 : window.innerWidth - BAR_WIDTH - 4
                        const minLeft = editorRect ? editorRect.left + 4 : 4
                        const clampedLeft = Math.max(minLeft, Math.min(maxLeft, rect.left))
                        setImgBarPos({ top: rect.top - 44, left: clampedLeft })
                      } else {
                        setSelectedImg(null)
                        setImgBarPos(null)
                      }
                    }}
                    suppressContentEditableWarning
                    data-placeholder={t('signature_placeholder')}
                    aria-label={t('signature_editor_aria')}
                  />

                  {/* Mini-toolbar redimensionnement image — portaled to body
                      so fixed positioning escapes the Dialog's transform containing block */}
                  {selectedImg && imgBarPos && createPortal(
                    <div
                      className="sig-img-resize-bar"
                      style={{ position: 'fixed', top: imgBarPos.top, left: imgBarPos.left }}
                      onMouseDown={e => e.preventDefault()}
                    >
                      <button type="button" onClick={() => resizeSelectedImg(-40)} title={t('signature_img_smaller', 'Smaller')}>−</button>
                      <input
                        type="number"
                        className="sig-img-size-input"
                        min={16}
                        max={2000}
                        step={1}
                        value={selectedImg.offsetWidth || 200}
                        onChange={(e) => {
                          const n = parseInt(e.target.value, 10)
                          if (!Number.isNaN(n)) setSelectedImgWidth(n)
                        }}
                        onMouseDown={e => e.stopPropagation()}
                        title={t('signature_img_size_title', 'Enter the exact pixel size')}
                        aria-label={t('signature_img_size_title', 'Enter the exact pixel size')}
                      />
                      <span className="sig-img-size-unit">px</span>
                      <button type="button" onClick={() => resizeSelectedImg(+40)} title={t('signature_img_larger', 'Larger')}>+</button>
                      <button type="button" onClick={replaceSelectedImg} title={t('signature_img_replace', 'Replace')} aria-label={t('signature_img_replace', 'Replace')}>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                          <polyline points="23 4 23 10 17 10"/>
                          <polyline points="1 20 1 14 7 14"/>
                          <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10"/>
                          <path d="M20.49 15a9 9 0 0 1-14.85 3.36L1 14"/>
                        </svg>
                      </button>
                      <button type="button" className="sig-img-resize-close" onClick={() => { setSelectedImg(null); setImgBarPos(null) }}><CloseIcon size={14} /></button>
                    </div>,
                    document.body
                  )}
                </div>

              </div>
            </>
          )}

          {successMessage && (
            <div className="sig-success" role="status">
              <CheckIcon size={14} />
              {successMessage}
            </div>
          )}

          {error && (
            <div id="sig-error" className="sig-error" role="alert">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
              </svg>
              {error}
            </div>
          )}
        </div>

        {/* ── Footer (vue éditeur uniquement) ── */}
        {view === 'editor' && (
          <div className="sig-footer">
            <div className="sig-footer-left">
              {!loading && (
                <button
                  className="sig-import-btn"
                  onClick={handleSyncFromProvider}
                  disabled={syncing || saving}
                  type="button"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <polyline points="8 17 12 21 16 17"/><line x1="12" y1="3" x2="12" y2="21"/>
                  </svg>
                  {syncButtonLabel}
                </button>
              )}
            </div>
            <div className="sig-footer-right">
              <Button
                onClick={handleSave}
                disabled={saving || loading || syncing}
                type="button"
                data-testid="sig-save"
              >
                {saving ? t('signature_saving') : t('signature_save')}
              </Button>
            </div>
          </div>
        )}

      </DialogContent>
    </Dialog>
  )
}
