import { describe, it, expect } from 'vitest'
import { snippetContentToInsertionHtml } from './snippetInsertion'

describe('snippetContentToInsertionHtml', () => {
  // Regression (2026-06-01): inserting a user-created snippet showed doubled
  // line spacing. Snippets are stored as RichTextEditor HTML, but the compose
  // inserter wrapped the whole blob in <p>, so TipTap re-parsed the nested
  // <div>s into extra empty paragraphs. The fix: HTML content is inserted
  // verbatim, never re-wrapped.

  // Regression (2026-06-09): even inserted verbatim, a blank line stored as
  // <div><br></div> still doubled — TipTap parses the contenteditable
  // placeholder <br> as a real hardBreak AND appends its own trailing break
  // (2 line heights). Blank-line divs must become <p></p> (TipTap's blank
  // line, 1 line height; a bare empty <div> would be dropped entirely), and
  // a trailing placeholder <br> after text must be removed.

  it('converts blank-line <div><br></div> to <p></p> (no doubling, no drop)', () => {
    expect(snippetContentToInsertionHtml('<div>A</div><div><br></div><div>B</div>'))
      .toBe('<div>A</div><p></p><div>B</div>')
  })

  it('normalizes blank lines in HTML that has newlines between block tags', () => {
    expect(snippetContentToInsertionHtml('<div>A</div>\n<div><br></div>\n<div>B</div>'))
      .toBe('<div>A</div>\n<p></p>\n<div>B</div>')
  })

  it('drops a trailing placeholder <br> after text (renders 1 line, not 2)', () => {
    expect(snippetContentToInsertionHtml('<div>A<br></div><div>B</div>'))
      .toBe('<div>A</div><div>B</div>')
  })

  it('keeps N-1 <br> for multi-br blank divs (contenteditable: N brs = N lines)', () => {
    expect(snippetContentToInsertionHtml('<div>A</div><div><br><br></div><div>B</div>'))
      .toBe('<div>A</div><div><br></div><div>B</div>')
  })

  it('unwraps a formatting-wrapped placeholder (<div><b><br></b></div>)', () => {
    expect(snippetContentToInsertionHtml('<div>A</div><div><b><br></b></div><div>B</div>'))
      .toBe('<div>A</div><p></p><div>B</div>')
  })

  it('does not touch divs whose only content is a non-br element (e.g. <img>)', () => {
    const html = '<div><img src="x.png"></div><div>B</div>'
    expect(snippetContentToInsertionHtml(html)).toBe(html)
  })

  it('does not introduce any <p> wrapper around HTML content', () => {
    const html = "Bonjour Nathansok,<div><br></div><div>Voici ma facture : XXX</div>" +
      "<div><br></div><div>Date :</div><div>Alexandre Simon</div>"
    const out = snippetContentToInsertionHtml(html)
    expect(out).toBe(
      'Bonjour Nathansok,<p></p><div>Voici ma facture : XXX</div>' +
      '<p></p><div>Date :</div><div>Alexandre Simon</div>'
    )
    expect(out).not.toMatch(/^<p>Bonjour/)
  })

  it('keeps {token} placeholder text and chip spans intact', () => {
    expect(snippetContentToInsertionHtml('Bonjour {first_name},<div><br></div><div>Voici…</div>'))
      .toBe('Bonjour {first_name},<p></p><div>Voici…</div>')
    const chip = '<div><span data-ar-token="first_name">Prénom</span></div><div><br></div>'
    expect(snippetContentToInsertionHtml(chip))
      .toBe('<div><span data-ar-token="first_name">Prénom</span></div><p></p>')
  })

  it('still wraps legacy plain text: blank lines → paragraphs, single newline → <br>', () => {
    expect(snippetContentToInsertionHtml('A\n\nB')).toBe('<p>A</p><p>B</p>')
    expect(snippetContentToInsertionHtml('A\nB')).toBe('<p>A<br>B</p>')
    expect(snippetContentToInsertionHtml('Just one line')).toBe('<p>Just one line</p>')
  })

  it('returns empty string for empty content', () => {
    expect(snippetContentToInsertionHtml('')).toBe('')
  })
})
