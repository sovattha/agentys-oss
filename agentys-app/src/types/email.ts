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

import type { EmailContext } from "../utils/contextualAgents";
import type { AutoBadge } from "./quickStep";

export interface EmailLabel {
  name: string;
  color: string;
  confidence?: number;
}

export interface Email {
  id: string;
  sender: string;
  sender_name?: string | null;
  subject: string;
  received_at: string;
  has_attachments?: boolean;
  conversation_id?: string | null;
  thread_count?: number;
  is_read?: boolean;
  body_preview?: string;
  contexts?: EmailContext[];
  has_pending_draft?: boolean;
  draft_skipped?: boolean;
  labels?: EmailLabel[];
  /**
   * Audit 2026-05-18: backend stamps this when the raw sender display name
   * carried invisible/format characters OR mixed Latin with a Latin-lookalike
   * script (Cyrillic / Greek). Rendered as a "Suspicious sender" warning chip
   * on the email row so phishing attempts surface before click.
   */
  sender_spoofed?: boolean;
  to?: string[];
  /**
   * Optional badge surfaced when this email was auto-actioned by a
   * Quick Step with `showAutoBadge=true`. Populated client-side by
   * the `useAutoBadges` hook after the inbox fetch — never written
   * by the email-list endpoint itself.
   */
  auto_badge?: AutoBadge | null;
  /**
   * Inferred deadline (ISO-8601 UTC) extracted automatically from the body
   * during ingest (regex over "due / by / expires / payment due / …").
   * Rendered as a clock chip on the email row, and exposed to Quick Steps
   * via the `has_deadline_detected` trigger condition.
   */
  deadline_at?: string | null;
  /**
   * Emoji marker stamped by the `mark_with_emoji` Quick Step action.
   * Renders as a chip right after the subject; when `include_deadline`
   * is set AND `deadline_at` is present, the chip merges them and the
   * standalone clock chip is suppressed on that row.
   */
  emoji_marker?: {
    /** Optional — a text-only marker (the "No emoji" path) omits it. */
    emoji?: string;
    text?: string;
    include_deadline?: boolean;
    /** Palette color — a `LABEL_COLORS` member tinting the chip + text. */
    color?: string;
    /** false = render the marker bare (no pill). Default/absent = chip. */
    chip?: boolean;
  } | null;
}

export interface EmailDetail extends Email {
  body: string | null;
  body_html?: string | null;
  body_text?: string;
  to?: string[];
  cc?: string[];
  attachments?: Attachment[];
  meeting_meta?: MeetingMeta | null;
}

export interface Attachment {
  id: string;
  filename: string;
  size: number;
  content_type: string;
}

export interface MeetingMeta {
  summary: string;
  dtstart: string | null;
  dtend: string | null;
  location: string;
  organizer: string;
  /**
   * 'invite' = a real iCal invitation you can RSVP to (Accept/Maybe/Decline).
   * 'appointment' = a booking-tool confirmation (Calendly): the slot is already
   * booked, so the UI offers Add-to-calendar / Reschedule / Cancel instead.
   * Absent on emails synced before the feature → treated as 'invite'.
   */
  kind?: 'invite' | 'appointment';
  provider?: string | null;
  /** Self-service deep-links carried in the confirmation body (appointment only). */
  reschedule_url?: string | null;
  cancel_url?: string | null;
  /** Human timezone label parsed from the "When" line, e.g. "Heure de l'Est - Toronto". */
  tz_label?: string | null;
}

export interface EmailsResponse {
  count: number;
  emails: Email[];
  no_account?: boolean;
  source?: string;
  has_more?: boolean;
  /** Backend short-circuited the provider fetch during cold start and triggered a background sync. */
  sync_in_progress?: boolean;
  /** Last completed background refresh for this folder failed (auth/provider) — terminal, show an error instead of the skeleton. */
  sync_failed?: boolean;
}

export interface EmailThreadResponse {
  count: number;
  emails: EmailDetail[];
}

export type EmailLoadingState = 'idle' | 'loading' | 'success' | 'error';

export type EmailStatus = 'all' | 'unread' | 'read' | 'draft_ready' | 'sent';

export interface SearchResult {
  id: number;
  email_id: string;
  subject: string;
  sender: string;
  date: string;
  snippet: string;
  relevance_score: number;
  is_read: boolean;
  is_starred: boolean;
}

export interface SearchResponse {
  success: boolean;
  query: string;
  total: number;
  results: SearchResult[];
  duration_ms: number;
  has_more: boolean;
}
