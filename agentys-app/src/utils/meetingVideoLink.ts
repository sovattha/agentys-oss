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
 * Extract a video conferencing link from a calendar event.
 *
 * Order of preference: explicit `meetLink` field, then URL detection in
 * `location` and `description`. Returns the canonical https:// URL or null.
 */

import type { CalendarEvent } from '../services/api'

const VIDEO_PROVIDER_PATTERNS: RegExp[] = [
  /https?:\/\/[a-z0-9.-]*zoom\.us\/[^\s<>"')]+/i,
  /https?:\/\/meet\.google\.com\/[a-z0-9-]+/i,
  /https?:\/\/teams\.(?:microsoft|live)\.com\/[^\s<>"')]+/i,
  /https?:\/\/[a-z0-9.-]*whereby\.com\/[^\s<>"')]+/i,
  /https?:\/\/[a-z0-9.-]*webex\.com\/[^\s<>"')]+/i,
  /https?:\/\/meet\.jit\.si\/[^\s<>"')]+/i,
  /https?:\/\/[a-z0-9.-]*around\.co\/[^\s<>"')]+/i,
]

export function extractVideoLink(event: Pick<CalendarEvent, 'meetLink' | 'location' | 'description'>): string | null {
  if (event.meetLink && event.meetLink.startsWith('http')) {
    return event.meetLink
  }
  const haystack = `${event.location ?? ''} ${event.description ?? ''}`
  for (const pattern of VIDEO_PROVIDER_PATTERNS) {
    const match = haystack.match(pattern)
    if (match) return match[0]
  }
  return null
}
