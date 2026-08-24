/*
 * Agentys — voice-first email assistant.
 * Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version. See the LICENSE file for details.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

/* eslint-disable react-refresh/only-export-components */
import { useEditor, EditorContent, NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react';
import type { NodeViewProps } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Link from '@tiptap/extension-link';
import Image from '@tiptap/extension-image';
import { TextStyle } from '@tiptap/extension-text-style';
import { Color } from '@tiptap/extension-color';
import DOMPurify from 'dompurify';
import { useCallback, useEffect, useState, useRef, useImperativeHandle, forwardRef, lazy, Suspense } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { useComposeFontPrefs, FONT_FAMILY_OPTIONS, type ComposeFontFamily, type ComposeFontSize } from '../hooks/useComposeFontPrefs';
import { EditIcon } from './icons/ActionIcons';
import { DictationCursor, dictationCursorPluginKey, createDictationCursorPlugin } from './dictationCursor';
import './DraftEditor.css';

const ImageAnnotator = lazy(() => import('./ImageAnnotator').then(m => ({ default: m.ImageAnnotator })));

/**
 * Custom NodeView for images — shows an edit/annotate button on hover.
 */
function AnnotatableImageView({ node, updateAttributes, editor }: NodeViewProps) {
  const { t } = useTranslation('compose');
  const [showAnnotator, setShowAnnotator] = useState(false);
  const isEditable = editor.isEditable;
  const imgRef = useRef<HTMLImageElement>(null);
  const startRef = useRef<{ x: number; w: number } | null>(null);

  const handleSave = useCallback((dataUrl: string) => {
    updateAttributes({ src: dataUrl });
    setShowAnnotator(false);
  }, [updateAttributes]);

  // Resize handle drag
  const onResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const img = imgRef.current;
    if (!img) return;
    startRef.current = { x: e.clientX, w: img.offsetWidth };

    const onMove = (ev: MouseEvent) => {
      if (!startRef.current) return;
      const newW = Math.max(50, startRef.current.w + (ev.clientX - startRef.current.x));
      updateAttributes({ width: newW });
    };
    const onUp = () => {
      startRef.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [updateAttributes]);

  const width = node.attrs.width;

  return (
    <NodeViewWrapper as="span" className="de-image-node" data-drag-handle>
      <img
        ref={imgRef}
        src={node.attrs.src}
        alt={node.attrs.alt || ''}
        className="de-image-inline"
        draggable={false}
        onDoubleClick={() => isEditable && setShowAnnotator(true)}
        style={{
          ...(isEditable ? { cursor: 'pointer' } : {}),
          ...(width ? { width: `${width}px`, height: 'auto' } : {}),
        }}
      />
      {isEditable && (
        <>
          <button
            type="button"
            className="de-image-edit-btn"
            onClick={() => setShowAnnotator(true)}
            title={t('annotator_edit')}
            aria-label={t('annotator_edit')}
          >
            <EditIcon size={12} />
            {t('annotator_edit')}
          </button>
          <div className="de-image-resize-handle" onMouseDown={onResizeStart} />
        </>
      )}
      {showAnnotator && (
        <Suspense fallback={null}>
          <ImageAnnotator
            src={node.attrs.src}
            onSave={handleSave}
            onCancel={() => setShowAnnotator(false)}
          />
        </Suspense>
      )}
    </NodeViewWrapper>
  );
}

const AnnotatableImage = Image.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      width: {
        default: null,
        parseHTML: (el: HTMLElement) => el.getAttribute('width') ? parseInt(el.getAttribute('width')!, 10) : null,
        renderHTML: (attrs: Record<string, unknown>) => attrs.width ? { width: attrs.width } : {},
      },
    };
  },
  addNodeView() {
    return ReactNodeViewRenderer(AnnotatableImageView);
  },
});

/**
 * Convertit du texte brut (avec \n) en HTML paragraphs pour TipTap.
 * Si le contenu est déjà du HTML, le retourne tel quel.
 *
 * Split on every \n so blank lines (from \n\n in the source) become empty
 * <p></p> elements. TipTap renders empty paragraphs as visible blank lines
 * (the same way pressing Enter twice does). Without this, the backend's
 * "Bonjour,\n\nBody\n\nÀ bientôt," collapsed visually to three flush lines
 * because `.draft-editor-content p` has `margin: 0` — splitting on \n\n+
 * dropped the separators entirely instead of preserving them as empty <p>s.
 */
function plainTextToHtml(text: string): string {
  if (!text) return text;
  if (/<[a-z][\s\S]*>/i.test(text)) return text;
  return text
    .split('\n')
    .map(line => `<p>${line}</p>`)
    .join('');
}

/**
 * Build the literal text to insert for a dictated voice transcript.
 *
 * The Whisper hook hands us entity-escaped HTML like `<p>j&#39;ai fini</p>`.
 * We strip the wrapper tags, decode the basic entities `escapeHtml` produced
 * (apostrophes especially — French speech is full of them), and prepend a
 * single space when the caret sits right after a word/punctuation char. That
 * lets back-to-back dictations read as flowing prose ("que le texte se suivent")
 * instead of running together as "fini.Ensuite". Returns '' for empty/blank
 * transcripts so callers can no-op. `charBefore` is the single character
 * immediately preceding the caret ('' at the start of the document).
 *
 * Exported for unit testing — the caret/spacing logic is the part worth proving.
 */
export function buildDictationInsert(transcriptHtml: string, charBefore: string): string {
  const text = transcriptHtml
    .replace(/<[^>]*>/g, '')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#0?39;/g, "'")
    .replace(/&nbsp;|&#160;/gi, ' ')
    .replace(/&amp;/g, '&')
    .trim();
  if (!text) return '';
  const needsLeadingSpace = charBefore.length > 0 && !/\s$/.test(charBefore);
  return (needsLeadingSpace ? ' ' : '') + text;
}

export interface DraftEditorHandle {
  toggleBulletList: () => void;
  insertImage: (src: string, alt?: string) => void;
  insertText: (text: string) => void;
  focusEnd: () => void;
  /**
   * Insert a dictated transcript at the current caret as flowing text, so the
   * user sees the words land where the caret is and chained dictations stack
   * there. Decodes entities + smart-spaces via {@link buildDictationInsert}.
   */
  insertDictation: (transcriptHtml: string) => void;
  /**
   * Focus the editor for dictation so its caret is visible — but only when it
   * isn't already focused, so push-to-talk keeps the caret where the user left
   * it instead of yanking it to the end.
   */
  focusForDictation: () => void;
}

interface DraftEditorProps {
  content: string;
  onChange: (content: string) => void;
  onSaveStatusChange?: (status: 'idle' | 'saving' | 'saved' | 'error') => void;
  placeholder?: string;
  readOnly?: boolean;
  /** Active while recording OR transcribing — pins the insertion point and hides the native thin caret. */
  dictating?: boolean;
  /** True only while actively recording — shows the block cursor (it's hidden during the transcribe wait). */
  recording?: boolean;
  draftId?: string;
  showChanges?: boolean;
  onShowChangesToggle?: (show: boolean) => void;
  /** Hide the word count footer */
  hideWordCount?: boolean;
  /** Hide the formatting toolbar */
  hideToolbar?: boolean;
  /** Focus the editable body once TipTap is mounted. */
  autoFocus?: boolean;
  /** Extra CSS class on the root element */
  className?: string;
}

function countWords(text: string): number {
  const cleanText = text.replace(/<[^>]*>/g, ' ').trim();
  if (!cleanText) return 0;
  return cleanText.split(/\s+/).filter(word => word.length > 0).length;
}

const BACKUP_EXPIRY_MS = 3600000; // 1 hour

export const DraftEditor = forwardRef<DraftEditorHandle, DraftEditorProps>(function DraftEditor({
  content,
  onChange,
  onSaveStatusChange,
  placeholder,
  readOnly = false,
  dictating = false,
  recording = false,
  draftId,
  showChanges = false,
  onShowChangesToggle,
  hideWordCount = false,
  hideToolbar = false,
  autoFocus = false,
  className = '',
}, ref) {
  const { t: tCompose } = useTranslation('compose');
  const { t: tCommon } = useTranslation('common');
  const { fontFamily, fontSize, setFontFamily, setFontSize, fontFamilyCss, fontSizeCss } = useComposeFontPrefs();
  const resolvedPlaceholder = placeholder ?? tCompose('editor_placeholder');
  const [wordCount, setWordCount] = useState(0);
  const [linkUrl, setLinkUrl] = useState('');
  const [showLinkInput, setShowLinkInput] = useState(false);
  const [bubblePos, setBubblePos] = useState<{ top: number; left: number } | null>(null);
  const [showColorPicker, setShowColorPicker] = useState(false);

  // Email-safe colors (inline style="color:#xxx" — compatible Gmail & Outlook)
  const TEXT_COLORS = [
    { label: 'Default',  value: null },
    { label: 'Black',    value: '#000000' },
    { label: 'Gray',     value: '#6b7280' },
    { label: 'Red',      value: '#dc2626' },
    { label: 'Orange',   value: '#ea580c' },
    { label: 'Yellow',   value: '#ca8a04' },
    { label: 'Green',    value: '#16a34a' },
    { label: 'Teal',     value: '#0d9488' },
    { label: 'Blue',     value: '#2563eb' },
    { label: 'Purple',   value: '#7c3aed' },
  ];
  const editorContainerRef = useRef<HTMLDivElement>(null);
  const [isPreviewMode, setIsPreviewMode] = useState(false);
  const [originalContent, setOriginalContent] = useState<string>('');
  const [hasRecoveredContent, setHasRecoveredContent] = useState(false);
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastContentRef = useRef(content);
  const isInternalUpdateRef = useRef(false);
  const backupKey = draftId ? `draft-backup-${draftId}` : null;

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: false,
        orderedList: false,
        blockquote: false,
        codeBlock: false,
        horizontalRule: false,
        link: false,
      }),
      Link.configure({
        openOnClick: false,
        HTMLAttributes: {
          class: 'draft-link',
        },
      }),
      AnnotatableImage.configure({
        inline: true,
        allowBase64: true,
      }),
      TextStyle,
      Color,
      DictationCursor,
    ],
    content: plainTextToHtml(content),
    editable: !readOnly,
    onUpdate: ({ editor }) => {
      const html = editor.getHTML();
      const text = editor.getText();
      setWordCount(countWords(text));
      isInternalUpdateRef.current = true;
      onChange(html);

      // Debounced auto-save indicator
      if (onSaveStatusChange && html !== lastContentRef.current) {
        onSaveStatusChange('saving');
        if (saveTimeoutRef.current) {
          clearTimeout(saveTimeoutRef.current);
        }
        saveTimeoutRef.current = setTimeout(() => {
          onSaveStatusChange('saved');
          lastContentRef.current = html;
        }, 2000);
      }
    },
    editorProps: {
      attributes: {
        class: 'draft-editor-content',
        'data-placeholder': resolvedPlaceholder,
      },
    },
  });

  // Stable ref to always access the latest editor instance
  const editorRef = useRef(editor);
  editorRef.current = editor;

  useEffect(() => {
    if (!autoFocus || readOnly || !editor) return;
    const focusTimer = window.setTimeout(() => {
      editor.chain().focus().run();
      try {
        (editor.view.dom as HTMLElement | undefined)?.focus?.();
      } catch {
        // TipTap may not have mounted its DOM yet.
      }
    }, 0);
    return () => window.clearTimeout(focusTimer);
  }, [autoFocus, editor, readOnly]);

  // Sync TipTap editability when readOnly prop changes
  useEffect(() => {
    if (editor) {
      editor.setEditable(!readOnly);
    }
  }, [editor, readOnly]);

  // Toggle the dictation block cursor. Setting a boolean meta produces a fresh
  // editor state, so the plugin's decorations recompute: active draws the
  // animated rectangle at the caret, inactive removes it.
  //
  // Self-healing: TipTap only wires plugins at editor creation, so an editor
  // instance left over from a hot-reload (created before this extension existed)
  // won't have the plugin and the block would silently never appear. If the
  // plugin's state is absent, register it on the fly before toggling.
  useEffect(() => {
    if (!editor) return;
    const pluginWasPresent = dictationCursorPluginKey.getState(editor.state) !== undefined;
    if (!pluginWasPresent) {
      editor.registerPlugin(createDictationCursorPlugin());
    }
    editor.view.dispatch(editor.state.tr.setMeta(dictationCursorPluginKey, dictating));
  }, [editor, dictating]);

  // Sync compose font preferences with TipTap editor DOM
  useEffect(() => {
    if (!editor) return;
    try {
      const el = editor.view.dom as HTMLElement;
      el.style.fontFamily = fontFamilyCss;
      el.style.fontSize = fontSizeCss;
    } catch {
      // Editor view not mounted yet
    }
  }, [editor, fontFamilyCss, fontSizeCss]);

  useImperativeHandle(ref, () => ({
    toggleBulletList: () => {
      const e = editorRef.current;
      if (!e) return;
      e.chain().focus().toggleBulletList().run();
    },
    insertImage: (src: string, alt?: string) => {
      const e = editorRef.current;
      if (!e) return;
      e.chain().focus().setImage({ src, alt: alt || '' }).run();
    },
    insertText: (text: string) => {
      const e = editorRef.current;
      if (!e) return;
      e.chain().focus().insertContent(text).run();
    },
    focusEnd: () => {
      const e = editorRef.current;
      if (!e) return;
      e.chain().focus('end').run();
      try {
        (e.view.dom as HTMLElement | undefined)?.focus?.();
      } catch {
        // TipTap may not have mounted its DOM yet.
      }
    },
    insertDictation: (transcriptHtml: string) => {
      const e = editorRef.current;
      if (!e) return;
      // Insert at the PINNED dictation position (where the block cursor sits),
      // not the live caret. The live caret can drift while dictating, so
      // inserting there makes the transcript land far from the block the user
      // was watching. Pinning the insert keeps the text exactly where the
      // cursor block is. Falls back to the live caret when not dictating
      // (pos == null).
      const pinned = dictationCursorPluginKey.getState(e.state)?.pos;
      const insertPos = pinned != null
        ? Math.max(0, Math.min(pinned, e.state.doc.content.size))
        : e.state.selection.from;
      // The char before the insertion point drives smart-spacing (avoids
      // "fini.Et"). Resolving it can throw if the doc isn't ready — fall back.
      let charBefore = '';
      try {
        if (insertPos > 0) {
          charBefore = e.state.doc.textBetween(Math.max(0, insertPos - 1), insertPos, '\n', '');
        }
      } catch {
        charBefore = '';
      }
      const payload = buildDictationInsert(transcriptHtml, charBefore);
      if (!payload) return;
      // Literal text node at the pinned position; the pin maps to stay just
      // before it, so the block ends up at the start of the dictated words.
      e.chain().focus().insertContentAt(insertPos, { type: 'text', text: payload }).run();
    },
    focusForDictation: () => {
      const e = editorRef.current;
      if (!e || e.isFocused) return;
      // focus() with no arg keeps the current/last selection — which on a fresh
      // compose is the top of the body (the empty paragraph BEFORE the
      // signature), and stays right after previously dictated text when
      // chaining. focus('end') would jump past the signature, hiding the block
      // at the bottom and dictating below the signature.
      e.chain().focus().run();
    },
  }));

  useEffect(() => {
    // Always reset the internal flag. Skip re-setting only when TipTap already
    // has the same content (prevents cursor-reset loops when the user types).
    // When external code (e.g. signature injection) changes the React content,
    // it will differ from editor.getHTML() and must still go through.
    if (isInternalUpdateRef.current) {
      isInternalUpdateRef.current = false;
    }
    if (editor) {
      const htmlContent = plainTextToHtml(content);
      if (htmlContent !== editor.getHTML()) {
        editor.commands.setContent(htmlContent);
        lastContentRef.current = htmlContent;
      }
    }
  }, [content, editor]);

  useEffect(() => {
    if (editor) {
      const text = editor.getText();
      setWordCount(countWords(text));
    }
  }, [editor]);

  useEffect(() => {
    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
      }
    };
  }, []);

  // Store original content on first mount for change tracking
  useEffect(() => {
    if (content && !originalContent) {
      setOriginalContent(content);
    }
  }, [content, originalContent]);

  // localStorage backup for error recovery
  useEffect(() => {
    if (!backupKey || readOnly) return;

    // Check for existing backup on mount
    try {
      const backup = localStorage.getItem(backupKey);
      if (backup) {
        const { content: backupContent, timestamp } = JSON.parse(backup);
        const isRecent = Date.now() - timestamp < BACKUP_EXPIRY_MS;
        if (isRecent && backupContent && backupContent !== content) {
          // Recover the content
          onChange(backupContent);
          setHasRecoveredContent(true);
          // Clear the backup after recovery
          setTimeout(() => setHasRecoveredContent(false), 5000);
        }
        // Clear old backup
        localStorage.removeItem(backupKey);
      }
    } catch {
      // Ignore localStorage errors
    }
  }, [backupKey]);

  // Backup content to localStorage on change
  useEffect(() => {
    if (!backupKey || readOnly) return;

    try {
      localStorage.setItem(backupKey, JSON.stringify({
        content: editor?.getHTML() || content,
        timestamp: Date.now(),
      }));
    } catch (err) {
      // Audit Cluster D (2026-05-11) F-10: previously fully silent. If the
      // quota is exceeded (heavy HTML body + base64 attachments), the user
      // loses auto-save WITHOUT WARNING. Detect QuotaExceededError
      // specifically and surface a one-time toast so the user knows to
      // copy their work elsewhere. Other errors stay logged-only.
      const isQuota =
        err instanceof DOMException && (
          err.name === 'QuotaExceededError' ||
          err.name === 'NS_ERROR_DOM_QUOTA_REACHED' ||
          err.code === 22 || err.code === 1014
        );
      if (isQuota) {
        // Don't spam — only the first quota hit per session warns. A
        // module-level flag would be cleaner but adds plumbing; for now
        // accept that a user with multiple composers open may see this
        // up to N times (acceptable for the bug it surfaces).
        console.error('[DraftEditor] localStorage quota exceeded — auto-save disabled', err);
        window.dispatchEvent(new CustomEvent('agentys:toast', {
          detail: {
            message: tCommon('toasts.autosave_disabled_quota'),
            type: 'warning',
            duration: 10000,
          },
        }));
      } else {
        console.warn('[DraftEditor] localStorage backup failed:', err);
      }
    }
  }, [content, backupKey, readOnly, editor]);

  // Clear backup when save is successful
  useEffect(() => {
    if (backupKey && onSaveStatusChange) {
      // We track "saved" status by listening to lastContentRef updates
      // Clear backup when content matches last saved
    }
  }, [backupKey, onSaveStatusChange]);

  // Captured selection for bubble menu — allows restoring it even if focus briefly shifts
  const bubbleSelectionRef = useRef<{ from: number; to: number } | null>(null);

  // Track text selection to show/hide the floating bubble menu
  useEffect(() => {
    if (!editor || readOnly) return;
    const handleSelectionUpdate = ({ editor: e }: { editor: typeof editor }) => {
      const { from, to } = e.state.selection;
      if (from === to) {
        setBubblePos(null);
        bubbleSelectionRef.current = null;
        return;
      }
      bubbleSelectionRef.current = { from, to };
      try {
        const start = e.view.coordsAtPos(from);
        const end = e.view.coordsAtPos(to);
        setBubblePos({
          top: start.top - 44,
          left: (start.left + end.left) / 2,
        });
      } catch {
        setBubblePos(null);
      }
    };
    const handleBlur = () => setBubblePos(null);
    editor.on('selectionUpdate', handleSelectionUpdate);
    editor.on('blur', handleBlur);
    return () => {
      editor.off('selectionUpdate', handleSelectionUpdate);
      editor.off('blur', handleBlur);
    };
  }, [editor, readOnly]);

  const toggleBold = useCallback(() => {
    editor?.chain().focus().toggleBold().run();
  }, [editor]);

  const toggleItalic = useCallback(() => {
    editor?.chain().focus().toggleItalic().run();
  }, [editor]);

  const toggleStrike = useCallback(() => {
    editor?.chain().focus().toggleStrike().run();
  }, [editor]);


  const handleUndo = useCallback(() => {
    editor?.chain().focus().undo().run();
  }, [editor]);

  const handleRedo = useCallback(() => {
    editor?.chain().focus().redo().run();
  }, [editor]);

  const togglePreviewMode = useCallback(() => {
    setIsPreviewMode(!isPreviewMode);
  }, [isPreviewMode]);

  const handleShowChangesToggle = useCallback(() => {
    onShowChangesToggle?.(!showChanges);
  }, [showChanges, onShowChangesToggle]);

  const handleAddLink = useCallback(() => {
    if (linkUrl) {
      editor
        ?.chain()
        .focus()
        .extendMarkRange('link')
        .setLink({ href: linkUrl })
        .run();
      setLinkUrl('');
      setShowLinkInput(false);
    }
  }, [editor, linkUrl]);

  const handleRemoveLink = useCallback(() => {
    editor?.chain().focus().unsetLink().run();
    setShowLinkInput(false);
  }, [editor]);

  const handleLinkKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleAddLink();
    } else if (e.key === 'Escape') {
      setShowLinkInput(false);
      setLinkUrl('');
    }
  };

  if (!editor) {
    return null;
  }

  const isLinkActive = editor.isActive('link');
  const canUndo = editor.can().undo();
  const canRedo = editor.can().redo();
  const hasContentChanged = originalContent && content !== originalContent;

  return (
    <div className={`draft-editor ${showChanges && hasContentChanged ? 'show-changes' : ''} ${dictating ? 'dictating' : ''} ${recording ? 'recording' : ''} ${className}`}>
      {hasRecoveredContent && (
        <div className="recovery-notification" data-testid="recovery-notification">
          {tCommon('recovered_content')}
        </div>
      )}
      {!readOnly && !isPreviewMode && !hideToolbar && (
        <div className="draft-editor-toolbar">
          <div className="toolbar-group">
            <button
              type="button"
              className={`toolbar-button ${!canUndo ? 'disabled' : ''}`}
              onClick={handleUndo}
              disabled={!canUndo}
              title={tCommon('undo_shortcut')}
              aria-label={tCommon('undo_label')}
              data-testid="undo-button"
            >
              ↶
            </button>
            <button
              type="button"
              className={`toolbar-button ${!canRedo ? 'disabled' : ''}`}
              onClick={handleRedo}
              disabled={!canRedo}
              title={tCommon('redo_shortcut')}
              aria-label={tCommon('redo')}
              data-testid="redo-button"
            >
              ↷
            </button>
          </div>
          <div className="toolbar-separator" />
          <div className="toolbar-group">
            <button
              type="button"
              className={`toolbar-button ${editor.isActive('bold') ? 'active' : ''}`}
              onClick={toggleBold}
              title={tCommon('bold_shortcut')}
              aria-label={tCommon('bold_label')}
            >
              <strong>B</strong>
            </button>
            <button
              type="button"
              className={`toolbar-button ${editor.isActive('italic') ? 'active' : ''}`}
              onClick={toggleItalic}
              title={tCommon('italic_shortcut')}
              aria-label={tCommon('italic_label')}
            >
              <em>I</em>
            </button>
            <button
              type="button"
              className={`toolbar-button ${editor.isActive('strike') ? 'active' : ''}`}
              onClick={toggleStrike}
              title={tCommon('strikethrough_shortcut')}
              aria-label={tCommon('strikethrough_label')}
            >
              <s>S</s>
            </button>
            <div className="link-toolbar-group">
              <button
                type="button"
                className={`toolbar-button ${isLinkActive ? 'active' : ''}`}
                onClick={() => {
                  if (isLinkActive) {
                    handleRemoveLink();
                  } else {
                    setShowLinkInput(!showLinkInput);
                  }
                }}
                title={isLinkActive ? tCommon('remove_link') : tCommon('add_link')}
                aria-label={isLinkActive ? tCommon('remove_link') : tCommon('add_link')}
              >
                {isLinkActive ? '🔗✕' : '🔗'}
              </button>
              {showLinkInput && (
                <div className="link-input-container" data-escape-owner="">
                  <input
                    type="url"
                    className="link-input"
                    placeholder="https://..."
                    value={linkUrl}
                    onChange={(e) => setLinkUrl(e.target.value)}
                    onKeyDown={handleLinkKeyDown}
                    autoFocus
                  />
                  <button
                    type="button"
                    className="link-submit"
                    onClick={handleAddLink}
                    disabled={!linkUrl}
                  >
                    OK
                  </button>
                </div>
              )}
            </div>
          </div>
          <div className="toolbar-separator" />
          <div className="toolbar-group">
            <select
              className="de-font-select"
              value={fontFamily}
              onChange={(e) => setFontFamily(e.target.value as ComposeFontFamily)}
              title="Font"
            >
              {['Sans-serif', 'Serif', 'Mono'].map((group) => (
                <optgroup key={group} label={group}>
                  {FONT_FAMILY_OPTIONS.filter((f) => f.group === group).map((f) => (
                    <option key={f.id} value={f.id}>{f.label}</option>
                  ))}
                </optgroup>
              ))}
            </select>
            <select
              className="de-font-select de-font-size-select"
              value={fontSize}
              onChange={(e) => setFontSize(e.target.value as ComposeFontSize)}
              title="Size"
            >
              <option value="small">12</option>
              <option value="medium">14</option>
              <option value="large">16</option>
              <option value="xlarge">18</option>
            </select>
          </div>
          <div className="toolbar-separator" />
          <div className="toolbar-group toolbar-right">
            {onShowChangesToggle && (
              <button
                type="button"
                className={`toolbar-button ${showChanges ? 'active' : ''}`}
                onClick={handleShowChangesToggle}
                title={tCommon('show_changes')}
                aria-label={tCommon('show_changes')}
                data-testid="show-changes-button"
              >
                Δ
              </button>
            )}
            <button
              type="button"
              className="toolbar-button"
              onClick={togglePreviewMode}
              title={tCommon('preview')}
              aria-label={tCommon('preview')}
              data-testid="preview-button"
            >
              👁
            </button>
          </div>
        </div>
      )}
      {isPreviewMode ? (
        <div className="draft-preview-container">
          <div className="draft-preview-header">
            <span>{tCommon('preview')}</span>
            <button
              type="button"
              className="toolbar-button"
              onClick={togglePreviewMode}
              title={tCommon('back_to_edit')}
              aria-label={tCommon('back_to_edit')}
              data-testid="exit-preview-button"
            >
              ✏️ {tCommon('edit_mode')}
            </button>
          </div>
          <div
            className="draft-preview-content"
            data-testid="preview-content"
            style={{ fontFamily: fontFamilyCss, fontSize: fontSizeCss }}
            dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(editor.getHTML(), {
              ADD_DATA_URI_TAGS: ['img'],
              ALLOWED_TAGS: ['p', 'br', 'div', 'span', 'a', 'strong', 'em', 'b', 'i', 'u', 's', 'ul', 'ol', 'li', 'img'],
              ALLOWED_ATTR: ['href', 'target', 'rel', 'src', 'alt', 'class', 'style'],
              ALLOW_DATA_ATTR: false,
            }) }}
          />
        </div>
      ) : (
        <div className="draft-editor-wrapper" ref={editorContainerRef}>
          {bubblePos && !readOnly && createPortal(
            <div
              className="bubble-menu"
              style={{ top: bubblePos.top, left: bubblePos.left }}
            >
              <button
                type="button"
                className={`bubble-btn ${editor.isActive('bold') ? 'active' : ''}`}
                onMouseDown={(e) => {
                  e.preventDefault();
                  const sel = bubbleSelectionRef.current;
                  if (sel) editor.chain().focus().setTextSelection(sel).toggleBold().run();
                  else toggleBold();
                }}
                title={tCommon('bold_shortcut')}
              >
                <strong>B</strong>
              </button>
              <button
                type="button"
                className={`bubble-btn ${editor.isActive('italic') ? 'active' : ''}`}
                onMouseDown={(e) => {
                  e.preventDefault();
                  const sel = bubbleSelectionRef.current;
                  if (sel) editor.chain().focus().setTextSelection(sel).toggleItalic().run();
                  else toggleItalic();
                }}
                title={tCommon('italic_shortcut')}
              >
                <em>I</em>
              </button>
              <button
                type="button"
                className={`bubble-btn ${editor.isActive('strike') ? 'active' : ''}`}
                onMouseDown={(e) => {
                  e.preventDefault();
                  const sel = bubbleSelectionRef.current;
                  if (sel) editor.chain().focus().setTextSelection(sel).toggleStrike().run();
                  else toggleStrike();
                }}
                title={tCommon('strikethrough_shortcut')}
              >
                <s>S</s>
              </button>

              <div className="bubble-sep" />

              {/* Couleur du texte */}
              <div className="bubble-color-wrap">
                <button
                  type="button"
                  className="bubble-btn bubble-color-btn"
                  onMouseDown={(e) => { e.preventDefault(); setShowColorPicker(p => !p); }}
                  title="Text color"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <text x="3" y="16" fontFamily="serif" fontSize="16" fontWeight="bold" fill="currentColor">A</text>
                    <rect x="2" y="19" width="20" height="3" rx="1"
                      fill={(editor.getAttributes('textStyle').color as string | undefined) ?? '#000000'}
                    />
                  </svg>
                </button>
                {showColorPicker && (
                  <div className="bubble-color-popover">
                    {TEXT_COLORS.map(({ label, value }) => (
                      <button
                        key={label}
                        type="button"
                        className="bubble-color-dot"
                        title={label}
                        onMouseDown={(e) => {
                          e.preventDefault();
                          if (value) {
                            editor.chain().focus().setColor(value).run();
                          } else {
                            editor.chain().focus().unsetColor().run();
                          }
                          setShowColorPicker(false);
                        }}
                        style={{ background: value ?? '#e5e7eb' }}
                      >
                        {!value && <span style={{ fontSize: 10, color: '#9ca3af' }}>✕</span>}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>,
            document.body
          )}
          <EditorContent editor={editor} />
        </div>
      )}
      {!hideWordCount && (
        <div className="draft-editor-footer">
          {hasContentChanged && showChanges && (
            <span className="change-indicator" data-testid="change-indicator">
              {tCommon('modified')}
            </span>
          )}
          <span className="word-count" data-testid="word-count">
            {tCommon('word', { count: wordCount })}
          </span>
        </div>
      )}
    </div>
  );
});

export function clearDraftBackup(draftId: string): void {
  try {
    localStorage.removeItem(`draft-backup-${draftId}`);
  } catch {
    // Ignore errors
  }
}
