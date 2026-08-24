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

import { describe, expect, it } from 'vitest'
import source from '../components/EmailDetailModal.tsx?raw'

describe('EmailDetailModal RSVP toast type (audit fix)', () => {
  it('dispatches RSVP failures with the toast type field used by GlobalToastHost', () => {
    const failureToast = source.match(
      /new CustomEvent\('agentys:toast',\s*\{\s*detail:\s*\{\s*message:\s*t\('meeting_rsvp_error'\),\s*type:\s*'error'\s*\}/,
    )

    expect(failureToast).not.toBeNull()
  })

  it('does not regress to the ignored toast level field around RSVP errors', () => {
    const rsvpErrorIndex = source.indexOf("meeting_rsvp_error")
    expect(rsvpErrorIndex).toBeGreaterThan(-1)

    const nearbyRsvpToastCode = source.slice(
      Math.max(0, rsvpErrorIndex - 400),
      rsvpErrorIndex + 400,
    )
    expect(nearbyRsvpToastCode).not.toContain('level:')
  })
})
