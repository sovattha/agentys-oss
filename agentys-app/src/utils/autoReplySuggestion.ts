// Shared helpers for the auto-reply "suggested message" pre-fill.
//
// When the auto-reply Message editor is opened empty, we drop in a localized,
// fully editable starter so the user isn't staring at a blank box. The pieces
// live here (rather than inline in AutoReplyModal) so the blank-detection that
// GATES the pre-fill and the chip-attribute it scans for can't drift apart,
// and so both can be unit-tested without rendering the modal.

// Dynamic-field chips carry this attribute (see AutoReplyModal `buildChipHtml`).
// A chip counts as real content, so the editor isn't "blank" once one is present.
export const AR_TOKEN_ATTR = 'data-ar-token';

/**
 * True when the message HTML holds no visible text AND no dynamic-field chip —
 * i.e. the editor is effectively empty and safe to pre-fill. Treats `&nbsp;`
 * and the various empty-contenteditable shapes (`<br>`, `<div><br></div>`,
 * `<p></p>`) as blank — `String.prototype.trim` strips the U+00A0 that
 * `&nbsp;` decodes to, since it counts as ECMAScript whitespace.
 */
export function isBlankAutoReplyMessage(html: string): boolean {
  if (!html) return true;
  // SSR / non-DOM fallback: strip tags + entities and check for leftover text.
  if (typeof document === 'undefined') {
    return html.replace(/<[^>]*>/g, '').replace(/&nbsp;/gi, '').trim() === '';
  }
  const tmp = document.createElement('div');
  tmp.innerHTML = html;
  if (tmp.querySelector(`[${AR_TOKEN_ATTR}]`)) return false;
  return (tmp.textContent ?? '').trim() === '';
}

// Minimal shape of i18next's `t` that this builder needs. Kept loose so the
// real react-i18next `TFunction` is assignable without ceremony.
type Translate = (key: string, options: Record<string, unknown>) => string;

/**
 * The localized "suggested message", with the absence-period chip spliced in
 * at the `{{period}}` marker. Interpolation escaping is disabled because the
 * only injected value is our own chip markup (its dynamic text is already
 * escaped inside `buildChipHtml`) — escaping it would render the chip as
 * literal `&lt;span&gt;…`. Falls back to French to match the auto-reply
 * modal's `fallbackLng`.
 */
export function buildAutoReplySuggestionHtml(t: Translate, periodChipHtml: string): string {
  return t('auto_reply_message_suggestion', {
    defaultValue:
      'Bonjour,<br><br>Merci pour votre message. Je suis actuellement absent(e) {{period}} et vous répondrai dès mon retour.<br><br>Cordialement,',
    period: periodChipHtml,
    interpolation: { escapeValue: false },
  });
}

// Chip text is neutralized to this sentinel before comparing: the absence chip
// rewrites itself with live dates, so its inner text can never participate in
// the "is this still our pristine starter?" decision. Distinctive on purpose:
// a message whose chip was DELETED by the user must not fingerprint-match a
// pristine candidate (removing the chip is an edit we must preserve).
const CHIP_SENTINEL = '[[ar-chip]]';

/**
 * Markup/whitespace-insensitive fingerprint of an auto-reply message.
 *
 * Used to decide whether a SAVED message is still the pristine pre-filled
 * suggestion (bug Karine 2026-06-09: the starter is auto-persisted on first
 * open, so it froze in that day's language — and, for messages saved before
 * 4be7990e, with the legacy trailing `&nbsp;` the chip used to carry). Two
 * messages fingerprint equal when their visible text matches once:
 *  - every `data-ar-token` chip's inner text is replaced by a sentinel
 *    (dates vs placeholder label vs language must not matter),
 *  - markup is ignored (contenteditable freely rewrites <br> into <div>s),
 *  - all whitespace runs (incl. `&nbsp;`) collapse to single spaces.
 */
export function suggestionFingerprint(html: string): string {
  if (!html) return '';
  if (typeof document === 'undefined') {
    // SSR / non-DOM fallback: regex-neutralize chips, then strip tags.
    return html
      .replace(new RegExp(`<span\\b[^>]*${AR_TOKEN_ATTR}="[^"]*"[^>]*>[\\s\\S]*?<\\/span>`, 'gi'), CHIP_SENTINEL)
      .replace(/<[^>]*>/g, ' ')
      .replace(/&nbsp;/gi, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }
  const tmp = document.createElement('div');
  tmp.innerHTML = html;
  tmp.querySelectorAll(`[${AR_TOKEN_ATTR}]`).forEach((chip) => {
    chip.textContent = CHIP_SENTINEL;
  });
  return (tmp.textContent ?? '')
    .replace(/\u00a0/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * True when `savedHtml` is a pristine (unedited) suggestion — i.e. its
 * fingerprint matches one of the `candidates` (the suggestion built in each
 * supported language). Any user edit to the body text breaks the match, so
 * relocalization can never clobber real user content.
 */
export function matchesAnySuggestionFingerprint(savedHtml: string, candidates: string[]): boolean {
  const saved = suggestionFingerprint(savedHtml);
  if (!saved) return false;
  return candidates.some((candidate) => suggestionFingerprint(candidate) === saved);
}
