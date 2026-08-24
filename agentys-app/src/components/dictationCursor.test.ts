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

import { describe, it, expect, afterEach } from 'vitest'
import { Editor } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'
import { DictationCursor, dictationCursorPluginKey, createDictationCursorPlugin, breatheDelay } from './dictationCursor'

/**
 * Integration check on a REAL TipTap editor (this file deliberately does NOT
 * mock @tiptap/react, unlike DraftEditor.test.tsx) — proves the widget
 * decoration actually renders a `.dictation-cursor` node into the editor DOM
 * when toggled, and disappears when toggled off.
 */
describe('DictationCursor decoration', () => {
  let editor: Editor | null = null

  afterEach(() => {
    editor?.destroy()
    editor = null
  })

  function makeEditor() {
    return new Editor({
      element: document.createElement('div'),
      extensions: [StarterKit, DictationCursor],
      content: '<p>hello</p>',
    })
  }

  it('renders no block cursor by default', () => {
    editor = makeEditor()
    expect(editor.view.dom.querySelector('.dictation-cursor')).toBeNull()
  })

  it('renders the block cursor when activated via meta', () => {
    editor = makeEditor()
    editor.view.dispatch(editor.state.tr.setMeta(dictationCursorPluginKey, true))
    expect(editor.view.dom.querySelector('.dictation-cursor')).not.toBeNull()
  })

  it('removes the block cursor when deactivated', () => {
    editor = makeEditor()
    editor.view.dispatch(editor.state.tr.setMeta(dictationCursorPluginKey, true))
    expect(editor.view.dom.querySelector('.dictation-cursor')).not.toBeNull()
    editor.view.dispatch(editor.state.tr.setMeta(dictationCursorPluginKey, false))
    expect(editor.view.dom.querySelector('.dictation-cursor')).toBeNull()
  })

  it('renders the block cursor in an EMPTY editor (first dictation on a blank body)', () => {
    editor = new Editor({
      element: document.createElement('div'),
      extensions: [StarterKit, DictationCursor],
      content: '<p></p>',
    })
    editor.view.dispatch(editor.state.tr.setMeta(dictationCursorPluginKey, true))
    expect(editor.view.dom.querySelector('.dictation-cursor')).not.toBeNull()
  })

  it('PINS the block at the start position even as the caret advances (streaming transcription)', () => {
    editor = new Editor({
      element: document.createElement('div'),
      extensions: [StarterKit, DictationCursor],
      content: '<p></p>',
    })
    // Dictation starts: pin at the current caret (pos 1 in an empty doc).
    editor.view.dispatch(editor.state.tr.setMeta(dictationCursorPluginKey, true))
    expect(dictationCursorPluginKey.getState(editor.state)?.pos).toBe(1)

    // Simulate Deepgram streaming words in — this advances the REAL caret.
    editor.commands.insertContent('Bonjour Marc, comment ça va aujourd’hui')
    expect(editor.state.selection.from).toBeGreaterThan(10)

    // The pinned block must NOT have followed the caret — it stays at the start.
    expect(dictationCursorPluginKey.getState(editor.state)?.pos).toBe(1)
    expect(editor.view.dom.querySelector('.dictation-cursor')).not.toBeNull()
  })

  it('applies a synced animation-delay to the rendered cursor (phase anchor)', () => {
    editor = new Editor({
      element: document.createElement('div'),
      extensions: [StarterKit, DictationCursor],
      content: '<p>hi</p>',
    })
    editor.view.dispatch(editor.state.tr.setMeta(dictationCursorPluginKey, true))
    const el = editor.view.dom.querySelector('.dictation-cursor') as HTMLElement | null
    expect(el).not.toBeNull()
    // At dictation start elapsed≈0 → '-0.000s' (browser normalises to '0s'); the
    // point is the property is being managed at all. The phase math is asserted
    // below in the breatheDelay unit test.
    expect(el!.style.animationDelay).toMatch(/s$/)
  })

  it('breatheDelay phase-syncs the breathe so per-frame widget rebuilds resume mid-cycle', () => {
    // Streaming STT recreates the widget dozens of times/sec; each rebuilt
    // element must resume at the right phase, not restart the cycle from 0%.
    expect(breatheDelay(0)).toBe('-0.000s')
    expect(breatheDelay(500)).toBe('-0.500s')
    expect(breatheDelay(1150)).toBe('-0.000s')  // exactly one cycle → phase 0
    expect(breatheDelay(2000)).toBe('-0.850s')  // 2.0s into a 1.15s cycle
    expect(breatheDelay(-5)).toBe('-0.000s')    // guards against negative elapsed
  })

  it('inserting at the pinned pos lands text at the start even when the caret drifted to the end', () => {
    editor = new Editor({
      element: document.createElement('div'),
      extensions: [StarterKit, DictationCursor],
      content: '<p>existing</p>',
    })
    // Pin at the start (this is what dictation start captures).
    editor.commands.setTextSelection(1)
    editor.view.dispatch(editor.state.tr.setMeta(dictationCursorPluginKey, true))
    const pinned = dictationCursorPluginKey.getState(editor.state)?.pos
    expect(pinned).toBe(1)

    // The live caret drifts to the end (what happens mid-dictation).
    editor.commands.focus('end')
    expect(editor.state.selection.from).toBeGreaterThan(1)

    // insertDictation inserts at the PINNED pos, not the live (drifted) caret.
    editor.chain().focus().insertContentAt(pinned!, { type: 'text', text: 'NEW ' }).run()

    // The dictated text landed at the START, not appended at the drifted caret.
    expect(editor.getText().startsWith('NEW ')).toBe(true)
  })

  it('self-heals: can be registered onto an editor created WITHOUT the extension (hot-reload case)', () => {
    // Simulate a stale, hot-reloaded editor that never got the extension.
    editor = new Editor({
      element: document.createElement('div'),
      extensions: [StarterKit],
      content: '<p>hello</p>',
    })
    expect(dictationCursorPluginKey.getState(editor.state)).toBeUndefined()
    expect(editor.view.dom.querySelector('.dictation-cursor')).toBeNull()

    // This is exactly what DraftEditor's effect does when the plugin is absent.
    editor.registerPlugin(createDictationCursorPlugin())
    editor.view.dispatch(editor.state.tr.setMeta(dictationCursorPluginKey, true))

    expect(dictationCursorPluginKey.getState(editor.state)?.active).toBe(true)
    expect(editor.view.dom.querySelector('.dictation-cursor')).not.toBeNull()
  })
})
