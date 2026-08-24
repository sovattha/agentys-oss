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

import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, waitFor, cleanup } from '@testing-library/react'
import { DraftEditor } from './DraftEditor'

/**
 * End-to-end wiring check: renders the REAL DraftEditor (this file deliberately
 * does NOT mock @tiptap/react, unlike DraftEditor.test.tsx) and proves the full
 * path the live app uses — `dictating` prop → useEffect → setMeta dispatch →
 * plugin decoration → a `.dictation-cursor` node in the rendered DOM.
 *
 * If this passes, the block-cursor feature works in a real editor and any
 * remaining "I see nothing" is a stale/hot-reloaded webview, not the code.
 */
describe('DraftEditor block cursor — full React wiring', () => {
  afterEach(() => cleanup())

  it('renders the block cursor in the DOM when dictating (empty body)', async () => {
    render(
      <DraftEditor content="<p></p>" onChange={vi.fn()} dictating hideToolbar hideWordCount />,
    )
    await waitFor(
      () => expect(document.querySelector('.dictation-cursor')).not.toBeNull(),
      { timeout: 3000 },
    )
  })

  it('does NOT render the block cursor when not dictating', async () => {
    render(
      <DraftEditor content="<p>bonjour</p>" onChange={vi.fn()} hideToolbar hideWordCount />,
    )
    // Wait for the real editor to mount, then assert the block is absent.
    await waitFor(() => expect(document.querySelector('.ProseMirror, .draft-editor-content')).not.toBeNull())
    expect(document.querySelector('.dictation-cursor')).toBeNull()
  })
})
