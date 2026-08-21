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
