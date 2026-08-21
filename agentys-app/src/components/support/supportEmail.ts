/**
 * supportEmail.ts — Pure builder for support emails.
 *
 * Kept separate from SupportChat so the rules are unit-testable in isolation:
 * no React, no i18n side effects, no closures. Whatever lives in the body
 * here ships verbatim to the support inbox, so this file is the single source
 * of truth for what we send.
 */

const SUBJECT_MAX_DESC_LEN = 30

export interface SupportEmailInput {
  /** User's free-text description. Required (caller validates non-empty). */
  description: string
  /** Account address the support team replies to. */
  accountEmail: string
  /** Client-generated reference (subject suffix + signature line). */
  ticketRef: string
  /** Localized signature line (e.g. "Sent from Agentys"). */
  signature: string
}

export interface SupportEmail {
  subject: string
  body: string
}

/**
 * Build the support email's subject + body from a user description.
 *
 * - Subject: `[Support] {first ~30 chars of description} - {ticketRef}`
 * - Body  : the user's description + a single signature line.
 *
 * Important: the body deliberately contains *only* the user's text and a
 * minimal signature. It must NEVER include chatbot rule responses, FR/EN
 * scaffolding (`Type: Support client`, `Référence:`, `Date:`), or any other
 * generated context — those leak into the customer's outbox and erode trust.
 */
export function buildSupportEmail({
  description,
  accountEmail,
  ticketRef,
  signature,
}: SupportEmailInput): SupportEmail {
  const cleaned = description.replace(/\s+/g, ' ').trim()
  const words = cleaned.split(' ').filter(Boolean)

  let shortDesc = ''
  for (const w of words) {
    const next = shortDesc ? `${shortDesc} ${w}` : w
    if (next.length > SUBJECT_MAX_DESC_LEN) break
    shortDesc = next
  }
  if (!shortDesc) {
    shortDesc = (words[0] || cleaned).slice(0, SUBJECT_MAX_DESC_LEN)
  }

  const subject = ticketRef
    ? `[Support] ${shortDesc} - ${ticketRef}`
    : `[Support] ${shortDesc}`
  const body = `${cleaned}\n\n—\n${signature} · ${accountEmail}`

  return { subject, body }
}
