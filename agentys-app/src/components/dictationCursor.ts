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

import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

/**
 * Block-cursor decoration shown while the user is dictating.
 *
 * Speech-to-text streams partial text in as you talk, firing a transaction per
 * partial — and ProseMirror recreates this widget's DOM on each one (dozens of
 * times a second). A naive CSS animation would restart from 0% on every rebuild
 * and look frozen while you speak. So we PIN the position (the live caret drifts
 * during streaming; the block must stay put and the transcript inserts here) AND
 * sync the breathe animation to a fixed start time via a negative
 * `animation-delay`, so each freshly-rebuilt element resumes at the correct
 * phase and the pulse looks continuous. The editor hides the native thin caret
 * via the `.dictating` class so only this block shows.
 *
 * Toggle it by dispatching a boolean meta on {@link dictationCursorPluginKey}:
 *   editor.view.dispatch(editor.state.tr.setMeta(dictationCursorPluginKey, true))
 */
export interface DictationCursorState {
  active: boolean
  /** Caret position frozen when dictation started (document coords). */
  pos: number | null
  /** Date.now() when dictation started — anchors the breathe animation phase. */
  startedAt: number | null
}

export const dictationCursorPluginKey = new PluginKey<DictationCursorState>('dictationCursor')

/** Breathe cycle length in seconds — must match the `dictation-cursor-breathe` keyframe duration. */
const BREATHE_DURATION_S = 1.15

/**
 * Negative `animation-delay` that resumes the breathe at the correct phase for a
 * given elapsed time. The cursor widget is rebuilt many times/sec during
 * streaming dictation; applying this to each rebuilt element makes it pick up
 * mid-cycle instead of restarting from 0% (which looked frozen while speaking).
 * Exported for unit testing.
 */
export function breatheDelay(elapsedMs: number): string {
  const elapsed = Math.max(0, elapsedMs) / 1000
  return `-${(elapsed % BREATHE_DURATION_S).toFixed(3)}s`
}

/**
 * The raw ProseMirror plugin. Exposed separately from the extension so it can be
 * `editor.registerPlugin()`-ed onto an editor instance that was created before
 * this extension existed (e.g. after a hot-reload) — TipTap only wires
 * extensions at editor creation, so without this the block never appears until a
 * full reload.
 */
export function createDictationCursorPlugin(): Plugin<DictationCursorState> {
  return new Plugin<DictationCursorState>({
    key: dictationCursorPluginKey,
    state: {
      init: () => ({ active: false, pos: null, startedAt: null }),
      apply: (tr, value) => {
        const meta = tr.getMeta(dictationCursorPluginKey)
        if (typeof meta === 'boolean') {
          // Freeze the caret at the instant dictation starts; the block renders
          // at THIS fixed position, never the live selection — so streaming
          // transcription advancing the real caret can't drag it around.
          return meta
            ? { active: true, pos: tr.selection.from, startedAt: Date.now() }
            : { active: false, pos: null, startedAt: null }
        }
        // Keep the frozen position valid across doc edits, biased to stay BEFORE
        // inserted text so appended words don't push the block along.
        if (value.active && value.pos != null && tr.docChanged) {
          return { ...value, pos: tr.mapping.map(value.pos, -1) }
        }
        return value
      },
    },
    props: {
      decorations(state) {
        const s = dictationCursorPluginKey.getState(state)
        if (!s || !s.active || s.pos == null) return null
        const pos = Math.max(0, Math.min(s.pos, state.doc.content.size))
        const startedAt = s.startedAt
        const widget = Decoration.widget(
          pos,
          () => {
            const el = document.createElement('span')
            el.className = 'dictation-cursor'
            el.setAttribute('aria-hidden', 'true')
            // Resume the breathe at the right phase even though this element is
            // rebuilt many times per second during streaming dictation. Without
            // this, every rebuild restarts the animation and it looks frozen.
            if (startedAt != null) {
              el.style.animationDelay = breatheDelay(Date.now() - startedAt)
            }
            return el
          },
          { side: -1, key: 'dictation-cursor' },
        )
        return DecorationSet.create(state.doc, [widget])
      },
    },
  })
}

export const DictationCursor = Extension.create({
  name: 'dictationCursor',
  addProseMirrorPlugins() {
    return [createDictationCursorPlugin()]
  },
})
