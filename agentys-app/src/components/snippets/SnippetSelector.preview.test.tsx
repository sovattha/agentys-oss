import { render } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { SnippetSelector } from './SnippetSelector'
import type { Snippet } from '../../types/snippets'

// i18n is initialised to `fr` by src/__tests__/setup.ts.
//
// Regression: snippet content is persisted as RichTextEditor HTML — a
// `{first_name}` token pill span plus <div>/<br> structure. The preview row
// used to render that string verbatim, so the user saw raw markup
// (`<span class="ar-token" data-ar-token="first_name"...`) instead of text.

const CHIP_HTML =
  'Bonjour <span class="ar-token" data-ar-token="first_name" contenteditable="false">First name</span>,' +
  '<div><br></div><div>Voici ma facture en pièce jointe.</div>'

function makeSnippet(content: string): Snippet {
  return {
    id: 's1',
    name: 'facturation',
    content,
    is_private: true,
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
    use_count: 0,
  }
}

function renderSelector(content: string) {
  return render(
    <SnippetSelector
      isOpen
      onClose={vi.fn()}
      snippets={[makeSnippet(content)]}
      onSelect={vi.fn()}
      onCreateNew={vi.fn()}
    />,
  )
}

describe('SnippetSelector — preview never leaks raw HTML', () => {
  it('strips chip/markup HTML to clean text and keeps {token} as a highlighted chip', () => {
    const { container } = renderSelector(CHIP_HTML)

    const preview = container.querySelector('.snippet-item-preview')
    expect(preview).toBeInTheDocument()

    // The regression — none of the raw markup may survive as text.
    expect(preview!.textContent).not.toContain('ar-token')
    expect(preview!.textContent).not.toContain('data-ar-token')
    expect(preview!.textContent).not.toContain('<span')
    expect(preview!.textContent).not.toContain('<div')

    // Clean, readable preview with the token in its {…} form.
    expect(preview!.textContent).toBe('Bonjour {first_name}, Voici ma facture en pièce jointe.')

    // The token is highlighted as a chip, not rendered as plain text.
    const chip = preview!.querySelector('.snippet-var-chip')
    expect(chip).toBeInTheDocument()
    expect(chip!.textContent).toBe('{first_name}')
  })

  it('leaves a plain-text snippet (no token) unchanged and uses no chip', () => {
    const { container } = renderSelector('Merci pour votre message, je reviens vers vous.')

    const preview = container.querySelector('.snippet-item-preview')
    expect(preview!.textContent).toBe('Merci pour votre message, je reviens vers vous.')
    expect(preview!.querySelector('.snippet-var-chip')).toBeNull()
  })
})
