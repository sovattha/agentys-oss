// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2024-2026 Agentys contributors
import { describe, it, expect } from 'vitest'
import {
  QUICK_STEP_ACTION_TYPES,
  defaultActionPayload,
  makeAction,
  type CreateReminderPayload,
  type CreateCalendarEventPayload,
} from './quickStep'

describe('deadline action type contract', () => {
  it('exposes both new action types', () => {
    expect(QUICK_STEP_ACTION_TYPES).toContain('create_reminder')
    expect(QUICK_STEP_ACTION_TYPES).toContain('create_calendar_event')
  })

  it('create_reminder defaults to 2 days before', () => {
    const payload = defaultActionPayload('create_reminder') as CreateReminderPayload
    expect(payload).toEqual({ days_before: 2 })
  })

  it('create_calendar_event defaults to 2 days before, 30 min', () => {
    const payload = defaultActionPayload('create_calendar_event') as CreateCalendarEventPayload
    expect(payload).toEqual({ days_before: 2, duration_minutes: 30 })
  })

  it('makeAction builds a well-formed reminder action', () => {
    const action = makeAction('create_reminder')
    expect(action.type).toBe('create_reminder')
    expect((action.payload as CreateReminderPayload).days_before).toBe(2)
  })

  it('makeAction builds a well-formed calendar-event action', () => {
    const action = makeAction('create_calendar_event')
    expect(action.type).toBe('create_calendar_event')
    const p = action.payload as CreateCalendarEventPayload
    expect(p.days_before).toBe(2)
    expect(p.duration_minutes).toBe(30)
  })
})
