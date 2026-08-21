/**
 * Convert a snippet's stored content into the HTML to splice into the compose
 * body.
 *
 * Snippets are persisted as RichTextEditor HTML (`<div>`/`<br>` blocks plus
 * `{token}` placeholder pills) since the placeholder-chips migration. The
 * compose body is a TipTap/ProseMirror editor.
 *
 * The trap this guards: passing already-HTML content through the plain-text
 * path (`split('\n\n')` → `<p>…</p>`) double-wraps its block structure. TipTap
 * then re-parses the nested `<div>`s and emits an extra empty paragraph per
 * block boundary — and for content with newlines between tags it multiplies
 * them — which the user sees as doubled line spacing on insert.
 *
 * So: if the content is already HTML, insert it as-is and let TipTap parse its
 * native block structure. Only genuinely plain-text (legacy) snippets get the
 * `\n\n` → paragraph / `\n` → `<br>` conversion. This mirrors the existing
 * `plainTextToHtml` guards in `RichTextEditor` and `DraftEditor`.
 */
export function snippetContentToInsertionHtml(content: string): string {
  if (!content) return ''
  // Already HTML (tag present) → keep the block structure, but translate the
  // contenteditable placeholder-<br> convention into TipTap's (see below).
  if (/<[a-z][\s\S]*>/i.test(content)) return normalizePlaceholderBreaks(content)
  // Legacy plain text → paragraphs on blank lines, <br> on single newlines.
  return content
    .split(/\n\n+/)
    .map((p) => `<p>${p.split('\n').join('<br>')}</p>`)
    .join('')
}

/**
 * Translate contenteditable's placeholder-<br> convention into TipTap's.
 *
 * In a contenteditable (RichTextEditor), a trailing <br> in a <div> is a
 * caret placeholder that renders NO extra line — a blank line is stored as
 * `<div><br></div>` and renders one line high. TipTap instead parses every
 * <br> as a real hardBreak AND appends its own trailing-break placeholder,
 * so each div ending in <br> gains one line on insert (the "one blank line
 * becomes two" bug).
 *
 * Rule: drop ONE trailing <br> per <div>; a div left empty becomes `<p></p>`
 * (TipTap's own blank-line form — an empty <div> would be dropped entirely,
 * losing the blank line).
 */
function normalizePlaceholderBreaks(html: string): string {
  const tpl = document.createElement('template')
  tpl.innerHTML = html
  for (const div of Array.from(tpl.content.querySelectorAll('div'))) {
    // Last meaningful node, skipping whitespace-only text.
    let last: ChildNode | null = div.lastChild
    while (last && last.nodeType === Node.TEXT_NODE && !last.textContent?.trim()) {
      last = last.previousSibling
    }
    if (last && last.nodeName === 'BR') {
      last.remove()
    } else if (!div.textContent?.trim() && div.querySelectorAll('br').length === 1) {
      // Placeholder wrapped in formatting (e.g. <div><b><br></b></div>):
      // remove the <br> and the now-empty inline wrappers around it.
      let node: ChildNode | null = div.querySelector('br')
      while (node && node !== div) {
        const parent: HTMLElement | null = node.parentElement
        node.remove()
        node = parent && parent !== div && !parent.hasChildNodes() ? parent : null
      }
    }
    // Empty after placeholder removal (no text, no remaining elements like
    // <img>) → explicit empty paragraph so TipTap keeps the blank line.
    if (!div.textContent?.trim() && !div.firstElementChild) {
      div.replaceWith(document.createElement('p'))
    }
  }
  return tpl.innerHTML
}
