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
