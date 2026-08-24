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

import { describe, it, expect, beforeEach } from 'vitest'
import { extractVideoLink } from '../utils/meetingVideoLink'
import { hasFired, markFired, _resetFiredStore } from '../services/meetingReminderStore'
import type { CalendarEvent } from '../services/api'

function makeEvent(overrides: Partial<CalendarEvent> = {}): CalendarEvent {
  return {
    id: 'ev-1',
    title: 'Test',
    start: new Date().toISOString(),
    end: new Date(Date.now() + 3600_000).toISOString(),
    isAllDay: false,
    attendees: [],
    calendarId: 'primary',
    status: 'confirmed',
    providerSource: 'google',
    isRecurring: false,
    ...overrides,
  }
}

describe('extractVideoLink', () => {
  it('returns null when no link is present', () => {
    expect(extractVideoLink(makeEvent())).toBeNull()
  })

  it('prefers explicit meetLink field', () => {
    const ev = makeEvent({
      meetLink: 'https://meet.google.com/abc-defg-hij',
      description: 'https://zoom.us/j/9999',
    })
    expect(extractVideoLink(ev)).toBe('https://meet.google.com/abc-defg-hij')
  })

  it('detects Zoom URLs in description', () => {
    const ev = makeEvent({ description: 'Join: https://us02web.zoom.us/j/1234567890?pwd=abc here' })
    expect(extractVideoLink(ev)).toBe('https://us02web.zoom.us/j/1234567890?pwd=abc')
  })

  it('detects Google Meet URLs in location', () => {
    const ev = makeEvent({ location: 'https://meet.google.com/xyz-pdqr-stu' })
    expect(extractVideoLink(ev)).toBe('https://meet.google.com/xyz-pdqr-stu')
  })

  it('detects Microsoft Teams URLs', () => {
    const ev = makeEvent({ description: 'Click https://teams.microsoft.com/l/meetup-join/abc to join' })
    expect(extractVideoLink(ev)).toBe('https://teams.microsoft.com/l/meetup-join/abc')
  })

  it('detects Whereby URLs', () => {
    const ev = makeEvent({ description: 'Room: https://whereby.com/agentys-team' })
    expect(extractVideoLink(ev)).toBe('https://whereby.com/agentys-team')
  })

  it('detects jit.si URLs', () => {
    const ev = makeEvent({ location: 'https://meet.jit.si/AgentysSync' })
    expect(extractVideoLink(ev)).toBe('https://meet.jit.si/AgentysSync')
  })

  it('ignores random URLs that do not match a known provider', () => {
    const ev = makeEvent({ description: 'See https://www.example.com/notes for context' })
    expect(extractVideoLink(ev)).toBeNull()
  })

  it('ignores meetLink without http scheme', () => {
    const ev = makeEvent({ meetLink: 'tel:+123' })
    expect(extractVideoLink(ev)).toBeNull()
  })
})

describe('meetingReminderStore', () => {
  beforeEach(() => {
    _resetFiredStore()
  })

  it('marks an event as fired and reads it back', () => {
    expect(hasFired('ev-1', 'lead')).toBe(false)
    markFired('ev-1', 'lead')
    expect(hasFired('ev-1', 'lead')).toBe(true)
  })

  it('treats lead and imminent tiers independently', () => {
    markFired('ev-1', 'lead')
    expect(hasFired('ev-1', 'lead')).toBe(true)
    expect(hasFired('ev-1', 'imminent')).toBe(false)
  })

  it('isolates entries per event id', () => {
    markFired('ev-1', 'lead')
    expect(hasFired('ev-1', 'lead')).toBe(true)
    expect(hasFired('ev-2', 'lead')).toBe(false)
  })

  it('survives across multiple writes (no clobber)', () => {
    markFired('ev-1', 'lead')
    markFired('ev-2', 'lead')
    markFired('ev-2', 'imminent')
    expect(hasFired('ev-1', 'lead')).toBe(true)
    expect(hasFired('ev-2', 'lead')).toBe(true)
    expect(hasFired('ev-2', 'imminent')).toBe(true)
  })
})
