// Shared helpers for the `{x}` "champs dynamiques" placeholder chips used by
// the RichTextEditor placeholder menu (auto-reply, snippets, quick steps).
//
// A chip is a styled, atomic span carrying the resolvable token in
// `data-ar-token` while showing a friendly label:
//   <span class="ar-token" data-ar-token="sender.firstname"
//         contenteditable="false">Prénom expéditeur</span>
//
// The existing token resolvers all work on plain `{token}` text, so before
// resolution the caller converts chips back to `{token}` via `chipsToTokens`.

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/** Build a placeholder chip whose visible text is `label` and whose token is
 *  `token` (e.g. `first_name`, `sender.firstname`). A trailing space lets the
 *  caret continue after the atomic chip. */
export function buildTokenChipHtml(token: string, label: string): string {
  return (
    `<span class="ar-token" data-ar-token="${escapeHtml(token)}" ` +
    `contenteditable="false">${escapeHtml(label)}</span>&nbsp;`
  )
}

// Matches a chip span and captures its token. Non-greedy body, dot-all so a
// label can't span past its own </span>.
const CHIP_SPAN_RE = /<span\b[^>]*\bdata-ar-token="([^"]+)"[^>]*>.*?<\/span>/gis

/** Replace every placeholder chip with its plain `{token}` form so downstream
 *  resolvers (`replaceSnippetVariables`, the quick-step template renderer) can
 *  substitute it. No-op when the HTML contains no chips. */
export function chipsToTokens(html: string): string {
  if (!html || !html.includes('data-ar-token=')) return html
  return html.replace(CHIP_SPAN_RE, (_m, token) => `{${token}}`)
}
