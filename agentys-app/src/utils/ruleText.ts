/**
 * The learner persists rules whose text already embeds the recipient as a
 * trailing "pour <email>" / "for <email>" clause (FR/EN backend strings).
 * That same recipient is also meant to live in `item.contact` + `item.scope`,
 * so the suffix is a duplicate that bloats every row and reads as "and finally,
 * for X" instead of "this rule applies to X".
 *
 * Strip the suffix on render so the row text reads cleanly, and surface the
 * extracted email as a fallback when the backend forgot to populate the
 * scoped fields. Backend follow-up: stop appending the suffix on persist.
 */
const RULE_TEXT_CONTACT_SUFFIX_RE =
  /[\s.]+(?:pour|for)\s+([\w.+-]+@[\w.-]+\.[A-Za-z]{2,})\.?\s*$/i;

export function extractContactFromRuleText(text: string): {
  stripped: string;
  email: string | null;
} {
  const m = text.match(RULE_TEXT_CONTACT_SUFFIX_RE);
  if (!m || m.index == null) return { stripped: text, email: null };
  return { stripped: text.slice(0, m.index).trimEnd(), email: m[1] };
}
