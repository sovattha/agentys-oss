// Régression (2026-06-09) : un interligne d'un snippet devenait DEUX
// interlignes après insertion dans le compose. Les snippets sont stockés en
// HTML contenteditable (ligne vide = <div><br></div>, le <br> final est un
// placeholder de caret qui ne rend AUCUNE ligne) ; TipTap parse chaque <br>
// en hardBreak réel PUIS ajoute son propre trailing break → +1 ligne par div
// finissant en <br>. Ce test d'intégration pin le rendu du VRAI éditeur
// TipTap (même stack que DraftEditor) après normalisation.
import { describe, it, expect } from 'vitest'
import { Editor } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'
import { snippetContentToInsertionHtml } from './snippetInsertion'

function renderInTipTap(content: string): { lineHeights: number; viewHtml: string } {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const editor = new Editor({ element: el, extensions: [StarterKit], content })
  const viewHtml = editor.view.dom.innerHTML
  // Hauteurs de ligne rendues = paragraphes + <br> NON-placeholder.
  // Un <p> vide rend 1 ligne via son unique trailingBreak ; un hardBreak readl
  // suivi du trailingBreak rend 2 lignes — compter chaque <br> réel + 1 par <p>.
  const dom = editor.view.dom
  let lines = 0
  for (const p of Array.from(dom.querySelectorAll('p'))) {
    lines += 1 + p.querySelectorAll('br:not(.ProseMirror-trailingBreak)').length
  }
  editor.destroy()
  el.remove()
  return { lineHeights: lines, viewHtml }
}

describe('snippet → TipTap insert: blank lines render single-height', () => {
  it('the reported snippet (2 blank lines) renders 6 lines, not 8', () => {
    // facture 1 / date : / (vide) / Merci / (vide) / À bientôt = 6 lignes.
    const stored =
      '<div>facture 1</div><div>date :</div><div><br></div><div>Merci</div><div><br></div><div>À bientôt</div>'
    const before = renderInTipTap(stored)
    expect(before.lineHeights).toBe(8) // le bug : 2 lignes fantômes

    const after = renderInTipTap(snippetContentToInsertionHtml(stored))
    expect(after.lineHeights).toBe(6) // fixé : 1 interligne = 1 ligne
  })

  it('blank lines survive (empty <p> is kept by TipTap, empty <div> would be dropped)', () => {
    const { viewHtml } = renderInTipTap(
      snippetContentToInsertionHtml('<div>A</div><div><br></div><div>B</div>')
    )
    expect(viewHtml).toBe(
      '<p>A</p><p><br class="ProseMirror-trailingBreak"></p><p>B</p>'
    )
  })

  it('trailing placeholder <br> after text does not add a line', () => {
    const { lineHeights } = renderInTipTap(
      snippetContentToInsertionHtml('<div>A<br></div><div>B</div>')
    )
    expect(lineHeights).toBe(2)
  })
})
