/*
 * Agentys — voice-first email assistant.
 * Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version. See the LICENSE file for details.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

/**
 * Pick the default "To:" address for a reply.
 *
 * Audit 2026-05-18: the legacy behaviour blindly used `email.sender`. When the
 * latest message in the thread was sent BY the user (self-only thread, or "I
 * just replied" sent-side thread), `sender` IS the user's own address — the
 * reply would email yourself. Fall back to the original outbound `To:` in
 * that case, skipping the user's own address if it also appears there.
 */
export function pickReplyRecipient(
  sender: string,
  to: string[] | undefined,
  ownEmail: string | null,
): string {
  const own = comparableEmailAddress(ownEmail);
  const from = comparableEmailAddress(sender);
  const isSelfSent = own && from && from === own;
  if (isSelfSent && to && to.length > 0) {
    const others = to.filter(addr => comparableEmailAddress(addr) !== own);
    return others[0] || to[0];
  }
  return sender;
}

export interface ReplyAllRecipientSource {
  sender: string;
  to?: string[];
  cc?: string[];
}

export interface ReplyAllRecipients {
  to: string[];
  cc: string[];
}

const EMAIL_ADDRESS_RE = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i;

/**
 * QA 2026-06-10: the reply composer seeded the To: chip with the bare sender
 * address, so the chip fell back to a capitalized local-part ("Nathansok")
 * while the thread header showed the real display name ("Nathan Roy").
 * When the picked recipient is the sender and we know their display name,
 * upgrade it to RFC-style "Name <address>" so the chip renders the name.
 */
export function withSenderDisplayName(
  recipient: string,
  sender: string,
  senderName?: string | null,
): string {
  const name = (senderName || '').trim();
  if (!name || recipient !== sender) return recipient;
  if (recipient.includes('<')) return recipient; // already "Name <addr>"
  if (name.includes('<') || name.includes(',') || EMAIL_ADDRESS_RE.test(name)) return recipient;
  return `${name} <${recipient.trim()}>`;
}

function comparableEmailAddress(value?: string | null): string {
  if (!value) return '';
  const angleMatch = value.match(/<([^<>]+)>/);
  const candidate = (angleMatch?.[1] || value).trim().replace(/^mailto:/i, '');
  return (candidate.match(EMAIL_ADDRESS_RE)?.[0] || value.match(EMAIL_ADDRESS_RE)?.[0] || candidate)
    .trim()
    .toLowerCase();
}

function uniqueRecipients(values: string[], excluded: string[] = []): string[] {
  const seen = new Set(excluded.map(comparableEmailAddress).filter(Boolean));
  const result: string[] = [];

  for (const value of values) {
    const display = value.trim();
    const comparable = comparableEmailAddress(display);
    if (!display && !comparable) continue;
    const key = comparable || display.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(display || comparable);
  }

  return result;
}

export function buildReplyAllRecipients(
  email: ReplyAllRecipientSource,
  ownEmail: string | null,
): ReplyAllRecipients {
  const sender = (email.sender || '').trim();
  const toCandidates = [
    ...(sender ? [sender] : []),
    ...(email.to || []),
  ];
  const to = uniqueRecipients(toCandidates, ownEmail ? [ownEmail] : []);
  const fallback = pickReplyRecipient(sender, email.to, ownEmail).trim();
  const finalTo = to.length > 0 ? to : (fallback ? uniqueRecipients([fallback], ownEmail ? [ownEmail] : []) : []);
  const cc = uniqueRecipients(email.cc || [], [
    ...(ownEmail ? [ownEmail] : []),
    ...finalTo,
  ]);

  return { to: finalTo, cc };
}
