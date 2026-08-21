import { useCallback, useEffect, useImperativeHandle, useRef, useState, forwardRef } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchSnippets } from '../../api/snippets'
import type { Snippet } from '../../types/snippets'
import { ChevronDownIcon } from '../icons/ActionIcons'
import './RichTextEditor.css'

export interface RichTextEditorHandle {
  /** Insert raw HTML at the current cursor position. */
  insertHtmlAtCursor: (html: string) => void
  /** Focus the editor. */
  focus: () => void
  /** Get the current HTML content. */
  getHtml: () => string
}

/** One entry in the placeholder menu (the `{ }` toolbar dropdown). Inserts
 *  HTML at the caret when chosen. */
export interface PlaceholderSuggestion {
  /** Stable key. */
  id: string
  /** Display name in the menu (e.g. "Période d'absence", "Prénom"). */
  label: string
  /** Optional secondary text shown right-aligned (e.g. a live date preview). */
  preview?: string
  /** HTML inserted at the caret. Called fresh on each click so it can reflect
   *  current state (e.g. the latest dates). */
  buildHtml: () => string
}

interface RichTextEditorProps {
  /** HTML value. Plain text with `\n` is auto-converted to `<div>` lines. */
  value: string
  /** Called with HTML on every edit. */
  onChange: (html: string) => void
  placeholder?: string
  disabled?: boolean
  /** Show the snippet picker (grid icon). Defaults to true. */
  enableSnippets?: boolean
  /** Optional placeholders shown in a `{ }` toolbar dropdown menu. */
  placeholders?: PlaceholderSuggestion[]
  /** Optional minimum editor height (px). Defaults to 120. */
  minHeight?: number
  /** Extra CSS class on the root element. */
  className?: string
  /** Accessible label for the editor surface. */
  ariaLabel?: string
}

function plainTextToHtml(text: string): string {
  if (!text) return ''
  // If it already contains tags, treat as HTML.
  if (/<[a-z][\s\S]*>/i.test(text)) return text
  return text.split('\n').map(l => `<div>${l || '<br>'}</div>`).join('')
}

type PopoverKey = 'size' | 'color' | 'snippets' | 'placeholders' | null

/**
 * Shared rich-text editor matching the SignatureModal toolbar (B/I/U,
 * font size, color, alignment, optional snippet picker). Stores HTML.
 * Insert-at-cursor snippets resolve variables (`{first_name}` etc.) at
 * runtime via the consumer's existing pipeline — the editor stores them
 * as-is in the HTML.
 */
export const RichTextEditor = forwardRef<RichTextEditorHandle, RichTextEditorProps>(
  function RichTextEditor(
    {
      value,
      onChange,
      placeholder,
      disabled = false,
      enableSnippets = true,
      placeholders,
      minHeight = 120,
      className = '',
      ariaLabel,
    },
    ref
  ) {
    const { t } = useTranslation('settings')
    const editorRef = useRef<HTMLDivElement>(null)
    const savedRangeRef = useRef<Range | null>(null)
    const toolbarRef = useRef<HTMLDivElement>(null)
    const lastHtmlRef = useRef<string>('')

    const [openPopover, setOpenPopover] = useState<PopoverKey>(null)
    const [snippets, setSnippets] = useState<Snippet[]>([])
    const [loadingSnippets, setLoadingSnippets] = useState(false)
    const [snippetsLoaded, setSnippetsLoaded] = useState(false)
    const [snippetsError, setSnippetsError] = useState(false)

    // Lazy-load snippets the first time the picker opens.
    // F-05 (audit 2026-06-11) : en échec, ne PAS marquer snippetsLoaded — le
    // flag à vie figeait un faux empty-state « aucun snippet » sans retry.
    // L'erreur est affichée dans le popover et le prochain open retente.
    useEffect(() => {
      if (openPopover !== 'snippets' || snippetsLoaded || !enableSnippets) return
      setLoadingSnippets(true)
      setSnippetsError(false)
      fetchSnippets()
        .then(r => {
          setSnippets(r.snippets || [])
          setSnippetsLoaded(true)
        })
        .catch(() => setSnippetsError(true))
        .finally(() => {
          setLoadingSnippets(false)
        })
    }, [openPopover, snippetsLoaded, enableSnippets])

    // Mirror `value` into the contenteditable. Only when an EXTERNAL value
    // change arrives — never when our own `emit` just fired. `lastHtmlRef`
    // holds the value last reflected in the DOM; comparing the raw `value`
    // against it (instead of the `plainTextToHtml`-normalised form) is what
    // makes this work: plain typed text like "Salut" normalises to
    // "<div>Salut</div>", so the old comparison always mismatched and re-set
    // innerHTML on every keystroke — destroying the caret and dropping an
    // inserted chip onto the next line. Skipping our own emits keeps the
    // caret put so chips land inline at the cursor.
    useEffect(() => {
      const el = editorRef.current
      if (!el) return
      if (value === lastHtmlRef.current) return
      const incoming = plainTextToHtml(value)
      if (incoming === el.innerHTML) return
      el.innerHTML = incoming
      lastHtmlRef.current = value
    }, [value])

    const saveSelection = useCallback(() => {
      const sel = window.getSelection()
      if (sel && sel.rangeCount > 0 && editorRef.current?.contains(sel.anchorNode)) {
        savedRangeRef.current = sel.getRangeAt(0).cloneRange()
      }
    }, [])

    const restoreSelection = useCallback(() => {
      const sel = window.getSelection()
      if (savedRangeRef.current && sel) {
        sel.removeAllRanges()
        sel.addRange(savedRangeRef.current)
      }
    }, [])

    const emit = useCallback(() => {
      const el = editorRef.current
      if (!el) return
      const html = el.innerHTML
      lastHtmlRef.current = html
      onChange(html)
    }, [onChange])

    const execFormat = useCallback(
      (cmd: string, val?: string) => {
        const el = editorRef.current
        if (!el) return
        restoreSelection()
        el.focus()
        try {
          document.execCommand('styleWithCSS', false, 'true')
        } catch {
          /* noop */
        }
        document.execCommand(cmd, false, val)
        emit()
        savedRangeRef.current = null
      },
      [emit, restoreSelection]
    )

    const handleBold = useCallback((e: React.MouseEvent) => { e.preventDefault(); execFormat('bold') }, [execFormat])
    const handleItalic = useCallback((e: React.MouseEvent) => { e.preventDefault(); execFormat('italic') }, [execFormat])
    const handleUnderline = useCallback((e: React.MouseEvent) => { e.preventDefault(); execFormat('underline') }, [execFormat])
    const handleAlign = useCallback((dir: 'Left' | 'Center' | 'Right') => execFormat(`justify${dir}`), [execFormat])

    const handleSetFontSize = useCallback(
      (size: string) => {
        execFormat('fontSize', size)
        setOpenPopover(null)
      },
      [execFormat]
    )

    const handleSetColor = useCallback(
      (color: string) => {
        if (color === 'inherit') {
          execFormat('foreColor', '')
        } else {
          execFormat('foreColor', color)
        }
        setOpenPopover(null)
      },
      [execFormat]
    )

    const insertHtmlAtCursor = useCallback(
      (html: string) => {
        const el = editorRef.current
        if (!el) return
        el.focus()
        restoreSelection()
        // Insert via the Range API rather than execCommand('insertHTML'):
        // execCommand wraps the fragment in its own block when the caret sits
        // in a bare text node (an editor where you just typed "Salut" with no
        // <div> wrapper), pushing an inline chip onto its own line. Splicing
        // the nodes into the current range keeps the chip inline at the caret.
        const sel = window.getSelection()
        if (!sel || sel.rangeCount === 0 || !el.contains(sel.anchorNode)) {
          el.insertAdjacentHTML('beforeend', html)
        } else {
          const range = sel.getRangeAt(0)
          range.deleteContents()
          const tmp = document.createElement('div')
          tmp.innerHTML = html
          const frag = document.createDocumentFragment()
          let lastNode: ChildNode | null = null
          while (tmp.firstChild) {
            lastNode = tmp.firstChild
            frag.appendChild(tmp.firstChild)
          }
          range.insertNode(frag)
          // Drop the caret right after the inserted content so typing continues
          // on the same line.
          if (lastNode) {
            const after = document.createRange()
            after.setStartAfter(lastNode)
            after.collapse(true)
            sel.removeAllRanges()
            sel.addRange(after)
          }
        }
        emit()
        savedRangeRef.current = null
      },
      [emit, restoreSelection]
    )

    const handleInsertSnippet = useCallback(
      (snippet: Snippet) => {
        // Snippet content is currently stored as plain text with `{var}`
        // placeholders. Convert linebreaks → <br> for inline insertion
        // so it flows with the surrounding HTML.
        const isAlreadyHtml = /<[a-z][\s\S]*>/i.test(snippet.content)
        const html = isAlreadyHtml
          ? snippet.content
          : snippet.content.replace(/\n/g, '<br>')
        insertHtmlAtCursor(html)
        setOpenPopover(null)
      },
      [insertHtmlAtCursor]
    )

    const handleInsertPlaceholder = useCallback(
      (p: PlaceholderSuggestion) => {
        insertHtmlAtCursor(p.buildHtml())
        setOpenPopover(null)
      },
      [insertHtmlAtCursor]
    )

    useImperativeHandle(ref, () => ({
      insertHtmlAtCursor,
      focus: () => editorRef.current?.focus(),
      getHtml: () => editorRef.current?.innerHTML ?? '',
    }))

    // Click-outside + Escape → close popovers.
    useEffect(() => {
      if (!openPopover) return
      const onDocClick = (e: MouseEvent) => {
        if (toolbarRef.current && !toolbarRef.current.contains(e.target as Node)) {
          setOpenPopover(null)
        }
      }
      const onKey = (e: KeyboardEvent) => {
        if (e.key === 'Escape') {
          // Capture + stopPropagation so the host modal's own Escape handler
          // doesn't also fire and close the whole modal.
          e.stopPropagation()
          setOpenPopover(null)
        }
      }
      document.addEventListener('mousedown', onDocClick)
      document.addEventListener('keydown', onKey, true)
      return () => {
        document.removeEventListener('mousedown', onDocClick)
        document.removeEventListener('keydown', onKey, true)
      }
    }, [openPopover])

    const onInput = useCallback(() => {
      emit()
    }, [emit])

    return (
      <div className={`rte-wrap ${className}`}>
        <div
          className="rte-toolbar"
          ref={toolbarRef}
          onMouseDown={e => {
            // Preserve selection in the editor when clicking the toolbar.
            if (!(e.target as HTMLElement).closest('.rte-popover')) {
              e.preventDefault()
            }
            saveSelection()
          }}
        >
          <div className="rte-toolbar-row">
          <button type="button" className="rte-btn" onMouseDown={handleBold} title={t('signature_bold_title', { defaultValue: 'Gras (Ctrl+B)' })} aria-label="Bold">
            <b>B</b>
          </button>
          <button type="button" className="rte-btn" onMouseDown={handleItalic} title={t('signature_italic_title', { defaultValue: 'Italique (Ctrl+I)' })} aria-label="Italic">
            <i style={{ fontStyle: 'italic', fontWeight: 400 }}>I</i>
          </button>
          <button type="button" className="rte-btn" onMouseDown={handleUnderline} title={t('signature_underline_title', { defaultValue: 'Souligné (Ctrl+U)' })} aria-label="Underline">
            <span style={{ textDecoration: 'underline' }}>U</span>
          </button>
          <div className="rte-sep" aria-hidden="true" />

          <button
            type="button"
            className="rte-btn rte-btn-dropdown"
            onClick={() => setOpenPopover(p => (p === 'size' ? null : 'size'))}
            title={t('signature_size_title', { defaultValue: 'Taille du texte' })}
            aria-label="Font size"
            aria-expanded={openPopover === 'size'}
          >
            <span style={{ fontWeight: 600 }}>A</span>
            <ChevronDownIcon size={10} className="rte-caret" />
          </button>

          <button
            type="button"
            className="rte-btn rte-btn-dropdown"
            onClick={() => setOpenPopover(p => (p === 'color' ? null : 'color'))}
            title={t('signature_color_title', { defaultValue: 'Couleur du texte' })}
            aria-label="Text color"
            aria-expanded={openPopover === 'color'}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M4 20h16" />
              <path d="m6 16 6-12 6 12" />
              <path d="M8 12h8" />
            </svg>
            <ChevronDownIcon size={10} className="rte-caret" />
          </button>
          <div className="rte-sep" aria-hidden="true" />

          <button type="button" className="rte-btn" onMouseDown={e => { e.preventDefault(); handleAlign('Left') }} title={t('signature_align_left_title', { defaultValue: 'Aligner à gauche' })} aria-label="Align left">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="15" y2="12" /><line x1="3" y1="18" x2="18" y2="18" />
            </svg>
          </button>
          <button type="button" className="rte-btn" onMouseDown={e => { e.preventDefault(); handleAlign('Center') }} title={t('signature_align_center_title', { defaultValue: 'Centrer' })} aria-label="Align center">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <line x1="3" y1="6" x2="21" y2="6" /><line x1="6" y1="12" x2="18" y2="12" /><line x1="5" y1="18" x2="19" y2="18" />
            </svg>
          </button>
          <button type="button" className="rte-btn" onMouseDown={e => { e.preventDefault(); handleAlign('Right') }} title={t('signature_align_right_title', { defaultValue: 'Aligner à droite' })} aria-label="Align right">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <line x1="3" y1="6" x2="21" y2="6" /><line x1="9" y1="12" x2="21" y2="12" /><line x1="6" y1="18" x2="21" y2="18" />
            </svg>
          </button>

          {placeholders && placeholders.length > 0 && (
            <>
              <div className="rte-sep" aria-hidden="true" />
              <button
                type="button"
                className="rte-btn"
                onClick={() => setOpenPopover(p => (p === 'placeholders' ? null : 'placeholders'))}
                title={t('rte_insert_placeholder', { defaultValue: 'Insérer un champ dynamique' })}
                aria-label="Insert placeholder"
                aria-expanded={openPopover === 'placeholders'}
              >
                <span style={{ fontWeight: 600, fontFamily: 'var(--font-mono, monospace)', fontSize: 12, letterSpacing: '-0.03em' }}>
                  {'{'}<span style={{ fontStyle: 'italic' }}>x</span>{'}'}
                </span>
              </button>
            </>
          )}

          {enableSnippets && (
            <>
              <div className="rte-sep" aria-hidden="true" />
              <button
                type="button"
                className="rte-btn rte-btn-dropdown"
                onClick={() => setOpenPopover(p => (p === 'snippets' ? null : 'snippets'))}
                title={t('quicksteps_use_snippet', { defaultValue: 'Insérer un snippet' })}
                aria-label="Insert snippet"
                aria-expanded={openPopover === 'snippets'}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M9 4H7a2 2 0 0 0-2 2v3a2 2 0 0 1-2 2 2 2 0 0 1 2 2v3a2 2 0 0 0 2 2h2" />
                  <path d="M15 4h2a2 2 0 0 1 2 2v3a2 2 0 0 0 2 2 2 2 0 0 0-2 2v3a2 2 0 0 1-2 2h-2" />
                </svg>
                <ChevronDownIcon size={10} className="rte-caret" />
              </button>
            </>
          )}
          </div>

          {openPopover && (
            <div
              className="rte-popover-backdrop"
              aria-hidden="true"
              onMouseDown={() => setOpenPopover(null)}
            />
          )}

          {placeholders && placeholders.length > 0 && openPopover === 'placeholders' && (
            <div className="rte-popover rte-popover-snippets" role="menu">
              <div className="rte-popover-title">{t('rte_placeholders_title', { defaultValue: 'Champs dynamiques' })}</div>
              <div className="rte-list">
                {placeholders.map(p => (
                  <button
                    key={p.id}
                    type="button"
                    className="rte-list-item rte-snippet-item"
                    onMouseDown={e => { e.preventDefault(); handleInsertPlaceholder(p) }}
                  >
                    <span className="rte-snippet-name">{p.label}</span>
                    {p.preview && <span className="rte-list-item-meta">{p.preview}</span>}
                  </button>
                ))}
              </div>
            </div>
          )}

          {openPopover === 'size' && (
            <div className="rte-popover" role="menu">
              <div className="rte-popover-title">{t('signature_size', { defaultValue: 'Taille' })}</div>
              <div className="rte-list">
                <button type="button" className="rte-list-item" onMouseDown={e => { e.preventDefault(); handleSetFontSize('2') }}>
                  <span className="rte-size-icon-s">Aa</span>
                  <span>{t('signature_size_small', { defaultValue: 'Petit' })}</span>
                  <span className="rte-list-item-meta">12</span>
                </button>
                <button type="button" className="rte-list-item" onMouseDown={e => { e.preventDefault(); handleSetFontSize('3') }}>
                  <span className="rte-size-icon-m">Aa</span>
                  <span>{t('signature_size_normal', { defaultValue: 'Normal' })}</span>
                  <span className="rte-list-item-meta">14</span>
                </button>
                <button type="button" className="rte-list-item" onMouseDown={e => { e.preventDefault(); handleSetFontSize('5') }}>
                  <span className="rte-size-icon-l">Aa</span>
                  <span>{t('signature_size_large', { defaultValue: 'Grand' })}</span>
                  <span className="rte-list-item-meta">18</span>
                </button>
              </div>
            </div>
          )}

          {openPopover === 'color' && (
            <div className="rte-popover" role="menu">
              <div className="rte-popover-title">{t('signature_color', { defaultValue: 'Couleur' })}</div>
              <div className="rte-color-grid">
                <button
                  type="button"
                  className="rte-color-swatch rte-color-default"
                  title={t('signature_color_default', { defaultValue: 'Défaut' })}
                  onMouseDown={e => { e.preventDefault(); handleSetColor('inherit') }}
                />
                {['#000000','#6b7280','#0d9488','#2563eb','#9333ea','#dc2626','#ea580c','#ca8a04','#16a34a'].map(c => (
                  <button
                    key={c}
                    type="button"
                    className="rte-color-swatch"
                    style={{ background: c }}
                    onMouseDown={e => { e.preventDefault(); handleSetColor(c) }}
                  />
                ))}
              </div>
            </div>
          )}

          {openPopover === 'snippets' && enableSnippets && (
            <div className="rte-popover rte-popover-snippets" role="menu">
              <div className="rte-popover-title">{t('quicksteps_use_snippet', { defaultValue: 'Insérer un snippet' })}</div>
              <div className="rte-list">
                {loadingSnippets ? (
                  <div className="rte-list-empty">{t('quicksteps_snippet_loading', { defaultValue: 'Chargement…' })}</div>
                ) : snippetsError ? (
                  <div className="rte-list-empty" role="alert">{t('quicksteps_snippet_error')}</div>
                ) : snippets.length === 0 ? (
                  <div className="rte-list-empty">{t('quicksteps_snippet_none', { defaultValue: 'Aucun snippet disponible' })}</div>
                ) : (
                  snippets.map(s => (
                    <button
                      key={s.id}
                      type="button"
                      className="rte-list-item rte-snippet-item"
                      onMouseDown={e => { e.preventDefault(); handleInsertSnippet(s) }}
                    >
                      <span className="rte-snippet-name">{s.name}</span>
                      {s.category && <span className="rte-list-item-meta">{s.category}</span>}
                    </button>
                  ))
                )}
              </div>
            </div>
          )}
        </div>

        <div
          ref={editorRef}
          className="rte-editor"
          contentEditable={!disabled}
          suppressContentEditableWarning
          data-placeholder={placeholder}
          aria-label={ariaLabel}
          onInput={onInput}
          onBlur={saveSelection}
          onKeyUp={saveSelection}
          onMouseUp={saveSelection}
          style={{ minHeight }}
        />
      </div>
    )
  }
)
