/**
 * Helpers for normalising an AI-generated draft body before it is shown in the
 * editable composer. Because the composer seeds the outgoing email from this
 * result, anything dropped here is also dropped from what gets SENT — so the
 * cleaning has to be conservative. Extracted from PendingDraftDetail so the
 * logic can be unit-tested in isolation.
 */

/** Convert simple draft HTML to text, preserving paragraph breaks. */
export function stripHtmlTags(html: string): string {
  return html
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>/gi, '\n')
    .replace(/<\/div>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

/**
 * Strips ONLY the leading metadata lines an AI draft sometimes emits
 * ("Objet: …", "Subject: …", "Re: …") before the real reply begins, stopping
 * at the first line of actual content.
 *
 * Previously this filtered such lines ANYWHERE in the body, which silently
 * deleted legitimate content — e.g. a reply paragraph beginning "Re: ton point
 * d'hier" or "Subject: Q3 budget" vanished — and because the composer seeds
 * `editedBody` from the result, that content disappeared from the SENT email
 * too. Anchoring the strip to the top of the body fixes that while still
 * removing the AI's subject-echo preamble.
 */
export function cleanDraftBody(body: string | undefined | null): string {
  if (!body) return '';
  const cleaned = /<[a-z][\s\S]*>/i.test(body) ? stripHtmlTags(body) : body;
  const lines = cleaned.split('\n');
  const isLeadingHeaderLine = (line: string): boolean => {
    const trimmed = line.trim().toLowerCase();
    return trimmed.startsWith('objet :') ||
           trimmed.startsWith('objet:') ||
           trimmed.startsWith('subject :') ||
           trimmed.startsWith('subject:') ||
           trimmed.startsWith('re:');
  };
  let start = 0;
  // Drop blank + header lines from the top, but bail out the moment we reach
  // the first real content line so mid-body "Re:" / "Subject:" lines survive.
  while (start < lines.length) {
    const trimmed = lines[start].trim();
    if (trimmed === '' || isLeadingHeaderLine(lines[start])) {
      start++;
    } else {
      break;
    }
  }
  return lines.slice(start).join('\n');
}
